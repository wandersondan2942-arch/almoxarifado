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

DATABASE_URL = os.environ.get("DATABASE_URL")


# =========================================================
# BANCO DE DADOS
# =========================================================

def usando_postgresql():
    return bool(DATABASE_URL)


def get_db():

    db = getattr(g, "_database", None)

    if db is not None:
        return db

    # -----------------------------------------
    # RENDER / POSTGRESQL
    # -----------------------------------------

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

    # -----------------------------------------
    # COMPUTADOR LOCAL / SQLITE
    # -----------------------------------------

    else:

        db = sqlite3.connect(
            "database.db"
        )

        db.row_factory = sqlite3.Row

    g._database = db

    return db


@app.teardown_appcontext
def close_connection(exception):

    db = getattr(
        g,
        "_database",
        None
    )

    if db is not None:
        db.close()


# =========================================================
# EXECUTAR SQL
# =========================================================

def executar(sql, parametros=()):

    db = get_db()

    # PostgreSQL usa %s
    # SQLite usa ?

    if not usando_postgresql():

        sql = sql.replace(
            "%s",
            "?"
        )

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

        return list(
            resultado.values()
        )[0]

    return resultado[0]


def fechar_cursor(cursor):

    if cursor:

        cursor.close()


# =========================================================
# USUÁRIO DISPONÍVEL NOS TEMPLATES
# =========================================================

@app.context_processor
def inject_user():

    return {
        "usuario_atual": session.get(
            "usuario"
        )
    }


# =========================================================
# CONTADORES
# =========================================================

def contar(sql, parametros=()):

    try:

        cursor = executar(
            sql,
            parametros
        )

        valor = obter_valor(
            cursor
        )

        fechar_cursor(
            cursor
        )

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
    # USUÁRIOS
    # =====================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY,
            nome TEXT NOT NULL,
            senha TEXT NOT NULL
        )
    """)

    # =====================================================
    # ATIVIDADES
    # =====================================================

    if usando_postgresql():

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
                concluido_em TIMESTAMP
            )
        """)

        # Garante que bancos antigos também recebam a coluna

        cursor.execute("""
            ALTER TABLE atividades
            ADD COLUMN IF NOT EXISTS concluido_em TIMESTAMP
        """)

    else:

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
                concluido_em TEXT
            )
        """)

        # ---------------------------------------------
        # MIGRAÇÃO DO SQLITE
        # ---------------------------------------------

        cursor.execute("""
            PRAGMA table_info(atividades)
        """)

        colunas = cursor.fetchall()

        nomes_colunas = []

        for coluna in colunas:

            nomes_colunas.append(
                coluna[1]
            )

        if "concluido_em" not in nomes_colunas:

            cursor.execute("""
                ALTER TABLE atividades
                ADD COLUMN concluido_em TEXT
            """)

    # =====================================================
    # CHAT
    # =====================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat (
            id INTEGER PRIMARY KEY,
            remetente TEXT NOT NULL,
            mensagem TEXT NOT NULL,
            horario TEXT NOT NULL
        )
    """)

    # =====================================================
    # MELHORIAS / PDCA
    # =====================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS melhorias (
            id INTEGER PRIMARY KEY,
            titulo TEXT NOT NULL,
            descricao TEXT,
            autor TEXT NOT NULL,
            etapa TEXT DEFAULT 'Planejar (Plan)',
            status TEXT DEFAULT 'Em Andamento'
        )
    """)

    # =====================================================
    # ESTOQUE
    # =====================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS estoque (
            id INTEGER PRIMARY KEY,
            rua TEXT NOT NULL,
            prateleira TEXT NOT NULL,
            codigo_material TEXT NOT NULL,
            descricao TEXT NOT NULL,
            quantidade INTEGER DEFAULT 0
        )
    """)

    # =====================================================
    # USUÁRIO INICIAL
    # =====================================================

    if usando_postgresql():

        cursor.execute("""
            SELECT id
            FROM usuarios
            WHERE nome = %s
        """, (
            "Wanderson Fernandes",
        ))

    else:

        cursor.execute("""
            SELECT id
            FROM usuarios
            WHERE nome = ?
        """, (
            "Wanderson Fernandes",
        ))

    usuario = cursor.fetchone()

    if not usuario:

        if usando_postgresql():

            cursor.execute("""
                INSERT INTO usuarios
                (nome, senha)
                VALUES (%s, %s)
            """, (
                "Wanderson Fernandes",
                "1234"
            ))

        else:

            cursor.execute("""
                INSERT INTO usuarios
                (nome, senha)
                VALUES (?, ?)
            """, (
                "Wanderson Fernandes",
                "1234"
            ))

    db.commit()

    cursor.close()


# =========================================================
# ARQUIVAMENTO AUTOMÁTICO
# =========================================================

def arquivar_atividades_expiradas():

    try:

        db = get_db()

        # -------------------------------------------------
        # POSTGRESQL
        # -------------------------------------------------

        if usando_postgresql():

            cursor = db.cursor()

            cursor.execute("""
                UPDATE atividades
                SET status = 'Arquivada'
                WHERE status = 'Concluído'
                AND concluido_em IS NOT NULL
                AND concluido_em <=
                    CURRENT_TIMESTAMP - INTERVAL '24 hours'
            """)

        # -------------------------------------------------
        # SQLITE
        # -------------------------------------------------

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

        cursor.close()

        if quantidade > 0:

            print(
                f"{quantidade} atividade(s) "
                "arquivada(s) automaticamente."
            )

    except Exception as erro:

        try:
            get_db().rollback()
        except Exception:
            pass

        print(
            f"Erro no arquivamento automático: {erro}"
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
            "usuario",
            ""
        ).strip()

        senha = request.form.get(
            "senha",
            ""
        ).strip()

        cursor = executar("""
            SELECT *
            FROM usuarios
            WHERE nome = %s
            AND senha = %s
        """, (
            nome,
            senha
        ))

        usuario = cursor.fetchone()

        fechar_cursor(
            cursor
        )

        if usuario:

            session["usuario"] = (
                usuario["nome"]
                if isinstance(usuario, dict)
                else usuario["nome"]
            )

            return redirect(
                url_for("index")
            )

        erro = (
            "Usuário ou senha inválidos!"
        )

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

    if "usuario" not in session:

        return redirect(
            url_for("login")
        )

    mensagem = None
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

            erro = (
                "Preencha nome e senha."
            )

        else:

            try:

                cursor = executar("""
                    INSERT INTO usuarios
                    (nome, senha)
                    VALUES (%s, %s)
                """, (
                    nome,
                    senha
                ))

                get_db().commit()

                fechar_cursor(
                    cursor
                )

                mensagem = (
                    "Usuário cadastrado com sucesso!"
                )

            except Exception as e:

                get_db().rollback()

                erro = (
                    f"Erro ao cadastrar usuário: {e}"
                )

    return render_template(
        "cadastro_usuario.html",
        mensagem=mensagem,
        erro=erro
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route(
    "/logout"
)
def logout():

    session.clear()

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
    # PRIMEIRO:
    # VERIFICA SE EXISTEM CONCLUÍDAS HÁ MAIS DE 24 HORAS
    # =====================================================

    arquivar_atividades_expiradas()

    # =====================================================
    # NOVA ATIVIDADE / CHAT
    # =====================================================

    if request.method == "POST":

        tipo = request.form.get(
            "tipo",
            ""
        )

        # -------------------------------------------------
        # CHAT
        # -------------------------------------------------

        if tipo == "chat":

            mensagem = request.form.get(
                "mensagem",
                ""
            ).strip()

            if mensagem:

                agora = datetime.now(
                    timezone.utc
                ).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                cursor = executar("""
                    INSERT INTO chat
                    (remetente, mensagem, horario)
                    VALUES (%s, %s, %s)
                """, (
                    session["usuario"],
                    mensagem,
                    agora
                ))

                get_db().commit()

                fechar_cursor(
                    cursor
                )

            return redirect(
                url_for("index")
            )

        # -------------------------------------------------
        # NOVA ATIVIDADE
        # -------------------------------------------------

        atividade = request.form.get(
            "atividade",
            ""
        ).strip()

        num_requisicao = request.form.get(
            "num_requisicao",
            ""
        ).strip()

        prioridade = request.form.get(
            "prioridade",
            "Média"
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

        if atividade and responsavel and prazo:

            cursor = executar("""
                INSERT INTO atividades
                (
                    num_requisicao,
                    prioridade,
                    atividade,
                    categoria,
                    responsavel,
                    prazo,
                    status,
                    concluido_em
                )
                VALUES
                (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                num_requisicao,
                prioridade,
                atividade,
                categoria,
                responsavel,
                prazo,
                "Pendente",
                None
            ))

            get_db().commit()

            fechar_cursor(
                cursor
            )

        return redirect(
            url_for("index")
        )

    # =====================================================
    # PESQUISA
    # =====================================================

    pesquisa = request.args.get(
        "q",
        ""
    ).strip()

    if pesquisa:

        termo = f"%{pesquisa}%"

        cursor = executar("""
            SELECT *
            FROM atividades
            WHERE status = 'Pendente'
            AND (
                atividade LIKE %s
                OR categoria LIKE %s
                OR responsavel LIKE %s
                OR num_requisicao LIKE %s
            )
            ORDER BY id DESC
        """, (
            termo,
            termo,
            termo,
            termo
        ))

    else:

        cursor = executar("""
            SELECT *
            FROM atividades
            WHERE status = 'Pendente'
            ORDER BY id DESC
        """)

    atividades = cursor.fetchall()

    fechar_cursor(
        cursor
    )

    # =====================================================
    # CHAT
    # =====================================================

    cursor = executar("""
        SELECT *
        FROM chat
        ORDER BY id DESC
        LIMIT 15
    """)

    mensagens = cursor.fetchall()

    fechar_cursor(
        cursor
    )

    # =====================================================
    # INDICADORES
    # =====================================================

    total_req = contar("""
        SELECT COUNT(*)
        FROM atividades
        WHERE categoria = %s
        AND status = 'Pendente'
    """, (
        "Separação",
    ))

    inv_total = contar("""
        SELECT COUNT(*)
        FROM atividades
        WHERE categoria = %s
    """, (
        "Inventário",
    ))

    inv_concluido = contar("""
        SELECT COUNT(*)
        FROM atividades
        WHERE categoria = %s
        AND status = 'Concluído'
    """, (
        "Inventário",
    ))

    exp_pend = contar("""
        SELECT COUNT(*)
        FROM atividades
        WHERE categoria = %s
        AND status = 'Pendente'
    """, (
        "Expedição",
    ))

    exp_total = contar("""
        SELECT COUNT(*)
        FROM atividades
        WHERE categoria = %s
    """, (
        "Expedição",
    ))

    exp_concluido = contar("""
        SELECT COUNT(*)
        FROM atividades
        WHERE categoria = %s
        AND status = 'Concluído'
    """, (
        "Expedição",
    ))

    rec_pend = contar("""
        SELECT COUNT(*)
        FROM atividades
        WHERE categoria = %s
        AND status = 'Pendente'
    """, (
        "Recebimento",
    ))

    total_oco = contar("""
        SELECT COUNT(*)
        FROM atividades
        WHERE prioridade = %s
        AND status = 'Pendente'
    """, (
        "Alta",
    ))

    total_atividades = contar("""
        SELECT COUNT(*)
        FROM atividades
    """)

    atividades_concluidas = contar("""
        SELECT COUNT(*)
        FROM atividades
        WHERE status = 'Concluído'
    """)

    atividades_arquivadas = contar("""
        SELECT COUNT(*)
        FROM atividades
        WHERE status = 'Arquivada'
    """)

    # =====================================================
    # PERCENTUAIS
    # =====================================================

    if inv_total > 0:

        percentual_inventario = round(
            (
                inv_concluido
                / inv_total
            ) * 100
        )

    else:

        percentual_inventario = 0

    if exp_total > 0:

        percentual_expedicao = round(
            (
                exp_concluido
                / exp_total
            ) * 100
        )

    else:

        percentual_expedicao = 0

    # =====================================================
    # USUÁRIOS
    # =====================================================

    cursor = executar("""
        SELECT *
        FROM usuarios
        ORDER BY nome
    """)

    usuarios = cursor.fetchall()

    fechar_cursor(
        cursor
    )

    # =====================================================
    # RENDERIZA O PAINEL
    # =====================================================

    return render_template(
        "index.html",

        atividades=atividades,

        mensagens=mensagens,

        usuarios=usuarios,

        pesquisa=pesquisa,

        total_req=total_req,

        inv_total=inv_total,

        inv_concluido=inv_concluido,

        percentual_inventario=percentual_inventario,

        exp_pend=exp_pend,

        exp_total=exp_total,

        exp_concluido=exp_concluido,

        percentual_expedicao=percentual_expedicao,

        rec_pend=rec_pend,

        total_oco=total_oco,

        total_atividades=total_atividades,

        atividades_concluidas=atividades_concluidas,

        atividades_arquivadas=atividades_arquivadas
    )


# =========================================================
# MÓDULOS
# =========================================================

@app.route(
    "/modulo/<path:nome>"
)
def modulo(nome):

    if "usuario" not in session:

        return redirect(
            url_for("login")
        )

    return render_template(
        "index.html",
        modulo=nome
    )


# =========================================================
# CONCLUIR ATIVIDADE
#
# IMPORTANTE:
# O nome da rota continua sendo /deletar/<id>
# porque provavelmente seu HTML/JavaScript já chama essa rota.
#
# MAS ELA NÃO DELETA.
#
# Apenas muda:
#
# Pendente
#     ↓
# Concluído
#
# =========================================================

@app.route(
    "/deletar/<int:id>"
)
def deletar(id):

    if "usuario" not in session:

        return redirect(
            url_for("login")
        )

    agora = datetime.now(
        timezone.utc
    )

    concluido_em = agora.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    cursor = executar("""
        UPDATE atividades

        SET
            status = 'Concluído',
            concluido_em = %s

        WHERE id = %s
        AND status = 'Pendente'
    """, (
        concluido_em,
        id
    ))

    get_db().commit()

    fechar_cursor(
        cursor
    )

    return redirect(
        request.referrer
        or url_for("index")
    )


# =========================================================
# EXCLUIR ESTOQUE
# =========================================================

@app.route(
    "/deletar_estoque/<int:id>"
)
def deletar_estoque(id):

    if "usuario" not in session:

        return redirect(
            url_for("login")
        )

    cursor = executar("""
        DELETE FROM estoque
        WHERE id = %s
    """, (
        id,
    ))

    get_db().commit()

    fechar_cursor(
        cursor
    )

    return redirect(
        request.referrer
        or url_for("index")
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
