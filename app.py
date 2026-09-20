import os
import sqlite3

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
    """
    Retorna True quando o sistema está rodando com PostgreSQL.
    No Render, DATABASE_URL será configurada.
    """
    return bool(DATABASE_URL)


def get_db():
    """
    Abre a conexão com o banco de dados.

    - Render: PostgreSQL
    - Computador local: SQLite
    """

    db = getattr(g, "_database", None)

    if db is not None:
        return db

    if usando_postgresql():

        url = DATABASE_URL

        # Compatibilidade com URLs antigas
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
    """
    Fecha o banco ao finalizar a requisição.
    """

    db = getattr(g, "_database", None)

    if db is not None:
        db.close()


# =========================================================
# FUNÇÕES AUXILIARES DO BANCO
# =========================================================

def executar(sql, parametros=()):
    """
    Executa comandos SQL funcionando tanto no SQLite
    quanto no PostgreSQL.
    """

    db = get_db()

    # SQLite utiliza ?
    if not usando_postgresql():
        sql = sql.replace("%s", "?")

    cursor = db.cursor()

    cursor.execute(sql, parametros)

    return cursor


def obter_primeiro(cursor):
    """
    Retorna a primeira linha da consulta.
    """

    resultado = cursor.fetchone()

    return resultado


def obter_valor(cursor):
    """
    Retorna o primeiro valor da primeira linha.
    Usado principalmente para COUNT().
    """

    resultado = cursor.fetchone()

    if not resultado:
        return 0

    if isinstance(resultado, dict):
        return list(resultado.values())[0]

    return resultado[0]


def fechar_cursor(cursor):
    """
    Fecha o cursor com segurança.
    """

    if cursor:
        cursor.close()


# =========================================================
# USUÁRIO LOGADO DISPONÍVEL NOS TEMPLATES
# =========================================================

@app.context_processor
def inject_user():

    return {
        "usuario_atual": session.get("usuario")
    }


# =========================================================
# CRIAÇÃO DO BANCO
# =========================================================

def init_db():

    db = get_db()

    cursor = db.cursor()

    if usando_postgresql():

        # -------------------------------------------------
        # POSTGRESQL
        # -------------------------------------------------

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
                status TEXT DEFAULT 'Pendente'
            )
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

    else:

        # -------------------------------------------------
        # SQLITE
        # -------------------------------------------------

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
                status TEXT DEFAULT 'Pendente'
            )
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

    # -----------------------------------------------------
    # CRIA USUÁRIO INICIAL
    # -----------------------------------------------------

    cursor.execute(
        "SELECT COUNT(*) FROM usuarios"
    )

    quantidade_usuarios = obter_valor(cursor)

    if quantidade_usuarios == 0:

        if usando_postgresql():

            cursor.execute(
                """
                INSERT INTO usuarios (nome, senha)
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
                INSERT INTO usuarios (nome, senha)
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
# LOGIN
# =========================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    erro = None

    if request.method == 'POST':
        nome = request.form.get('nome')
        senha = request.form.get('senha')

        db = get_db()
        cur = db.cursor()

        cur.execute(
            "SELECT * FROM usuarios WHERE nome = %s AND senha = %s",
            (nome, senha)
        )

        user = cur.fetchone()
        cur.close()

        if user:
            session['usuario'] = user['nome']
            return redirect(url_for('index'))
        else:
            erro = "Usuário ou senha inválidos!"

    return render_template('login.html', erro=erro)

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
                    (nome, senha)
                )

                get_db().commit()

                fechar_cursor(cursor)

                return redirect(
                    url_for("login")
                )

            except Exception:

                get_db().rollback()

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

    usuario_atual = session["usuario"]

    db = get_db()

    # -----------------------------------------------------
    # POST
    # -----------------------------------------------------

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
                        status
                    )
                    VALUES
                    (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        'Pendente'
                    )
                    """,
                    (
                        num_requisicao,
                        prioridade,
                        atividade,
                        categoria,
                        responsavel,
                        prazo
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
        FROM chat
        ORDER BY id DESC
        LIMIT 15
        """
    )

    mensagens_chat = cursor.fetchall()

    fechar_cursor(cursor)

 # =====================================================
# INDICADORES
# =====================================================

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

        print(f"Erro ao calcular indicador: {erro}")

        return 0


# -----------------------------------------------------
# REQUISIÇÕES PENDENTES
# -----------------------------------------------------

total_req = contar(
    """
    SELECT COUNT(*)
    FROM atividades
    WHERE categoria = 'Separação'
    AND status = 'Pendente'
    """
)


# -----------------------------------------------------
# INVENTÁRIO
# -----------------------------------------------------

inv_total = contar(
    """
    SELECT COUNT(*)
    FROM atividades
    WHERE categoria = 'Inventário'
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


# -----------------------------------------------------
# EXPEDIÇÃO
# -----------------------------------------------------

exp_pend = contar(
    """
    SELECT COUNT(*)
    FROM atividades
    WHERE categoria = 'Expedição'
    AND status = 'Pendente'
    """
)


exp_total = contar(
    """
    SELECT COUNT(*)
    FROM atividades
    WHERE categoria = 'Expedição'
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


# -----------------------------------------------------
# RECEBIMENTO
# -----------------------------------------------------

rec_pend = contar(
    """
    SELECT COUNT(*)
    FROM atividades
    WHERE categoria = 'Recebimento'
    AND status = 'Pendente'
    """
)


# -----------------------------------------------------
# OCORRÊNCIAS
# -----------------------------------------------------

total_oco = contar(
    """
    SELECT COUNT(*)
    FROM atividades
    WHERE prioridade = 'Alta'
    AND status = 'Pendente'
    """
)


# -----------------------------------------------------
# INDICADOR: ATENDIDAS
# -----------------------------------------------------

total_atividades = contar(
    """
    SELECT COUNT(*)
    FROM atividades
    """
)


atividades_concluidas = contar(
    """
    SELECT COUNT(*)
    FROM atividades
    WHERE status = 'Concluído'
    """
)


if total_atividades > 0:

    perc_atendidas = round(
        (atividades_concluidas / total_atividades) * 100
    )

else:

    perc_atendidas = 0


# -----------------------------------------------------
# INDICADOR: INVENTÁRIO
# -----------------------------------------------------

if inv_total > 0:

    perc_inventario = round(
        (inv_concluido / inv_total) * 100
    )

else:

    perc_inventario = 0


# -----------------------------------------------------
# INDICADOR: EXPEDIÇÃO
# -----------------------------------------------------

if exp_total > 0:
    perc_expedicao = round(
        (exp_concluido / exp_total) * 100
    )
else:
    perc_expedicao = 0

    # =====================================================
# USUÁRIOS PARA O FORMULÁRIO DE NOVA ATIVIDADE
# =====================================================
cursor = executar(
    """
    SELECT *
    FROM usuarios
    ORDER BY nome
    """
)

usuarios = cursor.fetchall()

fechar_cursor(cursor)

    # =====================================================
    # RENDERIZA PAINEL
    # =====================================================

return render_template(
        "index.html",
       
    atividades=atividades,

    mensagens_chat=mensagens_chat,

    usuarios=usuarios,

    busca=busca,

    total_req=total_req,
    inv_conc=inv_concluido,
    inv_total=inv_total,
    exp_pend=exp_pend,
    rec_pend=rec_pend,
    total_oco=total_oco,

    perc_atendidas=perc_atendidas,
    perc_inventario=perc_inventario,
    perc_expedicao=perc_expedicao
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

        total_geral = 0
        concluidas = 0
        pendentes = 0

        cursor = executar(
            "SELECT COUNT(*) FROM atividades"
        )

        total_geral = obter_valor(cursor)

        fechar_cursor(cursor)

        cursor = executar(
            """
            SELECT COUNT(*)
            FROM atividades
            WHERE status = 'Concluído'
            """
        )

        concluidas = obter_valor(cursor)

        fechar_cursor(cursor)

        cursor = executar(
            """
            SELECT COUNT(*)
            FROM atividades
            WHERE status = 'Pendente'
            """
        )

        pendentes = obter_valor(cursor)

        fechar_cursor(cursor)

        return render_template(
            "indicadores.html",
            total_geral=total_geral,
            concluidas=concluidas,
            pendentes=pendentes
        )

    # =====================================================
    # PDCA / MELHORIAS
    # =====================================================

    if (
        "PDCA" in nome_limpo
        or "Melhorias" in nome_limpo
    ):

        if request.method == "POST":

            titulo = request.form.get(
                "titulo"
            )

            descricao = request.form.get(
                "descricao"
            )

            etapa = request.form.get(
                "etapa"
            )

            autor = session["usuario"]

            if titulo:

                cursor = executar(
                    """
                    INSERT INTO melhorias
                    (
                        titulo,
                        descricao,
                        autor,
                        etapa
                    )
                    VALUES
                    (
                        %s,
                        %s,
                        %s,
                        %s
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

                fechar_cursor(cursor)

            return redirect(
                url_for(
                    "modulo",
                    nome="Melhorias / PDCA"
                )
            )

        cursor = executar(
            """
            SELECT *
            FROM melhorias
            ORDER BY id DESC
            """
        )

        melhorias = cursor.fetchall()

        fechar_cursor(cursor)

        return render_template(
            "pdca.html",
            melhorias=melhorias
        )

    # =====================================================
    # RELATÓRIOS
    # =====================================================

    if "Relatórios" in nome_limpo:

        cursor = executar(
            """
            SELECT *
            FROM atividades
            ORDER BY id DESC
            """
        )

        itens = cursor.fetchall()

        fechar_cursor(cursor)

        return render_template(
            "relatorios.html",
            itens=itens
        )

    # =====================================================
    # ESTOQUE
    # =====================================================

    if (
        "Estoque" in nome_limpo
        or "Cadastros" in nome_limpo
    ):

        if request.method == "POST":

            acao = request.form.get(
                "acao_estoque"
            )

            # ---------------------------------------------
            # CADASTRO MANUAL
            # ---------------------------------------------

            if acao == "cadastrar_manual":

                rua = request.form.get(
                    "rua"
                )

                prateleira = request.form.get(
                    "prateleira"
                )

                codigo = request.form.get(
                    "codigo_material"
                )

                descricao = request.form.get(
                    "descricao"
                )

                try:

                    quantidade = int(
                        request.form.get(
                            "quantidade",
                            0
                        )
                    )

                except ValueError:

                    quantidade = 0

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

                fechar_cursor(cursor)

                return redirect(
                    url_for(
                        "modulo",
                        nome="Estoque"
                    )
                )

        # ---------------------------------------------
        # USUÁRIOS
        # ---------------------------------------------

        cursor = executar(
            """
            SELECT *
            FROM usuarios
            ORDER BY nome
            """
        )

        usuarios = cursor.fetchall()

        fechar_cursor(cursor)

        # ---------------------------------------------
        # ESTOQUE
        # ---------------------------------------------

        cursor = executar(
            """
            SELECT *
            FROM estoque
            ORDER BY id DESC
            """
        )

        estoque_items = cursor.fetchall()

        fechar_cursor(cursor)

        return render_template(
            "estoque.html",
            usuarios=usuarios,
            estoque_items=estoque_items
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

        cursor = executar(
            """
            SELECT *
            FROM atividades
            WHERE categoria = %s
            ORDER BY id DESC
            """,
            (categoria,)
        )

        itens = cursor.fetchall()

        fechar_cursor(cursor)

    return render_template(
        "modulo.html",
        nome=nome_limpo,
        itens=itens
    )


# =========================================================
# CONCLUIR ATIVIDADE
# =========================================================

@app.route(
    "/deletar/<int:id>"
)
def deletar(id):

    if "usuario" not in session:

        return redirect(
            url_for("login")
        )

    cursor = executar(
        """
        UPDATE atividades
        SET status = 'Concluído'
        WHERE id = %s
        """,
        (id,)
    )

    get_db().commit()

    fechar_cursor(cursor)

    return redirect(
        request.referrer
        or url_for("index")
    )


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

    cursor = executar(
        """
        DELETE FROM estoque
        WHERE id = %s
        """,
        (id,)
    )

    get_db().commit()

    fechar_cursor(cursor)

    return redirect(
        url_for(
            "modulo",
            nome="Estoque"
        )
    )


# =========================================================
# INICIALIZAÇÃO
# =========================================================

with app.app_context():
    init_db()


# =========================================================
# EXECUÇÃO
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
