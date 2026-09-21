import os
import sqlite3
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    g,
    session
)


# =========================================================
# CONFIGURAÇÃO DO FLASK
# =========================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "chave-temporaria-apenas-para-desenvolvimento"
)


# =========================================================
# CONFIGURAÇÃO DO BANCO
# =========================================================

DATABASE_URL = os.environ.get("DATABASE_URL")


def usando_postgresql():
    return bool(DATABASE_URL)


def get_db():

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
def close_connection(exception):

    db = getattr(g, "_database", None)

    if db is not None:
        db.close()


# =========================================================
# FUNÇÕES AUXILIARES DO BANCO
# =========================================================

def executar(sql, parametros=()):

    db = get_db()

    if not usando_postgresql():
        sql = sql.replace("%s", "?")

    cursor = db.cursor()

    cursor.execute(
        sql,
        parametros
    )

    return cursor


def obter_primeiro(cursor):

    return cursor.fetchone()


def obter_valor(cursor):

    resultado = cursor.fetchone()

    if not resultado:
        return 0

    if isinstance(resultado, dict):
        return list(resultado.values())[0]

    return resultado[0]


def fechar_cursor(cursor):

    if cursor:
        cursor.close()


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

    try:

        cursor = executar(
            sql,
            parametros
        )

        valor = obter_valor(cursor)

        fechar_cursor(cursor)

        return valor

    except Exception as erro:

        print(
            f"Erro ao calcular indicador: {erro}"
        )

        return 0


# =========================================================
# CRIAÇÃO / ATUALIZAÇÃO DO BANCO
# =========================================================

def init_db():

    db = get_db()

    cursor = db.cursor()

    # =====================================================
    # POSTGRESQL
    # =====================================================

    if usando_postgresql():

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id SERIAL PRIMARY KEY,
                nome TEXT UNIQUE NOT NULL,
                senha TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS atividades (
                id SERIAL PRIMARY KEY,
                num_requisicao TEXT,
                prioridade TEXT NOT NULL,
                atividade TEXT NOT NULL,
                categoria TEXT NOT NULL,
                responsavel TEXT NOT NULL,
                prazo TEXT NOT NULL,
                status TEXT DEFAULT 'Pendente',
                inicio_em TIMESTAMP,
                concluido_em TIMESTAMP
            )
        """)

        # -------------------------------------------------
        # MIGRAÇÕES
        # -------------------------------------------------

        cursor.execute("""
            ALTER TABLE atividades
            ADD COLUMN IF NOT EXISTS inicio_em TIMESTAMP
        """)

        cursor.execute("""
            ALTER TABLE atividades
            ADD COLUMN IF NOT EXISTS concluido_em TIMESTAMP
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat (
                id SERIAL PRIMARY KEY,
                remetente TEXT NOT NULL,
                mensagem TEXT NOT NULL,
                horario TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS melhorias (
                id SERIAL PRIMARY KEY,
                titulo TEXT NOT NULL,
                descricao TEXT NOT NULL,
                autor TEXT NOT NULL,
                etapa TEXT DEFAULT 'Planejar (Plan)',
                status TEXT DEFAULT 'Em Andamento'
            )
        """)

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

        # -------------------------------------------------
        # PREENCHE inicio_em DE REGISTROS ANTIGOS
        # -------------------------------------------------

        cursor.execute("""
            UPDATE atividades
            SET inicio_em = COALESCE(
                inicio_em,
                concluido_em,
                CURRENT_TIMESTAMP
            )
            WHERE inicio_em IS NULL
        """)

    # =====================================================
    # SQLITE
    # =====================================================

    else:

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT UNIQUE NOT NULL,
                senha TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS atividades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                num_requisicao TEXT,
                prioridade TEXT NOT NULL,
                atividade TEXT NOT NULL,
                categoria TEXT NOT NULL,
                responsavel TEXT NOT NULL,
                prazo TEXT NOT NULL,
                status TEXT DEFAULT 'Pendente',
                inicio_em TEXT,
                concluido_em TEXT
            )
        """)

        # -------------------------------------------------
        # VERIFICA COLUNAS EXISTENTES
        # -------------------------------------------------

        cursor.execute("""
            PRAGMA table_info(atividades)
        """)

        colunas = cursor.fetchall()

        nomes_colunas = [
            coluna[1]
            for coluna in colunas
        ]

        # -------------------------------------------------
        # ADICIONA inicio_em SE NÃO EXISTIR
        # -------------------------------------------------

        if "inicio_em" not in nomes_colunas:

            print(
                "Adicionando coluna inicio_em ao SQLite..."
            )

            cursor.execute("""
                ALTER TABLE atividades
                ADD COLUMN inicio_em TEXT
            """)

        # -------------------------------------------------
        # ADICIONA concluido_em SE NÃO EXISTIR
        # -------------------------------------------------

        if "concluido_em" not in nomes_colunas:

            print(
                "Adicionando coluna concluido_em ao SQLite..."
            )

            cursor.execute("""
                ALTER TABLE atividades
                ADD COLUMN concluido_em TEXT
            """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                remetente TEXT NOT NULL,
                mensagem TEXT NOT NULL,
                horario TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS melhorias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                descricao TEXT NOT NULL,
                autor TEXT NOT NULL,
                etapa TEXT DEFAULT 'Planejar (Plan)',
                status TEXT DEFAULT 'Em Andamento'
            )
        """)

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

        # -------------------------------------------------
        # PREENCHE inicio_em DE REGISTROS ANTIGOS
        # -------------------------------------------------

        cursor.execute("""
            UPDATE atividades
            SET inicio_em = COALESCE(
                inicio_em,
                concluido_em,
                datetime('now')
            )
            WHERE inicio_em IS NULL
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

    fechar_cursor(cursor)


# =========================================================
# ARQUIVAMENTO AUTOMÁTICO APÓS 24 HORAS
# =========================================================

def arquivar_atividades_expiradas():

    try:

        db = get_db()

        if usando_postgresql():

            cursor = db.cursor()

            cursor.execute("""
                UPDATE atividades
                SET status = 'Arquivada'
                WHERE status = 'Concluído'
                AND concluido_em IS NOT NULL
                AND concluido_em <= (
                    CURRENT_TIMESTAMP - INTERVAL '24 hours'
                )
            """)

        else:

            cursor = db.cursor()

            limite = (
                datetime.now(timezone.utc)
                - timedelta(hours=24)
            )

            limite_texto = limite.strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            cursor.execute("""
                UPDATE atividades
                SET status = 'Arquivada'
                WHERE status = 'Concluído'
                AND concluido_em IS NOT NULL
                AND concluido_em <= ?
            """, (
                limite_texto,
            ))

        quantidade = cursor.rowcount

        db.commit()

        fechar_cursor(cursor)

        if quantidade > 0:

            print(
                f"[ARQUIVAMENTO] "
                f"{quantidade} atividade(s) "
                f"arquivada(s) após 24 horas."
            )

    except Exception as erro:

        try:
            get_db().rollback()
        except Exception:
            pass

        print(
            f"[ERRO ARQUIVAMENTO] {erro}"
        )


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    erro = None

    if request.method == "POST":

        nome = request.form.get(
            "nome",
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
            """,
            (
                nome,
                senha
            )
        )

        user = cursor.fetchone()

        fechar_cursor(cursor)

        if user:

            session["usuario"] = user["nome"]

            return redirect(
                url_for("index")
            )

        erro = "Usuário ou senha inválidos!"

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

            erro = "Preencha todos os campos."

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

                fechar_cursor(cursor)

                return redirect(
                    url_for("login")
                )

            except Exception as erro_banco:

                get_db().rollback()

                print(
                    f"Erro ao cadastrar usuário: {erro_banco}"
                )

                erro = (
                    "Não foi possível cadastrar "
                    "este usuário."
                )

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

    # =====================================================
    # VERIFICA ARQUIVAMENTO
    # =====================================================

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

                fechar_cursor(cursor)

            return redirect(
                url_for("index")
            )

        # =================================================
        # NOVA ATIVIDADE
        # =================================================

        num_requisicao = request.form.get(
            "num_requisicao"
        )

        prioridade = request.form.get(
            "prioridade"
        )

        atividade = request.form.get(
            "atividade"
        )

        categoria = request.form.get(
            "categoria"
        )

        responsavel = (
            request.form.get("responsavel")
            or usuario_atual
        )

        prazo = request.form.get(
            "prazo"
        )

        # =================================================
        # HORÁRIO DE INÍCIO
        # =================================================

        agora = datetime.now(
            timezone.utc
        )

        if usando_postgresql():

            inicio_em = agora

        else:

            inicio_em = agora.strftime(
                "%Y-%m-%d %H:%M:%S"
            )

        if atividade:

            try:

                cursor = executar(
                    """
                    INSERT INTO atividades
                    (
                        num_requisicao,
                        prioridade,
                        atividade,
                        categoria,
                        responsavel,
                        prazo,
                        status,
                        inicio_em,
                        concluido_em
                    )
                    VALUES
                    (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        'Pendente',
                        %s,
                        NULL
                    )
                    """,
                    (
                        num_requisicao,
                        prioridade,
                        atividade,
                        categoria,
                        responsavel,
                        prazo,
                        inicio_em
                    )
                )

                db.commit()

                fechar_cursor(cursor)

            except Exception as erro:

                db.rollback()

                print(
                    f"Erro ao inserir atividade: {erro}"
                )

        return redirect(
            url_for("index")
        )

    # =====================================================
    # LISTAGEM DE ATIVIDADES
    # =====================================================

    busca = request.args.get(
        "q",
        ""
    ).strip()

    if busca:

        cursor = executar(
            """
            SELECT *
            FROM atividades
            WHERE
                atividade LIKE %s
                OR categoria LIKE %s
                OR responsavel LIKE %s
                OR num_requisicao LIKE %s
            ORDER BY id DESC
            """,
            (
                f"%{busca}%",
                f"%{busca}%",
                f"%{busca}%",
                f"%{busca}%"
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

    fechar_cursor(cursor)

    # =====================================================
    # CHAT
    # =====================================================

    cursor = executar(
        """
        SELECT *
   
