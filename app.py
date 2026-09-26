import os
import sqlite3
import unicodedata

from datetime import datetime, timedelta, timezone
from io import BytesIO
from zoneinfo import ZoneInfo

import pandas as pd
import psycopg2
import psycopg2.extras

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    g,
    session,
    send_file,
    flash,
)

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
)


# ============================================================
# CONFIGURAÇÃO
# ============================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "chave-temporaria-desenvolvimento"
)

DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql://",
        1
    )

FUSO_BRASIL = ZoneInfo("America/Sao_Paulo")


# ============================================================
# STATUS
# ============================================================

STATUS_PENDENTE = "Pendente"
STATUS_ANDAMENTO = "Em andamento"
STATUS_CONCLUIDO = "Concluído"
STATUS_ARQUIVADO = "Arquivado"

STATUS_ATIVOS = (
    STATUS_PENDENTE,
    STATUS_ANDAMENTO,
)


# ============================================================
# CATEGORIAS
# ============================================================

CATEGORIAS_VALIDAS = [
    "Separação",
    "Inventário",
    "Expedição",
    "Recebimento",
    "Logística Reversa",
    "Estoque",
]

PRIORIDADES_VALIDAS = [
    "Baixa",
    "Média",
    "Alta",
]

STATUS_VALIDOS = [
    STATUS_PENDENTE,
    STATUS_ANDAMENTO,
    STATUS_CONCLUIDO,
    STATUS_ARQUIVADO,
]


# ============================================================
# BANCO DE DADOS
# ============================================================

def usando_postgresql():
    return bool(DATABASE_URL)


def get_db():
    if "db" not in g:

        if usando_postgresql():

            g.db = psycopg2.connect(
                DATABASE_URL,
                cursor_factory=psycopg2.extras.RealDictCursor
            )

        else:

            g.db = sqlite3.connect(
                "database.db",
                check_same_thread=False
            )

            g.db.row_factory = sqlite3.Row

    return g.db


@app.teardown_appcontext
def fechar_db(exception=None):

    db = g.pop("db", None)

    if db is not None:
        db.close()


def executar(
    sql,
    parametros=(),
    fetchone=False,
    fetchall=False,
    commit=False
):

    db = get_db()
    cursor = db.cursor()

    try:

        cursor.execute(
            sql,
            parametros
        )

        if commit:
            db.commit()

        if fetchone:

            resultado = cursor.fetchone()
            cursor.close()

            return resultado

        if fetchall:

            resultado = cursor.fetchall()
            cursor.close()

            return resultado

        return cursor

    except Exception:

        if commit:
            db.rollback()

        try:
            cursor.close()
        except Exception:
            pass

        raise


def linha_para_dict(linha):

    if linha is None:
        return None

    if isinstance(linha, dict):
        return dict(linha)

    return dict(linha)


def linhas_para_dict(linhas):

    return [
        linha_para_dict(linha)
        for linha in linhas
    ]


def obter_valor(
    linha,
    campo,
    padrao=None
):

    if linha is None:
        return padrao

    if isinstance(linha, dict):
        return linha.get(campo, padrao)

    try:
        return linha[campo]
    except Exception:
        return padrao


def contar(
    sql,
    parametros=()
):

    resultado = executar(
        sql,
        parametros,
        fetchone=True
    )

    if resultado is None:
        return 0

    valor = obter_valor(
        resultado,
        "total",
        0
    )

    try:
        return int(valor or 0)
    except Exception:
        return 0


# ============================================================
# NORMALIZAÇÃO
# ============================================================

def normalizar_texto(valor):

    if valor is None:
        return ""

    texto = str(valor).strip().lower()

    texto = unicodedata.normalize(
        "NFD",
        texto
    )

    texto = "".join(
        caractere
        for caractere in texto
        if unicodedata.category(caractere) != "Mn"
    )

    return texto


def normalizar_status(valor):
    return normalizar_texto(valor)


def normalizar_categoria(valor):
    return normalizar_texto(valor)


def normalizar_nome_modulo(valor):

    texto = str(valor or "")

    texto = unicodedata.normalize(
        "NFKD",
        texto
    )

    texto = "".join(
        caractere
        for caractere in texto
        if not unicodedata.combining(caractere)
    )

    return texto.strip().lower()


def normalizar_requisicao(valor):

    if valor is None:
        return ""

    return str(valor).strip().upper()


def categoria_eh(item, categoria):

    return (
        normalizar_categoria(
            obter_valor(
                item,
                "categoria",
                ""
            )
        )
        == normalizar_categoria(categoria)
    )


# ============================================================
# TESTES DE STATUS
# ============================================================

def status_eh_pendente(valor):

    return normalizar_status(valor) == "pendente"


def status_eh_andamento(valor):

    return normalizar_status(valor) in (
        "em andamento",
        "andamento",
        "em processo"
    )


def status_eh_concluido(valor):

    return normalizar_status(valor) in (
        "concluido",
        "concluida",
        "finalizado",
        "finalizada"
    )


def status_eh_arquivado(valor):

    return normalizar_status(valor) == "arquivado"


def status_eh_finalizado(valor):

    return (
        status_eh_concluido(valor)
        or status_eh_arquivado(valor)
    )


def status_eh_ativo(valor):

    return (
        status_eh_pendente(valor)
        or status_eh_andamento(valor)
    )


# ============================================================
# DATA / HORA
# ============================================================

def agora_utc():

    return datetime.now(
        timezone.utc
    )


def agora_brasil():

    return datetime.now(
        FUSO_BRASIL
    )


def agora_utc_naive():

    return agora_utc().replace(
        tzinfo=None
    )


def agora_sqlite():

    return datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def converter_para_brasil(valor):

    if not valor:
        return None

    if isinstance(valor, datetime):

        dt = valor

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            FUSO_BRASIL
        )

    texto = str(valor).strip()

    if not texto:
        return None

    texto = texto.replace(
        "Z",
        "+00:00"
    )

    dt = None

    try:

        dt = datetime.fromisoformat(
            texto
        )

    except Exception:
        pass

    if dt is None:

        formatos = [
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S%z",
        ]

        for formato in formatos:

            try:

                dt = datetime.strptime(
                    texto,
                    formato
                )

                break

            except Exception:
                continue

    if dt is None:
        return None

    if dt.tzinfo is None:

        dt = dt.replace(
            tzinfo=timezone.utc
        )

    return dt.astimezone(
        FUSO_BRASIL
    )


def formatar_data_hora(valor):

    dt = converter_para_brasil(valor)

    if not dt:
        return "-"

    return dt.strftime(
        "%d/%m/%Y %H:%M"
    )


def formatar_hora(valor):

    dt = converter_para_brasil(valor)

    if not dt:
        return "-"

    return dt.strftime(
        "%H:%M"
    )


def calcular_duracao(
    inicio,
    fim=None
):

    inicio_dt = converter_para_brasil(
        inicio
    )

    if not inicio_dt:
        return "-"

    if fim:
        fim_dt = converter_para_brasil(
            fim
        )
    else:
        fim_dt = agora_brasil()

    if not fim_dt:
        return "-"

    segundos = int(
        (
            fim_dt - inicio_dt
        ).total_seconds()
    )

    if segundos < 0:
        segundos = 0

    horas = segundos // 3600

    minutos = (
        segundos % 3600
    ) // 60

    if horas > 0:

        return (
            f"{horas}h "
            f"{minutos}min"
        )

    return f"{minutos}min"


# ============================================================
# PRAZOS
# ============================================================

def prazo_em_datetime(valor):

    if not valor:
        return None

    if isinstance(valor, datetime):

        dt = valor

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=FUSO_BRASIL
            )

        return dt.astimezone(
            FUSO_BRASIL
        )

    texto = str(valor).strip()

    if not texto:
        return None

    formatos = [
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
    ]

    for formato in formatos:

        try:

            return datetime.strptime(
                texto,
                formato
            ).replace(
                tzinfo=FUSO_BRASIL
            )

        except Exception:
            continue

    try:

        dt = datetime.fromisoformat(
            texto
        )

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=FUSO_BRASIL
            )

        return dt.astimezone(
            FUSO_BRASIL
        )

    except Exception:

        return None


# ============================================================
# ATRASADOS
# ============================================================

def prazo_atrasado(
    prazo,
    status=None
):

    if not status_eh_ativo(status):
        return False

    dt = prazo_em_datetime(prazo)

    if not dt:
        return False

    return agora_brasil() > dt


def registro_foi_atrasado(item):

    status = obter_valor(
        item,
        "status",
        ""
    )

    if not status_eh_ativo(status):
        return False

    prazo = obter_valor(
        item,
        "prazo"
    )

    if not prazo:
        return False

    return prazo_atrasado(
        prazo,
        status
    )


def texto_atraso(item):

    if not registro_foi_atrasado(item):
        return ""

    prazo_dt = prazo_em_datetime(
        obter_valor(item, "prazo")
    )

    if not prazo_dt:
        return ""

    diferenca = (
        agora_brasil()
        - prazo_dt
    )

    minutos = int(
        diferenca.total_seconds()
        // 60
    )

    if minutos <= 0:
        return ""

    dias = minutos // 1440

    horas = (
        minutos % 1440
    ) // 60

    mins = minutos % 60

    if dias > 0:

        return (
            f"{dias}d "
            f"{horas}h "
            f"{mins}min de atraso"
        )

    if horas > 0:

        return (
            f"{horas}h "
            f"{mins}min de atraso"
        )

    return f"{mins}min de atraso"


# ============================================================
# PREPARAÇÃO DOS REGISTROS
# ============================================================

def preparar_atividade(item):

    item = linha_para_dict(item)

    if not item:
        return item

    if not item.get("status"):
        item["status"] = STATUS_PENDENTE

    if not item.get("prioridade"):
        item["prioridade"] = "Baixa"

    item["inicio_formatado"] = formatar_data_hora(
        item.get("inicio_em")
    )

    item["concluido_formatado"] = formatar_data_hora(
        item.get("concluido_em")
    )

    item["criado_formatado"] = formatar_data_hora(
        item.get("criado_em")
    )

    item["prazo_formatado"] = formatar_data_hora(
        item.get("prazo")
    )

    item["foi_atrasada"] = registro_foi_atrasado(
        item
    )

    item["texto_atraso"] = texto_atraso(
        item
    )

    item["duracao"] = calcular_duracao(
        item.get("inicio_em"),
        item.get("concluido_em")
    )

    return item


def preparar_lista_atividades(itens):

    return [
        preparar_atividade(item)
        for item in itens
    ]


def preparar_chat(itens):

    resultado = []

    for item in itens:

        item = linha_para_dict(item)

        if item:

            item["data_formatada"] = formatar_data_hora(
                item.get("criado_em")
            )

            resultado.append(item)

    return resultado


# ============================================================
# BUSCA DE ATIVIDADES
# ============================================================

def buscar_atividades_ativas():

    registros = executar(
        """
        SELECT *
        FROM atividades
        ORDER BY id DESC
        """,
        fetchall=True
    )

    return [
        item
        for item in registros
        if status_eh_ativo(
            obter_valor(
                item,
                "status",
                ""
            )
        )
    ]


def buscar_atividades_historico():

    return executar(
        """
        SELECT *
        FROM atividades
        ORDER BY id DESC
        """,
        fetchall=True
    )


# ============================================================
# INDICADORES GERAIS
# ============================================================

def calcular_indicadores(atividades):

    atividades = [
        linha_para_dict(item)
        for item in atividades
        if linha_para_dict(item)
    ]

    atividades_pendentes = 0
    atividades_andamento = 0
    atividades_concluidas = 0
    atividades_arquivadas = 0

    for item in atividades:

        status = obter_valor(
            item,
            "status",
            ""
        )

        if status_eh_pendente(status):

            atividades_pendentes += 1

        elif status_eh_andamento(status):

            atividades_andamento += 1

        elif status_eh_concluido(status):

            atividades_concluidas += 1

        elif status_eh_arquivado(status):

            atividades_arquivadas += 1

    atividades_finalizadas = (
        atividades_concluidas
        + atividades_arquivadas
    )

    atividades_ativas = (
        atividades_pendentes
        + atividades_andamento
    )

    total_geral = len(atividades)

    if total_geral > 0:

        perc_atendidas = round(
            (
                atividades_finalizadas
                / total_geral
            ) * 100
        )

    else:

        perc_atendidas = 0

    inventarios = [
        item
        for item in atividades
        if categoria_eh(
            item,
            "Inventário"
        )
    ]

    inventario_total = len(inventarios)

    inventario_concluido = sum(
        1
        for item in inventarios
        if status_eh_finalizado(
            obter_valor(
                item,
                "status"
            )
        )
    )

    inventario_pendente = max(
        0,
        inventario_total
        - inventario_concluido
    )

    if inventario_total > 0:

        perc_inventario = round(
            (
                inventario_concluido
                / inventario_total
            ) * 100
        )

    else:

        perc_inventario = 0

    expedicoes = [
        item
        for item in atividades
        if categoria_eh(
            item,
            "Expedição"
        )
    ]

    expedicao_total = len(expedicoes)

    expedicao_concluida = sum(
        1
        for item in expedicoes
        if status_eh_finalizado(
            obter_valor(
                item,
                "status"
            )
        )
    )

    expedicao_pendente = max(
        0,
        expedicao_total
        - expedicao_concluida
    )

    if expedicao_total > 0:

        perc_expedicao = round(
            (
                expedicao_concluida
                / expedicao_total
            ) * 100
        )

    else:

        perc_expedicao = 0

    requisicoes_pendentes = set()

    for item in atividades:

        if not categoria_eh(
            item,
            "Separação"
        ):
            continue

        if not status_eh_ativo(
            obter_valor(
                item,
                "status",
                ""
            )
        ):
            continue

        numero = normalizar_requisicao(
            obter_valor(
                item,
                "num_requisicao"
            )
        )

        if numero:
            requisicoes_pendentes.add(numero)

    recebimento_pendente = sum(
        1
        for item in atividades
        if (
            categoria_eh(
                item,
                "Recebimento"
            )
            and status_eh_ativo(
                obter_valor(
                    item,
                    "status"
                )
            )
        )
    )

    ocorrencias = sum(
        1
        for item in atividades
        if (
            normalizar_texto(
                obter_valor(
                    item,
                    "prioridade",
                    ""
                )
            ) == "alta"
            and status_eh_ativo(
                obter_valor(
                    item,
                    "status"
                )
            )
        )
    )

    atrasados = sum(
        1
        for item in atividades
        if registro_foi_atrasado(item)
    )

    return {
        "total_geral": total_geral,

        "atividades_pendentes":
            atividades_pendentes,

        "atividades_andamento":
            atividades_andamento,

        "atividades_concluidas":
            atividades_concluidas,

        "atividades_arquivadas":
            atividades_arquivadas,

        "atividades_finalizadas":
            atividades_finalizadas,

        "atividades_ativas":
            atividades_ativas,

        "perc_atendidas":
            max(0, min(100, perc_atendidas)),

        "inventario_total":
            inventario_total,

        "inventario_concluido":
            inventario_concluido,

        "inventario_pendente":
            inventario_pendente,

        "perc_inventario":
            max(0, min(100, perc_inventario)),

        "expedicao_total":
            expedicao_total,

        "expedicao_concluida":
            expedicao_concluida,

        "expedicao_pendente":
            expedicao_pendente,

        "perc_expedicao":
            max(0, min(100, perc_expedicao)),

        "requisicoes_pendentes":
            len(requisicoes_pendentes),

        "recebimento_pendente":
            recebimento_pendente,

        "ocorrencias":
            ocorrencias,

        "atrasados":
            atrasados,
    }


# ============================================================
# INDICADORES DO DIA
#
# IMPORTANTE:
# Aqui não usamos todo o histórico.
# Somente atividades do dia atual no horário de Brasília.
# ============================================================

def atividade_eh_do_dia(item, data_referencia=None):

    if data_referencia is None:
        data_referencia = agora_brasil().date()

    data_valor = (
        obter_valor(item, "inicio_em")
        or obter_valor(item, "criado_em")
    )

    dt = converter_para_brasil(data_valor)

    if not dt:
        return False

    return dt.date() == data_referencia


def calcular_indicadores_do_dia(atividades):

    hoje = agora_brasil().date()

    atividades_dia = [
        linha_para_dict(item)
        for item in atividades
        if (
            linha_para_dict(item)
            and atividade_eh_do_dia(
                item,
                hoje
            )
        )
    ]

    total_dia = len(
        atividades_dia
    )

    finalizadas_dia = sum(
        1
        for item in atividades_dia
        if status_eh_finalizado(
            obter_valor(
                item,
                "status"
            )
        )
    )

    pendentes_dia = sum(
        1
        for item in atividades_dia
        if status_eh_ativo(
            obter_valor(
                item,
                "status"
            )
        )
    )

    if total_dia > 0:

        perc_atendidas = round(
            (
                finalizadas_dia
                / total_dia
            ) * 100
        )

    else:

        perc_atendidas = 0

    inventarios = [
        item
        for item in atividades_dia
        if categoria_eh(
            item,
            "Inventário"
        )
    ]

    inventario_total = len(
        inventarios
    )

    inventario_concluido = sum(
        1
        for item in inventarios
        if status_eh_finalizado(
            obter_valor(
                item,
                "status"
            )
        )
    )

    if inventario_total > 0:

        perc_inventario = round(
            (
                inventario_concluido
                / inventario_total
            ) * 100
        )

    else:

        perc_inventario = 0

    expedicoes = [
        item
        for item in atividades_dia
        if categoria_eh(
            item,
            "Expedição"
        )
    ]

    expedicao_total = len(
        expedicoes
    )

    expedicao_concluida = sum(
        1
        for item in expedicoes
        if status_eh_finalizado(
            obter_valor(
                item,
                "status"
            )
        )
    )

    if expedicao_total > 0:

        perc_expedicao = round(
            (
                expedicao_concluida
                / expedicao_total
            ) * 100
        )

    else:

        perc_expedicao = 0

    return {
        "data": hoje.strftime(
            "%d/%m/%Y"
        ),

        "total": total_dia,

        "finalizadas":
            finalizadas_dia,

        "pendentes":
            pendentes_dia,

        "perc_atendidas":
            max(
                0,
                min(
                    100,
                    perc_atendidas
                )
            ),

        "inventario_total":
            inventario_total,

        "inventario_concluido":
            inventario_concluido,

        "perc_inventario":
            max(
                0,
                min(
                    100,
                    perc_inventario
                )
            ),

        "expedicao_total":
            expedicao_total,

        "expedicao_concluida":
            expedicao_concluida,

        "perc_expedicao":
            max(
                0,
                min(
                    100,
                    perc_expedicao
                )
            ),
    }


# ============================================================
# DUPLICIDADE DE REQUISIÇÃO
# ============================================================

def requisicao_duplicada(
    num_requisicao,
    ignorar_id=None
):

    num_requisicao = normalizar_requisicao(
        num_requisicao
    )

    if not num_requisicao:
        return False

    registros = executar(
        """
        SELECT id, num_requisicao, status
        FROM atividades
        """,
        fetchall=True
    )

    for item in registros:

        item_id = obter_valor(
            item,
            "id"
        )

        if (
            ignorar_id is not None
            and int(item_id) == int(ignorar_id)
        ):
            continue

        numero = normalizar_requisicao(
            obter_valor(
                item,
                "num_requisicao"
            )
        )

        if numero != num_requisicao:
            continue

        if status_eh_ativo(
            obter_valor(
                item,
                "status"
            )
        ):
            return True

    return False


# ============================================================
# INICIALIZAÇÃO DO BANCO
# ============================================================

def init_db():

    db = get_db()

    if usando_postgresql():

        cursor = db.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id SERIAL PRIMARY KEY,
                nome TEXT NOT NULL,
                senha TEXT NOT NULL,
                criado_em TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS atividades (
                id SERIAL PRIMARY KEY,
                num_requisicao TEXT,
                atividade TEXT NOT NULL,
                descricao TEXT,
                categoria TEXT,
                responsavel TEXT,
                prioridade TEXT,
                prazo TEXT,
                status TEXT,
                inicio_em TIMESTAMP,
                concluido_em TIMESTAMP,
                encerrado_por TEXT,
                criado_em TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat (
                id SERIAL PRIMARY KEY,
                usuario TEXT,
                mensagem TEXT,
                criado_em TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS melhorias (
                id SERIAL PRIMARY KEY,
                titulo TEXT NOT NULL,
                descricao TEXT,
                etapa TEXT,
                autor TEXT,
                status TEXT,
                criado_em TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS estoque (
                id SERIAL PRIMARY KEY,
                codigo TEXT,
                descricao TEXT,
                quantidade INTEGER DEFAULT 0,
                criado_em TIMESTAMP
            )
        """)

        colunas_atividades = [
            ("num_requisicao", "TEXT"),
            ("descricao", "TEXT"),
            ("categoria", "TEXT"),
            ("responsavel", "TEXT"),
            ("prioridade", "TEXT"),
            ("prazo", "TEXT"),
            ("status", "TEXT"),
            ("inicio_em", "TIMESTAMP"),
            ("concluido_em", "TIMESTAMP"),
            ("encerrado_por", "TEXT"),
            ("criado_em", "TIMESTAMP"),
        ]

        for coluna, tipo in colunas_atividades:

            cursor.execute(
                f"""
                ALTER TABLE atividades
                ADD COLUMN IF NOT EXISTS {coluna} {tipo}
                """
            )

        cursor.execute("""
            ALTER TABLE usuarios
            ADD COLUMN IF NOT EXISTS criado_em TIMESTAMP
        """)

        cursor.execute("""
            ALTER TABLE melhorias
            ADD COLUMN IF NOT EXISTS etapa TEXT
        """)

        cursor.execute("""
            ALTER TABLE melhorias
            ADD COLUMN IF NOT EXISTS autor TEXT
        """)

        cursor.execute("""
            ALTER TABLE melhorias
            ADD COLUMN IF NOT EXISTS status TEXT
        """)

        cursor.execute("""
            ALTER TABLE melhorias
            ADD COLUMN IF NOT EXISTS criado_em TIMESTAMP
        """)

        cursor.execute("""
            ALTER TABLE estoque
            ADD COLUMN IF NOT EXISTS codigo TEXT
        """)

        cursor.execute("""
            ALTER TABLE estoque
            ADD COLUMN IF NOT EXISTS descricao TEXT
        """)

        cursor.execute("""
            ALTER TABLE estoque
            ADD COLUMN IF NOT EXISTS quantidade INTEGER DEFAULT 0
        """)

        cursor.execute("""
            ALTER TABLE estoque
            ADD COLUMN IF NOT EXISTS criado_em TIMESTAMP
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_atividades_req_busca
            ON atividades (num_requisicao)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_atividades_status
            ON atividades (status)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_atividades_categoria
            ON atividades (categoria)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_atividades_prazo
            ON atividades (prazo)
        """)

        db.commit()
        cursor.close()

    else:

        db.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                senha TEXT NOT NULL,
                criado_em TEXT
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS atividades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                num_requisicao TEXT,
                atividade TEXT NOT NULL,
                descricao TEXT,
                categoria TEXT,
                responsavel TEXT,
                prioridade TEXT,
                prazo TEXT,
                status TEXT,
                inicio_em TEXT,
                concluido_em TEXT,
                encerrado_por TEXT,
                criado_em TEXT
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS chat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT,
                mensagem TEXT,
                criado_em TEXT
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS melhorias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                descricao TEXT,
                etapa TEXT,
                autor TEXT,
                status TEXT,
                criado_em TEXT
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS estoque (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT,
                descricao TEXT,
                quantidade INTEGER DEFAULT 0,
                criado_em TEXT
            )
        """)

        tabelas_colunas = {

            "usuarios": [
                ("criado_em", "TEXT")
            ],

            "atividades": [
                ("num_requisicao", "TEXT"),
                ("descricao", "TEXT"),
                ("categoria", "TEXT"),
                ("responsavel", "TEXT"),
                ("prioridade", "TEXT"),
                ("prazo", "TEXT"),
                ("status", "TEXT"),
                ("inicio_em", "TEXT"),
                ("concluido_em", "TEXT"),
                ("encerrado_por", "TEXT"),
                ("criado_em", "TEXT"),
            ],

            "melhorias": [
                ("etapa", "TEXT"),
                ("autor", "TEXT"),
                ("status", "TEXT"),
                ("criado_em", "TEXT"),
            ],

            "estoque": [
                ("codigo", "TEXT"),
                ("descricao", "TEXT"),
                ("quantidade", "INTEGER DEFAULT 0"),
                ("criado_em", "TEXT"),
            ],
        }

        for tabela, colunas in tabelas_colunas.items():

            existentes = db.execute(
                f"PRAGMA table_info({tabela})"
            ).fetchall()

            nomes = [
                coluna["name"]
                for coluna in existentes
            ]

            for coluna, tipo in colunas:

                if coluna not in nomes:

                    db.execute(
                        f"""
                        ALTER TABLE {tabela}
                        ADD COLUMN {coluna} {tipo}
                        """
                    )

        db.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_atividades_req_busca
            ON atividades (num_requisicao)
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_atividades_status
            ON atividades (status)
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_atividades_categoria
            ON atividades (categoria)
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_atividades_prazo
            ON atividades (prazo)
        """)

        db.commit()

    # ========================================================
    # USUÁRIO ADMINISTRADOR
    # ========================================================

    usuario = executar(
        """
        SELECT id
        FROM usuarios
        WHERE LOWER(nome) = LOWER(%s)
        LIMIT 1
        """
        if usando_postgresql()
        else
        """
        SELECT id
        FROM usuarios
        WHERE LOWER(nome) = LOWER(?)
        LIMIT 1
        """,
        ("Wanderson Fernandes",),
        fetchone=True
    )

    if usuario is None:

        executar(
            """
            INSERT INTO usuarios
                (nome, senha, criado_em)
            VALUES
                (%s,%s,%s)
            """
            if usando_postgresql()
            else
            """
            INSERT INTO usuarios
                (nome, senha, criado_em)
            VALUES
                (?,?,?)
            """,
            (
                "Wanderson Fernandes",
                "1234",
                (
                    agora_utc_naive()
                    if usando_postgresql()
                    else agora_sqlite()
                )
            ),
            commit=True
        )


# ============================================================
# ARQUIVAMENTO AUTOMÁTICO
# ============================================================

def arquivar_atividades_expiradas():

    limite = (
        agora_utc()
        - timedelta(hours=24)
    )

    registros = executar(
        """
        SELECT id, status, concluido_em
        FROM atividades
        WHERE concluido_em IS NOT NULL
        """,
        fetchall=True
    )

    ids = []

    for item in registros:

        if not status_eh_concluido(
            obter_valor(
                item,
                "status"
            )
        ):
            continue

        concluido = obter_valor(
            item,
            "concluido_em"
        )

        if not concluido:
            continue

        dt = converter_para_brasil(
            concluido
        )

        if not dt:
            continue

        if dt.astimezone(
            timezone.utc
        ) <= limite:

            ids.append(
                obter_valor(
                    item,
                    "id"
                )
            )

    for item_id in ids:

        executar(
            """
            UPDATE atividades
            SET status = 'Arquivado'
            WHERE id = %s
            """
            if usando_postgresql()
            else
            """
            UPDATE atividades
            SET status = 'Arquivado'
            WHERE id = ?
            """,
            (item_id,),
            commit=True
        )


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        nome = request.form.get(
            "usuario",
            ""
        ).strip()

        senha = request.form.get(
            "senha",
            ""
        ).strip()

        usuario = executar(
            """
            SELECT *
            FROM usuarios
            WHERE LOWER(nome) = LOWER(%s)
              AND senha = %s
            LIMIT 1
            """
            if usando_postgresql()
            else
            """
            SELECT *
            FROM usuarios
            WHERE LOWER(nome) = LOWER(?)
              AND senha = ?
            LIMIT 1
            """,
            (
                nome,
                senha
            ),
            fetchone=True
        )

        if usuario:

            session["usuario_atual"] = obter_valor(
                usuario,
                "nome"
            )

            return redirect(
                url_for("index")
            )

        flash(
            "Usuário ou senha inválidos.",
            "danger"
        )

    return render_template(
        "login.html"
    )


# ============================================================
# CADASTRO DE USUÁRIO
# ============================================================

@app.route(
    "/cadastro_usuario",
    methods=["GET", "POST"]
)
def cadastro_usuario():

    if request.method == "POST":

        nome = request.form.get(
            "nome",
            ""
        ).strip()

        senha = request.form.get(
            "senha",
            ""
        ).strip()

        confirmar = request.form.get(
            "confirmar_senha",
            ""
        ).strip()

        if not nome or not senha:

            flash(
                "Preencha nome e senha.",
                "warning"
            )

            return redirect(
                url_for(
                    "cadastro_usuario"
                )
            )

        if confirmar and senha != confirmar:

            flash(
                "As senhas não conferem.",
                "warning"
            )

            return redirect(
                url_for(
                    "cadastro_usuario"
                )
            )

        if len(nome) < 2:

            flash(
                "O nome precisa ter pelo menos 2 caracteres.",
                "warning"
            )

            return redirect(
                url_for(
                    "cadastro_usuario"
                )
            )

        if len(senha) < 4:

            flash(
                "A senha deve ter pelo menos 4 caracteres.",
                "warning"
            )

            return redirect(
                url_for(
                    "cadastro_usuario"
                )
            )

        existe = executar(
            """
            SELECT id
            FROM usuarios
            WHERE LOWER(nome) = LOWER(%s)
            LIMIT 1
            """
            if usando_postgresql()
            else
            """
            SELECT id
            FROM usuarios
            WHERE LOWER(nome) = LOWER(?)
            LIMIT 1
            """,
            (nome,),
            fetchone=True
        )

        if existe:

            flash(
                "Esse usuário já existe.",
                "warning"
            )

            return redirect(
                url_for(
                    "cadastro_usuario"
                )
            )

        executar(
            """
            INSERT INTO usuarios
                (nome, senha, criado_em)
            VALUES
                (%s,%s,%s)
            """
            if usando_postgresql()
            else
            """
            INSERT INTO usuarios
                (nome, senha, criado_em)
            VALUES
                (?,?,?)
            """,
            (
                nome,
                senha,
                (
                    agora_utc_naive()
                    if usando_postgresql()
                    else agora_sqlite()
                )
            ),
            commit=True
        )

        flash(
            "Usuário cadastrado com sucesso.",
            "success"
        )

        return redirect(
            url_for("login")
        )

    return render_template(
        "cadastro.html"
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )


# ============================================================
# DADOS DO DASHBOARD
# ============================================================
def obter_dados_dashboard():
    """
    Centraliza os dados utilizados pelo index.html e dashboard.html.

    Cards superiores:
        - mostram a situação operacional atual.

    Indicadores do Dia:
        - consideram somente as atividades do dia atual,
          usando o horário de Brasília.

    Não altera nem exclui dados do banco.
    """

    # ========================================================
    # DATA DE HOJE
    # ========================================================

    hoje_brasilia = agora_brasil().date()

    # ========================================================
    # CARREGAR TODAS AS ATIVIDADES
    # ========================================================

    atividades_cursor = executar(
        """
        SELECT *
        FROM atividades
        ORDER BY id DESC
        """,
        fetchall=True
    )

    atividades_todas = preparar_lista_atividades(
        atividades_cursor
    )

    # ========================================================
    # FUNÇÃO AUXILIAR
    # IDENTIFICA SE A ATIVIDADE É DE HOJE
    # ========================================================

    def atividade_eh_de_hoje(item):
        """
        Verifica inicio_em primeiro.
        Se não existir, utiliza criado_em.

        Os horários armazenados no banco são convertidos
        para o horário de Brasília antes da comparação.
        """

        valor = item.get("inicio_em")

        if not valor:
            valor = item.get("criado_em")

        if not valor:
            return False

        try:
            data_brasilia = converter_para_brasil(valor)

            if data_brasilia:
                return data_brasilia.date() == hoje_brasilia

        except Exception:
            pass

        return False

    # ========================================================
    # ATIVIDADES DE HOJE
    # ========================================================

    atividades_hoje = [
        item
        for item in atividades_todas
        if atividade_eh_de_hoje(item)
    ]

    # ========================================================
    # ATIVIDADES EXIBIDAS NO PAINEL
    # ========================================================

    atividades = [
        item
        for item in atividades_todas
        if status_eh_pendente(
            item.get("status")
        )
    ]

    # ========================================================
    # REQUISIÇÕES PENDENTES
    # ========================================================

    total_req = sum(
        1
        for item in atividades_todas
        if item.get("categoria") == "Separação"
        and status_eh_pendente(
            item.get("status")
        )
    )

    # ========================================================
    # INVENTÁRIOS
    # ========================================================

    inventarios_ativos = [
        item
        for item in atividades_todas
        if item.get("categoria") == "Inventário"
        and not status_eh_arquivado(
            item.get("status")
        )
    ]

    inv_total = len(
        inventarios_ativos
    )

    inv_conc = sum(
        1
        for item in inventarios_ativos
        if status_eh_concluido(
            item.get("status")
        )
    )

    # ========================================================
    # EXPEDIÇÕES
    # ========================================================

    expedicoes_ativas = [
        item
        for item in atividades_todas
        if item.get("categoria") == "Expedição"
        and not status_eh_arquivado(
            item.get("status")
        )
    ]

    exp_total = len(
        expedicoes_ativas
    )

    exp_pend = sum(
        1
        for item in expedicoes_ativas
        if status_eh_pendente(
            item.get("status")
        )
    )

    exp_conc = sum(
        1
        for item in expedicoes_ativas
        if status_eh_concluido(
            item.get("status")
        )
    )

    # ========================================================
    # RECEBIMENTOS PENDENTES
    # ========================================================

    rec_pend = sum(
        1
        for item in atividades_todas
        if item.get("categoria") == "Recebimento"
        and status_eh_pendente(
            item.get("status")
        )
    )

    # ========================================================
    # OCORRÊNCIAS
    # ========================================================

    total_oco = sum(
        1
        for item in atividades_todas
        if str(
            item.get("prioridade", "")
        ).strip().lower() == "alta"
        and status_eh_pendente(
            item.get("status")
        )
    )

    # ========================================================
    # ATRASADOS
    # ========================================================

    total_atrasados = sum(
        1
        for item in atividades_todas
        if registro_foi_atrasado(item)
    )

    # ========================================================
    # ========================================================
    # INDICADORES DO DIA
    # ========================================================
    # ========================================================

    # --------------------------------------------------------
    # ATIVIDADES DO DIA
    # --------------------------------------------------------

    atividades_pendentes_hoje = sum(
        1
        for item in atividades_hoje
        if status_eh_pendente(
            item.get("status")
        )
    )

    atividades_concluidas_hoje = sum(
        1
        for item in atividades_hoje
        if status_eh_concluido(
            item.get("status")
        )
    )

    atividades_arquivadas_hoje = sum(
        1
        for item in atividades_hoje
        if status_eh_arquivado(
            item.get("status")
        )
    )

    # --------------------------------------------------------
    # TOTAL DE ATIVIDADES DO DIA
    #
    # Arquivadas não entram no percentual porque são
    # atividades que já foram concluídas e retiradas
    # do acompanhamento operacional.
    # --------------------------------------------------------

    total_atividades_hoje = (
        atividades_pendentes_hoje
        + atividades_concluidas_hoje
    )

    # --------------------------------------------------------
    # INDICADOR DE ATENDIMENTO DO DIA
    # --------------------------------------------------------

    if total_atividades_hoje > 0:

        perc_atendidas = round(
            (
                atividades_concluidas_hoje
                / total_atividades_hoje
            ) * 100
        )

    else:

        perc_atendidas = 0

    # ========================================================
    # INVENTÁRIO DO DIA
    # ========================================================

    inventarios_hoje = [
        item
        for item in atividades_hoje
        if item.get("categoria") == "Inventário"
        and not status_eh_arquivado(
            item.get("status")
        )
    ]

    inv_total_hoje = len(
        inventarios_hoje
    )

    inv_conc_hoje = sum(
        1
        for item in inventarios_hoje
        if status_eh_concluido(
            item.get("status")
        )
    )

    if inv_total_hoje > 0:

        perc_inventario = round(
            (
                inv_conc_hoje
                / inv_total_hoje
            ) * 100
        )

    else:

        perc_inventario = 0

    # ========================================================
    # EXPEDIÇÃO DO DIA
    # ========================================================

    expedicoes_hoje = [
        item
        for item in atividades_hoje
        if item.get("categoria") == "Expedição"
        and not status_eh_arquivado(
            item.get("status")
        )
    ]

    exp_total_hoje = len(
        expedicoes_hoje
    )

    exp_conc_hoje = sum(
        1
        for item in expedicoes_hoje
        if status_eh_concluido(
            item.get("status")
        )
    )

    if exp_total_hoje > 0:

        perc_expedicao = round(
            (
                exp_conc_hoje
                / exp_total_hoje
            ) * 100
        )

    else:

        perc_expedicao = 0

    # ========================================================
    # USUÁRIOS
    # ========================================================

    usuarios_cursor = executar(
        """
        SELECT *
        FROM usuarios
        ORDER BY nome
        """,
        fetchall=True
    )

    usuarios = [
        linha_para_dict(item)
        for item in usuarios_cursor
    ]

    # ========================================================
    # CHAT
    # ========================================================

    chat_cursor = executar(
        """
        SELECT *
        FROM chat
        ORDER BY id DESC
        LIMIT 15
        """,
        fetchall=True
    )

    chat = [
        linha_para_dict(item)
        for item in chat_cursor
    ]

    chat.reverse()

    # ========================================================
    # RETORNO
    # ========================================================

    return {
        # ----------------------------------------------------
        # ATIVIDADES DO PAINEL
        # ----------------------------------------------------

        "atividades": atividades,

        # ----------------------------------------------------
        # USUÁRIOS / CHAT
        # ----------------------------------------------------

        "usuarios": usuarios,
        "chat": chat,

        # ----------------------------------------------------
        # CARDS SUPERIORES
        # ----------------------------------------------------

        "total_req": total_req,

        "inv_conc": inv_conc,
        "inv_total": inv_total,

        "exp_pend": exp_pend,

        "rec_pend": rec_pend,

        "total_oco": total_oco,

        "total_atrasados": total_atrasados,

        # ----------------------------------------------------
        # INDICADORES DO DIA
        # ----------------------------------------------------

        "perc_atendidas": perc_atendidas,

        "perc_inventario": perc_inventario,

        "perc_expedicao": perc_expedicao,

        # ----------------------------------------------------
        # RESUMO DO DIA
        # ----------------------------------------------------

        "atividades_concluidas": atividades_concluidas_hoje,

        "atividades_pendentes": atividades_pendentes_hoje,

        "atividades_arquivadas": atividades_arquivadas_hoje,

        "total_atividades": total_atividades_hoje,

        # ----------------------------------------------------
        # DADOS AUXILIARES DO DIA
        # ----------------------------------------------------

        "inv_conc_hoje": inv_conc_hoje,
        "inv_total_hoje": inv_total_hoje,

        "exp_conc_hoje": exp_conc_hoje,
        "exp_total_hoje": exp_total_hoje,
    }

@app.route("/", methods=["GET", "POST"])
def index():

    if "usuario_atual" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":

        usuario_atual = session["usuario_atual"]
        acao_chat = request.form.get("acao_chat")

        # =========================
        # ENVIO DE MENSAGEM NO CHAT
        # =========================
        if acao_chat == "enviar":

            mensagem = request.form.get(
                "mensagem",
                ""
            ).strip()

            if mensagem:

                executar(
                    """
                    INSERT INTO chat
                        (usuario, mensagem, criado_em)
                    VALUES
                        (%s, %s, %s)
                    """
                    if usando_postgresql()
                    else
                    """
                    INSERT INTO chat
                        (usuario, mensagem, criado_em)
                    VALUES
                        (?, ?, ?)
                    """,
                    (
                        usuario_atual,
                        mensagem,
                        (
                            agora_utc_naive()
                            if usando_postgresql()
                            else agora_sqlite()
                        )
                    ),
                    commit=True
                )

            return redirect(url_for("index"))

        # =========================
        # NOVA ATIVIDADE
        # =========================

        num_requisicao = normalizar_requisicao(
            request.form.get("num_requisicao")
        )

        atividade = request.form.get(
            "atividade",
            ""
        ).strip()

        descricao = request.form.get(
            "descricao",
            ""
        ).strip()

        categoria = request.form.get(
            "categoria",
            "Separação"
        ).strip()

        responsavel = request.form.get(
            "responsavel",
            usuario_atual
        ).strip()

        prioridade = request.form.get(
            "prioridade",
            "Baixa"
        ).strip()

        prazo = request.form.get(
            "prazo",
            ""
        ).strip()

        # =========================
        # VALIDAÇÕES
        # =========================

        if categoria not in CATEGORIAS_VALIDAS:
            categoria = "Separação"

        if prioridade not in PRIORIDADES_VALIDAS:
            prioridade = "Baixa"

        if not atividade:

            flash(
                "Informe a atividade.",
                "warning"
            )

            return redirect(
                url_for("index")
            )

        if categoria == "Separação" and not num_requisicao:

            flash(
                "A Separação precisa de um número de requisição.",
                "warning"
            )

            return redirect(
                url_for("index")
            )

        if num_requisicao and requisicao_duplicada(
            num_requisicao
        ):

            flash(
                f"A requisição {num_requisicao} já possui uma atividade ativa.",
                "warning"
            )

            return redirect(
                url_for("index")
            )

        # =========================
        # HORÁRIO DE INÍCIO
        # =========================

        inicio_em = None

        if categoria == "Separação":

            inicio_em = (
                agora_utc_naive()
                if usando_postgresql()
                else agora_sqlite()
            )

        agora_criacao = (
            agora_utc_naive()
            if usando_postgresql()
            else agora_sqlite()
        )

        # =========================
        # SALVAR ATIVIDADE
        # =========================

        executar(
            """
            INSERT INTO atividades
            (
                num_requisicao,
                atividade,
                descricao,
                categoria,
                responsavel,
                prioridade,
                prazo,
                status,
                inicio_em,
                criado_em
            )
            VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            if usando_postgresql()
            else
            """
            INSERT INTO atividades
            (
                num_requisicao,
                atividade,
                descricao,
                categoria,
                responsavel,
                prioridade,
                prazo,
                status,
                inicio_em,
                criado_em
            )
            VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                num_requisicao or None,
                atividade,
                descricao,
                categoria,
                responsavel,
                prioridade,
                prazo or None,
                STATUS_PENDENTE,
                inicio_em,
                agora_criacao
            ),
            commit=True
        )

        flash(
            "Atividade criada com sucesso.",
            "success"
        )

        return redirect(
            url_for("index")
        )

    # =========================
    # DADOS DO DASHBOARD
    # =========================

    dados = obter_dados_dashboard()

    return render_template(
        "index.html",
        **dados
    )
@app.route("/editar/<int:id>", methods=["POST"])
def editar(id):

    if "usuario_atual" not in session:
        return redirect(url_for("login"))

    num_requisicao = normalizar_requisicao(
        request.form.get("num_requisicao")
    )

    atividade = request.form.get(
        "atividade",
        ""
    ).strip()

    descricao = request.form.get(
        "descricao",
        ""
    ).strip()

    categoria = request.form.get(
        "categoria",
        "Separação"
    ).strip()

    responsavel = request.form.get(
        "responsavel",
        session["usuario_atual"]
    ).strip()

    prioridade = request.form.get(
        "prioridade",
        "Baixa"
    ).strip()

    prazo = request.form.get(
        "prazo",
        ""
    ).strip()

    # =========================
    # VALIDAÇÕES
    # =========================

    if not atividade:
        flash(
            "Informe a atividade.",
            "warning"
        )
        return redirect(url_for("index"))

    if categoria not in CATEGORIAS_VALIDAS:
        categoria = "Separação"

    if prioridade not in PRIORIDADES_VALIDAS:
        prioridade = "Baixa"

    if categoria == "Separação" and not num_requisicao:
        flash(
            "A Separação precisa de um número de requisição.",
            "warning"
        )
        return redirect(url_for("index"))

    # =========================
    # ATUALIZA A ATIVIDADE
    # =========================
    #
    # Os campos abaixo NÃO serão alterados:
    #
    # inicio_em
    # concluido_em
    # criado_em
    # status
    # encerrado_por
    #
    # Apenas os dados editáveis da atividade
    # serão atualizados.
    # =========================

    executar(
        """
        UPDATE atividades
        SET
            num_requisicao = %s,
            atividade = %s,
            descricao = %s,
            categoria = %s,
            responsavel = %s,
            prioridade = %s,
            prazo = %s
        WHERE id = %s
        """
        if usando_postgresql()
        else
        """
        UPDATE atividades
        SET
            num_requisicao = ?,
            atividade = ?,
            descricao = ?,
            categoria = ?,
            responsavel = ?,
            prioridade = ?,
            prazo = ?
        WHERE id = ?
        """,
        (
            num_requisicao or None,
            atividade,
            descricao,
            categoria,
            responsavel,
            prioridade,
            prazo or None,
            id
        ),
        commit=True
    )

    flash(
        "Atividade atualizada com sucesso.",
        "success"
    )

    return redirect(
        url_for("index")
    )

@app.route("/editar/<int:id>", methods=["GET"])
def editar_form(id):

    if "usuario_atual" not in session:
        return redirect(url_for("login"))

    atividade = executar(
        """
        SELECT *
        FROM atividades
        WHERE id = %s
        """
        if usando_postgresql()
        else
        """
        SELECT *
        FROM atividades
        WHERE id = ?
        """,
        (id,),
        fetchone=True
    )

    if not atividade:
        flash(
            "Atividade não encontrada.",
            "warning"
        )
        return redirect(
            url_for("index")
        )

    atividade = linha_para_dict(
        atividade
    )

    usuarios_cursor = executar(
        """
        SELECT *
        FROM usuarios
        ORDER BY nome
        """,
        fetchall=True
    )

    usuarios = [
        linha_para_dict(item)
        for item in usuarios_cursor
    ]

    return render_template(
        "editar.html",
        atividade=atividade,
        usuarios=usuarios
    )
@app.route(
    "/dashboard",
    methods=["GET"]
)
def dashboard():

    if "usuario_atual" not in session:

        return redirect(
            url_for("login")
        )

    dados = obter_dados_dashboard()

    return render_template(
        "dashboard.html",
        **dados
    )


# ============================================================
# ATRASADOS
# ============================================================

@app.route("/atrasados")
def atrasados():

    if "usuario_atual" not in session:

        return redirect(
            url_for("login")
        )

    return redirect(
        url_for(
            "relatorios",
            filtro="atrasados"
        )
    )

# ============================================================
# INDICADORES
# ============================================================

@app.route("/indicadores")
def indicadores():

    if "usuario_atual" not in session:

        return redirect(
            url_for("login")
        )

    arquivar_atividades_expiradas()

    atividades = buscar_atividades_historico()

    indicadores_gerais = calcular_indicadores(
        atividades
    )

    indicadores_dia = calcular_indicadores_do_dia(
        atividades
    )

    return render_template(
        "indicadores.html",

        total_geral=indicadores_gerais[
            "total_geral"
        ],

        concluidas=indicadores_gerais[
            "atividades_finalizadas"
        ],

        atividades_pendentes=indicadores_gerais[
            "atividades_pendentes"
        ],

        atividades_andamento=indicadores_gerais[
            "atividades_andamento"
        ],

        atividades_concluidas=indicadores_gerais[
            "atividades_concluidas"
        ],

        atividades_arquivadas=indicadores_gerais[
            "atividades_arquivadas"
        ],

        perc_atendidas=indicadores_dia[
            "perc_atendidas"
        ],

        perc_inventario=indicadores_dia[
            "perc_inventario"
        ],

        perc_expedicao=indicadores_dia[
            "perc_expedicao"
        ],

        inventario_total=indicadores_gerais[
            "inventario_total"
        ],

        inventario_concluido=indicadores_gerais[
            "inventario_concluido"
        ],

        expedicao_total=indicadores_gerais[
            "expedicao_total"
        ],

        expedicao_concluida=indicadores_gerais[
            "expedicao_concluida"
        ],

        indicadores_dia=indicadores_dia
    )


# ============================================================
# RELATÓRIOS
# ============================================================

@app.route("/relatorios")
def relatorios():

    if "usuario_atual" not in session:

        return redirect(
            url_for("login")
        )

    arquivar_atividades_expiradas()

    filtro = request.args.get(
        "filtro",
        "todos"
    )

    data_param = request.args.get(
        "data",
        ""
    ).strip()

    if not data_param:

        data_relatorio = agora_brasil().date()

        data_param = data_relatorio.isoformat()

    else:

        try:

            data_relatorio = datetime.strptime(
                data_param,
                "%Y-%m-%d"
            ).date()

        except ValueError:

            data_relatorio = agora_brasil().date()

            data_param = data_relatorio.isoformat()

    inicio_brasilia = datetime.combine(
        data_relatorio,
        datetime.min.time(),
        tzinfo=FUSO_BRASIL
    )

    fim_brasilia = (
        inicio_brasilia
        + timedelta(days=1)
    )

    if usando_postgresql():

        inicio_busca = (
            inicio_brasilia
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )

        fim_busca = (
            fim_brasilia
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )

        sql = """
            SELECT *
            FROM atividades
            WHERE COALESCE(inicio_em, criado_em) >= %s
              AND COALESCE(inicio_em, criado_em) < %s
            ORDER BY
                COALESCE(inicio_em, criado_em) ASC,
                id ASC
        """

    else:

        inicio_busca = inicio_brasilia.replace(
            tzinfo=None
        )

        fim_busca = fim_brasilia.replace(
            tzinfo=None
        )

        sql = """
            SELECT *
            FROM atividades
            WHERE COALESCE(inicio_em, criado_em) >= ?
              AND COALESCE(inicio_em, criado_em) < ?
            ORDER BY
                COALESCE(inicio_em, criado_em) ASC,
                id ASC
        """

    todas = executar(
        sql,
        (
            inicio_busca,
            fim_busca
        ),
        fetchall=True
    )

    todas = preparar_lista_atividades(
        todas
    )

    if filtro == "pendentes":

        itens = [
            item
            for item in todas
            if status_eh_pendente(
                item.get("status")
            )
        ]

    elif filtro == "andamento":

        itens = [
            item
            for item in todas
            if status_eh_andamento(
                item.get("status")
            )
        ]

    elif filtro == "concluidos":

        itens = [
            item
            for item in todas
            if status_eh_concluido(
                item.get("status")
            )
        ]

    elif filtro == "arquivados":

        itens = [
            item
            for item in todas
            if status_eh_arquivado(
                item.get("status")
            )
        ]

    elif filtro == "atrasados":

        itens = [
            item
            for item in todas
            if registro_foi_atrasado(item)
        ]

    else:

        itens = todas

    total_todos = len(todas)

    total_pendentes = sum(
        1
        for item in todas
        if status_eh_pendente(
            item.get("status")
        )
    )

    total_andamento = sum(
        1
        for item in todas
        if status_eh_andamento(
            item.get("status")
        )
    )

    total_concluidos = sum(
        1
        for item in todas
        if status_eh_concluido(
            item.get("status")
        )
    )

    total_arquivados = sum(
        1
        for item in todas
        if status_eh_arquivado(
            item.get("status")
        )
    )

    total_atrasados = sum(
        1
        for item in todas
        if registro_foi_atrasado(item)
    )

    return render_template(
        "relatorios.html",

        itens=itens,

        filtro=filtro,

        data_relatorio=data_param,

        data_formatada=data_relatorio.strftime(
            "%d/%m/%Y"
        ),

        total_todos=total_todos,

        total_pendentes=total_pendentes,

        total_andamento=total_andamento,

        total_concluidos=total_concluidos,

        total_arquivados=total_arquivados,

        total_atrasados=total_atrasados,

        usuario_atual=session[
            "usuario_atual"
        ]
    )


# ============================================================
# MÓDULOS
# ============================================================
@app.route("/modulo/<path:nome>",
    methods=["GET", "POST"]
)
def modulo(nome):

    if "usuario_atual" not in session:
        return redirect(
            url_for("login")
        )

    nome_normalizado = normalizar_nome_modulo(
        nome
    )

    # --------------------------------------------------------
    # CONFIGURAÇÕES
    # --------------------------------------------------------

    if nome_normalizado == "configuracoes":

        return render_template(
            "configuracoes.html",
            usuario_atual=session[
                "usuario_atual"
            ]
        )

    # --------------------------------------------------------
    # INDICADORES
    # --------------------------------------------------------

    if nome_normalizado == "indicadores":

        return redirect(
            url_for("indicadores")
        )

    # --------------------------------------------------------
    # RELATÓRIOS
    # --------------------------------------------------------

    if nome_normalizado == "relatorios":

        return redirect(
            url_for("relatorios")
        )

    # --------------------------------------------------------
    # CADASTROS
    # --------------------------------------------------------

    if nome_normalizado == "cadastros":

        usuarios = executar(
            """
            SELECT id, nome
            FROM usuarios
            ORDER BY nome ASC
            """,
            fetchall=True
        )

        return render_template(
            "cadastros.html",

            usuarios=linhas_para_dict(
                usuarios
            ),

            usuario_atual=session[
                "usuario_atual"
            ]
        )

    # --------------------------------------------------------
    # MELHORIAS / PDCA
    # ------------------------------------------------------
    if (
        "melhoria" in nome_normalizado
        or "pdca" in nome_normalizado
    ):

        if request.method == "POST":

            titulo = request.form.get(
                "titulo",
                ""
            ).strip()

            descricao = request.form.get(
                "descricao",
                ""
            ).strip()

            etapa = request.form.get(
                "etapa",
                "PDCA"
            ).strip()

            status = request.form.get(
                "status",
                "A Fazer"
            ).strip()

            if not titulo:

                flash(
                    "Informe o título da melhoria.",
                    "warning"
                )

                return redirect(
                    url_for(
                        "modulo",
                        nome="Melhorias / PDCA"
                    )
                )

            agora_melhoria = (
                agora_utc_naive()
                if usando_postgresql()
                else agora_sqlite()
            )

            executar(
                """
                INSERT INTO melhorias
                (
                    titulo,
                    descricao,
                    etapa,
                    autor,
                    status,
                    criado_em
                )
                VALUES
                (%s,%s,%s,%s,%s,%s)
                """
                if usando_postgresql()
                else
                """
                INSERT INTO melhorias
                (
                    titulo,
                    descricao,
                    etapa,
                    autor,
                    status,
                    criado_em
                )
                VALUES
                (?,?,?,?,?,?)
                """,
                (
                    titulo,
                    descricao,
                    etapa,
                    session["usuario_atual"],
                    status,
                    agora_melhoria
                ),
                commit=True
            )

            flash(
                "Melhoria cadastrada com sucesso.",
                "success"
            )

            return redirect(
                url_for(
                    "modulo",
                    nome="Melhorias / PDCA"
                )
            )

        melhorias = executar(
            """
            SELECT
                id,
                titulo,
                descricao,
                etapa,
                autor,
                status,
                criado_em
            FROM melhorias
            WHERE LOWER(
                COALESCE(status, '')
            ) <> 'arquivado'
            ORDER BY id DESC
            """,
            fetchall=True
        )

        return render_template(
            "melhorias.html",
            melhorias=linhas_para_dict(
                melhorias
            ),
            usuario_atual=session[
                "usuario_atual"
            ]
        )

# ============================================================
# EDITAR
# ============================================================


@app.route ("/concluir/<int:id>",
    methods=["POST", "GET"]
)
def concluir(id):

    if "usuario_atual" not in session:

        return redirect(
            url_for("login")
        )

    atividade = executar(
        """
        SELECT *
        FROM atividades
        WHERE id = %s
        """
        if usando_postgresql()
        else
        """
        SELECT *
        FROM atividades
        WHERE id = ?
        """,
        (id,),
        fetchone=True
    )

    if atividade is None:

        flash(
            "Atividade não encontrada.",
            "warning"
        )

        return redirect(
            url_for("index")
        )

    status_atual = normalizar_status(
        obter_valor(
            atividade,
            "status",
            ""
        )
    )

    if status_atual in (
        "concluido",
        "concluida",
        "arquivado"
    ):

        flash(
            "Essa atividade já está encerrada.",
            "info"
        )

        return redirect(
            request.referrer
            or url_for("index")
        )

    agora = (
        agora_utc_naive()
        if usando_postgresql()
        else agora_sqlite()
    )

    executar(
        """
        UPDATE atividades
        SET
            status = 'Concluído',
            concluido_em = %s,
            encerrado_por = %s
        WHERE id = %s
        """
        if usando_postgresql()
        else
        """
        UPDATE atividades
        SET
            status = 'Concluído',
            concluido_em = ?,
            encerrado_por = ?
        WHERE id = ?
        """,
        (
            agora,
            session[
                "usuario_atual"
            ],
            id
        ),
        commit=True
    )

    # --------------------------------------------------------
    # SEPARAÇÃO -> EXPEDIÇÃO
    # --------------------------------------------------------

    num_requisicao = normalizar_requisicao(
        obter_valor(
            atividade,
            "num_requisicao"
        )
    )

    if (
        categoria_eh(
            atividade,
            "Separação"
        )
        and num_requisicao
    ):

        registros = executar(
            """
            SELECT *
            FROM atividades
            """,
            fetchall=True
        )

        expedicao_existente = None

        for item in registros:

            numero = normalizar_requisicao(
                obter_valor(
                    item,
                    "num_requisicao"
                )
            )

            if numero != num_requisicao:
                continue

            if not categoria_eh(
                item,
                "Expedição"
            ):
                continue

            if not status_eh_ativo(
                obter_valor(
                    item,
                    "status"
                )
            ):
                continue

            expedicao_existente = item
            break

        if expedicao_existente is None:

            descricao = (
                "Expedição gerada automaticamente "
                "após conclusão da Separação "
                f"da requisição {num_requisicao}."
            )

            executar(
                """
                INSERT INTO atividades
                (
                    num_requisicao,
                    atividade,
                    descricao,
                    categoria,
                    responsavel,
                    prioridade,
                    prazo,
                    status,
                    inicio_em,
                    criado_em
                )
                VALUES
                (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """
                if usando_postgresql()
                else
                """
                INSERT INTO atividades
                (
                    num_requisicao,
                    atividade,
                    descricao,
                    categoria,
                    responsavel,
                    prioridade,
                    prazo,
                    status,
                    inicio_em,
                    criado_em
                )
                VALUES
                (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    num_requisicao,
                    "Expedição",
                    descricao,
                    "Expedição",
                    obter_valor(
                        atividade,
                        "responsavel",
                        session[
                            "usuario_atual"
                        ]
                    ),
                    obter_valor(
                        atividade,
                        "prioridade",
                        "Baixa"
                    ),
                    obter_valor(
                        atividade,
                        "prazo"
                    ),
                    STATUS_PENDENTE,
                    agora,
                    agora
                ),
                commit=True
            )

            flash(
                "Separação concluída e Expedição criada automaticamente.",
                "success"
            )

        else:

            flash(
                "Separação concluída. Já existia uma Expedição ativa para essa requisição.",
                "info"
            )

    else:

        flash(
            "Atividade concluída com sucesso.",
            "success"
        )

    return redirect(
        request.referrer
        or url_for("index")
    )


# ============================================================
# ARQUIVAR
# ============================================================

@app.route(
    "/arquivar/<int:id>",
    methods=["POST", "GET"]
)
def arquivar(id):

    if "usuario_atual" not in session:

        return redirect(
            url_for("login")
        )

    atividade = executar(
        """
        SELECT *
        FROM atividades
        WHERE id = %s
        """
        if usando_postgresql()
        else
        """
        SELECT *
        FROM atividades
        WHERE id = ?
        """,
        (id,),
        fetchone=True
    )

    if atividade is None:

        flash(
            "Registro não encontrado.",
            "warning"
        )

        return redirect(
            url_for("relatorios")
        )

    if status_eh_arquivado(
        obter_valor(
            atividade,
            "status"
        )
    ):

        flash(
            "Esse registro já está arquivado.",
            "info"
        )

        return redirect(
            request.referrer
            or url_for("relatorios")
        )

    executar(
        """
        UPDATE atividades
        SET
            status = 'Arquivado'
        WHERE id = %s
        """
        if usando_postgresql()
        else
        """
        UPDATE atividades
        SET
            status = 'Arquivado'
        WHERE id = ?
        """,
        (id,),
        commit=True
    )

    flash(
        "Registro arquivado. Ele continua disponível em Relatórios > Arquivados.",
        "success"
    )

    return redirect(
        request.referrer
        or url_for("relatorios")
    )


# ============================================================
# DELETAR - COMPATIBILIDADE
# ============================================================

@app.route(
    "/deletar/<int:id>",
    methods=["POST", "GET"]
)
def deletar(id):

    return arquivar(id)


# ============================================================
# ESTOQUE - CADASTRO
# ============================================================

@app.route(
    "/salvar_estoque",
    methods=["POST"]
)
def salvar_estoque():

    if "usuario_atual" not in session:

        return redirect(
            url_for("login")
        )

    codigo = request.form.get(
        "codigo",
        ""
    ).strip()

    descricao = request.form.get(
        "descricao",
        ""
    ).strip()

    quantidade_texto = request.form.get(
        "quantidade",
        "0"
    ).strip()

    try:

        quantidade = int(
            float(
                quantidade_texto or 0
            )
        )

    except Exception:

        quantidade = 0

    if not codigo and not descricao:

        flash(
            "Informe o código ou a descrição do item.",
            "warning"
        )

        return redirect(
            url_for(
                "modulo",
                nome="Estoque"
            )
        )

    quantidade = max(
        0,
        quantidade
    )

    executar(
        """
        INSERT INTO estoque
        (
            codigo,
            descricao,
            quantidade,
            criado_em
        )
        VALUES
        (%s,%s,%s,%s)
        """
        if usando_postgresql()
        else
        """
        INSERT INTO estoque
        (
            codigo,
            descricao,
            quantidade,
            criado_em
        )
        VALUES
        (?,?,?,?)
        """,
        (
            codigo,
            descricao,
            quantidade,
            (
                agora_utc_naive()
                if usando_postgresql()
                else agora_sqlite()
            )
        ),
        commit=True
    )

    flash(
        "Item adicionado ao estoque.",
        "success"
    )

    return redirect(
        url_for(
            "modulo",
            nome="Estoque"
        )
    )


# ============================================================
# ESTOQUE - EXCLUSÃO
# ============================================================

@app.route(
    "/deletar_estoque/<int:id>",
    methods=["POST", "GET"]
)
def deletar_estoque(id):

    if "usuario_atual" not in session:

        return redirect(
            url_for("login")
        )

    executar(
        """
        DELETE FROM estoque
        WHERE id = %s
        """
        if usando_postgresql()
        else
        """
        DELETE FROM estoque
        WHERE id = ?
        """,
        (id,),
        commit=True
    )

    flash(
        "Item do estoque removido.",
        "success"
    )

    return redirect(
        url_for(
            "modulo",
            nome="Estoque"
        )
    )


# ============================================================
# MELHORIAS - ARQUIVAR
# ============================================================

@app.route(
    "/deletar_melhoria/<int:id>",
    methods=["POST", "GET"]
)
def deletar_melhoria(id):

    if "usuario_atual" not in session:

        return redirect(
            url_for("login")
        )

    executar(
        """
        UPDATE melhorias
        SET status = 'Arquivado'
        WHERE id = %s
        """
        if usando_postgresql()
        else
        """
        UPDATE melhorias
        SET status = 'Arquivado'
        WHERE id = ?
        """,
        (id,),
        commit=True
    )

    flash(
        "Melhoria arquivada.",
        "success"
    )

    return redirect(
        url_for(
            "modulo",
            nome="Melhorias / PDCA"
        )
    )


# ============================================================
# RELATÓRIO PDF
# ============================================================

@app.route("/relatorio_pdf")
def relatorio_pdf():

    if "usuario_atual" not in session:

        return redirect(
            url_for("login")
        )

    data_param = request.args.get(
        "data",
        ""
    ).strip()

    if not data_param:

        data_relatorio = agora_brasil().date()

        data_param = data_relatorio.isoformat()

    else:

        try:

            data_relatorio = datetime.strptime(
                data_param,
                "%Y-%m-%d"
            ).date()

        except ValueError:

            data_relatorio = agora_brasil().date()

            data_param = data_relatorio.isoformat()

    inicio_brasilia = datetime.combine(
        data_relatorio,
        datetime.min.time(),
        tzinfo=FUSO_BRASIL
    )

    fim_brasilia = (
        inicio_brasilia
        + timedelta(days=1)
    )

    if usando_postgresql():

        inicio_busca = (
            inicio_brasilia
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )

        fim_busca = (
            fim_brasilia
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )

        sql = """
            SELECT *
            FROM atividades
            WHERE COALESCE(inicio_em, criado_em) >= %s
              AND COALESCE(inicio_em, criado_em) < %s
            ORDER BY
                COALESCE(inicio_em, criado_em) ASC,
                id ASC
        """

    else:

        inicio_busca = inicio_brasilia.replace(
            tzinfo=None
        )

        fim_busca = fim_brasilia.replace(
            tzinfo=None
        )

        sql = """
            SELECT *
            FROM atividades
            WHERE COALESCE(inicio_em, criado_em) >= ?
              AND COALESCE(inicio_em, criado_em) < ?
            ORDER BY
                COALESCE(inicio_em, criado_em) ASC,
                id ASC
        """

    itens = executar(
        sql,
        (
            inicio_busca,
            fim_busca
        ),
        fetchall=True
    )

    itens = preparar_lista_atividades(
        itens
    )

    total = len(itens)

    concluidas = sum(
        1
        for item in itens
        if status_eh_concluido(
            item.get("status")
        )
    )

    pendentes = sum(
        1
        for item in itens
        if status_eh_pendente(
            item.get("status")
        )
    )

    arquivadas = sum(
        1
        for item in itens
        if status_eh_arquivado(
            item.get("status")
        )
    )

    buffer = BytesIO()

    documento = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=25,
        leftMargin=25,
        topMargin=25,
        bottomMargin=25
    )

    estilos = getSampleStyleSheet()

    elementos = []

    elementos.append(
        Paragraph(
            "RELATÓRIO DIÁRIO - ALMOXARIFADO",
            estilos["Title"]
        )
    )

    elementos.append(
        Paragraph(
            f"Data: {data_relatorio.strftime('%d/%m/%Y')}",
            estilos["Normal"]
        )
    )

    elementos.append(
        Spacer(1, 10)
    )

    elementos.append(
        Paragraph(
            f"Total: {total} &nbsp;&nbsp; "
            f"Concluídas: {concluidas} &nbsp;&nbsp; "
            f"Pendentes: {pendentes} &nbsp;&nbsp; "
            f"Arquivadas: {arquivadas}",
            estilos["Normal"]
        )
    )

    elementos.append(
        Spacer(1, 12)
    )

    dados = [[
        "Req.",
        "Atividade",
        "Categoria",
        "Responsável",
        "Prioridade",
        "Início",
        "Conclusão",
        "Status"
    ]]

    for item in itens:

        dados.append([
            str(
                item.get(
                    "num_requisicao"
                )
                or "-"
            ),

            str(
                item.get(
                    "atividade"
                )
                or "-"
            ),

            str(
                item.get(
                    "categoria"
                )
                or "-"
            ),

            str(
                item.get(
                    "responsavel"
                )
                or "-"
            ),

            str(
                item.get(
                    "prioridade"
                )
                or "-"
            ),

            str(
                item.get(
                    "inicio_formatado"
                )
                or "-"
            ),

            str(
                item.get(
                    "concluido_formatado"
                )
                or "-"
            ),

            str(
                item.get(
                    "status"
                )
                or "-"
            )
        ])

    if len(dados) == 1:

        dados.append([
            "-",
            "Nenhuma atividade encontrada para esta data.",
            "-",
            "-",
            "-",
            "-",
            "-",
            "-"
        ])

    tabela = Table(
        dados,
        repeatRows=1,
        colWidths=[
            55,
            150,
            90,
            115,
            65,
            95,
            95,
            75
        ]
    )

    tabela.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor("#212529")
            ),

            (
                "TEXTCOLOR",
                (0, 0),
                (-1, 0),
                colors.white
            ),

            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.grey
            ),

            (
                "FONTNAME",
                (0, 0),
                (-1, 0),
                "Helvetica-Bold"
            ),

            (
                "FONTSIZE",
                (0, 0),
                (-1, -1),
                7
            ),

            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "MIDDLE"
            ),

            (
                "ROWBACKGROUNDS",
                (0, 1),
                (-1, -1),
                [
                    colors.white,
                    colors.HexColor("#f4f4f4")
                ]
            )
        ])
    )

    elementos.append(
        tabela
    )

    elementos.append(
        Spacer(1, 10)
    )

    elementos.append(
        Paragraph(
            "Relatório gerado pelo sistema Almoxarifado Valenet.",
            estilos["Normal"]
        )
    )

    documento.build(
        elementos
    )

    buffer.seek(0)

    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=(
            f"relatorio_almoxarifado_{data_param}.pdf"
        )
    )


# ============================================================
# EXPORTAR ESTOQUE
# ============================================================

@app.route("/exportar_estoque")
def exportar_estoque():

    if "usuario_atual" not in session:

        return redirect(
            url_for("login")
        )

    try:

        itens = executar(
            """
            SELECT
                codigo,
                descricao,
                quantidade,
                criado_em
            FROM estoque
            ORDER BY id DESC
            """,
            fetchall=True
        )

        registros = []

        for item in itens:

            registros.append({
                "Código": obter_valor(
                    item,
                    "codigo",
                    ""
                ),

                "Descrição": obter_valor(
                    item,
                    "descricao",
                    ""
                ),

                "Quantidade": obter_valor(
                    item,
                    "quantidade",
                    0
                ),

                "Cadastrado em":
                    formatar_data_hora(
                        obter_valor(
                            item,
                            "criado_em"
                        )
                    )
            })

        df = pd.DataFrame(
            registros
        )

        arquivo = BytesIO()

        with pd.ExcelWriter(
            arquivo,
            engine="openpyxl"
        ) as writer:

            df.to_excel(
                writer,
                index=False,
                sheet_name="Estoque"
            )

        arquivo.seek(0)

        return send_file(
            arquivo,
            mimetype=(
                "application/vnd.openxmlformats-"
                "officedocument.spreadsheetml.sheet"
            ),
            as_attachment=True,
            download_name=(
                "estoque_almoxarifado.xlsx"
            )
        )

    except Exception as erro:

        flash(
            f"Erro ao gerar Excel do estoque: {erro}",
            "danger"
        )

        return redirect(
            url_for(
                "modulo",
                nome="Estoque"
            )
        )


# ============================================================
# IMPORTAR ESTOQUE
# ============================================================

@app.route(
    "/importar_estoque",
    methods=["POST"]
)
def importar_estoque():

    if "usuario_atual" not in session:

        return redirect(
            url_for("login")
        )

    arquivo = request.files.get(
        "arquivo"
    )

    if (
        not arquivo
        or not arquivo.filename
    ):

        flash(
            "Selecione um arquivo.",
            "warning"
        )

        return redirect(
            url_for(
                "modulo",
                nome="Estoque"
            )
        )

    nome = (
        arquivo.filename
        .lower()
        .strip()
    )

    try:

        if nome.endswith(".csv"):

            try:

                df = pd.read_csv(
                    arquivo
                )

            except Exception:

                arquivo.stream.seek(0)

                df = pd.read_csv(
                    arquivo,
                    sep=";"
                )

        elif nome.endswith(".xlsx"):

            df = pd.read_excel(
                arquivo,
                engine="openpyxl"
            )

        elif nome.endswith(".xls"):

            try:

                df = pd.read_excel(
                    arquivo,
                    engine="xlrd"
                )

            except Exception:

                flash(
                    "Não foi possível ler o arquivo .xls. "
                    "Prefira salvar o arquivo como .xlsx.",
                    "warning"
                )

                return redirect(
                    url_for(
                        "modulo",
                        nome="Estoque"
                    )
                )

        else:

            flash(
                "Formato não suportado. Use XLSX, XLS ou CSV.",
                "danger"
            )

            return redirect(
                url_for(
                    "modulo",
                    nome="Estoque"
                )
            )

        if df.empty:

            flash(
                "O arquivo não possui registros.",
                "warning"
            )

            return redirect(
                url_for(
                    "modulo",
                    nome="Estoque"
                )
            )

        # ----------------------------------------------------
        # NORMALIZAÇÃO DAS COLUNAS
        # ----------------------------------------------------

        df.columns = [
            normalizar_texto(
                coluna
            )
            for coluna in df.columns
        ]

        coluna_codigo = None
        coluna_descricao = None
        coluna_quantidade = None

        for coluna in df.columns:

            if coluna in [
                "codigo",
                "cod",
                "item",
                "codigo do item"
            ]:

                coluna_codigo = coluna

            if coluna in [
                "descricao",
                "produto",
                "material",
                "nome"
            ]:

                coluna_descricao = coluna

            if coluna in [
                "quantidade",
                "qtd",
                "qtde",
                "saldo",
                "estoque"
            ]:

                coluna_quantidade = coluna

        if coluna_codigo is None and len(df.columns) >= 1:
            coluna_codigo = df.columns[0]

        if coluna_descricao is None and len(df.columns) >= 2:
            coluna_descricao = df.columns[1]

        if coluna_quantidade is None and len(df.columns) >= 3:
            coluna_quantidade = df.columns[2]

        quantidade_importada = 0

        for _, linha in df.iterrows():

            codigo = ""

            if coluna_codigo:

                valor = linha.get(
                    coluna_codigo
                )

                if pd.notna(valor):

                    codigo = str(
                        valor
                    ).strip()

            descricao = ""

            if coluna_descricao:

                valor = linha.get(
                    coluna_descricao
                )

                if pd.notna(valor):

                    descricao = str(
                        valor
                    ).strip()

            quantidade = 0

            if coluna_quantidade:

                valor = linha.get(
                    coluna_quantidade
                )

                if pd.notna(valor):

                    try:

                        quantidade = int(
                            float(valor)
                        )

                    except Exception:

                        quantidade = 0

            if (
                not codigo
                and not descricao
                and quantidade == 0
            ):
                continue

            executar(
                """
                INSERT INTO estoque
                (
                    codigo,
                    descricao,
                    quantidade,
                    criado_em
                )
                VALUES
                (%s,%s,%s,%s)
                """
                if usando_postgresql()
                else
                """
                INSERT INTO estoque
                (
                    codigo,
                    descricao,
                    quantidade,
                    criado_em
                )
                VALUES
                (?,?,?,?)
                """,
                (
                    codigo,
                    descricao,
                    quantidade,
                    (
                        agora_utc_naive()
                        if usando_postgresql()
                        else agora_sqlite()
                    )
                ),
                commit=True
            )

            quantidade_importada += 1

        flash(
            f"Estoque importado com sucesso. "
            f"{quantidade_importada} registro(s) incluído(s).",
            "success"
        )

    except Exception as erro:

        flash(
            f"Erro ao importar estoque: {erro}",
            "danger"
        )

    return redirect(
        url_for(
            "modulo",
            nome="Estoque"
        )
    )


# ============================================================
# INICIALIZAÇÃO
# ============================================================

with app.app_context():

    try:

        init_db()

        print(
            "Banco de dados inicializado com sucesso."
        )

    except Exception as erro:

        print(
            "ERRO AO INICIALIZAR BANCO: "
            f"{erro}"
        )


# ============================================================
# EXECUÇÃO LOCAL
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),
        debug=True
    )
