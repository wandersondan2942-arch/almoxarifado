import os
import sqlite3
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

FUSO_BRASIL = ZoneInfo("America/Sao_Paulo")


# ============================================================
# BANCO DE DADOS
# ============================================================

def usando_postgresql():
    return bool(DATABASE_URL)


def get_db():

    if hasattr(g, "db"):
        return g.db

    if usando_postgresql():

        g.db = psycopg2.connect(
            DATABASE_URL,
            cursor_factory=psycopg2.extras.RealDictCursor
        )

    else:

        g.db = sqlite3.connect(
            "database.db"
        )

        g.db.row_factory = sqlite3.Row

    return g.db


@app.teardown_appcontext
def fechar_db(exception=None):

    db = g.pop("db", None)

    if db is not None:
        db.close()


def executar(sql, parametros=(), commit=False):

    db = get_db()

    if not usando_postgresql():
        sql = sql.replace("%s", "?")

    cursor = db.cursor()

    try:

        cursor.execute(
            sql,
            parametros
        )

        if commit:
            db.commit()

        return cursor

    except Exception:

        try:
            cursor.close()
        except Exception:
            pass

        if commit:

            try:
                db.rollback()
            except Exception:
                pass

        raise


def fechar_cursor(cursor):

    try:
        cursor.close()
    except Exception:
        pass


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


def obter_valor(linha, campo, padrao=None):

    if linha is None:
        return padrao

    if isinstance(linha, dict):
        return linha.get(campo, padrao)

    try:
        return linha[campo]
    except Exception:
        return padrao


def contar(sql, parametros=()):

    cursor = executar(
        sql,
        parametros
    )

    linha = cursor.fetchone()

    fechar_cursor(cursor)

    if linha is None:
        return 0

    return int(
        obter_valor(
            linha,
            "total",
            0
        ) or 0
    )


# ============================================================
# DATA E HORA
# ============================================================

def agora_utc():
    return datetime.now(timezone.utc)


def agora_brasil():
    return agora_utc().astimezone(
        FUSO_BRASIL
    )


def agora_utc_naive():
    return agora_utc().replace(
        tzinfo=None
    )


def agora_sqlite():

    return agora_utc_naive().isoformat(
        timespec="seconds"
    )


def converter_para_brasil(valor):

    if not valor:
        return None

    if isinstance(valor, datetime):

        dt = valor

    else:

        texto = str(valor).strip()

        formatos = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y %H:%M",
        ]

        dt = None

        for formato in formatos:

            try:

                dt = datetime.strptime(
                    texto,
                    formato
                )

                break

            except Exception:
                pass

        if dt is None:

            try:

                dt = datetime.fromisoformat(
                    texto.replace(
                        "Z",
                        "+00:00"
                    )
                )

            except Exception:
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
        return ""

    return dt.strftime(
        "%d/%m/%Y %H:%M"
    )


def formatar_hora(valor):

    dt = converter_para_brasil(valor)

    if not dt:
        return ""

    return dt.strftime(
        "%H:%M"
    )


def calcular_duracao(inicio, fim=None):

    if not inicio:
        return ""

    dt_inicio = converter_para_brasil(
        inicio
    )

    if not dt_inicio:
        return ""

    dt_fim = (
        converter_para_brasil(fim)
        if fim
        else agora_brasil()
    )

    if not dt_fim:
        return ""

    segundos = int(
        (
            dt_fim - dt_inicio
        ).total_seconds()
    )

    if segundos < 0:
        segundos = 0

    horas = segundos // 3600

    minutos = (
        segundos % 3600
    ) // 60

    if horas:

        return (
            f"{horas}h "
            f"{minutos}min"
        )

    return f"{minutos}min"


def normalizar_requisicao(valor):

    if valor is None:
        return ""

    return str(valor).strip().upper()


def prazo_em_datetime(valor):

    if not valor:
        return None

    if isinstance(valor, datetime):

        dt = valor

    else:

        texto = str(valor).strip()

        formatos = [
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y %H:%M",
        ]

        dt = None

        for formato in formatos:

            try:

                dt = datetime.strptime(
                    texto,
                    formato
                )

                break

            except Exception:
                pass

        if dt is None:

            try:

                dt = datetime.fromisoformat(
                    texto.replace(
                        "Z",
                        "+00:00"
                    )
                )

            except Exception:
                return None

    if dt.tzinfo is None:

        # Prazo vindo do formulário é horário de Brasília.
        dt = dt.replace(
            tzinfo=FUSO_BRASIL
        )

    return dt.astimezone(
        FUSO_BRASIL
    )


def prazo_atrasado(valor, referencia=None):

    dt = prazo_em_datetime(valor)

    if not dt:
        return False

    if referencia:

        dt_referencia = prazo_em_datetime(
            referencia
        )

        if dt_referencia:
            return dt_referencia > dt

    return dt < agora_brasil()


def registro_foi_atrasado(atividade):

    if not atividade:
        return False

    prazo = atividade.get("prazo")

    if not prazo:
        return False

    status = (
        atividade.get("status")
        or ""
    )

    status_normalizado = (
        str(status)
        .strip()
        .lower()
    )

    concluido_em = atividade.get(
        "concluido_em"
    )

    prazo_dt = prazo_em_datetime(
        prazo
    )

    if not prazo_dt:
        return False

    # --------------------------------------------------------
    # Se foi concluído ou arquivado:
    # verificamos se terminou depois do prazo.
    # --------------------------------------------------------

    if status_normalizado in {
        "concluído",
        "concluido",
        "arquivado",
        "arquivada",
    }:

        if concluido_em:

            conclusao_dt = prazo_em_datetime(
                concluido_em
            )

            if conclusao_dt:

                return conclusao_dt > prazo_dt

        # Registro arquivado sem conclusão registrada.
        if status_normalizado in {
            "arquivado",
            "arquivada"
        }:

            return prazo_dt < agora_brasil()

        return False

    # --------------------------------------------------------
    # Registro ainda aberto.
    # --------------------------------------------------------

    return prazo_dt < agora_brasil()


def texto_atraso(valor, referencia=None):

    dt = prazo_em_datetime(valor)

    if not dt:
        return ""

    if referencia:

        referencia_dt = prazo_em_datetime(
            referencia
        )

        if referencia_dt:

            diferenca = (
                referencia_dt - dt
            )

        else:

            diferenca = (
                agora_brasil() - dt
            )

    else:

        diferenca = (
            agora_brasil() - dt
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

    if dias:

        return (
            f"{dias}d "
            f"{horas}h atrasado"
        )

    if horas:

        return (
            f"{horas}h "
            f"{mins}min atrasado"
        )

    return f"{mins}min atrasado"


# ============================================================
# PREPARAÇÃO DOS DADOS
# ============================================================

def preparar_atividade(atividade):

    atividade = linha_para_dict(
        atividade
    )

    if not atividade:
        return atividade

    atividade["prazo_formatado"] = (
        formatar_data_hora(
            atividade.get("prazo")
        )
    )

    atividade["inicio_formatado"] = (
        formatar_data_hora(
            atividade.get("inicio_em")
        )
    )

    atividade["concluido_formatado"] = (
        formatar_data_hora(
            atividade.get("concluido_em")
        )
    )

    atividade["criado_formatado"] = (
        formatar_data_hora(
            atividade.get("criado_em")
        )
    )

    atividade["prazo_atrasado"] = (
        prazo_atrasado(
            atividade.get("prazo")
        )
    )

    atividade["foi_atrasada"] = (
        registro_foi_atrasado(
            atividade
        )
    )

    atividade["texto_atraso"] = (
        texto_atraso(
            atividade.get("prazo"),
            atividade.get("concluido_em")
        )
    )

    atividade["duracao"] = calcular_duracao(
        atividade.get("inicio_em"),
        atividade.get("concluido_em")
    )

    atividade["num_requisicao"] = (
        atividade.get("num_requisicao")
        or ""
    )

    atividade["status"] = (
        atividade.get("status")
        or "Pendente"
    )

    atividade["categoria"] = (
        atividade.get("categoria")
        or ""
    )

    atividade["responsavel"] = (
        atividade.get("responsavel")
        or ""
    )

    atividade["prioridade"] = (
        atividade.get("prioridade")
        or "Baixa"
    )

    return atividade


def preparar_lista_atividades(lista):

    return [
        preparar_atividade(item)
        for item in lista
    ]


def preparar_chat(lista):

    resultado = []

    for item in lista:

        item = linha_para_dict(item)

        if item:

            item["data_formatada"] = (
                formatar_data_hora(
                    item.get("criado_em")
                )
            )

            resultado.append(item)

    return resultado


# ============================================================
# REQUISIÇÃO DUPLICADA
# ============================================================

def requisicao_duplicada(
    num_requisicao,
    ignorar_id=None
):

    numero = normalizar_requisicao(
        num_requisicao
    )

    if not numero:
        return False

    if ignorar_id:

        cursor = executar(
            """
            SELECT id
            FROM atividades
            WHERE UPPER(TRIM(num_requisicao)) = %s
              AND status NOT IN (
                  'Concluído',
                  'Concluido',
                  'Arquivado',
                  'Arquivada'
              )
              AND id <> %s
            LIMIT 1
            """,
            (
                numero,
                ignorar_id
            )
        )

    else:

        cursor = executar(
            """
            SELECT id
            FROM atividades
            WHERE UPPER(TRIM(num_requisicao)) = %s
              AND status NOT IN (
                  'Concluído',
                  'Concluido',
                  'Arquivado',
                  'Arquivada'
              )
            LIMIT 1
            """,
            (numero,)
        )

    resultado = cursor.fetchone()

    fechar_cursor(cursor)

    return resultado is not None


# ============================================================
# INICIALIZAÇÃO DO BANCO
# ============================================================

def init_db():

    db = get_db()

    if usando_postgresql():

        cursor = db.cursor()

        # ----------------------------------------------------
        # USUÁRIOS
        # ----------------------------------------------------

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS usuarios (
                id SERIAL PRIMARY KEY,
                nome TEXT NOT NULL,
                senha TEXT NOT NULL
            )
            """
        )

        # ----------------------------------------------------
        # ATIVIDADES
        # ----------------------------------------------------

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS atividades (
                id SERIAL PRIMARY KEY,
                num_requisicao TEXT,
                prioridade TEXT DEFAULT 'Baixa',
                atividade TEXT NOT NULL,
                descricao TEXT,
                categoria TEXT DEFAULT 'Separação',
                responsavel TEXT,
                prazo TEXT,
                status TEXT DEFAULT 'Pendente',
                inicio_em TIMESTAMP,
                concluido_em TIMESTAMP,
                encerrado_por TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # ----------------------------------------------------
        # CHAT
        # ----------------------------------------------------

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS chat (
                id SERIAL PRIMARY KEY,
                usuario TEXT NOT NULL,
                mensagem TEXT NOT NULL,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # ----------------------------------------------------
        # MELHORIAS
        # ----------------------------------------------------

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS melhorias (
                id SERIAL PRIMARY KEY,
                titulo TEXT NOT NULL,
                descricao TEXT,
                status TEXT DEFAULT 'A Fazer',
                responsavel TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                etapa TEXT DEFAULT 'PDCA',
                autor TEXT
            )
            """
        )

        # ----------------------------------------------------
        # ESTOQUE
        # ----------------------------------------------------

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS estoque (
                id SERIAL PRIMARY KEY,
                codigo TEXT,
                descricao TEXT,
                categoria TEXT,
                quantidade NUMERIC DEFAULT 0,
                localizacao TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # ----------------------------------------------------
        # MIGRAÇÃO ATIVIDADES
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'atividades'
            """
        )

        colunas_existentes = {
            linha["column_name"]
            for linha in cursor.fetchall()
        }

        novas_colunas = {
            "num_requisicao": "TEXT",
            "prioridade": "TEXT DEFAULT 'Baixa'",
            "descricao": "TEXT",
            "categoria": "TEXT DEFAULT 'Separação'",
            "responsavel": "TEXT",
            "prazo": "TEXT",
            "status": "TEXT DEFAULT 'Pendente'",
            "inicio_em": "TIMESTAMP",
            "concluido_em": "TIMESTAMP",
            "encerrado_por": "TEXT",
            "criado_em": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        }

        for coluna, tipo in novas_colunas.items():

            if coluna not in colunas_existentes:

                cursor.execute(
                    f"""
                    ALTER TABLE atividades
                    ADD COLUMN {coluna} {tipo}
                    """
                )

        # ----------------------------------------------------
        # MIGRAÇÃO MELHORIAS
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'melhorias'
            """
        )

        colunas_melhorias = {
            linha["column_name"]
            for linha in cursor.fetchall()
        }

        novas_colunas_melhorias = {
            "etapa": "TEXT DEFAULT 'PDCA'",
            "autor": "TEXT",
        }

        for coluna, tipo in novas_colunas_melhorias.items():

            if coluna not in colunas_melhorias:

                cursor.execute(
                    f"""
                    ALTER TABLE melhorias
                    ADD COLUMN {coluna} {tipo}
                    """
                )

        db.commit()

        # ----------------------------------------------------
        # ÍNDICE NORMAL DE REQUISIÇÃO
        #
        # Não é UNIQUE.
        #
        # Isso evita que registros históricos antigos
        # impeçam o sistema de iniciar.
        # ----------------------------------------------------

        try:

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_atividades_req_busca
                ON atividades (
                    num_requisicao
                )
                """
            )

            db.commit()

        except Exception as erro:

            db.rollback()

            print(
                "AVISO: índice de requisição não criado:",
                erro
            )

        cursor.close()

    else:

        cursor = db.cursor()

        # ----------------------------------------------------
        # USUÁRIOS
        # ----------------------------------------------------

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                senha TEXT NOT NULL
            )
            """
        )

        # ----------------------------------------------------
        # ATIVIDADES
        # ----------------------------------------------------

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS atividades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                num_requisicao TEXT,
                prioridade TEXT DEFAULT 'Baixa',
                atividade TEXT NOT NULL,
                descricao TEXT,
                categoria TEXT DEFAULT 'Separação',
                responsavel TEXT,
                prazo TEXT,
                status TEXT DEFAULT 'Pendente',
                inicio_em TEXT,
                concluido_em TEXT,
                encerrado_por TEXT,
                criado_em TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # ----------------------------------------------------
        # CHAT
        # ----------------------------------------------------

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS chat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT NOT NULL,
                mensagem TEXT NOT NULL,
                criado_em TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # ----------------------------------------------------
        # MELHORIAS
        # ----------------------------------------------------

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS melhorias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                descricao TEXT,
                status TEXT DEFAULT 'A Fazer',
                responsavel TEXT,
                criado_em TEXT DEFAULT CURRENT_TIMESTAMP,
                etapa TEXT DEFAULT 'PDCA',
                autor TEXT
            )
            """
        )

        # ----------------------------------------------------
        # ESTOQUE
        # ----------------------------------------------------

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS estoque (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT,
                descricao TEXT,
                categoria TEXT,
                quantidade REAL DEFAULT 0,
                localizacao TEXT,
                criado_em TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # ----------------------------------------------------
        # MIGRAÇÃO ATIVIDADES
        # ----------------------------------------------------

        cursor.execute(
            "PRAGMA table_info(atividades)"
        )

        colunas_existentes = {
            linha["name"]
            for linha in cursor.fetchall()
        }

        novas_colunas = {
            "num_requisicao": "TEXT",
            "prioridade": "TEXT DEFAULT 'Baixa'",
            "descricao": "TEXT",
            "categoria": "TEXT DEFAULT 'Separação'",
            "responsavel": "TEXT",
            "prazo": "TEXT",
            "status": "TEXT DEFAULT 'Pendente'",
            "inicio_em": "TEXT",
            "concluido_em": "TEXT",
            "encerrado_por": "TEXT",
            "criado_em": "TEXT",
        }

        for coluna, tipo in novas_colunas.items():

            if coluna not in colunas_existentes:

                cursor.execute(
                    f"""
                    ALTER TABLE atividades
                    ADD COLUMN {coluna} {tipo}
                    """
                )

        # ----------------------------------------------------
        # MIGRAÇÃO MELHORIAS
        # ----------------------------------------------------

        cursor.execute(
            "PRAGMA table_info(melhorias)"
        )

        colunas_melhorias = {
            linha["name"]
            for linha in cursor.fetchall()
        }

        novas_colunas_melhorias = {
            "etapa": "TEXT",
            "autor": "TEXT",
        }

        for coluna, tipo in novas_colunas_melhorias.items():

            if coluna not in colunas_melhorias:

                cursor.execute(
                    f"""
                    ALTER TABLE melhorias
                    ADD COLUMN {coluna} {tipo}
                    """
                )

        db.commit()

        try:

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_atividades_req_busca
                ON atividades (
                    num_requisicao
                )
                """
            )

            db.commit()

        except Exception as erro:

            db.rollback()

            print(
                "AVISO: índice SQLite não criado:",
                erro
            )

        cursor.close()

    # ========================================================
    # USUÁRIO PADRÃO
    # ========================================================

    cursor = executar(
        """
        SELECT id
        FROM usuarios
        WHERE nome = %s
        LIMIT 1
        """,
        ("Wanderson Fernandes",)
    )

    usuario = cursor.fetchone()

    fechar_cursor(cursor)

    if usuario is None:

        executar(
            """
            INSERT INTO usuarios (
                nome,
                senha
            )
            VALUES (%s, %s)
            """,
            (
                "Wanderson Fernandes",
                "1234"
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

    if usando_postgresql():

        limite_valor = limite.replace(
            tzinfo=None
        )

    else:

        limite_valor = (
            limite.replace(
                tzinfo=None
            ).isoformat(
                timespec="seconds"
            )
        )

    executar(
        """
        UPDATE atividades
        SET status = 'Arquivado'
        WHERE status IN (
            'Concluído',
            'Concluido'
        )
          AND concluido_em IS NOT NULL
          AND concluido_em < %s
        """,
        (limite_valor,),
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

        cursor = executar(
            """
            SELECT *
            FROM usuarios
            WHERE nome = %s
              AND senha = %s
            LIMIT 1
            """,
            (
                nome,
                senha
            )
        )

        usuario = linha_para_dict(
            cursor.fetchone()
        )

        fechar_cursor(cursor)

        if usuario:

            session["usuario_atual"] = (
                usuario["nome"]
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

        cursor = executar(
            """
            SELECT id
            FROM usuarios
            WHERE nome = %s
            LIMIT 1
            """,
            (nome,)
        )

        existe = cursor.fetchone()

        fechar_cursor(cursor)

        if existe:

            flash(
                "Usuário já cadastrado.",
                "warning"
            )

            return redirect(
                url_for(
                    "cadastro_usuario"
                )
            )

        executar(
            """
            INSERT INTO usuarios (
                nome,
                senha
            )
            VALUES (%s, %s)
            """,
            (
                nome,
                senha
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
# DASHBOARD / INÍCIO
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

    try:

        arquivar_atividades_expiradas()

    except Exception as erro:

        print(
            "AVISO no arquivamento automático:",
            erro
        )

    usuario_atual = (
        session["usuario_atual"]
    )

    # ========================================================
    # POST
    # ========================================================

    if request.method == "POST":

        # ----------------------------------------------------
        # CHAT
        # ----------------------------------------------------

        acao_chat = request.form.get(
            "acao_chat"
        )

        if acao_chat == "enviar":

            mensagem = request.form.get(
                "mensagem",
                ""
            ).strip()

            if mensagem:

                executar(
                    """
                    INSERT INTO chat (
                        usuario,
                        mensagem
                    )
                    VALUES (%s, %s)
                    """,
                    (
                        usuario_atual,
                        mensagem
                    ),
                    commit=True
                )

            return redirect(
                url_for("index")
            )

        # ----------------------------------------------------
        # NOVA ATIVIDADE
        # ----------------------------------------------------

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

        prioridade = request.form.get(
            "prioridade",
            "Baixa"
        ).strip()

        responsavel = request.form.get(
            "responsavel",
            ""
        ).strip()

        prazo = request.form.get(
            "prazo",
            ""
        ).strip()

        num_requisicao = normalizar_requisicao(
            request.form.get(
                "num_requisicao",
                ""
            )
        )

        categorias_validas = {
            "Separação",
            "Inventário",
            "Expedição",
            "Recebimento",
            "Logística Reversa",
            "Estoque",
        }

        prioridades_validas = {
            "Baixa",
            "Média",
            "Alta",
        }

        if categoria not in categorias_validas:
            categoria = "Separação"

        if prioridade not in prioridades_validas:
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
                "Informe o número da requisição para uma atividade de Separação.",
                "warning"
            )

            return redirect(
                url_for("index")
            )

        if num_requisicao:

            if requisicao_duplicada(
                num_requisicao
            ):

                flash(
                    f"A requisição {num_requisicao} já possui uma atividade ativa.",
                    "warning"
                )

                return redirect(
                    url_for("index")
                )

        inicio_em = None

        if categoria == "Separação":

            if usando_postgresql():

                inicio_em = agora_utc_naive()

            else:

                inicio_em = agora_sqlite()

        executar(
            """
            INSERT INTO atividades (
                num_requisicao,
                prioridade,
                atividade,
                descricao,
                categoria,
                responsavel,
                prazo,
                status,
                inicio_em
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
            """,
            (
                num_requisicao or None,
                prioridade,
                atividade,
                descricao,
                categoria,
                responsavel,
                prazo or None,
                "Pendente",
                inicio_em
            ),
            commit=True
        )

        flash(
            "Atividade cadastrada com sucesso.",
            "success"
        )

        return redirect(
            url_for("index")
        )

    # ========================================================
    # BUSCA
    # ========================================================

    busca = request.args.get(
        "q",
        ""
    ).strip()

    if busca:

        termo = f"%{busca}%"

        cursor = executar(
            """
            SELECT *
            FROM atividades
            WHERE atividade LIKE %s
               OR descricao LIKE %s
               OR num_requisicao LIKE %s
               OR responsavel LIKE %s
               OR categoria LIKE %s
            ORDER BY id DESC
            """,
            (
                termo,
                termo,
                termo,
                termo,
                termo
            )
        )

    else:

        cursor = executar(
            """
            SELECT *
            FROM atividades
            WHERE status NOT IN (
                'Concluído',
                'Concluido',
                'Arquivado',
                'Arquivada'
            )
            ORDER BY
                CASE prioridade
                    WHEN 'Alta' THEN 1
                    WHEN 'Média' THEN 2
                    ELSE 3
                END,
                id DESC
            """
        )

    atividades = linhas_para_dict(
        cursor.fetchall()
    )

    fechar_cursor(cursor)

    atividades = preparar_lista_atividades(
        atividades
    )

    # ========================================================
    # CHAT
    # ========================================================

    cursor = executar(
        """
        SELECT *
        FROM chat
        ORDER BY id DESC
        LIMIT 30
        """
    )

    chat = preparar_chat(
        cursor.fetchall()
    )

    fechar_cursor(cursor)

    chat.reverse()

    # ========================================================
    # USUÁRIOS
    # ========================================================

    cursor = executar(
        """
        SELECT *
        FROM usuarios
        ORDER BY nome
        """
    )

    usuarios = linhas_para_dict(
        cursor.fetchall()
    )

    fechar_cursor(cursor)

    # ========================================================
    # INDICADORES
    # ========================================================

    total_req = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE status NOT IN (
            'Arquivado',
            'Arquivada'
        )
        """
    )

    inv_total = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = 'Inventário'
        """
    )

    inv_conc = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = 'Inventário'
          AND status IN (
              'Concluído',
              'Concluido'
          )
        """
    )

    exp_total = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = 'Expedição'
        """
    )

    exp_concluido = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = 'Expedição'
          AND status IN (
              'Concluído',
              'Concluido'
          )
        """
    )

    exp_pend = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = 'Expedição'
          AND status NOT IN (
              'Concluído',
              'Concluido',
              'Arquivado',
              'Arquivada'
          )
        """
    )

    rec_pend = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = 'Recebimento'
          AND status NOT IN (
              'Concluído',
              'Concluido',
              'Arquivado',
              'Arquivada'
          )
        """
    )

    total_oco = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE prioridade = 'Alta'
          AND status NOT IN (
              'Concluído',
              'Concluido',
              'Arquivado',
              'Arquivada'
          )
        """
    )

    total_atividades = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        """
    )

    atividades_concluidas = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE status IN (
            'Concluído',
            'Concluido'
        )
        """
    )

    atividades_arquivadas = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE status IN (
            'Arquivado',
            'Arquivada'
        )
        """
    )

    # ========================================================
    # ATRASADOS
    #
    # Não existe módulo separado.
    #
    # O histórico permanece em Relatórios.
    # ========================================================

    cursor = executar(
        """
        SELECT *
        FROM atividades
        WHERE prazo IS NOT NULL
        """
    )

    registros_prazo = linhas_para_dict(
        cursor.fetchall()
    )

    fechar_cursor(cursor)

    registros_prazo = preparar_lista_atividades(
        registros_prazo
    )

    total_atrasados = sum(
        1
        for item in registros_prazo
        if item.get("foi_atrasada")
    )

    # ========================================================
    # PERCENTUAIS
    # ========================================================

    if total_atividades > 0:

        perc_atendidas = round(
            (
                atividades_concluidas
                / total_atividades
            ) * 100
        )

    else:

        perc_atendidas = 0

    if inv_total > 0:

        perc_inventario = round(
            (
                inv_conc
                / inv_total
            ) * 100
        )

    else:

        perc_inventario = 0

    if exp_total > 0:

        perc_expedicao = round(
            (
                exp_concluido
                / exp_total
            ) * 100
        )

    else:

        perc_expedicao = 0

    # ========================================================
    # DASHBOARD
    # ========================================================

    return render_template(
        "dashboard.html",
        usuario_atual=usuario_atual,
        atividades=atividades,
        chat=chat,
        usuarios=usuarios,
        busca=busca,

        total_req=total_req,
        total_atrasados=total_atrasados,

        inv_conc=inv_conc,
        inv_total=inv_total,

        exp_pend=exp_pend,
        exp_concluido=exp_concluido,
        exp_total=exp_total,

        rec_pend=rec_pend,
        total_oco=total_oco,

        total_atividades=total_atividades,
        atividades_concluidas=atividades_concluidas,
        atividades_arquivadas=atividades_arquivadas,

        perc_atendidas=perc_atendidas,
        perc_inventario=perc_inventario,
        perc_expedicao=perc_expedicao
    )


# ============================================================
# ATRASADOS
#
# COMPATIBILIDADE
#
# Não existe atrasados.html.
# O link antigo simplesmente abre Relatórios filtrado.
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

    total_geral = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE status NOT IN (
            'Arquivado',
            'Arquivada'
        )
        """
    )

    concluidas = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE status IN (
            'Concluído',
            'Concluido'
        )
        """
    )

    pendentes = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE status NOT IN (
            'Concluído',
            'Concluido',
            'Arquivado',
            'Arquivada'
        )
        """
    )

    inv_total = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = 'Inventário'
        """
    )

    inv_concluido = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = 'Inventário'
          AND status IN (
              'Concluído',
              'Concluido'
          )
        """
    )

    exp_total = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = 'Expedição'
        """
    )

    exp_concluido = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = 'Expedição'
          AND status IN (
              'Concluído',
              'Concluido'
          )
        """
    )

    perc_atendidas = (
        round(
            concluidas / total_geral * 100
        )
        if total_geral > 0
        else 0
    )

    perc_inventario = (
        round(
            inv_concluido / inv_total * 100
        )
        if inv_total > 0
        else 0
    )

    perc_expedicao = (
        round(
            exp_concluido / exp_total * 100
        )
        if exp_total > 0
        else 0
    )

    return render_template(
        "indicadores.html",
        usuario_atual=session[
            "usuario_atual"
        ],
        total_geral=total_geral,
        concluidas=concluidas,
        pendentes=pendentes,
        perc_atendidas=perc_atendidas,
        perc_inventario=perc_inventario,
        perc_expedicao=perc_expedicao
    )


# ============================================================
# RELATÓRIOS / HISTÓRICO
#
# Aqui ficam as atividades antigas, concluídas e arquivadas.
#
# Filtros:
# - todos
# - pendentes
# - andamento
# - concluidos
# - arquivados
# - atrasados
# ============================================================

@app.route("/relatorios")
def relatorios():

    if "usuario_atual" not in session:

        return redirect(
            url_for("login")
        )

    filtro = (
        request.args.get(
            "filtro",
            "todos"
        )
        .strip()
        .lower()
    )

    filtros_validos = {
        "todos",
        "pendentes",
        "andamento",
        "concluidos",
        "arquivados",
        "atrasados",
    }

    if filtro not in filtros_validos:
        filtro = "todos"

    cursor = executar(
        """
        SELECT *
        FROM atividades
        ORDER BY id DESC
        """
    )

    itens = preparar_lista_atividades(
        cursor.fetchall()
    )

    fechar_cursor(cursor)

    # --------------------------------------------------------
    # FILTRO PENDENTES
    # --------------------------------------------------------

    if filtro == "pendentes":

        itens = [
            item
            for item in itens
            if str(
                item.get("status", "")
            ).strip().lower()
            == "pendente"
        ]

    # --------------------------------------------------------
    # FILTRO EM ANDAMENTO
    # --------------------------------------------------------

    elif filtro == "andamento":

        itens = [
            item
            for item in itens
            if str(
                item.get("status", "")
            ).strip().lower()
            == "em andamento"
        ]

    # --------------------------------------------------------
    # FILTRO CONCLUÍDOS
    # --------------------------------------------------------

    elif filtro == "concluidos":

        itens = [
            item
            for item in itens
            if str(
                item.get("status", "")
            ).strip().lower()
            in {
                "concluído",
                "concluido"
            }
        ]

    # --------------------------------------------------------
    # FILTRO ARQUIVADOS
    # --------------------------------------------------------

    elif filtro == "arquivados":

        itens = [
            item
            for item in itens
            if str(
                item.get("status", "")
            ).strip().lower()
            in {
                "arquivado",
                "arquivada"
            }
        ]

    # --------------------------------------------------------
    # FILTRO ATRASADOS
    #
    # IMPORTANTE:
    # Não criamos uma página separada.
    #
    # Um registro pode aparecer aqui mesmo se já estiver
    # concluído ou arquivado, desde que tenha sido finalizado
    # depois do prazo.
    # --------------------------------------------------------

    elif filtro == "atrasados":

        itens = [
            item
            for item in itens
            if item.get("foi_atrasada")
        ]

    return render_template(
        "relatorios.html",
        usuario_atual=session[
            "usuario_atual"
        ],
        itens=itens,
        filtro=filtro
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

    nome_original = nome.strip()

    nome_normalizado = (
        nome_original
        .lower()
        .strip()
    )

    mapa = {

        "inicio":
            "Início",

        "início":
            "Início",

        "dashboard":
            "Início",

        "configuracoes":
            "Configurações",

        "configurações":
            "Configurações",

        "indicadores":
            "Indicadores",

        "melhorias":
            "Melhorias / PDCA",

        "melhorias / pdca":
            "Melhorias / PDCA",

        "melhorias/pdca":
            "Melhorias / PDCA",

        "pdca":
            "Melhorias / PDCA",

        "relatorios":
            "Relatórios",

        "relatórios":
            "Relatórios",

        "cadastros":
            "Cadastros",

        "estoque":
            "Estoque",

        "requisicoes":
            "Requisições",

        "requisições":
            "Requisições",

        "inventario":
            "Inventário",

        "inventário":
            "Inventário",

        "expedicao":
            "Expedição",

        "expedição":
            "Expedição",

        "recebimento":
            "Recebimento",

        "logistica reversa":
            "Logística Reversa",

        "logística reversa":
            "Logística Reversa",
    }

    titulo = mapa.get(
        nome_normalizado,
        nome_original.title()
    )

    # --------------------------------------------------------
    # INÍCIO
    # --------------------------------------------------------

    if titulo == "Início":

        return redirect(
            url_for("index")
        )

    # --------------------------------------------------------
    # CONFIGURAÇÕES
    # --------------------------------------------------------

    if titulo == "Configurações":

        return render_template(
            "configuracoes.html",
            usuario_atual=session[
                "usuario_atual"
            ]
        )

    # --------------------------------------------------------
    # INDICADORES
    # --------------------------------------------------------

    if titulo == "Indicadores":

        return redirect(
            url_for("indicadores")
        )

    # --------------------------------------------------------
    # RELATÓRIOS
    # --------------------------------------------------------

    if titulo == "Relatórios":

        return redirect(
            url_for("relatorios")
        )

    # --------------------------------------------------------
    # CADASTROS
    # --------------------------------------------------------

    if titulo == "Cadastros":

        cursor = executar(
            """
            SELECT *
            FROM usuarios
            ORDER BY nome
            """
        )

        usuarios = linhas_para_dict(
            cursor.fetchall()
        )

        fechar_cursor(cursor)

        return render_template(
            "cadastros.html",
            usuarios=usuarios,
            usuario_atual=session[
                "usuario_atual"
            ]
        )

    # --------------------------------------------------------
    # MELHORIAS / PDCA
    # --------------------------------------------------------

    if titulo == "Melhorias / PDCA":

        # ----------------------------------------------------
        # SALVAR NOVA MELHORIA
        # ----------------------------------------------------

        if request.method == "POST":

            titulo_melhoria = request.form.get(
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

            responsavel = request.form.get(
                "responsavel",
                session["usuario_atual"]
            ).strip()

            if not titulo_melhoria:

                flash(
                    "Informe o título da melhoria.",
                    "warning"
                )

                return redirect(
                    url_for(
                        "modulo",
                        nome="melhorias"
                    )
                )

            executar(
                """
                INSERT INTO melhorias (
                    titulo,
                    descricao,
                    status,
                    responsavel,
                    etapa,
                    autor
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    titulo_melhoria,
                    descricao,
                    "A Fazer",
                    responsavel,
                    etapa or "PDCA",
                    session["usuario_atual"]
                ),
                commit=True
            )

            flash(
                "Melhoria registrada com sucesso.",
                "success"
            )

            return redirect(
                url_for(
                    "modulo",
                    nome="melhorias"
                )
            )

        # ----------------------------------------------------
        # LISTAR MELHORIAS
        # ----------------------------------------------------

        cursor = executar(
            """
            SELECT *
            FROM melhorias
            ORDER BY id DESC
            """
        )

        melhorias = linhas_para_dict(
            cursor.fetchall()
        )

        fechar_cursor(cursor)

        return render_template(
            "melhorias.html",
            melhorias=melhorias,
            usuario_atual=session[
                "usuario_atual"
            ]
        )

    # --------------------------------------------------------
    # ESTOQUE
    # --------------------------------------------------------

    if titulo == "Estoque":

        cursor = executar(
            """
            SELECT *
            FROM estoque
            ORDER BY id DESC
            """
        )

        estoque = linhas_para_dict(
            cursor.fetchall()
        )

        fechar_cursor(cursor)

        return render_template(
            "modulo.html",
            titulo=titulo,
            modulo=nome_normalizado,
            usuario_atual=session[
                "usuario_atual"
            ],
            itens=estoque
        )

    # --------------------------------------------------------
    # CORREÇÃO DOS MÓDULOS
    #
    # "Requisições" é o módulo visual.
    # A categoria gravada no banco é "Separação".
    # --------------------------------------------------------

    categorias_modulo = {

        "Requisições": "Separação",

        "Inventário": "Inventário",

        "Expedição": "Expedição",

        "Recebimento": "Recebimento",

        "Logística Reversa": "Logística Reversa",
    }

    categoria_filtro = categorias_modulo.get(
        titulo
    )

    if categoria_filtro:

        cursor = executar(
            """
            SELECT *
            FROM atividades
            WHERE categoria = %s
            ORDER BY id DESC
            """,
            (categoria_filtro,)
        )

        itens = preparar_lista_atividades(
            cursor.fetchall()
        )

        fechar_cursor(cursor)

        return render_template(
            "modulo.html",
            titulo=titulo,
            modulo=nome_normalizado,
            usuario_atual=session[
                "usuario_atual"
            ],
            itens=itens
        )

    # --------------------------------------------------------
    # FALLBACK
    # --------------------------------------------------------

    return redirect(
        url_for("index")
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

    cursor = executar(
        """
        SELECT *
        FROM atividades
        ORDER BY id DESC
        """
    )

    atividades = preparar_lista_atividades(
        cursor.fetchall()
    )

    fechar_cursor(cursor)

    buffer = BytesIO()

    documento = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=20,
        leftMargin=20,
        topMargin=20,
        bottomMargin=20
    )

    estilos = getSampleStyleSheet()

    elementos = []

    elementos.append(
        Paragraph(
            "Relatório do Almoxarifado",
            estilos["Title"]
        )
    )

    elementos.append(
        Spacer(1, 15)
    )

    dados = [
        [
            "ID",
            "Requisição",
            "Atividade",
            "Categoria",
            "Responsável",
            "Prioridade",
            "Status",
            "Prazo",
            "Conclusão",
            "Atrasada"
        ]
    ]

    for item in atividades:

        dados.append(
            [
                str(
                    item.get(
                        "id",
                        ""
                    )
                ),

                str(
                    item.get(
                        "num_requisicao",
                        ""
                    )
                ),

                str(
                    item.get(
                        "atividade",
                        ""
                    )
                ),

                str(
                    item.get(
                        "categoria",
                        ""
                    )
                ),

                str(
                    item.get(
                        "responsavel",
                        ""
                    )
                ),

                str(
                    item.get(
                        "prioridade",
                        ""
                    )
                ),

                str(
                    item.get(
                        "status",
                        ""
                    )
                ),

                str(
                    item.get(
                        "prazo_formatado",
                        ""
                    )
                ),

                str(
                    item.get(
                        "concluido_formatado",
                        ""
                    )
                ),

                (
                    "SIM"
                    if item.get(
                        "foi_atrasada"
                    )
                    else "NÃO"
                )
            ]
        )

    tabela = Table(
        dados,
        repeatRows=1
    )

    tabela.setStyle(
        TableStyle(
            [
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
                )
            ]
        )
    )

    elementos.append(
        tabela
    )

    documento.build(
        elementos
    )

    buffer.seek(0)

    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="relatorio_almoxarifado.pdf"
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

    cursor = executar(
        """
        SELECT *
        FROM atividades
        WHERE id = %s
        LIMIT 1
        """,
        (id,)
    )

    atividade = linha_para_dict(
        cursor.fetchone()
    )

    fechar_cursor(cursor)

    if not atividade:

        flash(
            "Atividade não encontrada.",
            "danger"
        )

        return redirect(
            url_for("index")
        )

    cursor = executar(
        """
        SELECT *
        FROM usuarios
        ORDER BY nome
        """
    )

    usuarios = linhas_para_dict(
        cursor.fetchall()
    )

    fechar_cursor(cursor)

    if request.method == "POST":

        num_requisicao = normalizar_requisicao(
            request.form.get(
                "num_requisicao",
                ""
            )
        )

        prioridade = request.form.get(
            "prioridade",
            "Baixa"
        ).strip()

        atividade_nome = request.form.get(
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
            ""
        ).strip()

        prazo = request.form.get(
            "prazo",
            ""
        ).strip()

        status = request.form.get(
            "status",
            atividade.get(
                "status",
                "Pendente"
            )
        ).strip()

        prioridades_validas = {
            "Baixa",
            "Média",
            "Alta"
        }

        categorias_validas = {
            "Separação",
            "Inventário",
            "Expedição",
            "Recebimento",
            "Logística Reversa",
            "Estoque"
        }

        status_validos = {
            "Pendente",
            "Em andamento",
            "Concluído",
            "Concluido",
            "Arquivado",
            "Arquivada"
        }

        if prioridade not in prioridades_validas:
            prioridade = "Baixa"

        if categoria not in categorias_validas:
            categoria = "Separação"

        if status not in status_validos:
            status = "Pendente"

        if (
            categoria == "Separação"
            and not num_requisicao
        ):

            flash(
                "Informe o número da requisição para Separação.",
                "warning"
            )

            return render_template(
                "editar.html",
                atividade=atividade,
                usuarios=usuarios,
                prazo_form=prazo
            )

        if not atividade_nome:

            flash(
                "Informe a atividade.",
                "warning"
            )

            return render_template(
                "editar.html",
                atividade=atividade,
                usuarios=usuarios,
                prazo_form=prazo
            )

        if num_requisicao:

            if requisicao_duplicada(
                num_requisicao,
                ignorar_id=id
            ):

                flash(
                    f"A requisição {num_requisicao} já está em outra atividade ativa.",
                    "warning"
                )

                return render_template(
                    "editar.html",
                    atividade=atividade,
                    usuarios=usuarios,
                    prazo_form=prazo
                )

        # ----------------------------------------------------
        # Se mudou para Separação e ainda não tinha início,
        # registramos o início.
        # ----------------------------------------------------

        inicio_em = atividade.get(
            "inicio_em"
        )

        if (
            categoria == "Separação"
            and not inicio_em
        ):

            if usando_postgresql():

                inicio_em = agora_utc_naive()

            else:

                inicio_em = agora_sqlite()

        executar(
            """
            UPDATE atividades
            SET
                num_requisicao = %s,
                prioridade = %s,
                atividade = %s,
                descricao = %s,
                categoria = %s,
                responsavel = %s,
                prazo = %s,
                status = %s,
                inicio_em = %s
            WHERE id = %s
            """,
            (
                num_requisicao or None,
                prioridade,
                atividade_nome,
                descricao,
                categoria,
                responsavel,
                prazo or None,
                status,
                inicio_em,
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

    prazo_form = (
        atividade.get("prazo")
        or ""
    )

    if prazo_form and "T" not in str(
        prazo_form
    ):

        try:

            dt = prazo_em_datetime(
                prazo_form
            )

            if dt:

                prazo_form = dt.strftime(
                    "%Y-%m-%dT%H:%M"
                )

        except Exception:
            pass

    return render_template(
        "editar.html",
        atividade=atividade,
        usuarios=usuarios,
        prazo_form=prazo_form
    )


# ============================================================
# CONCLUIR
# ============================================================

@app.route("/concluir/<int:id>")
def concluir(id):

    if "usuario_atual" not in session:

        return redirect(
            url_for("login")
        )

    cursor = executar(
        """
        SELECT *
        FROM atividades
        WHERE id = %s
        LIMIT 1
        """,
        (id,)
    )

    atividade = linha_para_dict(
        cursor.fetchone()
    )

    fechar_cursor(cursor)

    if not atividade:

        flash(
            "Atividade não encontrada.",
            "danger"
        )

        return redirect(
            url_for("index")
        )

    if atividade.get("status") not in {
        "Pendente",
        "Em andamento"
    }:

        flash(
            "Essa atividade não pode ser concluída.",
            "warning"
        )

        return redirect(
            url_for("index")
        )

    if usando_postgresql():

        agora = agora_utc_naive()

    else:

        agora = agora_sqlite()

    executar(
        """
        UPDATE atividades
        SET
            status = 'Concluído',
            concluido_em = %s,
            encerrado_por = %s
        WHERE id = %s
        """,
        (
            agora,
            session["usuario_atual"],
            id
        ),
        commit=True
    )

    # ========================================================
    # EXPEDIÇÃO AUTOMÁTICA
    # ========================================================

    if atividade.get("categoria") == "Separação":

        requisicao = normalizar_requisicao(
            atividade.get("num_requisicao")
        )

        if requisicao:

            cursor = executar(
                """
                SELECT id
                FROM atividades
                WHERE UPPER(TRIM(num_requisicao)) = %s
                  AND categoria = 'Expedição'
                  AND status NOT IN (
                      'Concluído',
                      'Concluido',
                      'Arquivado',
                      'Arquivada'
                  )
                LIMIT 1
                """,
                (requisicao,)
            )

            expedicao_existente = (
                cursor.fetchone()
            )

            fechar_cursor(cursor)

            if not expedicao_existente:

                executar(
                    """
                    INSERT INTO atividades (
                        num_requisicao,
                        prioridade,
                        atividade,
                        descricao,
                        categoria,
                        responsavel,
                        prazo,
                        status,
                        inicio_em
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    """,
                    (
                        requisicao,
                        atividade.get(
                            "prioridade",
                            "Baixa"
                        ),
                        (
                            "Expedição da "
                            f"requisição {requisicao}"
                        ),
                        (
                            "Expedição criada "
                            "automaticamente após "
                            "conclusão da separação."
                        ),
                        "Expedição",
                        "",
                        None,
                        "Pendente",
                        agora
                    ),
                    commit=True
                )

    flash(
        "Atividade concluída com sucesso.",
        "success"
    )

    return redirect(
        url_for("index")
    )


# ============================================================
# ARQUIVAR
# ============================================================

@app.route("/arquivar/<int:id>")
def arquivar(id):

    if "usuario_atual" not in session:

        return redirect(
            url_for("login")
        )

    executar(
        """
        UPDATE atividades
        SET
            status = 'Arquivado',
            encerrado_por = %s
        WHERE id = %s
        """,
        (
            session["usuario_atual"],
            id
        ),
        commit=True
    )

    flash(
        "Registro arquivado com sucesso.",
        "success"
    )

    return redirect(
        url_for("index")
    )


# ============================================================
# DELETAR ANTIGO = ARQUIVAR
# ============================================================

@app.route("/deletar/<int:id>")
def deletar(id):

    return arquivar(id)


# ============================================================
# ESTOQUE
# ============================================================

@app.route(
    "/deletar_estoque/<int:id>"
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
        """,
        (id,),
        commit=True
    )

    flash(
        "Item removido do estoque.",
        "success"
    )

    return redirect(
        url_for(
            "modulo",
            nome="estoque"
        )
    )


# ============================================================
# MELHORIAS / PDCA
# ============================================================

@app.route(
    "/deletar_melhoria/<int:id>"
)
def deletar_melhoria(id):

    if "usuario_atual" not in session:

        return redirect(
            url_for("login")
        )

    # Não apagamos a melhoria.
    # Ela fica preservada no banco.
    executar(
        """
        UPDATE melhorias
        SET status = 'Arquivado'
        WHERE id = %s
        """,
        (id,),
        commit=True
    )

    flash(
        "Melhoria arquivada com sucesso.",
        "success"
    )

    return redirect(
        url_for(
            "modulo",
            nome="melhorias"
        )
    )


# ============================================================
# INICIALIZAÇÃO
# ============================================================

try:

    with app.app_context():

        init_db()

    print(
        "Banco de dados inicializado com sucesso."
    )

except Exception as erro:

    print(
        "ERRO AO INICIALIZAR O BANCO:"
    )

    print(
        repr(erro)
    )


# ============================================================
# EXECUÇÃO LOCAL
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
