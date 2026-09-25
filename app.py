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

FUSO_BRASIL = ZoneInfo("America/Sao_Paulo")


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

        return linha.get(
            campo,
            padrao
        )

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
# NORMALIZAÇÃO DE TEXTO
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


def normalizar_requisicao(valor):

    if valor is None:
        return ""

    return str(valor).strip().upper()


# ============================================================
# DATA E HORA
# ============================================================

def agora_utc():
    return datetime.now(timezone.utc)


def agora_brasil():
    return datetime.now(FUSO_BRASIL)


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

        if valor.tzinfo is None:

            valor = valor.replace(
                tzinfo=timezone.utc
            )

        return valor.astimezone(
            FUSO_BRASIL
        )

    texto = str(valor).strip()

    if not texto:
        return None

    texto = texto.replace(
        "Z",
        "+00:00"
    )

    formatos = [
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S%z",
    ]

    dt = None

    try:

        dt = datetime.fromisoformat(
            texto
        )

    except Exception:
        pass

    if dt is None:

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
# ATRASOS
# ============================================================

def registro_foi_atrasado(item):

    status = normalizar_texto(
        obter_valor(
            item,
            "status",
            ""
        )
    )

    # ========================================================
    # REGRA ABSOLUTA:
    # ARQUIVADO NUNCA É ATRASADO
    # ========================================================

    if status == "arquivado":
        return False

    prazo = obter_valor(
        item,
        "prazo"
    )

    if not prazo:
        return False

    prazo_dt = prazo_em_datetime(
        prazo
    )

    if not prazo_dt:
        return False

    concluido = obter_valor(
        item,
        "concluido_em"
    )

    # Se foi concluído, compara o momento da conclusão
    if concluido:

        fim = converter_para_brasil(
            concluido
        )

        if fim:

            return fim > prazo_dt

    # Se ainda não foi concluído,
    # compara com o momento atual
    return agora_brasil() > prazo_dt


def texto_atraso(item):

    status = normalizar_texto(
        obter_valor(
            item,
            "status",
            ""
        )
    )

    if status == "arquivado":
        return ""

    prazo = obter_valor(
        item,
        "prazo"
    )

    if not prazo:
        return ""

    prazo_dt = prazo_em_datetime(
        prazo
    )

    if not prazo_dt:
        return ""

    concluido = obter_valor(
        item,
        "concluido_em"
    )

    if concluido:

        fim = converter_para_brasil(
            concluido
        )

    else:

        fim = agora_brasil()

    if not fim:
        return ""

    diferenca = (
        fim - prazo_dt
    )

    if diferenca.total_seconds() <= 0:
        return ""

    minutos = int(
        diferenca.total_seconds()
        // 60
    )

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
# PREPARAÇÃO DE ATIVIDADES
# ============================================================

def preparar_atividade(item):

    item = linha_para_dict(
        item
    )

    if not item:
        return item

    if not item.get("status"):
        item["status"] = "Pendente"

    if not item.get("prioridade"):
        item["prioridade"] = "Baixa"

    item["inicio_formatado"] = (
        formatar_data_hora(
            item.get("inicio_em")
        )
    )

    item["concluido_formatado"] = (
        formatar_data_hora(
            item.get("concluido_em")
        )
    )

    item["criado_formatado"] = (
        formatar_data_hora(
            item.get("criado_em")
        )
    )

    item["prazo_formatado"] = (
        formatar_data_hora(
            item.get("prazo")
        )
    )

    item["foi_atrasada"] = (
        registro_foi_atrasado(
            item
        )
    )

    item["texto_atraso"] = (
        texto_atraso(
            item
        )
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

        item = linha_para_dict(
            item
        )

        if item:

            item["data_formatada"] = (
                formatar_data_hora(
                    item.get("criado_em")
                )
            )

            resultado.append(item)

    return resultado


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

    if usando_postgresql():

        sql = """
            SELECT id
            FROM atividades
            WHERE UPPER(TRIM(num_requisicao)) = %s
              AND COALESCE(status,'')
                  NOT IN ('Concluído','Arquivado')
        """

        parametros = [
            num_requisicao
        ]

        if ignorar_id:

            sql += """
                AND id <> %s
            """

            parametros.append(
                ignorar_id
            )

        sql += " LIMIT 1"

    else:

        sql = """
            SELECT id
            FROM atividades
            WHERE UPPER(TRIM(num_requisicao)) = ?
              AND COALESCE(status,'')
                  NOT IN ('Concluído','Arquivado')
        """

        parametros = [
            num_requisicao
        ]

        if ignorar_id:

            sql += """
                AND id <> ?
            """

            parametros.append(
                ignorar_id
            )

        sql += " LIMIT 1"

    resultado = executar(
        sql,
        tuple(parametros),
        fetchone=True
    )

    return resultado is not None


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
                categoria TEXT NOT NULL,
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

        # ----------------------------------------------------
        # MIGRAÇÕES
        # ----------------------------------------------------

        cursor.execute("""
            ALTER TABLE melhorias
            ADD COLUMN IF NOT EXISTS etapa TEXT
        """)

        cursor.execute("""
            ALTER TABLE melhorias
            ADD COLUMN IF NOT EXISTS autor TEXT
        """)

        cursor.execute("""
            ALTER TABLE atividades
            ADD COLUMN IF NOT EXISTS encerrado_por TEXT
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
                categoria TEXT NOT NULL,
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

        # ----------------------------------------------------
        # MIGRAÇÃO SQLITE - MELHORIAS
        # ----------------------------------------------------

        colunas = db.execute(
            "PRAGMA table_info(melhorias)"
        ).fetchall()

        nomes = [
            coluna["name"]
            for coluna in colunas
        ]

        if "etapa" not in nomes:

            db.execute("""
                ALTER TABLE melhorias
                ADD COLUMN etapa TEXT
            """)

        if "autor" not in nomes:

            db.execute("""
                ALTER TABLE melhorias
                ADD COLUMN autor TEXT
            """)

        # ----------------------------------------------------
        # MIGRAÇÃO SQLITE - ATIVIDADES
        # ----------------------------------------------------

        colunas = db.execute(
            "PRAGMA table_info(atividades)"
        ).fetchall()

        nomes = [
            coluna["name"]
            for coluna in colunas
        ]

        if "encerrado_por" not in nomes:

            db.execute("""
                ALTER TABLE atividades
                ADD COLUMN encerrado_por TEXT
            """)

        if "inicio_em" not in nomes:

            db.execute("""
                ALTER TABLE atividades
                ADD COLUMN inicio_em TEXT
            """)

        if "concluido_em" not in nomes:

            db.execute("""
                ALTER TABLE atividades
                ADD COLUMN concluido_em TEXT
            """)

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

        db.commit()

    # ========================================================
    # USUÁRIO ADMINISTRADOR INICIAL
    # ========================================================

    usuario = executar(
        """
        SELECT id
        FROM usuarios
        WHERE nome = %s
        LIMIT 1
        """
        if usando_postgresql()
        else
        """
        SELECT id
        FROM usuarios
        WHERE nome = ?
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

    if usando_postgresql():

        executar(
            """
            UPDATE atividades
            SET status = 'Arquivado'
            WHERE status = 'Concluído'
              AND concluido_em IS NOT NULL
              AND concluido_em <= %s
            """,
            (
                limite.replace(
                    tzinfo=None
                ),
            ),
            commit=True
        )

    else:

        limite_texto = (
            limite.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        executar(
            """
            UPDATE atividades
            SET status = 'Arquivado'
            WHERE status = 'Concluído'
              AND concluido_em IS NOT NULL
              AND concluido_em <= ?
            """,
            (limite_texto,),
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
            WHERE nome = %s
              AND senha = %s
            LIMIT 1
            """
            if usando_postgresql()
            else
            """
            SELECT *
            FROM usuarios
            WHERE nome = ?
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

            session["usuario_atual"] = (
                obter_valor(
                    usuario,
                    "nome"
                )
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

        if senha != confirmar:

            flash(
                "As senhas não conferem.",
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
# DASHBOARD
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

    arquivar_atividades_expiradas()

    usuario_atual = session[
        "usuario_atual"
    ]

    # ========================================================
    # POST
    # ========================================================

    if request.method == "POST":

        acao_chat = request.form.get(
            "acao_chat"
        )

        # ----------------------------------------------------
        # CHAT
        # ----------------------------------------------------

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

            return redirect(
                url_for("index")
            )

        # ----------------------------------------------------
        # NOVA ATIVIDADE
        # ----------------------------------------------------

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

        categorias_validas = [
            "Separação",
            "Inventário",
            "Expedição",
            "Recebimento",
            "Logística Reversa",
            "Estoque"
        ]

        prioridades_validas = [
            "Baixa",
            "Média",
            "Alta"
        ]

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

        inicio_em = None

        if categoria == "Separação":

            inicio_em = (
                agora_utc_naive()
                if usando_postgresql()
                else agora_sqlite()
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
                num_requisicao or None,
                atividade,
                descricao,
                categoria,
                responsavel,
                prioridade,
                prazo or None,
                "Pendente",
                inicio_em,
                (
                    agora_utc_naive()
                    if usando_postgresql()
                    else agora_sqlite()
                )
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

    # ========================================================
    # BUSCA
    # ========================================================

    busca = request.args.get(
        "q",
        ""
    ).strip()

    if busca:

        termo = f"%{busca}%"

        if usando_postgresql():

            itens = executar(
                """
                SELECT *
                FROM atividades
                WHERE
                    COALESCE(status,'')
                        NOT IN ('Concluído','Arquivado')
                    AND (
                        COALESCE(num_requisicao,'') ILIKE %s
                        OR COALESCE(atividade,'') ILIKE %s
                        OR COALESCE(descricao,'') ILIKE %s
                        OR COALESCE(responsavel,'') ILIKE %s
                    )
                ORDER BY id DESC
                """,
                (
                    termo,
                    termo,
                    termo,
                    termo
                ),
                fetchall=True
            )

        else:

            itens = executar(
                """
                SELECT *
                FROM atividades
                WHERE
                    COALESCE(status,'')
                        NOT IN ('Concluído','Arquivado')
                    AND (
                        LOWER(COALESCE(num_requisicao,'')) LIKE ?
                        OR LOWER(COALESCE(atividade,'')) LIKE ?
                        OR LOWER(COALESCE(descricao,'')) LIKE ?
                        OR LOWER(COALESCE(responsavel,'')) LIKE ?
                    )
                ORDER BY id DESC
                """,
                (
                    termo.lower(),
                    termo.lower(),
                    termo.lower(),
                    termo.lower()
                ),
                fetchall=True
            )

    else:

        itens = executar(
            """
            SELECT *
            FROM atividades
            WHERE COALESCE(status,'')
                NOT IN ('Concluído','Arquivado')
            ORDER BY id DESC
            """,
            fetchall=True
        )

    itens = preparar_lista_atividades(
        itens
    )

    # ========================================================
    # USUÁRIOS
    # ========================================================

    usuarios = executar(
        """
        SELECT *
        FROM usuarios
        ORDER BY nome
        """,
        fetchall=True
    )

    usuarios = linhas_para_dict(
        usuarios
    )

    # ========================================================
    # CHAT
    # ========================================================

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

    # ========================================================
    # INDICADORES
    # ========================================================

    total_req = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = %s
          AND COALESCE(status,'')
              NOT IN ('Arquivado')
        """
        if usando_postgresql()
        else
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = ?
          AND COALESCE(status,'')
              NOT IN ('Arquivado')
        """,
        ("Separação",)
    )

    inv_total = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = %s
          AND COALESCE(status,'')
              NOT IN ('Arquivado')
        """
        if usando_postgresql()
        else
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = ?
          AND COALESCE(status,'')
              NOT IN ('Arquivado')
        """,
        ("Inventário",)
    )

    inv_conc = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = %s
          AND status = %s
        """
        if usando_postgresql()
        else
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = ?
          AND status = ?
        """,
        (
            "Inventário",
            "Concluído"
        )
    )

    exp_pend = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = %s
          AND status NOT IN
              ('Concluído','Arquivado')
        """
        if usando_postgresql()
        else
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = ?
          AND status NOT IN
              ('Concluído','Arquivado')
        """,
        ("Expedição",)
    )

    rec_pend = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = %s
          AND status NOT IN
              ('Concluído','Arquivado')
        """
        if usando_postgresql()
        else
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = ?
          AND status NOT IN
              ('Concluído','Arquivado')
        """,
        ("Recebimento",)
    )

    total_oco = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE prioridade = %s
          AND status NOT IN
              ('Concluído','Arquivado')
        """
        if usando_postgresql()
        else
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE prioridade = ?
          AND status NOT IN
              ('Concluído','Arquivado')
        """,
        ("Alta",)
    )

    # ========================================================
    # CÁLCULOS
    # ========================================================

    todas = executar(
        """
        SELECT *
        FROM atividades
        """,
        fetchall=True
    )

    todas_preparadas = (
        preparar_lista_atividades(
            todas
        )
    )

    total_atrasados = sum(
        1
        for item in todas_preparadas
        if (
            item.get("foi_atrasada")
            and normalizar_texto(
                item.get("status")
            ) != "arquivado"
        )
    )

    total_geral = len(
        todas_preparadas
    )

    total_concluidas = sum(
        1
        for item in todas_preparadas
        if normalizar_texto(
            item.get("status")
        ) in (
            "concluido",
            "arquivado"
        )
    )

    total_expedicao = sum(
        1
        for item in todas_preparadas
        if item.get("categoria")
        == "Expedição"
    )

    expedicao_concluida = sum(
        1
        for item in todas_preparadas
        if (
            item.get("categoria")
            == "Expedição"
            and normalizar_texto(
                item.get("status")
            ) in (
                "concluido",
                "arquivado"
            )
        )
    )

    perc_atendidas = (
        round(
            (
                total_concluidas
                / total_geral
            ) * 100
        )
        if total_geral
        else 0
    )

    perc_inventario = (
        round(
            (
                inv_conc
                / inv_total
            ) * 100
        )
        if inv_total
        else 0
    )

    perc_expedicao = (
        round(
            (
                expedicao_concluida
                / total_expedicao
            ) * 100
        )
        if total_expedicao
        else 0
    )

    # ========================================================
    # GRÁFICOS
    # ========================================================

    atendidas_pizza = max(
        0,
        min(
            100,
            perc_atendidas
        )
    )

    pendentes_pizza = (
        100 - atendidas_pizza
    )

    inventario_pizza = max(
        0,
        min(
            100,
            perc_inventario
        )
    )

    inventario_pendente_pizza = (
        100 - inventario_pizza
    )

    expedicao_pizza = max(
        0,
        min(
            100,
            perc_expedicao
        )
    )

    expedicao_pendente_pizza = (
        100 - expedicao_pizza
    )

    # ========================================================
    # DASHBOARD
    #
    # IMPORTANTE:
    # usamos index.html, que é o template do dashboard atual.
    # ========================================================

    return render_template(
        "index.html",

        usuario_atual=usuario_atual,

        itens=itens,
        atividades=itens,

        usuarios=usuarios,

        mensagens=mensagens,
        chat=mensagens,

        total_req=total_req,

        inv_total=inv_total,
        inv_conc=inv_conc,

        exp_pend=exp_pend,
        rec_pend=rec_pend,

        total_oco=total_oco,
        total_atrasados=total_atrasados,

        total_geral=total_geral,

        concluidas=total_concluidas,
        atividades_concluidas=total_concluidas,

        perc_atendidas=perc_atendidas,
        perc_inventario=perc_inventario,
        perc_expedicao=perc_expedicao,

        atendidas_pizza=atendidas_pizza,
        pendentes_pizza=pendentes_pizza,

        inventario_pizza=inventario_pizza,
        inventario_pendente_pizza=(
            inventario_pendente_pizza
        ),

        expedicao_pizza=expedicao_pizza,
        expedicao_pendente_pizza=(
            expedicao_pendente_pizza
        ),

        busca=busca
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

    itens = executar(
        """
        SELECT *
        FROM atividades
        """,
        fetchall=True
    )

    itens = preparar_lista_atividades(
        itens
    )

    total_geral = len(
        itens
    )

    concluidas = sum(
        1
        for item in itens
        if normalizar_texto(
            item.get("status")
        ) in (
            "concluido",
            "arquivado"
        )
    )

    inventario_total = sum(
        1
        for item in itens
        if item.get("categoria")
        == "Inventário"
    )

    inventario_concluido = sum(
        1
        for item in itens
        if (
            item.get("categoria")
            == "Inventário"
            and normalizar_texto(
                item.get("status")
            ) in (
                "concluido",
                "arquivado"
            )
        )
    )

    expedicao_total = sum(
        1
        for item in itens
        if item.get("categoria")
        == "Expedição"
    )

    expedicao_concluido = sum(
        1
        for item in itens
        if (
            item.get("categoria")
            == "Expedição"
            and normalizar_texto(
                item.get("status")
            ) in (
                "concluido",
                "arquivado"
            )
        )
    )

    perc_atendidas = (
        round(
            (
                concluidas
                / total_geral
            ) * 100
        )
        if total_geral
        else 0
    )

    perc_inventario = (
        round(
            (
                inventario_concluido
                / inventario_total
            ) * 100
        )
        if inventario_total
        else 0
    )

    perc_expedicao = (
        round(
            (
                expedicao_concluido
                / expedicao_total
            ) * 100
        )
        if expedicao_total
        else 0
    )

    return render_template(
        "indicadores.html",

        total_geral=total_geral,

        concluidas=concluidas,

        perc_atendidas=perc_atendidas,

        perc_inventario=perc_inventario,

        perc_expedicao=perc_expedicao
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

    todas = executar(
        """
        SELECT *
        FROM atividades
        ORDER BY id DESC
        """,
        fetchall=True
    )

    todas = preparar_lista_atividades(
        todas
    )

    if filtro == "pendentes":

        itens = [
            item
            for item in todas
            if item.get("status")
            == "Pendente"
        ]

    elif filtro == "andamento":

        itens = [
            item
            for item in todas
            if item.get("status")
            == "Em andamento"
        ]

    elif filtro == "concluidos":

        itens = [
            item
            for item in todas
            if item.get("status")
            == "Concluído"
        ]

    elif filtro == "arquivados":

        itens = [
            item
            for item in todas
            if item.get("status")
            == "Arquivado"
        ]

    elif filtro == "atrasados":

        itens = [
            item
            for item in todas
            if (
                item.get("foi_atrasada")
                and normalizar_texto(
                    item.get("status")
                ) != "arquivado"
            )
        ]

    else:

        itens = todas

    total_todos = len(
        todas
    )

    total_pendentes = sum(
        1
        for item in todas
        if item.get("status")
        == "Pendente"
    )

    total_andamento = sum(
        1
        for item in todas
        if item.get("status")
        == "Em andamento"
    )

    total_concluidos = sum(
        1
        for item in todas
        if item.get("status")
        == "Concluído"
    )

    total_arquivados = sum(
        1
        for item in todas
        if item.get("status")
        == "Arquivado"
    )

    total_atrasados = sum(
        1
        for item in todas
        if (
            item.get("foi_atrasada")
            and normalizar_texto(
                item.get("status")
            ) != "arquivado"
        )
    )

    return render_template(
        "relatorios.html",

        itens=itens,

        filtro=filtro,

        usuario_atual=session[
            "usuario_atual"
        ],

        total_todos=total_todos,

        total_pendentes=total_pendentes,

        total_andamento=total_andamento,

        total_concluidos=total_concluidos,

        total_arquivados=total_arquivados,

        total_atrasados=total_atrasados
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

    # ========================================================
    # CORREÇÃO PRINCIPAL:
    # normalização agora remove TODOS os acentos,
    # inclusive ç.
    # ========================================================

    nome_normalizado = normalizar_texto(
        nome
    )

    # ========================================================
    # CONFIGURAÇÕES
    # ========================================================

    if nome_normalizado == "configuracoes":

        return render_template(
            "configuracoes.html",
            usuario_atual=session[
                "usuario_atual"
            ]
        )

    # ========================================================
    # INDICADORES
    # ========================================================

    if nome_normalizado == "indicadores":

        return redirect(
            url_for("indicadores")
        )

    # ========================================================
    # RELATÓRIOS
    # ========================================================

    if nome_normalizado == "relatorios":

        return redirect(
            url_for("relatorios")
        )

    # ========================================================
    # CADASTROS
    # ========================================================

    if nome_normalizado == "cadastros":

        return render_template(
            "cadastros.html",
            usuario_atual=session[
                "usuario_atual"
            ]
        )

    # ========================================================
    # MELHORIAS / PDCA
    # ========================================================

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
                    (
                        agora_utc_naive()
                        if usando_postgresql()
                        else agora_sqlite()
                    )
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
            WHERE COALESCE(status,'')
                <> 'Arquivado'
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

    # ========================================================
    # ESTOQUE
    # ========================================================

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

    # ========================================================
    # MAPA DOS MÓDULOS
    # ========================================================

    mapa_modulos = {

        "requisicoes": {
            "titulo": "Requisições",
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

        categoria = (
            configuracao["categoria"]
        )

        itens = executar(
            """
            SELECT *
            FROM atividades
            WHERE categoria = %s
            ORDER BY id DESC
            """
            if usando_postgresql()
            else
            """
            SELECT *
            FROM atividades
            WHERE categoria = ?
            ORDER BY id DESC
            """,
            (categoria,),
            fetchall=True
        )

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

    # ========================================================
    # MÓDULO DESCONHECIDO
    # ========================================================

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

    # GET:
    # a edição é feita pelo modal do relatório
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
            "Pendente"
        )
    ).strip()

    categorias_validas = [
        "Separação",
        "Inventário",
        "Expedição",
        "Recebimento",
        "Logística Reversa",
        "Estoque"
    ]

    prioridades_validas = [
        "Baixa",
        "Média",
        "Alta"
    ]

    status_validos = [
        "Pendente",
        "Em andamento",
        "Concluído",
        "Arquivado"
    ]

    if not atividade_texto:

        flash(
            "Informe a atividade.",
            "warning"
        )

        return redirect(
            url_for("relatorios")
        )

    if categoria not in categorias_validas:

        flash(
            "Categoria inválida.",
            "warning"
        )

        return redirect(
            url_for("relatorios")
        )

    if prioridade not in prioridades_validas:

        prioridade = "Baixa"

    if status not in status_validos:

        status = "Pendente"

    if (
        categoria == "Separação"
        and not num_requisicao
    ):

        flash(
            "A Separação precisa de um número de requisição.",
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
            f"A requisição {num_requisicao} já está sendo utilizada.",
            "warning"
        )

        return redirect(
            url_for("relatorios")
        )

    status_anterior = obter_valor(
        atividade,
        "status",
        "Pendente"
    )

    concluido_em = obter_valor(
        atividade,
        "concluido_em"
    )

    encerrado_por = obter_valor(
        atividade,
        "encerrado_por"
    )

    # --------------------------------------------------------
    # Se editar para concluído e ainda não tiver conclusão,
    # registra agora.
    # --------------------------------------------------------

    if (
        status == "Concluído"
        and normalizar_texto(
            status_anterior
        ) != "concluido"
    ):

        concluido_em = (
            agora_utc_naive()
            if usando_postgresql()
            else agora_sqlite()
        )

        encerrado_por = session[
            "usuario_atual"
        ]

    # --------------------------------------------------------
    # Se voltar para ativo, limpa encerramento.
    # --------------------------------------------------------

    if status in (
        "Pendente",
        "Em andamento"
    ):

        concluido_em = None
        encerrado_por = None

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
            prazo or None,
            status,
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

    status_atual = normalizar_texto(
        obter_valor(
            atividade,
            "status",
            ""
        )
    )

    if status_atual in (
        "concluido",
        "arquivado"
    ):

        flash(
            "Essa atividade já foi encerrada.",
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

    # ========================================================
    # SEPARAÇÃO CONCLUÍDA
    # → CRIA EXPEDIÇÃO AUTOMATICAMENTE
    # ========================================================

    categoria = obter_valor(
        atividade,
        "categoria"
    )

    num_requisicao = normalizar_requisicao(
        obter_valor(
            atividade,
            "num_requisicao"
        )
    )

    if (
        categoria == "Separação"
        and num_requisicao
    ):

        expedicao_existente = executar(
            """
            SELECT id
            FROM atividades
            WHERE categoria = %s
              AND UPPER(TRIM(num_requisicao)) = %s
              AND status NOT IN
                  ('Concluído','Arquivado')
            LIMIT 1
            """
            if usando_postgresql()
            else
            """
            SELECT id
            FROM atividades
            WHERE categoria = ?
              AND UPPER(TRIM(num_requisicao)) = ?
              AND status NOT IN
                  ('Concluído','Arquivado')
            LIMIT 1
            """,
            (
                "Expedição",
                num_requisicao
            ),
            fetchone=True
        )

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
                    "Pendente",

                    # INÍCIO DA EXPEDIÇÃO =
                    # MOMENTO DA CONCLUSÃO DA SEPARAÇÃO
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
                "Separação concluída. "
                "Já existia uma Expedição ativa para essa requisição.",
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
        SELECT id
        FROM atividades
        WHERE id = %s
        """
        if usando_postgresql()
        else
        """
        SELECT id
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
        (id,),
        commit=True
    )

    flash(
        "Registro arquivado. "
        "Ele continua disponível em "
        "Relatórios > Arquivados.",
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

    itens = executar(
        """
        SELECT *
        FROM atividades
        ORDER BY id DESC
        """,
        fetchall=True
    )

    itens = preparar_lista_atividades(
        itens
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
            "Relatório do Almoxarifado",
            estilos["Title"]
        )
    )

    elementos.append(
        Spacer(1, 15)
    )

    dados = [[
        "Req.",
        "Atividade",
        "Categoria",
        "Responsável",
        "Início",
        "Prazo",
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
                    "inicio_formatado"
                )
                or "-"
            ),

            str(
                item.get(
                    "prazo_formatado"
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

    tabela = Table(
        dados,
        repeatRows=1
    )

    tabela.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor(
                    "#212529"
                )
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
                    colors.HexColor(
                        "#f4f4f4"
                    )
                ]
            )
        ])
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
        download_name=(
            "relatorio_almoxarifado.pdf"
        )
    )


# ============================================================
# EXPORTAR ESTOQUE PARA EXCEL
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

                "Cadastrado em": formatar_data_hora(
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
# XLSX / XLS / CSV
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

        # ====================================================
        # CSV
        # ====================================================

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

        # ====================================================
        # XLSX
        # ====================================================

        elif nome.endswith(".xlsx"):

            df = pd.read_excel(
                arquivo,
                engine="openpyxl"
            )

        # ====================================================
        # XLS
        # ====================================================

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
                "Formato não suportado. "
                "Use XLSX, XLS ou CSV.",
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

        # ====================================================
        # NORMALIZAÇÃO DE COLUNAS
        # ====================================================

        df.columns = [
            normalizar_texto(coluna)
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

        # ====================================================
        # FALLBACK
        # ====================================================

        if coluna_codigo is None:

            if len(df.columns) >= 1:

                coluna_codigo = df.columns[0]

        if coluna_descricao is None:

            if len(df.columns) >= 2:

                coluna_descricao = df.columns[1]

        if coluna_quantidade is None:

            if len(df.columns) >= 3:

                coluna_quantidade = df.columns[2]

        quantidade_importada = 0

        # ====================================================
        # IMPORTAÇÃO
        # ====================================================

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
