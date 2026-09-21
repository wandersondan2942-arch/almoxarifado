```python
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from io import BytesIO

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
from reportlab.lib.styles import getSampleStyleSheet
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


# =========================================================
# CONFIGURAÇÃO DO BANCO
# =========================================================

DATABASE_URL = os.environ.get("DATABASE_URL")


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
def close_connection(exception):

    db = getattr(g, "_database", None)

    if db is not None:
        db.close()


# =========================================================
# FUNÇÕES AUXILIARES DO BANCO
# =========================================================

def executar(sql, parametros=()):
    """
    Executa SQL compatível com SQLite e PostgreSQL.
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
# DATA/HORA
# =========================================================

def agora_utc():

    return datetime.now(
        timezone.utc
    )


def agora_utc_naive():

    """
    PostgreSQL está usando TIMESTAMP sem timezone.
    Portanto armazenamos UTC sem informação de timezone.
    """

    return agora_utc().replace(
        tzinfo=None
    )


def agora_sqlite():

    """
    SQLite armazena a data como texto em UTC.
    """

    return agora_utc().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


# =========================================================
# CRIAÇÃO DO BANCO
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

        cursor.execute("""
            PRAGMA table_info(atividades)
        """)

        colunas = cursor.fetchall()

        nomes_colunas = [
            coluna[1]
            for coluna in colunas
        ]

        if "inicio_em" not in nomes_colunas:

            print(
                "Adicionando coluna inicio_em ao SQLite..."
            )

            cursor.execute("""
                ALTER TABLE atividades
                ADD COLUMN inicio_em TEXT
            """)

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

        # Preenche início das atividades antigas
        # que ainda não possuem data de início.

        cursor.execute("""
            UPDATE atividades
            SET inicio_em = COALESCE(
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

    """
    Concluído
          ↓
    após 24 horas
          ↓
    Arquivada

    O registro permanece no banco.
    """

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
                agora_utc()
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
                    f"Erro ao cadastrar usuário: "
                    f"{erro_banco}"
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

        # Para Separação, a requisição é obrigatória.

        if categoria == "Separação" and not num_requisicao:

            flash(
                "Informe o número da requisição para criar uma Separação.",
                "warning"
            )

            return redirect(
                url_for("index")
            )

        # =================================================
        # DATA/HORA DE INÍCIO
        # =================================================

        if usando_postgresql():

            inicio_em = agora_utc_naive()

        else:

            inicio_em = agora_sqlite()

        # =================================================
        # INSERE ATIVIDADE
        # =================================================

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
                    num_requisicao or None,
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

            flash(
                "Não foi possível registrar a atividade.",
                "danger"
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

    # Requisições pendentes

    total_req = contar(
        """
        SELECT COUNT(*)
        FROM atividades
        WHERE categoria = 'Separação'
        AND status = 'Pendente'
        """
    )

    # Inventários pendentes

    inv_pendentes = contar(
        """
        SELECT COUNT(*)
        FROM atividades
        WHERE categoria = 'Inventário'
        AND status = 'Pendente'
        """
    )

    # Inventários concluídos

    inv_concluido = contar(
        """
        SELECT COUNT(*)
        FROM atividades
        WHERE categoria = 'Inventário'
        AND status = 'Concluído'
        """
    )

    # Total de Inventários para o indicador

    inv_total_indicador = contar(
        """
        SELECT COUNT(*)
        FROM atividades
        WHERE categoria = 'Inventário'
        AND status IN ('Pendente', 'Concluído')
        """
    )

    # Expedições pendentes

    exp_pend = contar(
        """
        SELECT COUNT(*)
        FROM atividades
        WHERE categoria = 'Expedição'
        AND status = 'Pendente'
        """
    )

    # Expedições concluídas

    exp_concluido = contar(
        """
        SELECT COUNT(*)
        FROM atividades
        WHERE categoria = 'Expedição'
        AND status = 'Concluído'
        """
    )

    # Total de Expedições

    exp_total = contar(
        """
        SELECT COUNT(*)
        FROM atividades
        WHERE categoria = 'Expedição'
        AND status IN ('Pendente', 'Concluído')
        """
    )

    # Recebimentos pendentes

    rec_pend = contar(
        """
        SELECT COUNT(*)
        FROM atividades
        WHERE categoria = 'Recebimento'
        AND status = 'Pendente'
        """
    )

    # Ocorrências = prioridade alta pendente

    total_oco = contar(
        """
        SELECT COUNT(*)
        FROM atividades
        WHERE prioridade = 'Alta'
        AND status = 'Pendente'
        """
    )

    # Total de atividades ativas

    total_atividades = contar(
        """
        SELECT COUNT(*)
        FROM atividades
        WHERE status IN ('Pendente', 'Concluído')
        """
    )

    # Atividades concluídas

    atividades_concluidas = contar(
        """
        SELECT COUNT(*)
        FROM atividades
        WHERE status = 'Concluído'
        """
    )

    # Atividades arquivadas

    atividades_arquivadas = contar(
        """
        SELECT COUNT(*)
        FROM atividades
        WHERE status = 'Arquivada'
        """
    )

    # =====================================================
    # PERCENTUAL DE ATENDIMENTO
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

    # =====================================================
    # PERCENTUAL DO INVENTÁRIO
    # =====================================================

    if inv_total_indicador > 0:

        perc_inventario = round(
            (
                inv_concluido
                / inv_total_indicador
            ) * 100
        )

    else:

        perc_inventario = 0

    # =====================================================
    # PERCENTUAL DA EXPEDIÇÃO
    # =====================================================

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

        # IMPORTANTE:
        # agora mostra o total real de Inventários
        inv_conc=inv_concluido,

        inv_total=inv_total_indicador,

        exp_pend=exp_pend,

        rec_pend=rec_pend,

        total_oco=total_oco,

        perc_atendidas=perc_atendidas,

        perc_inventario=perc_inventario,

        perc_expedicao=perc_expedicao,

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

                try:

                    quantidade = int(
                        request.form.get(
                            "quantidade",
                            0
                        )
                    )

                except ValueError:

                    quantidade = 0

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

                    fechar_cursor(cursor)

                except Exception as erro:

                    get_db().rollback()

                    print(
                        f"Erro ao cadastrar estoque: {erro}"
                    )

                return redirect(
                    url_for(
                        "modulo",
                        nome="Estoque"
                    )
                )

        cursor = executar(
            """
            SELECT *
            FROM usuarios
            ORDER BY nome
            """
        )

        usuarios = cursor.fetchall()

        fechar_cursor(cursor)

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
            (
                categoria,
            )
        )

        itens = cursor.fetchall()

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

    try:

        # =================================================
        # DATA ATUAL DO BRASIL
        # =================================================

        agora_utc = agora_utc()

        agora_brasil = (
            agora_utc
            - timedelta(hours=3)
        )

        data_hoje = agora_brasil.strftime(
            "%Y-%m-%d"
        )

        data_formatada = agora_brasil.strftime(
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

        fechar_cursor(cursor)

        # =================================================
        # QUANTIDADES
        # =================================================

        total = len(
            atividades_dia
        )

        concluidas = sum(
            1
            for item in atividades_dia
            if item["status"] == "Concluído"
        )

        pendentes = sum(
            1
            for item in atividades_dia
            if item["status"] == "Pendente"
        )

        arquivadas = sum(
            1
            for item in atividades_dia
            if item["status"] == "Arquivada"
        )

        # =================================================
        # CRIA PDF NA MEMÓRIA
        # =================================================

        buffer = BytesIO()

        documento = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            rightMargin=1 * cm,
            leftMargin=1 * cm,
            topMargin=1 * cm,
            bottomMargin=1 * cm
        )

        estilos = getSampleStyleSheet()

        elementos = []

        # =================================================
        # TÍTULO
        # =================================================

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
                "Req.",
                "Atividade",
                "Categoria",
                "Responsável",
                "Prioridade",
                "Início",
                "Conclusão",
                "Status"
            ]
        ]

        for item in atividades_dia:

            inicio = item["inicio_em"]

            conclusao = item["concluido_em"]

            if inicio:

                inicio = str(inicio)[:19]

            else:

                inicio = "-"

            if conclusao:

                conclusao = str(conclusao)[:19]

            else:

                conclusao = "-"

            requisicao = (
                item["num_requisicao"]
                or "-"
            )

            atividade = (
                item["atividade"]
                or "-"
            )

            categoria = (
                item["categoria"]
                or "-"
            )

            responsavel = (
                item["responsavel"]
                or "-"
            )

            prioridade = (
                item["prioridade"]
                or "-"
            )

            status = (
                item["status"]
                or "-"
            )

            dados.append([
                requisicao,
                atividade,
                categoria,
                responsavel,
                prioridade,
                inicio,
                conclusao,
                status
            ])

        # =================================================
        # CASO NÃO TENHA ATIVIDADES
        # =================================================

        if len(dados) == 1:

            dados.append([
                "-",
                "Nenhuma atividade registrada no dia.",
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
                2.2 * cm,
                5.5 * cm,
                3.2 * cm,
                4.0 * cm,
                2.5 * cm,
                3.5 * cm,
                3.5 * cm,
                2.8 * cm
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
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    7
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
                "Relatório gerado pelo sistema Almoxarifado Valenet.",
                estilos["Normal"]
            )
        )

        # =================================================
        # GERA PDF
        # =================================================

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
            "Não foi possível gerar o relatório PDF.",
            500
        )


# =========================================================
# CONCLUIR ATIVIDADE
# =========================================================

@app.route(
    "/concluir/<int:id>"
)
@app.route(
    "/deletar/<int:id>"
)
def concluir_atividade(id):

    if "usuario" not in session:

        return redirect(
            url_for("login")
        )

    # =====================================================
    # BUSCA A ATIVIDADE
    # =====================================================

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

    atividade = cursor.fetchone()

    fechar_cursor(cursor)

    if not atividade:

        return redirect(
            request.referrer
            or url_for("index")
        )

    # =====================================================
    # MOMENTO DA CONCLUSÃO
    # =====================================================

    if usando_postgresql():

        concluido_em = agora_utc_naive()

    else:

        concluido_em = agora_sqlite()

    # =====================================================
    # CONCLUI A ATIVIDADE
    # =====================================================

    cursor = executar(
        """
        UPDATE atividades
        SET
            status = 'Concluído',
            concluido_em = %s
        WHERE id = %s
        AND status = 'Pendente'
        """,
        (
            concluido_em,
            id
        )
    )

    get_db().commit()

    fechar_cursor(cursor)

    # =====================================================
    # SE FOR SEPARAÇÃO:
    #
    # CRIA AUTOMATICAMENTE A EXPEDIÇÃO
    # =====================================================

    categoria_original = atividade["categoria"]

    if categoria_original == "Separação":

        num_requisicao = (
            atividade["num_requisicao"]
            or ""
        ).strip()

        prioridade = (
            atividade["prioridade"]
            or "Baixa"
        )

        responsavel = (
            atividade["responsavel"]
            or session["usuario"]
        )

        prazo = (
            atividade["prazo"]
            or ""
        )

        # =================================================
        # SEGURANÇA
        # =================================================

        if not num_requisicao:

            print(
                "[AVISO] Separação concluída "
                "sem número de requisição."
            )

            return redirect(
                request.referrer
                or url_for("index")
            )

        # =================================================
        # VERIFICA DUPLICIDADE
        # =================================================

        cursor = executar(
            """
            SELECT COUNT(*)
            FROM atividades
            WHERE categoria = 'Expedição'
            AND num_requisicao = %s
            """,
            (
                num_requisicao,
            )
        )

        existe_expedicao = obter_valor(
            cursor
        )

        fechar_cursor(cursor)

        # =================================================
        # CRIA EXPEDIÇÃO
        # =================================================

        if existe_expedicao == 0:

            if usando_postgresql():

                inicio_expedicao = agora_utc_naive()

            else:

                inicio_expedicao = agora_sqlite()

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
                    'Expedição',
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
                    f"Expedição da requisição {num_requisicao}",
                    responsavel,
                    prazo,
                    inicio_expedicao
                )
            )

            get_db().commit()

            fechar_cursor(cursor)

            print(
                f"[EXPEDIÇÃO] "
                f"Criada automaticamente "
                f"para a requisição "
                f"{num_requisicao}."
            )

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
        (
            id,
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
```
