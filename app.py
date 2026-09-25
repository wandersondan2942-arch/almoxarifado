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
    flash
)

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer
)


# =========================================================
# CONFIGURAÇÃO DO FLASK
# =========================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "chave-temporaria-apenas-para-desenvolvimento"
)

DATABASE_URL = os.environ.get("DATABASE_URL")

# Horário oficial para EXIBIÇÃO
FUSO_BRASIL = ZoneInfo("America/Sao_Paulo")


# =========================================================
# CONFIGURAÇÃO DO BANCO
# =========================================================

def usando_postgresql():
    return bool(DATABASE_URL)


def get_db():
    """
    Render:
        PostgreSQL

    Computador local:
        SQLite
    """

    db = getattr(g, "_database", None)

    if db is not None:
        return db

    if usando_postgresql():

        url = DATABASE_URL

        if url.startswith("postgres://"):
            url = url.replace(
                "postgres://",
                "postgresql://",
                1
            )

        db = psycopg2.connect(
            url,
            cursor_factory=psycopg2.extras.RealDictCursor
        )

    else:

        db = sqlite3.connect(
            "database.db"
        )

        db.row_factory = sqlite3.Row

    g._database = db

    return db


@app.teardown_appcontext
def close_connection(exception=None):

    db = getattr(g, "_database", None)

    if db is not None:

        try:
            db.close()

        except Exception:
            pass


# =========================================================
# FUNÇÕES AUXILIARES DO BANCO
# =========================================================

def executar(sql, parametros=()):
    """
    Executa SQL compatível com SQLite e PostgreSQL.

    O código utiliza %s nas consultas.
    Quando estiver no SQLite, convertemos %s para ?.
    """

    db = get_db()

    if not usando_postgresql():
        sql = sql.replace("%s", "?")

    cursor = db.cursor()

    cursor.execute(
        sql,
        parametros
    )

    return cursor


def linha_para_dict(linha):
    """
    Converte uma linha do banco para dict.

    PostgreSQL:
        RealDictRow

    SQLite:
        sqlite3.Row
    """

    if linha is None:
        return {}

    if isinstance(linha, dict):
        return dict(linha)

    try:
        return dict(linha)

    except Exception:

        try:

            return {
                chave: linha[chave]
                for chave in linha.keys()
            }

        except Exception:

            return {}


def linhas_para_dict(itens):

    return [
        linha_para_dict(item)
        for item in itens
    ]


def obter_valor(cursor):

    resultado = cursor.fetchone()

    if not resultado:
        return 0

    if isinstance(resultado, dict):
        return list(resultado.values())[0]

    try:
        return resultado[0]

    except Exception:

        try:
            return list(resultado.values())[0]

        except Exception:
            return 0


def fechar_cursor(cursor):

    if cursor:

        try:
            cursor.close()

        except Exception:
            pass


# =========================================================
# CONTEXTO DO USUÁRIO
# =========================================================

@app.context_processor
def inject_user():

    return {
        "usuario_atual": session.get("usuario")
    }


# =========================================================
# CONTADOR
# =========================================================

def contar(sql, parametros=()):

    cursor = None

    try:

        cursor = executar(
            sql,
            parametros
        )

        valor = obter_valor(
            cursor
        )

        return int(
            valor or 0
        )

    except Exception as erro:

        try:
            get_db().rollback()

        except Exception:
            pass

        print(
            f"[ERRO CONTADOR] {erro}"
        )

        return 0

    finally:

        fechar_cursor(cursor)


# =========================================================
# DATA / HORA
# =========================================================

def agora_utc():
    """
    Retorna o momento atual em UTC.
    """

    return datetime.now(
        timezone.utc
    )


def agora_brasil():
    """
    Retorna o momento atual no horário de Brasília.
    """

    return agora_utc().astimezone(
        FUSO_BRASIL
    )


def agora_utc_naive():
    """
    PostgreSQL utiliza TIMESTAMP sem timezone.

    O sistema armazena UTC sem tzinfo.
    """

    return agora_utc().replace(
        tzinfo=None
    )


def agora_sqlite():
    """
    SQLite armazena data/hora como texto UTC.
    """

    return agora_utc().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def data_brasil():

    return agora_brasil().date()


def converter_para_brasil(valor):
    """
    Converte valores armazenados em UTC
    para horário de Brasília.

    Aceita:
        - datetime
        - texto ISO
        - texto YYYY-MM-DD HH:MM:SS
    """

    if not valor:
        return None

    try:

        if isinstance(valor, datetime):

            dt = valor

        else:

            texto = str(
                valor
            ).strip()

            if not texto:
                return None

            texto = texto.replace(
                "Z",
                "+00:00"
            )

            try:

                dt = datetime.fromisoformat(
                    texto
                )

            except Exception:

                dt = datetime.strptime(
                    texto[:19],
                    "%Y-%m-%d %H:%M:%S"
                )

        # Valores antigos sem timezone
        # são tratados como UTC.
        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            FUSO_BRASIL
        )

    except Exception as erro:

        print(
            f"[ERRO CONVERSÃO DATA] "
            f"{valor} -> {erro}"
        )

        return None


def formatar_data_hora(valor):

    dt = converter_para_brasil(
        valor
    )

    if not dt:
        return "-"

    return dt.strftime(
        "%d/%m/%Y %H:%M"
    )


def formatar_hora(valor):

    dt = converter_para_brasil(
        valor
    )

    if not dt:
        return "-"

    return dt.strftime(
        "%H:%M"
    )


def calcular_duracao(inicio, fim):
    """
    Calcula a duração entre início e conclusão.

    Exemplo:

        01/09/2026 08:00
        01/09/2026 10:35

        Resultado:

        2h 35min
    """

    dt_inicio = converter_para_brasil(
        inicio
    )

    dt_fim = converter_para_brasil(
        fim
    )

    if not dt_inicio or not dt_fim:
        return "-"

    diferenca = dt_fim - dt_inicio

    segundos = int(
        diferenca.total_seconds()
    )

    if segundos < 0:
        return "-"

    horas = segundos // 3600

    minutos = (
        segundos % 3600
    ) // 60

    if horas > 0:

        return (
            f"{horas}h "
            f"{minutos:02d}min"
        )

    return (
        f"{minutos}min"
    )


# =========================================================
# PREPARAÇÃO DAS ATIVIDADES
# =========================================================

def preparar_atividade(item):
    """
    Prepara uma atividade para exibição.

    Mantém os valores originais para cálculo
    e também fornece os valores formatados.
    """

    dados = linha_para_dict(
        item
    )

    inicio_original = dados.get(
        "inicio_em"
    )

    conclusao_original = dados.get(
        "concluido_em"
    )

    # -----------------------------------------------------
    # VALORES ORIGINAIS
    # -----------------------------------------------------

    dados["inicio_original"] = (
        inicio_original
    )

    dados["conclusao_original"] = (
        conclusao_original
    )

    # -----------------------------------------------------
    # VALORES FORMATADOS
    # -----------------------------------------------------

    dados["inicio_formatado"] = (
        formatar_data_hora(
            inicio_original
        )
    )

    dados["conclusao_formatada"] = (
        formatar_data_hora(
            conclusao_original
        )
    )

    # -----------------------------------------------------
    # COMPATIBILIDADE COM HTML ANTIGO
    # -----------------------------------------------------

    dados["inicio_em"] = (
        dados["inicio_formatado"]
    )

    dados["concluido_em"] = (
        dados["conclusao_formatada"]
    )

    # -----------------------------------------------------
    # ENCERRADO POR
    # -----------------------------------------------------

    dados["encerrado_por"] = (
        dados.get("encerrado_por")
        or "-"
    )

    # -----------------------------------------------------
    # DURAÇÃO
    # -----------------------------------------------------

    dados["duracao"] = calcular_duracao(
        inicio_original,
        conclusao_original
    )

    return dados


def preparar_lista_atividades(itens):

    return [
        preparar_atividade(item)
        for item in itens
    ]


# =========================================================
# PREPARAÇÃO DO CHAT
# =========================================================

def preparar_mensagem_chat(item):

    dados = linha_para_dict(
        item
    )

    horario_original = dados.get(
        "horario"
    )

    dados["horario_original"] = (
        horario_original
    )

    dados["horario"] = formatar_data_hora(
        horario_original
    )

    return dados


def preparar_lista_chat(itens):

    return [
        preparar_mensagem_chat(item)
        for item in itens
    ]


# =========================================================
# CRIAÇÃO E MIGRAÇÃO DO BANCO
# =========================================================

def init_db():

    db = get_db()

    cursor = db.cursor()

    try:

        # =====================================================
        # POSTGRESQL
        # =====================================================

        if usando_postgresql():

            # -------------------------------------------------
            # USUÁRIOS
            # -------------------------------------------------

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    id SERIAL PRIMARY KEY,
                    nome TEXT UNIQUE NOT NULL,
                    senha TEXT NOT NULL
                )
            """)

            # -------------------------------------------------
            # ATIVIDADES
            # -------------------------------------------------

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS atividades (
                    id SERIAL PRIMARY KEY,
                    num_requisicao TEXT,
                    prioridade TEXT NOT NULL DEFAULT 'Baixa',
                    atividade TEXT NOT NULL,
                    descricao TEXT,
                    categoria TEXT NOT NULL DEFAULT 'Separação',
                    responsavel TEXT NOT NULL,
                    prazo TEXT NOT NULL DEFAULT '',
                    status TEXT DEFAULT 'Pendente',
                    inicio_em TIMESTAMP,
                    concluido_em TIMESTAMP,
                    encerrado_por TEXT
                )
            """)

            # -------------------------------------------------
            # MIGRAÇÃO
            # -------------------------------------------------

            cursor.execute("""
                ALTER TABLE atividades
                ADD COLUMN IF NOT EXISTS num_requisicao TEXT
            """)

            cursor.execute("""
                ALTER TABLE atividades
                ADD COLUMN IF NOT EXISTS prioridade TEXT
            """)

            cursor.execute("""
                ALTER TABLE atividades
                ADD COLUMN IF NOT EXISTS atividade TEXT
            """)

            cursor.execute("""
                ALTER TABLE atividades
                ADD COLUMN IF NOT EXISTS descricao TEXT
            """)

            cursor.execute("""
                ALTER TABLE atividades
                ADD COLUMN IF NOT EXISTS categoria TEXT
            """)

            cursor.execute("""
                ALTER TABLE atividades
                ADD COLUMN IF NOT EXISTS responsavel TEXT
            """)

            cursor.execute("""
                ALTER TABLE atividades
                ADD COLUMN IF NOT EXISTS prazo TEXT
            """)

            cursor.execute("""
                ALTER TABLE atividades
                ADD COLUMN IF NOT EXISTS status TEXT
            """)

            cursor.execute("""
                ALTER TABLE atividades
                ADD COLUMN IF NOT EXISTS inicio_em TIMESTAMP
            """)

            cursor.execute("""
                ALTER TABLE atividades
                ADD COLUMN IF NOT EXISTS concluido_em TIMESTAMP
            """)

            cursor.execute("""
                ALTER TABLE atividades
                ADD COLUMN IF NOT EXISTS encerrado_por TEXT
            """)

            # -------------------------------------------------
            # CORREÇÃO DE DADOS ANTIGOS
            # -------------------------------------------------

            cursor.execute("""
                UPDATE atividades
                SET prioridade = 'Baixa'
                WHERE prioridade IS NULL
            """)

            cursor.execute("""
                UPDATE atividades
                SET categoria = 'Separação'
                WHERE categoria IS NULL
            """)

            cursor.execute("""
                UPDATE atividades
                SET prazo = ''
                WHERE prazo IS NULL
            """)

            cursor.execute("""
                UPDATE atividades
                SET status = 'Pendente'
                WHERE status IS NULL
            """)

            cursor.execute("""
                UPDATE atividades
                SET descricao = ''
                WHERE descricao IS NULL
            """)

            # -------------------------------------------------
            # CHAT
            # -------------------------------------------------

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat (
                    id SERIAL PRIMARY KEY,
                    remetente TEXT NOT NULL,
                    mensagem TEXT NOT NULL,
                    horario TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # -------------------------------------------------
            # MELHORIAS / PDCA
            # -------------------------------------------------

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS melhorias (
                    id SERIAL PRIMARY KEY,
                    titulo TEXT NOT NULL,
                    descricao TEXT NOT NULL,
                    autor TEXT NOT NULL,
                    etapa TEXT DEFAULT 'Planejar (Plan)',
                    status TEXT DEFAULT 'Pendente',
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                ALTER TABLE melhorias
                ADD COLUMN IF NOT EXISTS descricao TEXT
            """)

            cursor.execute("""
                ALTER TABLE melhorias
                ADD COLUMN IF NOT EXISTS autor TEXT
            """)

            cursor.execute("""
                ALTER TABLE melhorias
                ADD COLUMN IF NOT EXISTS etapa TEXT
            """)

            cursor.execute("""
                ALTER TABLE melhorias
                ADD COLUMN IF NOT EXISTS status TEXT
            """)

            cursor.execute("""
                ALTER TABLE melhorias
                ADD COLUMN IF NOT EXISTS criado_em TIMESTAMP
            """)

            # -------------------------------------------------
            # ESTOQUE
            # -------------------------------------------------

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS estoque (
                    id SERIAL PRIMARY KEY,
                    rua TEXT,
                    prateleira TEXT,
                    codigo_material TEXT,
                    descricao TEXT,
                    quantidade INTEGER DEFAULT 0
                )
            """)

        # =====================================================
        # SQLITE
        # =====================================================

        else:

            # -------------------------------------------------
            # USUÁRIOS
            # -------------------------------------------------

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT UNIQUE NOT NULL,
                    senha TEXT NOT NULL
                )
            """)

            # -------------------------------------------------
            # ATIVIDADES
            # -------------------------------------------------

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS atividades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    num_requisicao TEXT,
                    prioridade TEXT NOT NULL DEFAULT 'Baixa',
                    atividade TEXT NOT NULL,
                    descricao TEXT,
                    categoria TEXT NOT NULL DEFAULT 'Separação',
                    responsavel TEXT NOT NULL,
                    prazo TEXT NOT NULL DEFAULT '',
                    status TEXT DEFAULT 'Pendente',
                    inicio_em TEXT,
                    concluido_em TEXT,
                    encerrado_por TEXT
                )
            """)

            # -------------------------------------------------
            # MIGRAÇÃO SQLITE
            # -------------------------------------------------

            cursor.execute("""
                PRAGMA table_info(atividades)
            """)

            colunas = cursor.fetchall()

            nomes_colunas = []

            for coluna in colunas:

                try:

                    nomes_colunas.append(
                        coluna["name"]
                    )

                except Exception:

                    nomes_colunas.append(
                        coluna[1]
                    )

            colunas_necessarias = {

                "num_requisicao":
                    "ALTER TABLE atividades "
                    "ADD COLUMN num_requisicao TEXT",

                "prioridade":
                    "ALTER TABLE atividades "
                    "ADD COLUMN prioridade TEXT",

                "atividade":
                    "ALTER TABLE atividades "
                    "ADD COLUMN atividade TEXT",

                "descricao":
                    "ALTER TABLE atividades "
                    "ADD COLUMN descricao TEXT",

                "categoria":
                    "ALTER TABLE atividades "
                    "ADD COLUMN categoria TEXT",

                "responsavel":
                    "ALTER TABLE atividades "
                    "ADD COLUMN responsavel TEXT",

                "prazo":
                    "ALTER TABLE atividades "
                    "ADD COLUMN prazo TEXT",

                "status":
                    "ALTER TABLE atividades "
                    "ADD COLUMN status TEXT",

                "inicio_em":
                    "ALTER TABLE atividades "
                    "ADD COLUMN inicio_em TEXT",

                "concluido_em":
                    "ALTER TABLE atividades "
                    "ADD COLUMN concluido_em TEXT",

                "encerrado_por":
                    "ALTER TABLE atividades "
                    "ADD COLUMN encerrado_por TEXT"
            }

            for nome_coluna, comando in colunas_necessarias.items():

                if nome_coluna not in nomes_colunas:

                    print(
                        f"[BANCO] Adicionando coluna "
                        f"{nome_coluna}..."
                    )

                    cursor.execute(
                        comando
                    )

            # -------------------------------------------------
            # CORREÇÃO DE DADOS ANTIGOS
            # -------------------------------------------------

            cursor.execute("""
                UPDATE atividades
                SET prioridade = 'Baixa'
                WHERE prioridade IS NULL
            """)

            cursor.execute("""
                UPDATE atividades
                SET categoria = 'Separação'
                WHERE categoria IS NULL
            """)

            cursor.execute("""
                UPDATE atividades
                SET prazo = ''
                WHERE prazo IS NULL
            """)

            cursor.execute("""
                UPDATE atividades
                SET status = 'Pendente'
                WHERE status IS NULL
            """)

            cursor.execute("""
                UPDATE atividades
                SET descricao = ''
                WHERE descricao IS NULL
            """)

            # IMPORTANTE:
            # Não criamos artificialmente um horário de início
            # para registros antigos.
            #
            # Se não sabemos quando começaram,
            # mantemos NULL.
            #
            # Isso evita falsificar o histórico.

            # -------------------------------------------------
            # CHAT
            # -------------------------------------------------

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    remetente TEXT NOT NULL,
                    mensagem TEXT NOT NULL,
                    horario TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # -------------------------------------------------
            # MELHORIAS
            # -------------------------------------------------

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS melhorias (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    titulo TEXT NOT NULL,
                    descricao TEXT NOT NULL,
                    autor TEXT NOT NULL,
                    etapa TEXT DEFAULT 'Planejar (Plan)',
                    status TEXT DEFAULT 'Pendente',
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                PRAGMA table_info(melhorias)
            """)

            colunas_melhorias = cursor.fetchall()

            nomes_melhorias = []

            for coluna in colunas_melhorias:

                try:

                    nomes_melhorias.append(
                        coluna["name"]
                    )

                except Exception:

                    nomes_melhorias.append(
                        coluna[1]
                    )

            colunas_melhoria_necessarias = {

                "descricao":
                    "ALTER TABLE melhorias "
                    "ADD COLUMN descricao TEXT",

                "autor":
                    "ALTER TABLE melhorias "
                    "ADD COLUMN autor TEXT",

                "etapa":
                    "ALTER TABLE melhorias "
                    "ADD COLUMN etapa TEXT",

                "status":
                    "ALTER TABLE melhorias "
                    "ADD COLUMN status TEXT",

                "criado_em":
                    "ALTER TABLE melhorias "
                    "ADD COLUMN criado_em TIMESTAMP"
            }

            for nome_coluna, comando in colunas_melhoria_necessarias.items():

                if nome_coluna not in nomes_melhorias:

                    cursor.execute(
                        comando
                    )

            # -------------------------------------------------
            # ESTOQUE
            # -------------------------------------------------

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS estoque (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rua TEXT,
                    prateleira TEXT,
                    codigo_material TEXT,
                    descricao TEXT,
                    quantidade INTEGER DEFAULT 0
                )
            """)

        # =====================================================
        # USUÁRIO INICIAL
        # =====================================================

        cursor.execute(
            "SELECT COUNT(*) FROM usuarios"
        )

        quantidade_usuarios = obter_valor(
            cursor
        )

        if quantidade_usuarios == 0:

            if usando_postgresql():

                cursor.execute(
                    """
                    INSERT INTO usuarios
                    (nome, senha)
                    VALUES (%s, %s)
                    """,
                    (
                        "Wanderson Fernandes",
                        "1234"
                    )
                )

            else:

                cursor.execute(
                    """
                    INSERT INTO usuarios
                    (nome, senha)
                    VALUES (?, ?)
                    """,
                    (
                        "Wanderson Fernandes",
                        "1234"
                    )
                )

        db.commit()

        print(
            "[BANCO] Banco inicializado com sucesso."
        )

    except Exception as erro:

        db.rollback()

        print(
            f"[ERRO BANCO] {erro}"
        )

        raise

    finally:

        fechar_cursor(cursor)


# =========================================================
# ARQUIVAMENTO AUTOMÁTICO APÓS 24 HORAS
# =========================================================

def arquivar_atividades_expiradas():

    cursor = None

    try:

        db = get_db()

        cursor = db.cursor()

        if usando_postgresql():

            limite = (
                agora_utc_naive()
                - timedelta(hours=24)
            )

            cursor.execute(
                """
                UPDATE atividades
                SET status = 'Arquivada'
                WHERE status = 'Concluído'
                AND concluido_em IS NOT NULL
                AND concluido_em <= %s
                """,
                (
                    limite,
                )
            )

        else:

            limite = (
                agora_utc()
                - timedelta(hours=24)
            )

            limite_texto = limite.strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            cursor.execute(
                """
                UPDATE atividades
                SET status = 'Arquivada'
                WHERE status = 'Concluído'
                AND concluido_em IS NOT NULL
                AND concluido_em <= ?
                """,
                (
                    limite_texto,
                )
            )

        quantidade = cursor.rowcount

        db.commit()

        if quantidade > 0:

            print(
                f"[ARQUIVAMENTO] "
                f"{quantidade} atividade(s) arquivada(s)."
            )

    except Exception as erro:

        try:
            get_db().rollback()

        except Exception:
            pass

        print(
            f"[ERRO ARQUIVAMENTO] {erro}"
        )

    finally:

        fechar_cursor(cursor)


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    erro = None

    cursor = None

    if request.method == "POST":

        nome = request.form.get(
            "nome",
            ""
        ).strip()

        senha = request.form.get(
            "senha",
            ""
        ).strip()

        try:

            cursor = executar(
                """
                SELECT *
                FROM usuarios
                WHERE nome = %s
                AND senha = %s
                """,
                (
                    nome,
                    senha
                )
            )

            user = cursor.fetchone()

            if user:

                usuario = linha_para_dict(
                    user
                )

                session["usuario"] = (
                    usuario["nome"]
                )

                return redirect(
                    url_for("index")
                )

            erro = (
                "Usuário ou senha inválidos!"
            )

        except Exception as erro_banco:

            get_db().rollback()

            print(
                f"[ERRO LOGIN] {erro_banco}"
            )

            erro = (
                "Erro ao realizar login."
            )

        finally:

            fechar_cursor(cursor)

    return render_template(
        "login.html",
        erro=erro
    )


# =========================================================
# CADASTRO DE USUÁRIO
# =========================================================

@app.route(
    "/cadastro_usuario",
    methods=["GET", "POST"]
)
def cadastro_usuario():

    erro = None

    cursor = None

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

            erro = (
                "Preencha todos os campos."
            )

        else:

            try:

                cursor = executar(
                    """
                    INSERT INTO usuarios
                    (nome, senha)
                    VALUES (%s, %s)
                    """,
                    (
                        nome,
                        senha
                    )
                )

                get_db().commit()

                flash(
                    "Usuário cadastrado com sucesso.",
                    "success"
                )

                return redirect(
                    url_for("login")
                )

            except Exception as erro_banco:

                get_db().rollback()

                print(
                    f"[ERRO USUÁRIO] "
                    f"{erro_banco}"
                )

                erro = (
                    "Não foi possível cadastrar "
                    "este usuário. "
                    "O nome pode já estar cadastrado."
                )

            finally:

                fechar_cursor(cursor)

    return render_template(
        "cadastro_usuario.html",
        erro=erro
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.pop(
        "usuario",
        None
    )

    return redirect(
        url_for("login")
    )


# =========================================================
# PAINEL PRINCIPAL
# =========================================================

@app.route(
    "/",
    methods=["GET", "POST"]
)
def index():

    if "usuario" not in session:

        return redirect(
            url_for("login")
        )

    arquivar_atividades_expiradas()

    usuario_atual = session["usuario"]

    db = get_db()

    # =====================================================
    # POST
    # =====================================================

    if request.method == "POST":

        acao_chat = request.form.get(
            "acao_chat"
        )

        # =================================================
        # CHAT
        # =================================================

        if acao_chat == "enviar":

            mensagem = request.form.get(
                "mensagem",
                ""
            ).strip()

            if mensagem:

                cursor = None

                try:

                    cursor = executar(
                        """
                        INSERT INTO chat
                        (remetente, mensagem)
                        VALUES (%s, %s)
                        """,
                        (
                            usuario_atual,
                            mensagem
                        )
                    )

                    db.commit()

                except Exception as erro:

                    db.rollback()

                    print(
                        f"[ERRO CHAT] {erro}"
                    )

                finally:

                    fechar_cursor(cursor)

            return redirect(
                url_for("index")
            )

        # =================================================
        # NOVA ATIVIDADE
        # =================================================

        num_requisicao = (
            request.form.get(
                "num_requisicao",
                ""
            ).strip()
        )

        prioridade = (
            request.form.get(
                "prioridade"
            )
            or "Baixa"
        )

        atividade = (
            request.form.get(
                "atividade",
                ""
            ).strip()
        )

        descricao = (
            request.form.get(
                "descricao",
                ""
            ).strip()
        )

        categoria = (
            request.form.get(
                "categoria"
            )
            or "Separação"
        )

        responsavel = (
            request.form.get(
                "responsavel"
            )
            or usuario_atual
        )

        prazo = (
            request.form.get(
                "prazo"
            )
            or ""
        )

        # =================================================
        # VALIDAÇÕES
        # =================================================

        if not atividade:

            flash(
                "Informe a atividade.",
                "danger"
            )

            return redirect(
                url_for("index")
            )

        if (
            categoria == "Separação"
            and not num_requisicao
        ):

            flash(
                "Informe o número da requisição "
                "para criar uma Separação.",
                "warning"
            )

            return redirect(
                url_for("index")
            )

        # =================================================
        # DATA/HORA DE INÍCIO
        # =================================================

        if usando_postgresql():

            inicio_em = (
                agora_utc_naive()
            )

        else:

            inicio_em = (
                agora_sqlite()
            )

        # =================================================
        # INSERÇÃO
        # =================================================

        cursor = None

        try:

            cursor = executar(
                """
                INSERT INTO atividades
                (
                    num_requisicao,
                    prioridade,
                    atividade,
                    descricao,
                    categoria,
                    responsavel,
                    prazo,
                    status,
                    inicio_em,
                    concluido_em,
                    encerrado_por
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    'Pendente',
                    %s,
                    NULL,
                    NULL
                )
                """,
                (
                    num_requisicao or None,
                    prioridade,
                    atividade,
                    descricao,
                    categoria,
                    responsavel,
                    prazo,
                    inicio_em
                )
            )

            db.commit()

            flash(
                "Atividade registrada com sucesso.",
                "success"
            )

        except Exception as erro:

            db.rollback()

            print(
                f"[ERRO ATIVIDADE] {erro}"
            )

            flash(
                "Não foi possível registrar "
                "a atividade.",
                "danger"
            )

        finally:

            fechar_cursor(cursor)

        return redirect(
            url_for("index")
        )

    # =====================================================
    # LISTAGEM
    # =====================================================

    busca = request.args.get(
        "q",
        ""
    ).strip()

    cursor = None

    try:

        if busca:

            termo = f"%{busca}%"

            cursor = executar(
                """
                SELECT *
                FROM atividades
                WHERE
                    atividade LIKE %s
                    OR descricao LIKE %s
                    OR categoria LIKE %s
                    OR responsavel LIKE %s
                    OR num_requisicao LIKE %s
                    OR status LIKE %s
                    OR encerrado_por LIKE %s
                ORDER BY id DESC
                """,
                (
                    termo,
                    termo,
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
                WHERE status = 'Pendente'
                ORDER BY id DESC
                """
            )

        atividades = cursor.fetchall()

        atividades = preparar_lista_atividades(
            atividades
        )

    except Exception as erro:

        print(
            f"[ERRO LISTAGEM] {erro}"
        )

        atividades = []

    finally:

        fechar_cursor(cursor)

    # =====================================================
    # CHAT
    # =====================================================

    cursor = None

    try:

        cursor = executar(
            """
            SELECT *
            FROM chat
            ORDER BY id DESC
            LIMIT 15
            """
        )

        mensagens_chat = cursor.fetchall()

        mensagens_chat = preparar_lista_chat(
            mensagens_chat
        )

    except Exception as erro:

        print(
            f"[ERRO CHAT LISTA] {erro}"
        )

        mensagens_chat = []

    finally:

        fechar_cursor(cursor)

    # =====================================================
    # INDICADORES
    # =====================================================

    total_req = contar(
        """
        SELECT COUNT(*)
        FROM atividades
        WHERE categoria = 'Separação'
        AND status = 'Pendente'
        """
    )

    inv_concluido = contar(
        """
        SELECT COUNT(*)
        FROM atividades
        WHERE categoria = 'Inventário'
        AND status = 'Concluído'
        """
    )

    inv_total_indicador = contar(
        """
        SELECT COUNT(*)
        FROM atividades
        WHERE categoria = 'Inventário'
        AND status IN ('Pendente', 'Concluído')
        """
    )

    exp_pend = contar(
        """
        SELECT COUNT(*)
        FROM atividades
        WHERE categoria = 'Expedição'
        AND status = 'Pendente'
        """
    )

    exp_concluido = contar(
        """
        SELECT COUNT(*)
        FROM atividades
        WHERE categoria = 'Expedição'
        AND status = 'Concluído'
        """
    )

    exp_total = contar(
        """
        SELECT COUNT(*)
        FROM atividades
        WHERE categoria = 'Expedição'
        AND status IN ('Pendente', 'Concluído')
        """
    )

    rec_pend = contar(
        """
        SELECT COUNT(*)
        FROM atividades
        WHERE categoria = 'Recebimento'
        AND status = 'Pendente'
        """
    )

    total_oco = contar(
        """
        SELECT COUNT(*)
        FROM atividades
        WHERE prioridade = 'Alta'
        AND status = 'Pendente'
        """
    )

    total_atividades = contar(
        """
        SELECT COUNT(*)
        FROM atividades
        WHERE status IN ('Pendente', 'Concluído')
        """
    )

    atividades_concluidas = contar(
        """
        SELECT COUNT(*)
        FROM atividades
        WHERE status = 'Concluído'
        """
    )

    atividades_arquivadas = contar(
        """
        SELECT COUNT(*)
        FROM atividades
        WHERE status = 'Arquivada'
        """
    )

    # =====================================================
    # PERCENTUAIS
    # =====================================================

    if total_atividades > 0:

        perc_atendidas = round(
            (
                atividades_concluidas
                / total_atividades
            ) * 100
        )

    else:

        perc_atendidas = 0

    if inv_total_indicador > 0:

        perc_inventario = round(
            (
                inv_concluido
                / inv_total_indicador
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

    # =====================================================
    # USUÁRIOS
    # =====================================================

    cursor = None

    try:

        cursor = executar(
            """
            SELECT *
            FROM usuarios
            ORDER BY nome
            """
        )

        usuarios = cursor.fetchall()

        usuarios = linhas_para_dict(
            usuarios
        )

    except Exception as erro:

        print(
            f"[ERRO USUÁRIOS] {erro}"
        )

        usuarios = []

    finally:

        fechar_cursor(cursor)

    # =====================================================
    # RENDER
    # =====================================================

    return render_template(
        "index.html",

        atividades=atividades,

        mensagens_chat=mensagens_chat,

        usuarios=usuarios,

        busca=busca,

        total_req=total_req,

        inv_conc=inv_concluido,

        inv_total=inv_total_indicador,

        exp_pend=exp_pend,

        rec_pend=rec_pend,

        total_oco=total_oco,

        perc_atendidas=perc_atendidas,

        perc_inventario=perc_inventario,

        perc_expedicao=perc_expedicao,

        total_atividades=total_atividades,

        atividades_concluidas=atividades_concluidas,

        atividades_arquivadas=atividades_arquivadas
    )


# =========================================================
# MÓDULOS
# =========================================================

@app.route(
    "/modulo/<path:nome>",
    methods=["GET", "POST"]
)
def modulo(nome):

    if "usuario" not in session:

        return redirect(
            url_for("login")
        )

    nome_limpo = nome

    # =====================================================
    # CONFIGURAÇÕES
    # =====================================================

    if "Configurações" in nome_limpo:

        return render_template(
            "configuracoes.html"
        )

    # =====================================================
    # INDICADORES
    # =====================================================

    if "Indicadores" in nome_limpo:

        total_geral = contar(
            """
            SELECT COUNT(*)
            FROM atividades
            WHERE status IN ('Pendente', 'Concluído')
            """
        )

        concluidas = contar(
            """
            SELECT COUNT(*)
            FROM atividades
            WHERE status = 'Concluído'
            """
        )

        pendentes = contar(
            """
            SELECT COUNT(*)
            FROM atividades
            WHERE status = 'Pendente'
            """
        )

        inv_total = contar(
            """
            SELECT COUNT(*)
            FROM atividades
            WHERE categoria = 'Inventário'
            AND status IN ('Pendente', 'Concluído')
            """
        )

        inv_concluido = contar(
            """
            SELECT COUNT(*)
            FROM atividades
            WHERE categoria = 'Inventário'
            AND status = 'Concluído'
            """
        )

        exp_total = contar(
            """
            SELECT COUNT(*)
            FROM atividades
            WHERE categoria = 'Expedição'
            AND status IN ('Pendente', 'Concluído')
            """
        )

        exp_concluido = contar(
            """
            SELECT COUNT(*)
            FROM atividades
            WHERE categoria = 'Expedição'
            AND status = 'Concluído'
            """
        )

        perc_atendidas = (
            round(
                concluidas
                / total_geral
                * 100
            )
            if total_geral
            else 0
        )

        perc_inventario = (
            round(
                inv_concluido
                / inv_total
                * 100
            )
            if inv_total
            else 0
        )

        perc_expedicao = (
            round(
                exp_concluido
                / exp_total
                * 100
            )
            if exp_total
            else 0
        )

        return render_template(
            "indicadores.html",

            total_geral=total_geral,

            concluidas=concluidas,

            pendentes=pendentes,

            perc_atendidas=perc_atendidas,

            perc_inventario=perc_inventario,

            perc_expedicao=perc_expedicao
        )

    # =====================================================
    # PDCA / MELHORIAS
    # =====================================================

    if (
        "PDCA" in nome_limpo
        or "Melhorias" in nome_limpo
    ):

        if request.method == "POST":

            titulo = (
                request.form.get(
                    "titulo",
                    ""
                ).strip()
            )

            descricao = (
                request.form.get(
                    "descricao",
                    ""
                ).strip()
            )

            etapa = (
                request.form.get(
                    "etapa"
                )
                or "Planejar (Plan)"
            )

            autor = session["usuario"]

            if not titulo:

                flash(
                    "Informe um título para a melhoria.",
                    "warning"
                )

                return redirect(
                    url_for(
                        "modulo",
                        nome="Melhorias / PDCA"
                    )
                )

            cursor = None

            try:

                cursor = executar(
                    """
                    INSERT INTO melhorias
                    (
                        titulo,
                        descricao,
                        autor,
                        etapa,
                        status
                    )
                    VALUES
                    (
                        %s,
                        %s,
                        %s,
                        %s,
                        'Pendente'
                    )
                    """,
                    (
                        titulo,
                        descricao,
                        autor,
                        etapa
                    )
                )

                get_db().commit()

                flash(
                    "Melhoria cadastrada com sucesso.",
                    "success"
                )

            except Exception as erro:

                get_db().rollback()

                print(
                    f"[ERRO PDCA] {erro}"
                )

                flash(
                    "Não foi possível cadastrar "
                    "a melhoria.",
                    "danger"
                )

            finally:

                fechar_cursor(cursor)

            return redirect(
                url_for(
                    "modulo",
                    nome="Melhorias / PDCA"
                )
            )

        cursor = None

        try:

            cursor = executar(
                """
                SELECT *
                FROM melhorias
                ORDER BY id DESC
                """
            )

            melhorias = cursor.fetchall()

            melhorias = linhas_para_dict(
                melhorias
            )

        except Exception as erro:

            print(
                f"[ERRO PDCA LISTA] {erro}"
            )

            melhorias = []

        finally:

            fechar_cursor(cursor)

        return render_template(
            "pdca.html",
            melhorias=melhorias
        )

    # =====================================================
    # RELATÓRIOS
    # =====================================================

    if "Relatórios" in nome_limpo:

        cursor = None

        try:

            cursor = executar(
                """
                SELECT *
                FROM atividades
                ORDER BY id DESC
                """
            )

            itens = cursor.fetchall()

            itens = preparar_lista_atividades(
                itens
            )

        except Exception as erro:

            print(
                f"[ERRO RELATÓRIOS] {erro}"
            )

            itens = []

        finally:

            fechar_cursor(cursor)

        return render_template(
            "relatorios.html",
            itens=itens
        )

    # =====================================================
    # CADASTROS
    # =====================================================

    if "Cadastros" in nome_limpo:

        cursor = None

        try:

            cursor = executar(
                """
                SELECT *
                FROM usuarios
                ORDER BY nome
                """
            )

            usuarios = cursor.fetchall()

            usuarios = linhas_para_dict(
                usuarios
            )

        except Exception as erro:

            print(
                f"[ERRO CADASTROS] {erro}"
            )

            usuarios = []

        finally:

            fechar_cursor(cursor)

        return render_template(
            "cadastros.html",
            usuarios=usuarios
        )

    # =====================================================
    # ESTOQUE
    # =====================================================

    if "Estoque" in nome_limpo:

        if request.method == "POST":

            acao = request.form.get(
                "acao_estoque"
            )

            # =================================================
            # CADASTRO MANUAL
            # =================================================

            if acao == "cadastrar_manual":

                rua = (
                    request.form.get(
                        "rua",
                        ""
                    ).strip()
                )

                prateleira = (
                    request.form.get(
                        "prateleira",
                        ""
                    ).strip()
                )

                codigo = (
                    request.form.get(
                        "codigo_material",
                        ""
                    ).strip()
                )

                descricao = (
                    request.form.get(
                        "descricao",
                        ""
                    ).strip()
                )

                quantidade_texto = (
                    request.form.get(
                        "quantidade",
                        "0"
                    ).strip()
                )

                try:

                    quantidade = int(
                        quantidade_texto
                    )

                except ValueError:

                    quantidade = -1

                if not rua:

                    flash(
                        "Informe a rua.",
                        "warning"
                    )

                    return redirect(
                        url_for(
                            "modulo",
                            nome="Estoque"
                        )
                    )

                if not codigo:

                    flash(
                        "Informe o código do material.",
                        "warning"
                    )

                    return redirect(
                        url_for(
                            "modulo",
                            nome="Estoque"
                        )
                    )

                if not descricao:

                    flash(
                        "Informe a descrição.",
                        "warning"
                    )

                    return redirect(
                        url_for(
                            "modulo",
                            nome="Estoque"
                        )
                    )

                if quantidade < 0:

                    flash(
                        "A quantidade não pode ser negativa.",
                        "warning"
                    )

                    return redirect(
                        url_for(
                            "modulo",
                            nome="Estoque"
                        )
                    )

                cursor = None

                try:

                    cursor = executar(
                        """
                        INSERT INTO estoque
                        (
                            rua,
                            prateleira,
                            codigo_material,
                            descricao,
                            quantidade
                        )
                        VALUES
                        (
                            %s,
                            %s,
                            %s,
                            %s,
                            %s
                        )
                        """,
                        (
                            rua,
                            prateleira,
                            codigo,
                            descricao,
                            quantidade
                        )
                    )

                    get_db().commit()

                    flash(
                        "Material cadastrado no estoque.",
                        "success"
                    )

                except Exception as erro:

                    get_db().rollback()

                    print(
                        f"[ERRO ESTOQUE] {erro}"
                    )

                    flash(
                        "Não foi possível cadastrar "
                        "o material.",
                        "danger"
                    )

                finally:

                    fechar_cursor(cursor)

                return redirect(
                    url_for(
                        "modulo",
                        nome="Estoque"
                    )
                )

            # =================================================
            # IMPORTAÇÃO EXCEL / CSV
            # =================================================

            if acao == "importar_excel":

                arquivo = request.files.get(
                    "arquivo_excel"
                )

                if not arquivo:

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

                nome_arquivo = (
                    arquivo.filename
                    or ""
                ).lower()

                if not (
                    nome_arquivo.endswith(".xlsx")
                    or nome_arquivo.endswith(".xls")
                    or nome_arquivo.endswith(".csv")
                ):

                    flash(
                        "Formato inválido. "
                        "Use XLSX, XLS ou CSV.",
                        "danger"
                    )

                    return redirect(
                        url_for(
                            "modulo",
                            nome="Estoque"
                        )
                    )

                try:

                    if nome_arquivo.endswith(".csv"):

                        df = pd.read_csv(
                            arquivo
                        )

                    else:

                        df = pd.read_excel(
                            arquivo
                        )

                    # -----------------------------------------
                    # NORMALIZA NOMES DAS COLUNAS
                    # -----------------------------------------

                    mapa_colunas = {}

                    for coluna in df.columns:

                        texto = str(
                            coluna
                        ).strip().lower()

                        texto = (
                            texto
                            .replace("á", "a")
                            .replace("à", "a")
                            .replace("ã", "a")
                            .replace("â", "a")
                            .replace("é", "e")
                            .replace("ê", "e")
                            .replace("í", "i")
                            .replace("ó", "o")
                            .replace("ô", "o")
                            .replace("õ", "o")
                            .replace("ú", "u")
                            .replace("ç", "c")
                        )

                        mapa_colunas[
                            texto
                        ] = coluna

                    def encontrar_coluna(opcoes):

                        for opcao in opcoes:

                            if opcao in mapa_colunas:

                                return mapa_colunas[
                                    opcao
                                ]

                        return None

                    coluna_rua = encontrar_coluna([
                        "rua"
                    ])

                    coluna_prateleira = encontrar_coluna([
                        "prateleira"
                    ])

                    coluna_codigo = encontrar_coluna([
                        "codigo",
                        "codigo_material",
                        "codigomaterial",
                        "material"
                    ])

                    coluna_descricao = encontrar_coluna([
                        "descricao",
                        "descricao_material",
                        "material_descricao"
                    ])

                    coluna_quantidade = encontrar_coluna([
                        "quantidade",
                        "qtd",
                        "quant"
                    ])

                    if not coluna_rua:

                        raise ValueError(
                            "A coluna 'Rua' não foi encontrada."
                        )

                    if not coluna_codigo:

                        raise ValueError(
                            "A coluna 'Código' não foi encontrada."
                        )

                    if not coluna_descricao:

                        raise ValueError(
                            "A coluna 'Descrição' não foi encontrada."
                        )

                    if not coluna_quantidade:

                        raise ValueError(
                            "A coluna 'Quantidade' não foi encontrada."
                        )

                    inseridos = 0

                    ignorados = 0

                    cursor = None

                    try:

                        # Um único cursor para toda
                        # a importação.
                        cursor = get_db().cursor()

                        for _, linha in df.iterrows():

                            valor_rua = (
                                linha[coluna_rua]
                                if coluna_rua
                                else ""
                            )

                            valor_prateleira = (
                                linha[coluna_prateleira]
                                if coluna_prateleira
                                else ""
                            )

                            valor_codigo = (
                                linha[coluna_codigo]
                                if coluna_codigo
                                else ""
                            )

                            valor_descricao = (
                                linha[coluna_descricao]
                                if coluna_descricao
                                else ""
                            )

                            valor_quantidade = (
                                linha[coluna_quantidade]
                                if coluna_quantidade
                                else 0
                            )

                            if pd.isna(
                                valor_codigo
                            ):

                                ignorados += 1
                                continue

                            if pd.isna(
                                valor_descricao
                            ):

                                ignorados += 1
                                continue

                            rua_valor = str(
                                valor_rua
                            ).strip()

                            prateleira_valor = str(
                                valor_prateleira
                            ).strip()

                            codigo_valor = str(
                                valor_codigo
                            ).strip()

                            descricao_valor = str(
                                valor_descricao
                            ).strip()

                            if (
                                not codigo_valor
                                or not descricao_valor
                            ):

                                ignorados += 1
                                continue

                            try:

                                quantidade_valor = int(
                                    float(
                                        valor_quantidade
                                    )
                                )

                            except (
                                ValueError,
                                TypeError
                            ):

                                quantidade_valor = 0

                            sql = """
                                INSERT INTO estoque
                                (
                                    rua,
                                    prateleira,
                                    codigo_material,
                                    descricao,
                                    quantidade
                                )
                                VALUES
                                (
                                    %s,
                                    %s,
                                    %s,
                                    %s,
                                    %s
                                )
                            """

                            if not usando_postgresql():

                                sql = sql.replace(
                                    "%s",
                                    "?"
                                )

                            cursor.execute(
                                sql,
                                (
                                    rua_valor,
                                    prateleira_valor,
                                    codigo_valor,
                                    descricao_valor,
                                    quantidade_valor
                                )
                            )

                            inseridos += 1

                        get_db().commit()

                    except Exception:

                        get_db().rollback()

                        raise

                    finally:

                        fechar_cursor(cursor)

                    flash(
                        f"Importação concluída: "
                        f"{inseridos} registro(s) inserido(s) "
                        f"e {ignorados} ignorado(s).",
                        "success"
                    )

                except Exception as erro:

                    get_db().rollback()

                    print(
                        f"[ERRO IMPORTAÇÃO ESTOQUE] "
                        f"{erro}"
                    )

                    flash(
                        f"Erro na importação: {erro}",
                        "danger"
                    )

                return redirect(
                    url_for(
                        "modulo",
                        nome="Estoque"
                    )
                )

        # =================================================
        # LISTAGEM DO ESTOQUE
        # =================================================

        cursor = None

        try:

            cursor = executar(
                """
                SELECT *
                FROM estoque
                ORDER BY rua, prateleira, descricao
                """
            )

            estoque_itens = cursor.fetchall()

            estoque_itens = linhas_para_dict(
                estoque_itens
            )

        except Exception as erro:

            print(
                f"[ERRO LISTA ESTOQUE] {erro}"
            )

            estoque_itens = []

        finally:

            fechar_cursor(cursor)

        return render_template(
            "estoque.html",
            estoque_itens=estoque_itens
        )

    # =====================================================
    # MÓDULOS OPERACIONAIS
    # =====================================================

    categoria_map = {

        "Requisições": "Separação",

        "Inventário": "Inventário",

        "Expedição": "Expedição",

        "Recebimento": "Recebimento"
    }

    categoria = categoria_map.get(
        nome_limpo
    )

    itens = []

    if categoria:

        cursor = None

        try:

            cursor = executar(
                """
                SELECT *
                FROM atividades
                WHERE categoria = %s
                ORDER BY id DESC
                """,
                (
                    categoria,
                )
            )

            itens = cursor.fetchall()

            itens = preparar_lista_atividades(
                itens
            )

        except Exception as erro:

            print(
                f"[ERRO MÓDULO] {erro}"
            )

            itens = []

        finally:

            fechar_cursor(cursor)

    return render_template(
        "modulo.html",

        nome=nome_limpo,

        itens=itens
    )


# =========================================================
# RELATÓRIO PDF DO DIA
# =========================================================

@app.route("/relatorio_pdf")
def relatorio_pdf():

    if "usuario" not in session:

        return redirect(
            url_for("login")
        )

    cursor = None

    try:

        # =================================================
        # DATA DO BRASIL
        # =================================================

        agora_atual = agora_brasil()

        data_hoje = agora_atual.strftime(
            "%Y-%m-%d"
        )

        data_formatada = agora_atual.strftime(
            "%d/%m/%Y"
        )

        # =================================================
        # BUSCA ATIVIDADES DO DIA
        # =================================================

        if usando_postgresql():

            cursor = executar(
                """
                SELECT *
                FROM atividades
                WHERE
                    (
                        inicio_em IS NOT NULL
                        AND DATE(
                            inicio_em
                            AT TIME ZONE 'UTC'
                            AT TIME ZONE 'America/Sao_Paulo'
                        ) = %s
                    )
                    OR
                    (
                        concluido_em IS NOT NULL
                        AND DATE(
                            concluido_em
                            AT TIME ZONE 'UTC'
                            AT TIME ZONE 'America/Sao_Paulo'
                        ) = %s
                    )
                ORDER BY id ASC
                """,
                (
                    data_hoje,
                    data_hoje
                )
            )

        else:

            cursor = executar(
                """
                SELECT *
                FROM atividades
                WHERE
                    (
                        inicio_em IS NOT NULL
                        AND date(
                            datetime(
                                inicio_em,
                                '-3 hours'
                            )
                        ) = ?
                    )
                    OR
                    (
                        concluido_em IS NOT NULL
                        AND date(
                            datetime(
                                concluido_em,
                                '-3 hours'
                            )
                        ) = ?
                    )
                ORDER BY id ASC
                """,
                (
                    data_hoje,
                    data_hoje
                )
            )

        atividades_dia = cursor.fetchall()

        atividades_dia = linhas_para_dict(
            atividades_dia
        )

        fechar_cursor(cursor)

        cursor = None

        # =================================================
        # QUANTIDADES
        # =================================================

        total = len(
            atividades_dia
        )

        concluidas = sum(
            1
            for item in atividades_dia
            if item.get("status") == "Concluído"
        )

        pendentes = sum(
            1
            for item in atividades_dia
            if item.get("status") == "Pendente"
        )

        arquivadas = sum(
            1
            for item in atividades_dia
            if item.get("status") == "Arquivada"
        )

        # =================================================
        # PDF
        # =================================================

        buffer = BytesIO()

        documento = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            rightMargin=0.5 * cm,
            leftMargin=0.5 * cm,
            topMargin=0.7 * cm,
            bottomMargin=0.7 * cm
        )

        estilos = getSampleStyleSheet()

        estilo_celula = ParagraphStyle(
            "Celula",
            parent=estilos["Normal"],
            fontName="Helvetica",
            fontSize=6,
            leading=7,
            alignment=1
        )

        estilo_celula_esquerda = ParagraphStyle(
            "CelulaEsquerda",
            parent=estilos["Normal"],
            fontName="Helvetica",
            fontSize=6,
            leading=7,
            alignment=0
        )

        estilo_cabecalho = ParagraphStyle(
            "Cabecalho",
            parent=estilos["Normal"],
            fontName="Helvetica-Bold",
            fontSize=6,
            leading=7,
            textColor=colors.white,
            alignment=1
        )

        elementos = []

        elementos.append(
            Paragraph(
                "RELATÓRIO DIÁRIO - ALMOXARIFADO",
                estilos["Title"]
            )
        )

        elementos.append(
            Spacer(
                1,
                0.2 * cm
            )
        )

        elementos.append(
            Paragraph(
                f"Data: {data_formatada}",
                estilos["Normal"]
            )
        )

        elementos.append(
            Paragraph(
                "Horários exibidos no fuso "
                "America/Sao_Paulo (Brasília).",
                estilos["Normal"]
            )
        )

        elementos.append(
            Spacer(
                1,
                0.3 * cm
            )
        )

        # =================================================
        # RESUMO
        # =================================================

        resumo = [
            [
                "Total",
                "Concluídas",
                "Pendentes",
                "Arquivadas"
            ],
            [
                str(total),
                str(concluidas),
                str(pendentes),
                str(arquivadas)
            ]
        ]

        tabela_resumo = Table(
            resumo,
            colWidths=[
                5 * cm,
                5 * cm,
                5 * cm,
                5 * cm
            ]
        )

        tabela_resumo.setStyle(
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
                    "ALIGN",
                    (0, 0),
                    (-1, -1),
                    "CENTER"
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (-1, 0),
                    "Helvetica-Bold"
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.grey
                ),
                (
                    "BACKGROUND",
                    (0, 1),
                    (-1, 1),
                    colors.whitesmoke
                )
            ])
        )

        elementos.append(
            tabela_resumo
        )

        elementos.append(
            Spacer(
                1,
                0.5 * cm
            )
        )

        # =================================================
        # TABELA PRINCIPAL
        # =================================================

        dados = [
            [
                Paragraph(
                    "Req.",
                    estilo_cabecalho
                ),

                Paragraph(
                    "Atividade",
                    estilo_cabecalho
                ),

                Paragraph(
                    "Categoria",
                    estilo_cabecalho
                ),

                Paragraph(
                    "Responsável",
                    estilo_cabecalho
                ),

                Paragraph(
                    "Encerrado por",
                    estilo_cabecalho
                ),

                Paragraph(
                    "Início",
                    estilo_cabecalho
                ),

                Paragraph(
                    "Encerramento",
                    estilo_cabecalho
                ),

                Paragraph(
                    "Duração",
                    estilo_cabecalho
                ),

                Paragraph(
                    "Status",
                    estilo_cabecalho
                )
            ]
        ]

        for item in atividades_dia:

            requisicao = (
                item.get(
                    "num_requisicao"
                )
                or "-"
            )

            atividade = (
                item.get(
                    "atividade"
                )
                or "-"
            )

            categoria_item = (
                item.get(
                    "categoria"
                )
                or "-"
            )

            responsavel = (
                item.get(
                    "responsavel"
                )
                or "-"
            )

            encerrado_por = (
                item.get(
                    "encerrado_por"
                )
                or "-"
            )

            inicio = formatar_data_hora(
                item.get(
                    "inicio_em"
                )
            )

            conclusao = formatar_data_hora(
                item.get(
                    "concluido_em"
                )
            )

            duracao = calcular_duracao(
                item.get(
                    "inicio_em"
                ),
                item.get(
                    "concluido_em"
                )
            )

            status = (
                item.get(
                    "status"
                )
                or "-"
            )

            dados.append([
                Paragraph(
                    str(requisicao),
                    estilo_celula
                ),

                Paragraph(
                    str(atividade),
                    estilo_celula_esquerda
                ),

                Paragraph(
                    str(categoria_item),
                    estilo_celula
                ),

                Paragraph(
                    str(responsavel),
                    estilo_celula
                ),

                Paragraph(
                    str(encerrado_por),
                    estilo_celula
                ),

                Paragraph(
                    str(inicio),
                    estilo_celula
                ),

                Paragraph(
                    str(conclusao),
                    estilo_celula
                ),

                Paragraph(
                    str(duracao),
                    estilo_celula
                ),

                Paragraph(
                    str(status),
                    estilo_celula
                )
            ])

        if len(dados) == 1:

            dados.append([
                Paragraph(
                    "-",
                    estilo_celula
                ),

                Paragraph(
                    "Nenhuma atividade registrada no dia.",
                    estilo_celula
                ),

                Paragraph(
                    "-",
                    estilo_celula
                ),

                Paragraph(
                    "-",
                    estilo_celula
                ),

                Paragraph(
                    "-",
                    estilo_celula
                ),

                Paragraph(
                    "-",
                    estilo_celula
                ),

                Paragraph(
                    "-",
                    estilo_celula
                ),

                Paragraph(
                    "-",
                    estilo_celula
                ),

                Paragraph(
                    "-",
                    estilo_celula
                )
            ])

        tabela = Table(
            dados,
            repeatRows=1,
            colWidths=[
                1.7 * cm,
                4.6 * cm,
                2.7 * cm,
                3.3 * cm,
                3.3 * cm,
                3.0 * cm,
                3.0 * cm,
                2.1 * cm,
                2.4 * cm
            ]
        )

        tabela.setStyle(
            TableStyle([
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor("#343a40")
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.white
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (-1, 0),
                    "Helvetica-Bold"
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    colors.grey
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE"
                ),
                (
                    "ALIGN",
                    (0, 0),
                    (-1, -1),
                    "CENTER"
                ),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [
                        colors.white,
                        colors.HexColor("#f8f9fa")
                    ]
                )
            ])
        )

        elementos.append(
            tabela
        )

        elementos.append(
            Spacer(
                1,
                0.5 * cm
            )
        )

        elementos.append(
            Paragraph(
                "Legenda: Responsável = usuário atribuído "
                "à atividade. Encerrado por = usuário que "
                "realmente realizou o encerramento.",
                estilos["Normal"]
            )
        )

        elementos.append(
            Spacer(
                1,
                0.15 * cm
            )
        )

        elementos.append(
            Paragraph(
                "Relatório gerado pelo sistema "
                "Almoxarifado Valenet.",
                estilos["Normal"]
            )
        )

        documento.build(
            elementos
        )

        buffer.seek(0)

        nome_arquivo = (
            f"relatorio_almoxarifado_"
            f"{data_hoje}.pdf"
        )

        return send_file(
            buffer,
            as_attachment=True,
            download_name=nome_arquivo,
            mimetype="application/pdf"
        )

    except Exception as erro:

        print(
            f"[ERRO PDF] {erro}"
        )

        return (
            "Não foi possível gerar "
            "o relatório PDF.",
            500
        )

    finally:

        fechar_cursor(cursor)


# =========================================================
# ENCERRAR ATIVIDADE / REQUISIÇÃO
# =========================================================

@app.route(
    "/concluir/<int:id>"
)
def concluir(id):

    if "usuario" not in session:

        return redirect(
            url_for("login")
        )

    db = get_db()

    cursor = None

    try:

        usuario_que_encerrou = (
            session["usuario"]
        )

        # =================================================
        # BUSCA ATIVIDADE PENDENTE
        # =================================================

        cursor = executar(
            """
            SELECT *
            FROM atividades
            WHERE id = %s
            AND status = 'Pendente'
            """,
            (
                id,
            )
        )

        atividade_raw = cursor.fetchone()

        fechar_cursor(cursor)

        cursor = None

        if not atividade_raw:

            flash(
                "A atividade não foi encontrada "
                "ou já foi concluída.",
                "warning"
            )

            return redirect(
                request.referrer
                or url_for("index")
            )

        atividade = linha_para_dict(
            atividade_raw
        )

        # =================================================
        # MOMENTO EXATO DO ENCERRAMENTO
        # =================================================

        if usando_postgresql():

            momento_encerramento = (
                agora_utc_naive()
            )

        else:

            momento_encerramento = (
                agora_sqlite()
            )

        # =================================================
        # ENCERRA A ATIVIDADE
        # =================================================

        cursor = executar(
            """
            UPDATE atividades
            SET
                status = 'Concluído',
                concluido_em = %s,
                encerrado_por = %s
            WHERE id = %s
            AND status = 'Pendente'
            """,
            (
                momento_encerramento,
                usuario_que_encerrou,
                id
            )
        )

        quantidade_atualizada = (
            cursor.rowcount
        )

        fechar_cursor(cursor)

        cursor = None

        if quantidade_atualizada == 0:

            db.rollback()

            flash(
                "A atividade já foi concluída "
                "ou não está mais disponível.",
                "warning"
            )

            return redirect(
                request.referrer
                or url_for("index")
            )

        # =================================================
        # SEPARAÇÃO → EXPEDIÇÃO
        # =================================================

        if atividade.get(
            "categoria"
        ) == "Separação":

            num_requisicao = (
                atividade.get(
                    "num_requisicao"
                )
                or ""
            ).strip()

            prioridade = (
                atividade.get(
                    "prioridade"
                )
                or "Baixa"
            )

            responsavel = (
                atividade.get(
                    "responsavel"
                )
                or usuario_que_encerrou
            )

            prazo = (
                atividade.get(
                    "prazo"
                )
                or ""
            )

            if num_requisicao:

                # -----------------------------------------
                # VERIFICA EXPEDIÇÃO EXISTENTE
                # -----------------------------------------

                cursor = executar(
                    """
                    SELECT COUNT(*)
                    FROM atividades
                    WHERE categoria = 'Expedição'
                    AND num_requisicao = %s
                    AND status <> 'Arquivada'
                    """,
                    (
                        num_requisicao,
                    )
                )

                existe_expedicao = obter_valor(
                    cursor
                )

                fechar_cursor(cursor)

                cursor = None

                # -----------------------------------------
                # CRIA EXPEDIÇÃO
                # -----------------------------------------

                if int(
                    existe_expedicao or 0
                ) == 0:

                    # A Expedição começa exatamente
                    # no encerramento da Separação.

                    inicio_expedicao = (
                        momento_encerramento
                    )

                    cursor = executar(
                        """
                        INSERT INTO atividades
                        (
                            num_requisicao,
                            prioridade,
                            atividade,
                            descricao,
                            categoria,
                            responsavel,
                            prazo,
                            status,
                            inicio_em,
                            concluido_em,
                            encerrado_por
                        )
                        VALUES
                        (
                            %s,
                            %s,
                            %s,
                            %s,
                            'Expedição',
                            %s,
                            %s,
                            'Pendente',
                            %s,
                            NULL,
                            NULL
                        )
                        """,
                        (
                            num_requisicao,
                            prioridade,
                            (
                                "Expedição da requisição "
                                f"{num_requisicao}"
                            ),
                            (
                                "Expedição gerada "
                                "automaticamente após "
                                "a conclusão da Separação."
                            ),
                            responsavel,
                            prazo,
                            inicio_expedicao
                        )
                    )

                    fechar_cursor(cursor)

                    cursor = None

                    flash(
                        (
                            f"Separação da requisição "
                            f"{num_requisicao} encerrada por "
                            f"{usuario_que_encerrou}. "
                            f"A Expedição foi criada "
                            f"automaticamente."
                        ),
                        "success"
                    )

                else:

                    flash(
                        (
                            "Atividade encerrada por "
                            f"{usuario_que_encerrou}. "
                            "A Expedição já estava "
                            "cadastrada."
                        ),
                        "success"
                    )

            else:

                flash(
                    (
                        "Separação encerrada por "
                        f"{usuario_que_encerrou}, porém não "
                        "foi possível criar a Expedição "
                        "porque não existe número de "
                        "requisição."
                    ),
                    "warning"
                )

        else:

            flash(
                (
                    "Atividade encerrada por "
                    f"{usuario_que_encerrou} com sucesso."
                ),
                "success"
            )

        # =================================================
        # COMMIT
        # =================================================

        db.commit()

    except Exception as erro:

        db.rollback()

        print(
            f"[ERRO CONCLUSÃO] {erro}"
        )

        flash(
            "Não foi possível encerrar a atividade.",
            "danger"
        )

    finally:

        fechar_cursor(cursor)

    return redirect(
        request.referrer
        or url_for("index")
    )


# =========================================================
# ARQUIVAR ATIVIDADE MANUALMENTE
# =========================================================

@app.route(
    "/arquivar/<int:id>"
)
def arquivar(id):

    if "usuario" not in session:

        return redirect(
            url_for("login")
        )

    cursor = None

    try:

        cursor = executar(
            """
            UPDATE atividades
            SET status = 'Arquivada'
            WHERE id = %s
            AND status = 'Concluído'
            """,
            (
                id,
            )
        )

        quantidade = cursor.rowcount

        get_db().commit()

        if quantidade > 0:

            flash(
                "Atividade arquivada com sucesso.",
                "success"
            )

        else:

            flash(
                "A atividade não foi encontrada "
                "ou ainda não está concluída.",
                "warning"
            )

    except Exception as erro:

        get_db().rollback()

        print(
            f"[ERRO ARQUIVAMENTO MANUAL] {erro}"
        )

        flash(
            "Não foi possível arquivar a atividade.",
            "danger"
        )

    finally:

        fechar_cursor(cursor)

    return redirect(
        request.referrer
        or url_for("index")
    )


# =========================================================
# COMPATIBILIDADE COM VERSÃO ANTIGA
# =========================================================

@app.route(
    "/deletar/<int:id>"
)
def deletar_compatibilidade(id):

    """
    Compatibilidade com versões antigas.

    IMPORTANTE:

    A atividade NÃO é apagada.

    Se estiver concluída, será arquivada.
    """

    return arquivar(id)


# =========================================================
# EXCLUIR ITEM DO ESTOQUE
# =========================================================

@app.route(
    "/deletar_estoque/<int:id>"
)
def deletar_estoque(id):

    if "usuario" not in session:

        return redirect(
            url_for("login")
        )

    cursor = None

    try:

        cursor = executar(
            """
            DELETE FROM estoque
            WHERE id = %s
            """,
            (
                id,
            )
        )

        get_db().commit()

        flash(
            "Item removido do estoque.",
            "success"
        )

    except Exception as erro:

        get_db().rollback()

        print(
            f"[ERRO EXCLUSÃO ESTOQUE] {erro}"
        )

        flash(
            "Não foi possível remover "
            "o item do estoque.",
            "danger"
        )

    finally:

        fechar_cursor(cursor)

    return redirect(
        url_for(
            "modulo",
            nome="Estoque"
        )
    )


# =========================================================
# EXCLUIR MELHORIA / PDCA
# =========================================================

@app.route(
    "/deletar_melhoria/<int:id>"
)
def deletar_melhoria(id):

    if "usuario" not in session:

        return redirect(
            url_for("login")
        )

    cursor = None

    try:

        cursor = executar(
            """
            DELETE FROM melhorias
            WHERE id = %s
            """,
            (
                id,
            )
        )

        get_db().commit()

        flash(
            "Melhoria removida.",
            "success"
        )

    except Exception as erro:

        get_db().rollback()

        print(
            f"[ERRO EXCLUSÃO PDCA] {erro}"
        )

        flash(
            "Não foi possível remover "
            "a melhoria.",
            "danger"
        )

    finally:

        fechar_cursor(cursor)

    return redirect(
        url_for(
            "modulo",
            nome="Melhorias / PDCA"
        )
    )


# =========================================================
# INICIALIZAÇÃO DO BANCO
# =========================================================

with app.app_context():

    init_db()


# =========================================================
# EXECUÇÃO LOCAL
# =========================================================

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
