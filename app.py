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
# BANCO
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


def contar(sql, parametros=()):

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
# STATUS
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
# DATA E HORA
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

    return agora_brasil().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def agora_banco():

    if usando_postgresql():
        return agora_utc_naive()

    return agora_sqlite()


def converter_para_brasil(valor):

    if not valor:
        return None

    if isinstance(valor, datetime):

        dt = valor

        if dt.tzinfo is None:

            if usando_postgresql():

                dt = dt.replace(
                    tzinfo=timezone.utc
                )

            else:

                dt = dt.replace(
                    tzinfo=FUSO_BRASIL
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

        if usando_postgresql():

            dt = dt.replace(
                tzinfo=timezone.utc
            )

        else:

            dt = dt.replace(
                tzinfo=FUSO_BRASIL
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
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
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


def prazo_formulario_valido(valor):

    if not valor:
        return False, None

    prazo_dt = prazo_em_datetime(
        valor
    )

    if not prazo_dt:
        return False, None

    if prazo_dt < agora_brasil():
        return False, prazo_dt

    return True, prazo_dt


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
        obter_valor(
            item,
            "prazo"
        )
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
# PREPARAÇÃO
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

            if not item.get("usuario"):
                item["usuario"] = "Usuário"

            item["data_formatada"] = formatar_data_hora(
                item.get("criado_em")
            )

            resultado.append(item)

    return resultado


# ============================================================
# BUSCA
# ============================================================

def buscar_atividades_ativas():

    registros = executar(
        """
        SELECT *
        FROM atividades
        WHERE status IS NULL
           OR LOWER(status) NOT IN (
               'concluído',
               'concluido',
               'arquivado'
           )
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

    inventario_pendente = max(
        0,
        inventario_total
        - inventario_concluido
    )

    if inventario_total:

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

    expedicao_pendente = max(
        0,
        expedicao_total
        - expedicao_concluida
    )

    if expedicao_total:

        perc_expedicao = round(
            (
                expedicao_concluida
                / expedicao_total
            ) * 100
        )

    else:

        perc_expedicao = 0

    requisicao_pendentes = set()

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
            requisicao_pendentes.add(
                numero
            )

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
        "atividades_pendentes": atividades_pendentes,
        "atividades_andamento": atividades_andamento,
        "atividades_concluidas": atividades_concluidas,
        "atividades_arquivadas": atividades_arquivadas,
        "atividades_finalizadas": atividades_finalizadas,
        "atividades_ativas": atividades_ativas,

        "perc_atendidas": max(
            0,
            min(
                100,
                perc_atendidas
            )
        ),

        "inventario_total": inventario_total,
        "inventario_concluido": inventario_concluido,
        "inventario_pendente": inventario_pendente,

        "perc_inventario": max(
            0,
            min(
                100,
                perc_inventario
            )
        ),

        "expedicao_total": expedicao_total,
        "expedicao_concluida": expedicao_concluida,
        "expedicao_pendente": expedicao_pendente,

        "perc_expedicao": max(
            0,
            min(
                100,
                perc_expedicao
            )
        ),

        "requisicao_pendentes":
            len(requisicao_pendentes),

        "recebimento_pendente":
            recebimento_pendente,

        "ocorrencias":
            ocorrencias,

        "atrasados":
            atrasados,
    }


# ============================================================
# INDICADORES DO DIA
# ============================================================

def atividade_eh_do_dia(
    item,
    data_referencia=None
):

    if data_referencia is None:
        data_referencia = agora_brasil().date()

    data_valor = (
        obter_valor(
            item,
            "inicio_em"
        )
        or obter_valor(
            item,
            "criado_em"
        )
    )

    dt = converter_para_brasil(
        data_valor
    )

    if not dt:
        return False

    return dt.date() == data_referencia


def calcular_indicadores_do_dia(atividades):

    hoje = agora_brasil().date()

    atividades_dia = []

    for item in atividades:

        item_dict = linha_para_dict(item)

        if not item_dict:
            continue

        if atividade_eh_do_dia(
            item_dict,
            hoje
        ):
            atividades_dia.append(
                item_dict
            )

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

    if total_dia:

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

    if inventario_total:

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

    if expedicao_total:

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

        "perc_atendidas": max(
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

        "perc_inventario": max(
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

        "perc_expedicao": max(
            0,
            min(
                100,
                perc_expedicao
            )
        ),
    }


# ============================================================
# DUPLICIDADE
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
# BANCO - INICIALIZAÇÃO
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

        tabelas = {
            "usuarios": [
                ("criado_em", "TIMESTAMP")
            ],

            "chat": [
                ("usuario", "TEXT"),
                ("mensagem", "TEXT"),
                ("criado_em", "TIMESTAMP")
            ],

            "melhorias": [
                ("etapa", "TEXT"),
                ("autor", "TEXT"),
                ("status", "TEXT"),
                ("criado_em", "TIMESTAMP")
            ],

            "estoque": [
                ("codigo", "TEXT"),
                ("descricao", "TEXT"),
                ("quantidade", "INTEGER DEFAULT 0"),
                ("criado_em", "TIMESTAMP")
            ],
        }

        for tabela, colunas in tabelas.items():

            for coluna, tipo in colunas:

                cursor.execute(
                    f"""
                    ALTER TABLE {tabela}
                    ADD COLUMN IF NOT EXISTS {coluna} {tipo}
                    """
                )

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
            idx_atividades_inicio
            ON atividades (inicio_em)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_atividades_prazo
            ON atividades (prazo)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_chat_criado_em
            ON chat (criado_em)
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

            "chat": [
                ("usuario", "TEXT"),
                ("mensagem", "TEXT"),
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
            idx_atividades_inicio
            ON atividades (inicio_em)
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_atividades_prazo
            ON atividades (prazo)
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_chat_criado_em
            ON chat (criado_em)
        """)

        db.commit()

    # ========================================================
    # ADMIN
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
                agora_banco()
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

        dt = converter_para_brasil(
            concluido
        )

        if not dt:
            continue

        if (
            dt.astimezone(
                timezone.utc
            ) <= limite
        ):

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
                (
                    obter_valor(
                        item,
                        "id"
                    ),
                ),
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

            nome_usuario = obter_valor(
                usuario,
                "nome"
            )

            if nome_usuario:

                session["usuario_atual"] = str(
                    nome_usuario
                ).strip()

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
# CADASTRO
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
                agora_banco()
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

    usuario_atual = str(
        session.get(
            "usuario_atual",
            ""
        )
    ).strip()

    if not usuario_atual:
        return {}

    arquivar_atividades_expiradas()

    atividades_brutas = buscar_atividades_ativas()

    busca = request.args.get(
        "q",
        ""
    ).strip()

    if busca:

        busca_normalizada = normalizar_texto(
            busca
        )

        itens = []

        for item in atividades_brutas:

            campos = [
                obter_valor(
                    item,
                    "num_requisicao",
                    ""
                ),
                obter_valor(
                    item,
                    "atividade",
                    ""
                ),
                obter_valor(
                    item,
                    "descricao",
                    ""
                ),
                obter_valor(
                    item,
                    "responsavel",
                    ""
                ),
                obter_valor(
                    item,
                    "categoria",
                    ""
                ),
            ]

            if any(
                busca_normalizada
                in normalizar_texto(campo)
                for campo in campos
            ):

                itens.append(item)

    else:

        itens = atividades_brutas

    itens = preparar_lista_atividades(
        itens
    )

    usuarios = executar(
        """
        SELECT id, nome
        FROM usuarios
        ORDER BY nome ASC
        """,
        fetchall=True
    )

    usuarios = linhas_para_dict(
        usuarios
    )

    mensagens = executar(
        """
        SELECT *
        FROM chat
        ORDER BY id DESC
        LIMIT 30
        """,
        fetchall=True
    )

    mensagens = preparar_chat(
        mensagens
    )

    mensagens.reverse()

    atividades_todas = buscar_atividades_historico()

    atividades_todas = [
        linha_para_dict(item)
        for item in atividades_todas
    ]

    indicadores = calcular_indicadores(
        atividades_todas
    )

    indicadores_dia = calcular_indicadores_do_dia(
        atividades_todas
    )

    todas_preparadas = preparar_lista_atividades(
        atividades_todas
    )

    atendidas_pizza = indicadores_dia[
        "perc_atendidas"
    ]

    pendentes_pizza = max(
        0,
        100 - atendidas_pizza
    )

    inventario_pizza = indicadores_dia[
        "perc_inventario"
    ]

    inventario_pendente_pizza = max(
        0,
        100 - inventario_pizza
    )

    expedicao_pizza = indicadores_dia[
        "perc_expedicao"
    ]

    expedicao_pendente_pizza = max(
        0,
        100 - expedicao_pizza
    )

    return {

        "usuario_atual":
            usuario_atual,

        "itens":
            itens,

        "atividades":
            itens,

        "usuarios":
            usuarios,

        "mensagens":
            mensagens,

        "chat":
            mensagens,

        "total_req":
            indicadores[
                "requisicao_pendentes"
            ],

        "inv_total":
            indicadores[
                "inventario_total"
            ],

        "inv_conc":
            indicadores[
                "inventario_concluido"
            ],

        "inv_pend":
            indicadores[
                "inventario_pendente"
            ],

        "exp_pend":
            indicadores[
                "expedicao_pendente"
            ],

        "exp_total":
            indicadores[
                "expedicao_total"
            ],

        "exp_conc":
            indicadores[
                "expedicao_concluida"
            ],

        "rec_pend":
            indicadores[
                "recebimento_pendente"
            ],

        "total_oco":
            indicadores[
                "ocorrencias"
            ],

        "total_atrasados":
            indicadores[
                "atrasados"
            ],

        "total_geral":
            indicadores[
                "total_geral"
            ],

        "atividades_pendentes":
            indicadores[
                "atividades_pendentes"
            ],

        "atividades_andamento":
            indicadores[
                "atividades_andamento"
            ],

        "atividades_concluidas":
            indicadores[
                "atividades_concluidas"
            ],

        "atividades_arquivadas":
            indicadores[
                "atividades_arquivadas"
            ],

        "atividades_finalizadas":
            indicadores[
                "atividades_finalizadas"
            ],

        "concluidas":
            indicadores[
                "atividades_finalizadas"
            ],

        "perc_atendidas":
            indicadores_dia[
                "perc_atendidas"
            ],

        "perc_inventario":
            indicadores_dia[
                "perc_inventario"
            ],

        "perc_expedicao":
            indicadores_dia[
                "perc_expedicao"
            ],

        "indicadores_dia":
            indicadores_dia,

        "total_dia":
            indicadores_dia[
                "total"
            ],

        "finalizadas_dia":
            indicadores_dia[
                "finalizadas"
            ],

        "pendentes_dia":
            indicadores_dia[
                "pendentes"
            ],

        "atendidas_pizza":
            atendidas_pizza,

        "pendentes_pizza":
            pendentes_pizza,

        "inventario_pizza":
            inventario_pizza,

        "inventario_pendente_pizza":
            inventario_pendente_pizza,

        "expedicao_pizza":
            expedicao_pizza,

        "expedicao_pendente_pizza":
            expedicao_pendente_pizza,

        "todas_preparadas":
            todas_preparadas,

        "busca":
            busca,
    }


# ============================================================
# DASHBOARD PRINCIPAL
# ============================================================

@app.route(
    "/",
    methods=["GET", "POST"]
)
def index():

    if "usuario_atual" not in session:

        return redirect(
            url_for("login")
        )

    if request.method == "POST":

        usuario_atual = str(
            session.get(
                "usuario_atual",
                ""
            )
        ).strip()

        if not usuario_atual:

            session.clear()

            return redirect(
                url_for("login")
            )

        acao_chat = request.form.get(
            "acao_chat",
            ""
        ).strip()

        if acao_chat == "enviar":

            mensagem = request.form.get(
                "mensagem",
                ""
            ).strip()

            if not mensagem:

                flash(
                    "Digite uma mensagem antes de enviar.",
                    "warning"
                )

                return redirect(
                    url_for("index")
                )

            mensagem = mensagem[:2000]

            try:

                nome_chat = str(
                    session.get(
                        "usuario_atual",
                        ""
                    )
                ).strip()

                if not nome_chat:

                    session.clear()

                    flash(
                        "Sua sessão expirou. Faça login novamente.",
                        "warning"
                    )

                    return redirect(
                        url_for("login")
                    )

                executar(
                    """
                    INSERT INTO chat
                        (usuario, mensagem, criado_em)
                    VALUES
                        (%s,%s,%s)
                    """
                    if usando_postgresql()
                    else
                    """
                    INSERT INTO chat
                        (usuario, mensagem, criado_em)
                    VALUES
                        (?,?,?)
                    """,
                    (
                        nome_chat,
                        mensagem,
                        agora_banco()
                    ),
                    commit=True
                )

                flash(
                    "Mensagem enviada.",
                    "success"
                )

            except Exception as erro:

                print(
                    "ERRO AO ENVIAR CHAT:",
                    repr(erro)
                )

                flash(
                    "Não foi possível enviar a mensagem.",
                    "danger"
                )

            return redirect(
                url_for("index")
            )

        num_requisicao = normalizar_requisicao(
            request.form.get(
                "num_requisicao"
            )
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

        if (
            categoria == "Separação"
            and not num_requisicao
        ):

            flash(
                "A Separação precisa de um número de requisição.",
                "warning"
            )

            return redirect(
                url_for("index")
            )

        prazo_valido, prazo_dt = prazo_formulario_valido(
            prazo
        )

        if not prazo_valido:

            if prazo_dt:

                flash(
                    "O prazo informado já passou. "
                    "Escolha uma data e horário futuros.",
                    "warning"
                )

            else:

                flash(
                    "Informe um prazo válido com data e horário.",
                    "warning"
                )

            return redirect(
                url_for("index")
            )

        prazo = prazo_dt.strftime(
            "%Y-%m-%d %H:%M"
        )

        if (
            num_requisicao
            and requisicao_duplicada(
                num_requisicao
            )
        ):

            flash(
                f"A requisicao {num_requisicao} já possui uma atividade ativa.",
                "warning"
            )

            return redirect(
                url_for("index")
            )

        agora_registro = agora_banco()

        inicio_em = None

        if categoria == "Separação":

            inicio_em = agora_registro

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
                num_requisicao or None,
                atividade,
                descricao,
                categoria,
                responsavel,
                prioridade,
                prazo,
                STATUS_PENDENTE,
                inicio_em,
                agora_registro
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

    dados = obter_dados_dashboard()

    return render_template(
        "index.html",
        **dados
    )


# ============================================================
# DASHBOARD
# ============================================================

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
            .astimezone(
                timezone.utc
            )
            .replace(
                tzinfo=None
            )
        )

        fim_busca = (
            fim_brasilia
            .astimezone(
                timezone.utc
            )
            .replace(
                tzinfo=None
            )
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

@app.route(
    "/modulo/<path:nome>",
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

    if nome_normalizado == "configuracoes":

        return render_template(
            "configuracoes.html",
            usuario_atual=session[
                "usuario_atual"
            ]
        )

    if nome_normalizado == "indicadores":

        return redirect(
            url_for("indicadores")
        )

    if nome_normalizado == "relatorios":

        return redirect(
            url_for("relatorios")
        )

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
                    session[
                        "usuario_atual"
                    ],
                    status,
                    agora_banco()
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
            SELECT *
            FROM melhorias
            WHERE LOWER(
                COALESCE(status,'')
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

    if nome_normalizado == "estoque":

        itens = executar(
            """
            SELECT *
            FROM estoque
            ORDER BY id DESC
            """,
            fetchall=True
        )

        return render_template(
            "modulo.html",

            titulo="Estoque",

            modulo="Estoque",

            itens=linhas_para_dict(
                itens
            ),

            usuario_atual=session[
                "usuario_atual"
            ]
        )

    mapa_modulos = {

        "requisicao": {
            "titulo": "Requisicao",
            "categoria": "Separação"
        },

        "inventario": {
            "titulo": "Inventário",
            "categoria": "Inventário"
        },

        "expedicao": {
            "titulo": "Expedição",
            "categoria": "Expedição"
        },

        "recebimento": {
            "titulo": "Recebimento",
            "categoria": "Recebimento"
        },

        "logistica reversa": {
            "titulo": "Logística Reversa",
            "categoria": "Logística Reversa"
        },

        "reversa": {
            "titulo": "Logística Reversa",
            "categoria": "Logística Reversa"
        }
    }

    configuracao = mapa_modulos.get(
        nome_normalizado
    )

    if configuracao:

        categoria = configuracao[
            "categoria"
        ]

        registros = executar(
            """
            SELECT *
            FROM atividades
            ORDER BY id DESC
            """,
            fetchall=True
        )

        itens = [
            item
            for item in registros
            if (
                categoria_eh(
                    item,
                    categoria
                )
                and status_eh_ativo(
                    obter_valor(
                        item,
                        "status"
                    )
                )
            )
        ]

        return render_template(
            "modulo.html",

            titulo=configuracao[
                "titulo"
            ],

            modulo=configuracao[
                "titulo"
            ],

            itens=preparar_lista_atividades(
                itens
            ),

            usuario_atual=session[
                "usuario_atual"
            ]
        )

    flash(
        f"Módulo '{nome}' não encontrado.",
        "warning"
    )

    return redirect(
        url_for("index")
    )


# ============================================================
# EDITAR
# ============================================================

@app.route(
    "/editar/<int:id>",
    methods=["GET", "POST"]
)
def editar(id):

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
            url_for("relatorios")
        )

    if request.method == "GET":

        return redirect(
            url_for(
                "relatorios",
                filtro="todos"
            )
        )

    num_requisicao = normalizar_requisicao(
        request.form.get(
            "num_requisicao"
        )
    )

    atividade_texto = request.form.get(
        "atividade",
        ""
    ).strip()

    descricao = request.form.get(
        "descricao",
        ""
    ).strip()

    categoria = request.form.get(
        "categoria",
        ""
    ).strip()

    responsavel = request.form.get(
        "responsavel",
        ""
    ).strip()

    prioridade = request.form.get(
        "prioridade",
        "Baixa"
    ).strip()

    prazo = request.form.get(
        "prazo",
        ""
    ).strip()

    status = request.form.get(
        "status",
        obter_valor(
            atividade,
            "status",
            STATUS_PENDENTE
        )
    ).strip()

    if not atividade_texto:

        flash(
            "Informe a atividade.",
            "warning"
        )

        return redirect(
            url_for("relatorios")
        )

    if categoria not in CATEGORIAS_VALIDAS:

        flash(
            "Categoria inválida.",
            "warning"
        )

        return redirect(
            url_for("relatorios")
        )

    if prioridade not in PRIORIDADES_VALIDAS:
        prioridade = "Baixa"

    status_normalizado = normalizar_status(
        status
    )

    if status_normalizado == "pendente":

        status = STATUS_PENDENTE

    elif status_normalizado in (
        "em andamento",
        "andamento",
        "em processo"
    ):

        status = STATUS_ANDAMENTO

    elif status_normalizado in (
        "concluido",
        "concluida",
        "finalizado",
        "finalizada"
    ):

        status = STATUS_CONCLUIDO

    elif status_normalizado == "arquivado":

        status = STATUS_ARQUIVADO

    else:

        status = STATUS_PENDENTE

    if (
        categoria == "Separação"
        and not num_requisicao
    ):

        flash(
            "A Separação precisa de um número de requisicao.",
            "warning"
        )

        return redirect(
            url_for("relatorios")
        )

    if (
        num_requisicao
        and requisicao_duplicada(
            num_requisicao,
            ignorar_id=id
        )
    ):

        flash(
            f"A requisicao {num_requisicao} já possui uma atividade ativa.",
            "warning"
        )

        return redirect(
            url_for("relatorios")
        )

    # CARREGA OS VALORES ATUAIS DO REGISTRO NO BANCO
    status_anterior = obter_valor(atividade, "status")
    inicio_em = obter_valor(atividade, "inicio_em")
    concluido_em = obter_valor(atividade, "concluido_em")
    encerrado_por = obter_valor(atividade, "encerrado_por")

    # ========================================================
    # PRAZO
    # ========================================================
    prazo_original = obter_valor(atividade, "prazo")

    if prazo:
        prazo_valido, prazo_dt = prazo_formulario_valido(prazo)

        if not prazo_valido:
            if status_eh_ativo(status):
                flash(
                    "O prazo informado já passou. Escolha uma data e horário futuros.",
                    "warning"
                )
                return redirect(url_for("relatorios"))
            else:
                prazo = prazo_dt.strftime("%Y-%m-%d %H:%M") if prazo_dt else prazo_original
        else:
            prazo = prazo_dt.strftime("%Y-%m-%d %H:%M")
    else:
        prazo = prazo_original

    # ========================================================
    # CORREÇÃO DO HORÁRIO DE INÍCIO
    # ========================================================

    if (
        categoria == "Separação"
        and not inicio_em
        and status_eh_ativo(status)
    ):

        inicio_em = agora_banco()

    elif (
        status_eh_andamento(status)
        and not inicio_em
    ):

        inicio_em = agora_banco()

    # ========================================================
    # CONCLUSÃO
    # ========================================================

    if (
        status == STATUS_CONCLUIDO
        and not status_eh_concluido(
            status_anterior
        )
    ):

        concluido_em = agora_banco()

        encerrado_por = session[
            "usuario_atual"
        ]

    if status in (
        STATUS_PENDENTE,
        STATUS_ANDAMENTO
    ):

        concluido_em = None
        encerrado_por = None

    if status == STATUS_ARQUIVADO:

        if not concluido_em:

            concluido_em = agora_banco()

        if not encerrado_por:

            encerrado_por = session[
                "usuario_atual"
            ]

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
            prazo = %s,
            status = %s,
            inicio_em = %s,
            concluido_em = %s,
            encerrado_por = %s
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
            prazo = ?,
            status = ?,
            inicio_em = ?,
            concluido_em = ?,
            encerrado_por = ?
        WHERE id = ?
        """,
        (
            num_requisicao or None,
            atividade_texto,
            descricao,
            categoria,
            responsavel,
            prioridade,
            prazo,
            status,
            inicio_em,
            concluido_em,
            encerrado_por,
            id
        ),
        commit=True
    )

    flash(
        "Atividade atualizada com sucesso.",
        "success"
    )

    return redirect(
        url_for("relatorios")
    )


# ============================================================
# CONCLUIR
# ============================================================

@app.route(
    "/concluir/<int:id>",
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

    agora = agora_banco()

    inicio_existente = obter_valor(
        atividade,
        "inicio_em"
    )

    if not inicio_existente:

        executar(
            """
            UPDATE atividades
            SET
                inicio_em = %s
            WHERE id = %s
            """
            if usando_postgresql()
            else
            """
            UPDATE atividades
            SET
                inicio_em = ?
            WHERE id = ?
            """,
            (
                agora,
                id
            ),
            commit=True
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
                f"da requisicao {num_requisicao}."
            )

            prazo_expedicao = (
                agora_brasil()
                + timedelta(hours=1)
            ).strftime(
                "%Y-%m-%d %H:%M"
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
                    prazo_expedicao,
                    STATUS_PENDENTE,
                    agora,
                    agora
                ),
                commit=True
            )

            flash(
                "Separação concluída e Expedição criada automaticamente. "
                f"Prazo da Expedição: "
                f"{formatar_data_hora(prazo_expedicao)}.",
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
        request.referrer or url_for("index")
    )


# ============================================================
# INICIALIZAÇÃO DO SERVIDOR
# ============================================================

if __name__ == "__main__":

    with app.app_context():
        init_db()

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=True
    )
