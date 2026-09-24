from pathlib import Path

code = r'''import os
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
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
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
    "chave-temporaria-apenas-para-desenvolvimento",
)

DATABASE_URL = os.environ.get("DATABASE_URL")
FUSO_BRASIL = ZoneInfo("America/Sao_Paulo")


# ============================================================
# BANCO DE DADOS
# ============================================================

def usando_postgresql():
    return bool(DATABASE_URL)


def get_db():
    if "db" in g:
        return g.db

    if usando_postgresql():
        url = DATABASE_URL

        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]

        g.db = psycopg2.connect(
            url,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
    else:
        g.db = sqlite3.connect("database.db")
        g.db.row_factory = sqlite3.Row

    return g.db


@app.teardown_appcontext
def fechar_db(exception=None):
    db = g.pop("db", None)

    if db is not None:
        db.close()


def executar(sql, parametros=()):
    db = get_db()

    if not usando_postgresql():
        sql = sql.replace("%s", "?")

    cursor = db.cursor()
    cursor.execute(sql, parametros)

    return cursor


def linha_para_dict(linha):
    if linha is None:
        return None

    if isinstance(linha, dict):
        return dict(linha)

    return dict(linha)


def linhas_para_dict(linhas):
    return [linha_para_dict(linha) for linha in linhas]


def obter_valor(linha, chave, padrao=None):
    if linha is None:
        return padrao

    if isinstance(linha, dict):
        return linha.get(chave, padrao)

    try:
        return linha[chave]
    except Exception:
        return padrao


def fechar_cursor(cursor):
    try:
        cursor.close()
    except Exception:
        pass


def contar(sql, parametros=()):
    cursor = executar(sql, parametros)

    try:
        linha = cursor.fetchone()
        valor = obter_valor(linha, "total", 0)

        try:
            return int(valor or 0)
        except Exception:
            return 0
    finally:
        fechar_cursor(cursor)


# ============================================================
# DATA E HORA
# ============================================================

def agora_utc():
    return datetime.now(timezone.utc)


def agora_brasil():
    return agora_utc().astimezone(FUSO_BRASIL)


def agora_utc_naive():
    return agora_utc().replace(tzinfo=None)


def agora_sqlite():
    return agora_utc_naive().strftime("%Y-%m-%d %H:%M:%S")


def data_brasil():
    return agora_brasil().strftime("%Y-%m-%d")


def converter_para_brasil(valor):
    if valor is None or valor == "":
        return None

    if isinstance(valor, datetime):
        dt = valor

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(FUSO_BRASIL)

    texto = str(valor).strip()

    if not texto:
        return None

    try:
        dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        formatos = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y %H:%M",
        ]

        dt = None

        for formato in formatos:
            try:
                dt = datetime.strptime(texto, formato)
                break
            except ValueError:
                continue

        if dt is None:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(FUSO_BRASIL)


def formatar_data_hora(valor):
    dt = converter_para_brasil(valor)

    if not dt:
        return "-"

    return dt.strftime("%d/%m/%Y %H:%M")


def formatar_hora(valor):
    dt = converter_para_brasil(valor)

    if not dt:
        return "-"

    return dt.strftime("%H:%M")


def calcular_duracao(inicio, fim):
    dt_inicio = converter_para_brasil(inicio)
    dt_fim = converter_para_brasil(fim)

    if not dt_inicio or not dt_fim:
        return "-"

    diferenca = dt_fim - dt_inicio

    if diferenca.total_seconds() < 0:
        return "-"

    segundos = int(diferenca.total_seconds())
    horas, resto = divmod(segundos, 3600)
    minutos, _ = divmod(resto, 60)

    if horas:
        return f"{horas}h {minutos:02d}min"

    return f"{minutos}min"


def normalizar_requisicao(valor):
    if valor is None:
        return ""

    return str(valor).strip()


def prazo_em_datetime(valor):
    if valor is None or str(valor).strip() == "":
        return None

    texto = str(valor).strip()

    try:
        dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        formatos = [
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%d/%m/%Y %H:%M",
        ]

        dt = None

        for formato in formatos:
            try:
                dt = datetime.strptime(texto, formato)
                break
            except ValueError:
                continue

        if dt is None:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=FUSO_BRASIL)

    return dt.astimezone(FUSO_BRASIL)


def prazo_atrasado(valor):
    prazo = prazo_em_datetime(valor)

    if not prazo:
        return False

    return prazo < agora_brasil()


def texto_atraso(valor):
    prazo = prazo_em_datetime(valor)

    if not prazo:
        return ""

    diferenca = agora_brasil() - prazo

    if diferenca.total_seconds() <= 0:
        return ""

    segundos = int(diferenca.total_seconds())
    dias, resto = divmod(segundos, 86400)
    horas, minutos = divmod(resto, 3600)
    minutos //= 60

    if dias > 0:
        return f"{dias}d {horas}h atrasado"

    if horas > 0:
        return f"{horas}h {minutos:02d}min atrasado"

    return f"{minutos}min atrasado"


# ============================================================
# PREPARAÇÃO DOS DADOS
# ============================================================

def preparar_atividade(item):
    item = linha_para_dict(item) or {}

    item["atividade_original"] = item.get("atividade") or ""
    item["descricao_original"] = item.get("descricao") or ""
    item["responsavel_original"] = item.get("responsavel") or ""
    item["prioridade_original"] = item.get("prioridade") or "Baixa"
    item["categoria_original"] = item.get("categoria") or "Separação"
    item["status_original"] = item.get("status") or "Pendente"

    item["num_requisicao"] = normalizar_requisicao(
        item.get("num_requisicao")
    )

    item["atividade"] = item.get("atividade") or ""
    item["descricao"] = item.get("descricao") or ""
    item["responsavel"] = item.get("responsavel") or ""
    item["prioridade"] = item.get("prioridade") or "Baixa"
    item["categoria"] = item.get("categoria") or "Separação"
    item["status"] = item.get("status") or "Pendente"
    item["encerrado_por"] = item.get("encerrado_por") or ""

    item["inicio_formatado"] = formatar_data_hora(item.get("inicio_em"))
    item["concluido_formatado"] = formatar_data_hora(
        item.get("concluido_em")
    )
    item["prazo_formatado"] = formatar_data_hora(item.get("prazo"))

    item["hora_inicio"] = formatar_hora(item.get("inicio_em"))
    item["hora_conclusao"] = formatar_hora(item.get("concluido_em"))

    item["duracao"] = calcular_duracao(
        item.get("inicio_em"),
        item.get("concluido_em"),
    )

    item["atrasado"] = (
        item["status"] not in ("Concluído", "Arquivada")
        and prazo_atrasado(item.get("prazo"))
    )

    item["texto_atraso"] = (
        texto_atraso(item.get("prazo"))
        if item["atrasado"]
        else ""
    )

    item["prazo_form"] = ""

    prazo = item.get("prazo")

    if prazo:
        dt_prazo = prazo_em_datetime(prazo)

        if dt_prazo:
            item["prazo_form"] = dt_prazo.strftime("%Y-%m-%dT%H:%M")

    return item


def preparar_lista_atividades(itens):
    return [preparar_atividade(item) for item in itens]


def preparar_chat(item):
    item = linha_para_dict(item) or {}
    item["horario_formatado"] = formatar_data_hora(item.get("horario"))
    return item


# ============================================================
# REQUISIÇÕES
# ============================================================

def requisicao_duplicada(num_requisicao, id_atual=None):
    num_requisicao = normalizar_requisicao(num_requisicao)

    if not num_requisicao:
        return False

    if id_atual is not None:
        sql = """
            SELECT id
            FROM atividades
            WHERE TRIM(COALESCE(num_requisicao, '')) = %s
              AND status <> 'Arquivada'
              AND id <> %s
            LIMIT 1
        """
        cursor = executar(sql, (num_requisicao, id_atual))
    else:
        sql = """
            SELECT id
            FROM atividades
            WHERE TRIM(COALESCE(num_requisicao, '')) = %s
              AND status <> 'Arquivada'
            LIMIT 1
        """
        cursor = executar(sql, (num_requisicao,))

    try:
        return cursor.fetchone() is not None
    finally:
        fechar_cursor(cursor)


# ============================================================
# BANCO - INICIALIZAÇÃO E MIGRAÇÕES
# ============================================================

def init_db():
    db = get_db()

    if usando_postgresql():
        cursor = db.cursor()

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

        colunas_atividades = {
            "num_requisicao": "TEXT",
            "prioridade": "TEXT DEFAULT 'Baixa'",
            "atividade": "TEXT",
            "descricao": "TEXT",
            "categoria": "TEXT DEFAULT 'Separação'",
            "responsavel": "TEXT",
            "prazo": "TEXT DEFAULT ''",
            "status": "TEXT DEFAULT 'Pendente'",
            "inicio_em": "TIMESTAMP",
            "concluido_em": "TIMESTAMP",
            "encerrado_por": "TEXT",
        }

        for coluna, tipo in colunas_atividades.items():
            cursor.execute(
                f"ALTER TABLE atividades "
                f"ADD COLUMN IF NOT EXISTS {coluna} {tipo}"
            )

        cursor.execute("""
            UPDATE atividades
            SET prioridade = 'Baixa'
            WHERE prioridade IS NULL OR TRIM(prioridade) = ''
        """)

        cursor.execute("""
            UPDATE atividades
            SET categoria = 'Separação'
            WHERE categoria IS NULL OR TRIM(categoria) = ''
        """)

        cursor.execute("""
            UPDATE atividades
            SET prazo = ''
            WHERE prazo IS NULL
        """)

        cursor.execute("""
            UPDATE atividades
            SET status = 'Pendente'
            WHERE status IS NULL OR TRIM(status) = ''
        """)

        cursor.execute("""
            UPDATE atividades
            SET descricao = ''
            WHERE descricao IS NULL
        """)

        cursor.execute("""
            UPDATE atividades
            SET atividade = 'Atividade sem descrição'
            WHERE atividade IS NULL OR TRIM(atividade) = ''
        """)

        cursor.execute("""
            UPDATE atividades
            SET responsavel = 'Não informado'
            WHERE responsavel IS NULL OR TRIM(responsavel) = ''
        """)

        cursor.execute("""
            SELECT TRIM(num_requisicao) AS requisicao, COUNT(*) AS total
            FROM atividades
            WHERE TRIM(COALESCE(num_requisicao, '')) <> ''
              AND status <> 'Arquivada'
            GROUP BY TRIM(num_requisicao)
            HAVING COUNT(*) > 1
            LIMIT 1
        """)

        duplicado = cursor.fetchone()

        if duplicado is None:
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_atividades_req_ativa
                ON atividades (TRIM(num_requisicao))
                WHERE TRIM(COALESCE(num_requisicao, '')) <> ''
                  AND status <> 'Arquivada'
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
                status TEXT DEFAULT 'Pendente',
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            ALTER TABLE melhorias
            ADD COLUMN IF NOT EXISTS etapa TEXT DEFAULT 'Planejar (Plan)'
        """)

        cursor.execute("""
            ALTER TABLE melhorias
            ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'Pendente'
        """)

        cursor.execute("""
            ALTER TABLE melhorias
            ADD COLUMN IF NOT EXISTS criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

        db.commit()
        fechar_cursor(cursor)

    else:
        cursor = db.cursor()

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

        cursor.execute("PRAGMA table_info(atividades)")
        existentes = {row[1] for row in cursor.fetchall()}

        colunas_atividades = {
            "num_requisicao": "TEXT",
            "prioridade": "TEXT DEFAULT 'Baixa'",
            "atividade": "TEXT",
            "descricao": "TEXT",
            "categoria": "TEXT DEFAULT 'Separação'",
            "responsavel": "TEXT",
            "prazo": "TEXT DEFAULT ''",
            "status": "TEXT DEFAULT 'Pendente'",
            "inicio_em": "TEXT",
            "concluido_em": "TEXT",
            "encerrado_por": "TEXT",
        }

        for coluna, tipo in colunas_atividades.items():
            if coluna not in existentes:
                cursor.execute(
                    f"ALTER TABLE atividades ADD COLUMN {coluna} {tipo}"
                )

        cursor.execute("""
            UPDATE atividades
            SET prioridade = 'Baixa'
            WHERE prioridade IS NULL OR TRIM(prioridade) = ''
        """)

        cursor.execute("""
            UPDATE atividades
            SET categoria = 'Separação'
            WHERE categoria IS NULL OR TRIM(categoria) = ''
        """)

        cursor.execute("""
            UPDATE atividades
            SET prazo = ''
            WHERE prazo IS NULL
        """)

        cursor.execute("""
            UPDATE atividades
            SET status = 'Pendente'
            WHERE status IS NULL OR TRIM(status) = ''
        """)

        cursor.execute("""
            UPDATE atividades
            SET descricao = ''
            WHERE descricao IS NULL
        """)

        cursor.execute("""
            UPDATE atividades
            SET atividade = 'Atividade sem descrição'
            WHERE atividade IS NULL OR TRIM(atividade) = ''
        """)

        cursor.execute("""
            UPDATE atividades
            SET responsavel = 'Não informado'
            WHERE responsavel IS NULL OR TRIM(responsavel) = ''
        """)

        cursor.execute("""
            SELECT TRIM(num_requisicao) AS requisicao, COUNT(*) AS total
            FROM atividades
            WHERE TRIM(COALESCE(num_requisicao, '')) <> ''
              AND status <> 'Arquivada'
            GROUP BY TRIM(num_requisicao)
            HAVING COUNT(*) > 1
            LIMIT 1
        """)

        duplicado = cursor.fetchone()

        if duplicado is None:
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_atividades_req_ativa
                ON atividades (TRIM(num_requisicao))
                WHERE TRIM(COALESCE(num_requisicao, '')) <> ''
                  AND status <> 'Arquivada'
            """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                remetente TEXT NOT NULL,
                mensagem TEXT NOT NULL,
                horario TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS melhorias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                descricao TEXT NOT NULL,
                autor TEXT NOT NULL,
                etapa TEXT DEFAULT 'Planejar (Plan)',
                status TEXT DEFAULT 'Pendente',
                criado_em TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("PRAGMA table_info(melhorias)")
        colunas_melhorias = {row[1] for row in cursor.fetchall()}

        if "etapa" not in colunas_melhorias:
            cursor.execute("""
                ALTER TABLE melhorias
                ADD COLUMN etapa TEXT DEFAULT 'Planejar (Plan)'
            """)

        if "status" not in colunas_melhorias:
            cursor.execute("""
                ALTER TABLE melhorias
                ADD COLUMN status TEXT DEFAULT 'Pendente'
            """)

        if "criado_em" not in colunas_melhorias:
            cursor.execute("""
                ALTER TABLE melhorias
                ADD COLUMN criado_em TEXT
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

        db.commit()
        fechar_cursor(cursor)

    # Usuário inicial
    total_usuarios = contar("SELECT COUNT(*) AS total FROM usuarios")

    if total_usuarios == 0:
        cursor = executar(
            """
            INSERT INTO usuarios (nome, senha)
            VALUES (%s, %s)
            """,
            ("Wanderson Fernandes", "1234"),
        )
        get_db().commit()
        fechar_cursor(cursor)


# ============================================================
# ARQUIVAMENTO AUTOMÁTICO
# ============================================================

def arquivar_atividades_expiradas():
    limite = agora_utc_naive() - timedelta(hours=24)

    if usando_postgresql():
        cursor = executar(
            """
            UPDATE atividades
            SET status = 'Arquivada'
            WHERE status = 'Concluído'
              AND concluido_em IS NOT NULL
              AND concluido_em <= %s
            """,
            (limite,),
        )
    else:
        limite_texto = limite.strftime("%Y-%m-%d %H:%M:%S")

        cursor = executar(
            """
            UPDATE atividades
            SET status = 'Arquivada'
            WHERE status = 'Concluído'
              AND concluido_em IS NOT NULL
              AND concluido_em <= %s
            """,
            (limite_texto,),
        )

    get_db().commit()
    fechar_cursor(cursor)


# ============================================================
# LOGIN
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        senha = request.form.get("senha", "")

        cursor = executar(
            """
            SELECT *
            FROM usuarios
            WHERE nome = %s
              AND senha = %s
            LIMIT 1
            """,
            (nome, senha),
        )

        usuario = cursor.fetchone()
        fechar_cursor(cursor)

        if usuario:
            session["usuario"] = nome
            return redirect(url_for("index"))

        flash("Usuário ou senha inválidos.", "danger")

    return render_template("login.html")


@app.route("/cadastro_usuario", methods=["GET", "POST"])
def cadastro_usuario():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        senha = request.form.get("senha", "")

        if not nome or not senha:
            flash("Preencha nome e senha.", "warning")
            return render_template("cadastro_usuario.html")

        try:
            cursor = executar(
                """
                INSERT INTO usuarios (nome, senha)
                VALUES (%s, %s)
                """,
                (nome, senha),
            )

            get_db().commit()
            fechar_cursor(cursor)

            flash("Usuário cadastrado com sucesso.", "success")
            return redirect(url_for("login"))

        except Exception as erro:
            get_db().rollback()
            flash(f"Não foi possível cadastrar: {erro}", "danger")

    return render_template("cadastro_usuario.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ============================================================
# INÍCIO / DASHBOARD
# ============================================================

@app.route("/", methods=["GET", "POST"])
def index():
    if "usuario" not in session:
        return redirect(url_for("login"))

    arquivar_atividades_expiradas()

    if request.method == "POST":
        acao_chat = request.form.get("acao_chat")

        if acao_chat == "enviar":
            mensagem = request.form.get("mensagem", "").strip()

            if mensagem:
                cursor = executar(
                    """
                    INSERT INTO chat (remetente, mensagem, horario)
                    VALUES (%s, %s, %s)
                    """,
                    (
                        session["usuario"],
                        mensagem,
                        agora_utc_naive() if usando_postgresql()
                        else agora_sqlite(),
                    ),
                )

                get_db().commit()
                fechar_cursor(cursor)

            return redirect(url_for("index"))

        num_requisicao = normalizar_requisicao(
            request.form.get("num_requisicao")
        )
        prioridade = request.form.get("prioridade", "Baixa").strip()
        atividade = request.form.get("atividade", "").strip()
        descricao = request.form.get("descricao", "").strip()
        categoria = request.form.get("categoria", "Separação").strip()
        responsavel = request.form.get("responsavel", "").strip()
        prazo = request.form.get("prazo", "").strip()

        prioridades_validas = {"Baixa", "Média", "Alta"}
        categorias_validas = {
            "Separação",
            "Inventário",
            "Expedição",
            "Recebimento",
        }

        if prioridade not in prioridades_validas:
            prioridade = "Baixa"

        if categoria not in categorias_validas:
            flash("Categoria inválida.", "danger")
            return redirect(url_for("index"))

        if not atividade:
            flash("Informe a atividade.", "warning")
            return redirect(url_for("index"))

        if not responsavel:
            responsavel = session["usuario"]

        if categoria == "Separação" and not num_requisicao:
            flash(
                "Para uma atividade de Separação, informe a requisição.",
                "warning",
            )
            return redirect(url_for("index"))

        if num_requisicao and requisicao_duplicada(num_requisicao):
            flash(
                f"A requisição {num_requisicao} já possui uma atividade ativa.",
                "danger",
            )
            return redirect(url_for("index"))

        inicio = (
            agora_utc_naive()
            if usando_postgresql()
            else agora_sqlite()
        )

        try:
            cursor = executar(
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
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'Pendente', %s)
                """,
                (
                    num_requisicao or None,
                    prioridade,
                    atividade,
                    descricao,
                    categoria,
                    responsavel,
                    prazo,
                    inicio,
                ),
            )

            get_db().commit()
            fechar_cursor(cursor)

            flash("Atividade criada com sucesso.", "success")

        except Exception as erro:
            get_db().rollback()

            flash(
                f"Não foi possível salvar a atividade: {erro}",
                "danger",
            )

        return redirect(url_for("index"))

    q = request.args.get("q", "").strip()

    if q:
        termo = f"%{q}%"

        cursor = executar(
            """
            SELECT *
            FROM atividades
            WHERE CAST(id AS TEXT) LIKE %s
               OR COALESCE(num_requisicao, '') LIKE %s
               OR COALESCE(atividade, '') LIKE %s
               OR COALESCE(descricao, '') LIKE %s
               OR COALESCE(categoria, '') LIKE %s
               OR COALESCE(responsavel, '') LIKE %s
               OR COALESCE(status, '') LIKE %s
               OR COALESCE(encerrado_por, '') LIKE %s
            ORDER BY id DESC
            """,
            (
                termo,
                termo,
                termo,
                termo,
                termo,
                termo,
                termo,
                termo,
            ),
        )
    else:
        cursor = executar(
            """
            SELECT *
            FROM atividades
            WHERE status = 'Pendente'
            ORDER BY
                CASE prioridade
                    WHEN 'Alta' THEN 1
                    WHEN 'Média' THEN 2
                    ELSE 3
                END,
                id DESC
            """
        )

    atividades = preparar_lista_atividades(cursor.fetchall())
    fechar_cursor(cursor)

    cursor = executar(
        """
        SELECT *
        FROM chat
        ORDER BY id DESC
        LIMIT 15
        """
    )

    chat = [preparar_chat(item) for item in cursor.fetchall()]
    fechar_cursor(cursor)

    # Indicadores
    total_req = contar("""
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = 'Separação'
          AND status = 'Pendente'
    """)

    cursor = executar("""
        SELECT prazo, status
        FROM atividades
        WHERE COALESCE(prazo, '') <> ''
          AND status NOT IN ('Concluído', 'Arquivada')
    """)

    total_atrasados = 0

    for linha in cursor.fetchall():
        if prazo_atrasado(obter_valor(linha, "prazo")):
            total_atrasados += 1

    fechar_cursor(cursor)

    inv_total_indicador = contar("""
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = 'Inventário'
          AND status <> 'Arquivada'
    """)

    inv_concluido = contar("""
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = 'Inventário'
          AND status = 'Concluído'
    """)

    exp_total = contar("""
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = 'Expedição'
          AND status <> 'Arquivada'
    """)

    exp_pend = contar("""
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = 'Expedição'
          AND status = 'Pendente'
    """)

    exp_concluido = contar("""
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = 'Expedição'
          AND status = 'Concluído'
    """)

    rec_pend = contar("""
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = 'Recebimento'
          AND status = 'Pendente'
    """)

    total_oco = contar("""
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE prioridade = 'Alta'
          AND status = 'Pendente'
    """)

    total_atividades = contar("""
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE status <> 'Arquivada'
    """)

    atividades_concluidas = contar("""
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE status = 'Concluído'
    """)

    atividades_arquivadas = contar("""
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE status = 'Arquivada'
    """)

    perc_atendidas = (
        round((atividades_concluidas / total_atividades) * 100)
        if total_atividades
        else 0
    )

    perc_inventario = (
        round((inv_concluido / inv_total_indicador) * 100)
        if inv_total_indicador
        else 0
    )

    perc_expedicao = (
        round((exp_concluido / exp_total) * 100)
        if exp_total
        else 0
    )

    cursor = executar("""
        SELECT *
        FROM usuarios
        ORDER BY nome
    """)

    usuarios = linhas_para_dict(cursor.fetchall())
    fechar_cursor(cursor)

    return render_template(
        "index.html",
        atividades=atividades,
        chat=chat,
        usuarios=usuarios,
        q=q,
        total_req=total_req,
        total_atrasados=total_atrasados,
        inv_concluido=inv_concluido,
        inv_total_indicador=inv_total_indicador,
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
        perc_expedicao=perc_expedicao,
    )


# ============================================================
# ATRASADOS
# ============================================================

@app.route("/atrasados")
def atrasados():
    if "usuario" not in session:
        return redirect(url_for("login"))

    cursor = executar("""
        SELECT *
        FROM atividades
        WHERE COALESCE(prazo, '') <> ''
          AND status NOT IN ('Concluído', 'Arquivada')
        ORDER BY id DESC
    """)

    itens = preparar_lista_atividades(cursor.fetchall())
    fechar_cursor(cursor)

    itens = [item for item in itens if item["atrasado"]]

    return render_template(
        "modulo.html",
        nome="Atrasados",
        itens=itens,
    )


# ============================================================
# MÓDULOS
# ============================================================

@app.route("/modulo/<path:nome>", methods=["GET", "POST"])
def modulo(nome):
    if "usuario" not in session:
        return redirect(url_for("login"))

    nome = nome.strip()

    if nome.lower() == "atrasados":
        return redirect(url_for("atrasados"))

    if nome == "Configurações":
        return render_template(
            "configuracoes.html",
            nome=nome,
        )

    if nome == "Indicadores":
        total = contar("""
            SELECT COUNT(*) AS total
            FROM atividades
            WHERE status <> 'Arquivada'
        """)

        concluidas = contar("""
            SELECT COUNT(*) AS total
            FROM atividades
            WHERE status = 'Concluído'
        """)

        inventario_total = contar("""
            SELECT COUNT(*) AS total
            FROM atividades
            WHERE categoria = 'Inventário'
              AND status <> 'Arquivada'
        """)

        inventario_concluido = contar("""
            SELECT COUNT(*) AS total
            FROM atividades
            WHERE categoria = 'Inventário'
              AND status = 'Concluído'
        """)

        expedicao_total = contar("""
            SELECT COUNT(*) AS total
            FROM atividades
            WHERE categoria = 'Expedição'
              AND status <> 'Arquivada'
        """)

        expedicao_concluida = contar("""
            SELECT COUNT(*) AS total
            FROM atividades
            WHERE categoria = 'Expedição'
              AND status = 'Concluído'
        """)

        perc_atendidas = (
            round((concluidas / total) * 100)
            if total
            else 0
        )

        perc_inventario = (
            round(
                (inventario_concluido / inventario_total) * 100
            )
            if inventario_total
            else 0
        )

        perc_expedicao = (
            round(
                (expedicao_concluida / expedicao_total) * 100
            )
            if expedicao_total
            else 0
        )

        return render_template(
            "indicadores.html",
            total=total,
            concluidas=concluidas,
            inventario_total=inventario_total,
            inventario_concluido=inventario_concluido,
            expedicao_total=expedicao_total,
            expedicao_concluida=expedicao_concluida,
            perc_atendidas=perc_atendidas,
            perc_inventario=perc_inventario,
            perc_expedicao=perc_expedicao,
        )

    if nome in ("Melhorias", "PDCA"):
        if request.method == "POST":
            titulo = request.form.get("titulo", "").strip()
            descricao = request.form.get("descricao", "").strip()
            etapa = request.form.get(
                "etapa",
                "Planejar (Plan)",
            ).strip()
            status = request.form.get(
                "status",
                "Pendente",
            ).strip()

            if not titulo or not descricao:
                flash(
                    "Preencha título e descrição da melhoria.",
                    "warning",
                )
            else:
                cursor = executar(
                    """
                    INSERT INTO melhorias (
                        titulo,
                        descricao,
                        autor,
                        etapa,
                        status,
                        criado_em
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        titulo,
                        descricao,
                        session["usuario"],
                        etapa,
                        status,
                        agora_utc_naive()
                        if usando_postgresql()
                        else agora_sqlite(),
                    ),
                )

                get_db().commit()
                fechar_cursor(cursor)

                flash(
                    "Melhoria registrada com sucesso.",
                    "success",
                )

            return redirect(
                url_for("modulo", nome="Melhorias")
            )

        cursor = executar("""
            SELECT *
            FROM melhorias
            ORDER BY id DESC
        """)

        melhorias = linhas_para_dict(cursor.fetchall())
        fechar_cursor(cursor)

        return render_template(
            "pdca.html",
            melhorias=melhorias,
        )

    if nome == "Relatórios":
        cursor = executar("""
            SELECT *
            FROM atividades
            ORDER BY id DESC
        """)

        itens = preparar_lista_atividades(cursor.fetchall())
        fechar_cursor(cursor)

        return render_template(
            "relatorios.html",
            itens=itens,
        )

    if nome == "Cadastros":
        cursor = executar("""
            SELECT *
            FROM usuarios
            ORDER BY nome
        """)

        usuarios = linhas_para_dict(cursor.fetchall())
        fechar_cursor(cursor)

        return render_template(
            "cadastros.html",
            usuarios=usuarios,
        )

    if nome == "Estoque":
        if request.method == "POST":
            acao_estoque = request.form.get("acao_estoque")

            if acao_estoque == "cadastrar_manual":
                rua = request.form.get("rua", "").strip()
                prateleira = request.form.get(
                    "prateleira",
                    "",
                ).strip()
                codigo_material = request.form.get(
                    "codigo_material",
                    "",
                ).strip()
                descricao = request.form.get(
                    "descricao",
                    "",
                ).strip()

                try:
                    quantidade = int(
                        request.form.get(
                            "quantidade",
                            "0",
                        )
                    )
                except ValueError:
                    quantidade = 0

                if not descricao:
                    flash(
                        "Informe a descrição do material.",
                        "warning",
                    )
                else:
                    cursor = executar(
                        """
                        INSERT INTO estoque (
                            rua,
                            prateleira,
                            codigo_material,
                            descricao,
                            quantidade
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            rua,
                            prateleira,
                            codigo_material,
                            descricao,
                            quantidade,
                        ),
                    )

                    get_db().commit()
                    fechar_cursor(cursor)

                    flash(
                        "Material cadastrado no estoque.",
                        "success",
                    )

                return redirect(
                    url_for("modulo", nome="Estoque")
                )

            if acao_estoque == "importar_excel":
                arquivo = request.files.get("arquivo")

                if not arquivo or not arquivo.filename:
                    flash(
                        "Selecione um arquivo.",
                        "warning",
                    )
                    return redirect(
                        url_for("modulo", nome="Estoque")
                    )

                extensao = (
                    arquivo.filename.rsplit(".", 1)[-1]
                    .lower()
                    if "." in arquivo.filename
                    else ""
                )

                if extensao not in {
                    "xlsx",
                    "xls",
                    "csv",
                }:
                    flash(
                        "Formato inválido. Use XLSX, XLS ou CSV.",
                        "danger",
                    )
                    return redirect(
                        url_for("modulo", nome="Estoque")
                    )

                try:
                    arquivo.seek(0)

                    if extensao == "csv":
                        df = pd.read_csv(arquivo)
                    else:
                        df = pd.read_excel(arquivo)

                    def normalizar_coluna(coluna):
                        texto = str(coluna).strip().lower()

                        substituicoes = {
                            "á": "a",
                            "à": "a",
                            "ã": "a",
                            "â": "a",
                            "ä": "a",
                            "é": "e",
                            "è": "e",
                            "ê": "e",
                            "ë": "e",
                            "í": "i",
                            "ì": "i",
                            "î": "i",
                            "ï": "i",
                            "ó": "o",
                            "ò": "o",
                            "õ": "o",
                            "ô": "o",
                            "ö": "o",
                            "ú": "u",
                            "ù": "u",
                            "û": "u",
                            "ü": "u",
                            "ç": "c",
                        }

                        for origem, destino in substituicoes.items():
                            texto = texto.replace(
                                origem,
                                destino,
                            )

                        return (
                            texto
                            .replace(" ", "_")
                            .replace("-", "_")
                        )

                    df.columns = [
                        normalizar_coluna(coluna)
                        for coluna in df.columns
                    ]

                    mapa_colunas = {}

                    for coluna in df.columns:
                        if coluna in ("rua",):
                            mapa_colunas["rua"] = coluna

                        elif coluna in (
                            "codigo",
                            "codigo_material",
                            "cod_material",
                        ):
                            mapa_colunas[
                                "codigo_material"
                            ] = coluna

                        elif coluna in (
                            "descricao",
                            "descricao_material",
                            "material",
                        ):
                            mapa_colunas["descricao"] = coluna

                        elif coluna in (
                            "quantidade",
                            "qtd",
                            "qtde",
                        ):
                            mapa_colunas["quantidade"] = coluna

                        elif coluna in (
                            "prateleira",
                            "posicao",
                            "localizacao",
                        ):
                            mapa_colunas["prateleira"] = coluna

                    obrigatorias = {
                        "rua",
                        "codigo_material",
                        "descricao",
                        "quantidade",
                    }

                    faltantes = obrigatorias - set(
                        mapa_colunas.keys()
                    )

                    if faltantes:
                        raise ValueError(
                            "Colunas obrigatórias ausentes: "
                            + ", ".join(sorted(faltantes))
                        )

                    total_importado = 0

                    for _, linha in df.iterrows():
                        rua = str(
                            linha.get(
                                mapa_colunas["rua"],
                                "",
                            )
                        ).strip()

                        codigo = str(
                            linha.get(
                                mapa_colunas[
                                    "codigo_material"
                                ],
                                "",
                            )
                        ).strip()

                        descricao = str(
                            linha.get(
                                mapa_colunas["descricao"],
                                "",
                            )
                        ).strip()

                        quantidade_bruta = linha.get(
                            mapa_colunas["quantidade"],
                            0,
                        )

                        try:
                            if pd.isna(quantidade_bruta):
                                quantidade = 0
                            else:
                                quantidade = int(
                                    float(quantidade_bruta)
                                )
                        except Exception:
                            quantidade = 0

                        prateleira = ""

                        if "prateleira" in mapa_colunas:
                            valor = linha.get(
                                mapa_colunas["prateleira"],
                                "",
                            )

                            if not pd.isna(valor):
                                prateleira = str(
                                    valor
                                ).strip()

                        if not descricao:
                            continue

                        cursor = executar(
                            """
                            INSERT INTO estoque (
                                rua,
                                prateleira,
                                codigo_material,
                                descricao,
                                quantidade
                            )
                            VALUES (%s, %s, %s, %s, %s)
                            """,
                            (
                                rua,
                                prateleira,
                                codigo,
                                descricao,
                                quantidade,
                            ),
                        )

                        fechar_cursor(cursor)
                        total_importado += 1

                    get_db().commit()

                    flash(
                        f"{total_importado} item(ns) "
                        "importado(s) com sucesso.",
                        "success",
                    )

                except Exception as erro:
                    get_db().rollback()

                    flash(
                        f"Erro ao importar estoque: {erro}",
                        "danger",
                    )

                return redirect(
                    url_for("modulo", nome="Estoque")
                )

        cursor = executar("""
            SELECT *
            FROM estoque
            ORDER BY rua, prateleira, descricao
        """)

        estoque = linhas_para_dict(cursor.fetchall())
        fechar_cursor(cursor)

        return render_template(
            "estoque.html",
            estoque=estoque,
        )

    categoria_map = {
        "Requisições": "Separação",
        "Inventário": "Inventário",
        "Expedição": "Expedição",
        "Recebimento": "Recebimento",
    }

    categoria = categoria_map.get(nome)

    if categoria:
        cursor = executar(
            """
            SELECT *
            FROM atividades
            WHERE categoria = %s
            ORDER BY
                CASE status
                    WHEN 'Pendente' THEN 1
                    WHEN 'Em andamento' THEN 2
                    WHEN 'Concluído' THEN 3
                    WHEN 'Arquivada' THEN 4
                    ELSE 5
                END,
                id DESC
            """,
            (categoria,),
        )

        itens = preparar_lista_atividades(
            cursor.fetchall()
        )
        fechar_cursor(cursor)

        return render_template(
            "modulo.html",
            nome=nome,
            itens=itens,
        )

    return render_template(
        "modulo.html",
        nome=nome,
        itens=[],
    )


# ============================================================
# RELATÓRIO PDF
# ============================================================

@app.route("/relatorio_pdf")
def relatorio_pdf():
    if "usuario" not in session:
        return redirect(url_for("login"))

    hoje = data_brasil()

    if usando_postgresql():
        cursor = executar("""
            SELECT
                *,
                (
                    inicio_em
                    AT TIME ZONE 'UTC'
                    AT TIME ZONE 'America/Sao_Paulo'
                ) AS inicio_brasil,
                (
                    concluido_em
                    AT TIME ZONE 'UTC'
                    AT TIME ZONE 'America/Sao_Paulo'
                ) AS concluido_brasil
            FROM atividades
            ORDER BY id DESC
        """)
    else:
        cursor = executar("""
            SELECT
                *,
                datetime(
                    inicio_em,
                    '-3 hours'
                ) AS inicio_brasil,
                datetime(
                    concluido_em,
                    '-3 hours'
                ) AS concluido_brasil
            FROM atividades
            ORDER BY id DESC
        """)

    itens = cursor.fetchall()
    fechar_cursor(cursor)

    itens_preparados = preparar_lista_atividades(itens)

    total = len(itens_preparados)
    concluidas = sum(
        1
        for item in itens_preparados
        if item["status"] == "Concluído"
    )
    pendentes = sum(
        1
        for item in itens_preparados
        if item["status"] in (
            "Pendente",
            "Em andamento",
        )
    )
    arquivadas = sum(
        1
        for item in itens_preparados
        if item["status"] == "Arquivada"
    )

    buffer = BytesIO()

    documento = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=0.7 * cm,
        leftMargin=0.7 * cm,
        topMargin=0.7 * cm,
        bottomMargin=0.7 * cm,
    )

    estilos = getSampleStyleSheet()

    estilo_titulo = ParagraphStyle(
        "TituloAlmoxarifado",
        parent=estilos["Title"],
        fontSize=16,
        leading=20,
        spaceAfter=10,
    )

    estilo_pequeno = ParagraphStyle(
        "Pequeno",
        parent=estilos["Normal"],
        fontSize=7,
        leading=9,
    )

    elementos = []

    elementos.append(
        Paragraph(
            "Relatório do Almoxarifado",
            estilo_titulo,
        )
    )

    elementos.append(
        Paragraph(
            f"Data do relatório: {hoje}",
            estilos["Normal"],
        )
    )

    elementos.append(Spacer(1, 0.3 * cm))

    resumo = [
        ["Total", "Concluídas", "Pendentes", "Arquivadas"],
        [
            str(total),
            str(concluidas),
            str(pendentes),
            str(arquivadas),
        ],
    ]

    tabela_resumo = Table(
        resumo,
        colWidths=[
            5 * cm,
            5 * cm,
            5 * cm,
            5 * cm,
        ],
    )

    tabela_resumo.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#212529")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("PADDING", (0, 0), (-1, -1), 6),
        ])
    )

    elementos.append(tabela_resumo)
    elementos.append(Spacer(1, 0.5 * cm))

    cabecalho = [
        "Req.",
        "Atividade",
        "Categoria",
        "Responsável",
        "Encerrado por",
        "Início",
        "Encerramento",
        "Duração",
        "Status",
    ]

    dados = [cabecalho]

    for item in itens_preparados:
        dados.append([
            item.get("num_requisicao") or "-",
            item.get("atividade") or "-",
            item.get("categoria") or "-",
            item.get("responsavel") or "-",
            item.get("encerrado_por") or "-",
            item.get("inicio_formatado") or "-",
            item.get("concluido_formatado") or "-",
            item.get("duracao") or "-",
            item.get("status") or "-",
        ])

    tabela = Table(
        dados,
        repeatRows=1,
        colWidths=[
            2.2 * cm,
            5.5 * cm,
            3.1 * cm,
            3.3 * cm,
            3.3 * cm,
            3.2 * cm,
            3.2 * cm,
            2.4 * cm,
            2.6 * cm,
        ],
    )

    tabela.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d6efd")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 6.5),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("PADDING", (0, 0), (-1, -1), 3),
        ])
    )

    elementos.append(tabela)

    documento.build(elementos)

    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"relatorio_almoxarifado_{hoje}.pdf",
        mimetype="application/pdf",
    )


# ============================================================
# EDITAR ATIVIDADE
# ============================================================

@app.route("/editar/<int:id>", methods=["GET", "POST"])
def editar(id):
    if "usuario" not in session:
        return redirect(url_for("login"))

    cursor = executar(
        """
        SELECT *
        FROM atividades
        WHERE id = %s
        LIMIT 1
        """,
        (id,),
    )

    atividade = cursor.fetchone()
    fechar_cursor(cursor)

    if not atividade:
        flash("Atividade não encontrada.", "danger")
        return redirect(url_for("index"))

    atividade = linha_para_dict(atividade)

    if atividade.get("status") in (
        "Concluído",
        "Arquivada",
    ):
        flash(
            "Atividades concluídas ou arquivadas não podem ser editadas.",
            "warning",
        )
        return redirect(url_for("index"))

    cursor = executar("""
        SELECT *
        FROM usuarios
        ORDER BY nome
    """)

    usuarios = linhas_para_dict(cursor.fetchall())
    fechar_cursor(cursor)

    if request.method == "POST":
        num_requisicao = normalizar_requisicao(
            request.form.get("num_requisicao")
        )
        nova_atividade = request.form.get(
            "atividade",
            "",
        ).strip()
        descricao = request.form.get(
            "descricao",
            "",
        ).strip()
        categoria = request.form.get(
            "categoria",
            "Separação",
        ).strip()
        responsavel = request.form.get(
            "responsavel",
            "",
        ).strip()
        prioridade = request.form.get(
            "prioridade",
            "Baixa",
        ).strip()
        prazo = request.form.get(
            "prazo",
            "",
        ).strip()

        categorias_validas = {
            "Separação",
            "Inventário",
            "Expedição",
            "Recebimento",
        }

        prioridades_validas = {
            "Baixa",
            "Média",
            "Alta",
        }

        if categoria not in categorias_validas:
            categoria = atividade.get(
                "categoria",
                "Separação",
            )

        if prioridade not in prioridades_validas:
            prioridade = atividade.get(
                "prioridade",
                "Baixa",
            )

        if not nova_atividade:
            flash(
                "Informe a atividade.",
                "warning",
            )

            atividade["num_requisicao"] = num_requisicao
            atividade["atividade"] = nova_atividade
            atividade["descricao"] = descricao
            atividade["categoria"] = categoria
            atividade["responsavel"] = responsavel
            atividade["prioridade"] = prioridade
            atividade["prazo"] = prazo

            atividade_preparada = preparar_atividade(
                atividade
            )

            return render_template(
                "editar_requisicao.html",
                atividade=atividade_preparada,
                usuarios=usuarios,
            )

        if categoria == "Separação" and not num_requisicao:
            flash(
                "Para Separação, informe a requisição.",
                "warning",
            )

            atividade["num_requisicao"] = num_requisicao
            atividade["atividade"] = nova_atividade
            atividade["descricao"] = descricao
            atividade["categoria"] = categoria
            atividade["responsavel"] = responsavel
            atividade["prioridade"] = prioridade
            atividade["prazo"] = prazo

            atividade_preparada = preparar_atividade(
                atividade
            )

            return render_template(
                "editar_requisicao.html",
                atividade=atividade_preparada,
                usuarios=usuarios,
            )

        if requisicao_duplicada(
            num_requisicao,
            id_atual=id,
        ):
            flash(
                f"A requisição {num_requisicao} já possui outra atividade ativa.",
                "danger",
            )

            atividade["num_requisicao"] = num_requisicao
            atividade["atividade"] = nova_atividade
            atividade["descricao"] = descricao
            atividade["categoria"] = categoria
            atividade["responsavel"] = responsavel
            atividade["prioridade"] = prioridade
            atividade["prazo"] = prazo

            atividade_preparada = preparar_atividade(
                atividade
            )

            return render_template(
                "editar_requisicao.html",
                atividade=atividade_preparada,
                usuarios=usuarios,
            )

        if not responsavel:
            responsavel = session["usuario"]

        try:
            cursor = executar(
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
                  AND status IN (
                      'Pendente',
                      'Em andamento'
                  )
                """,
                (
                    num_requisicao or None,
                    nova_atividade,
                    descricao,
                    categoria,
                    responsavel,
                    prioridade,
                    prazo,
                    id,
                ),
            )

            alteradas = cursor.rowcount

            get_db().commit()
            fechar_cursor(cursor)

            if alteradas:
                flash(
                    "Atividade atualizada com sucesso.",
                    "success",
                )
            else:
                flash(
                    "A atividade não pôde ser atualizada.",
                    "warning",
                )

            return redirect(url_for("index"))

        except Exception as erro:
            get_db().rollback()

            flash(
                f"Erro ao editar atividade: {erro}",
                "danger",
            )

            atividade["num_requisicao"] = num_requisicao
            atividade["atividade"] = nova_atividade
            atividade["descricao"] = descricao
            atividade["categoria"] = categoria
            atividade["responsavel"] = responsavel
            atividade["prioridade"] = prioridade
            atividade["prazo"] = prazo

            atividade_preparada = preparar_atividade(
                atividade
            )

            return render_template(
                "editar_requisicao.html",
                atividade=atividade_preparada,
                usuarios=usuarios,
            )

    atividade = preparar_atividade(atividade)

    return render_template(
        "editar_requisicao.html",
        atividade=atividade,
        usuarios=usuarios,
    )


# ============================================================
# CONCLUIR ATIVIDADE
# ============================================================

@app.route("/concluir/<int:id>", methods=["POST", "GET"])
def concluir(id):
    if "usuario" not in session:
        return redirect(url_for("login"))

    cursor = executar(
        """
        SELECT *
        FROM atividades
        WHERE id = %s
          AND status IN (
              'Pendente',
              'Em andamento'
          )
        LIMIT 1
        """,
        (id,),
    )

    atividade = cursor.fetchone()
    fechar_cursor(cursor)

    if not atividade:
        flash(
            "Atividade não encontrada ou já concluída.",
            "warning",
        )
        return redirect(url_for("index"))

    atividade = linha_para_dict(atividade)

    momento_encerramento = (
        agora_utc_naive()
        if usando_postgresql()
        else agora_sqlite()
    )

    db = get_db()

    try:
        cursor = executar(
            """
            UPDATE atividades
            SET
                status = 'Concluído',
                concluido_em = %s,
                encerrado_por = %s
            WHERE id = %s
              AND status IN (
                  'Pendente',
                  'Em andamento'
              )
            """,
            (
                momento_encerramento,
                session["usuario"],
                id,
            ),
        )

        alteradas = cursor.rowcount
        fechar_cursor(cursor)

        if alteradas == 0:
            raise Exception(
                "A atividade não pôde ser concluída."
            )

        # Quando uma Separação é concluída,
        # cria automaticamente a Expedição.
        categoria = atividade.get("categoria")
        requisicao = normalizar_requisicao(
            atividade.get("num_requisicao")
        )

        if categoria == "Separação" and requisicao:
            cursor = executar(
                """
                SELECT id
                FROM atividades
                WHERE TRIM(COALESCE(num_requisicao, '')) = %s
                  AND categoria = 'Expedição'
                  AND status <> 'Arquivada'
                LIMIT 1
                """,
                (requisicao,),
            )

            expedicao_existente = cursor.fetchone()
            fechar_cursor(cursor)

            if not expedicao_existente:
                descricao_expedicao = (
                    "Expedição criada automaticamente após "
                    f"a conclusão da Separação da requisição "
                    f"{requisicao}."
                )

                cursor = executar(
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
                        'Expedição',
                        %s,
                        %s,
                        'Pendente',
                        %s
                    )
                    """,
                    (
                        requisicao,
                        atividade.get(
                            "prioridade",
                            "Baixa",
                        ),
                        f"Expedição da requisição {requisicao}",
                        descricao_expedicao,
                        atividade.get(
                            "responsavel"
                        )
                        or session["usuario"],
                        atividade.get("prazo") or "",
                        momento_encerramento,
                    ),
                )

                fechar_cursor(cursor)

        db.commit()

        flash(
            "Atividade concluída com sucesso.",
            "success",
        )

    except Exception as erro:
        db.rollback()

        flash(
            f"Não foi possível concluir a atividade: {erro}",
            "danger",
        )

    return redirect(url_for("index"))


# ============================================================
# ARQUIVAR MANUALMENTE
# ============================================================

@app.route("/arquivar/<int:id>", methods=["POST", "GET"])
def arquivar(id):
    if "usuario" not in session:
        return redirect(url_for("login"))

    cursor = executar(
        """
        UPDATE atividades
        SET status = 'Arquivada'
        WHERE id = %s
          AND status = 'Concluído'
        """,
        (id,),
    )

    alteradas = cursor.rowcount
    get_db().commit()
    fechar_cursor(cursor)

    if alteradas:
        flash(
            "Atividade arquivada. O histórico foi preservado.",
            "success",
        )
    else:
        flash(
            "Somente atividades concluídas podem ser arquivadas.",
            "warning",
        )

    return redirect(request.referrer or url_for("index"))


# ============================================================
# COMPATIBILIDADE COM ROTA ANTIGA DE EXCLUSÃO
# ============================================================

@app.route("/deletar/<int:id>", methods=["POST", "GET"])
def deletar(id):
    if "usuario" not in session:
        return redirect(url_for("login"))

    # Não apaga a atividade: arquiva para preservar o histórico.
    cursor = executar(
        """
        UPDATE atividades
        SET status = 'Arquivada'
        WHERE id = %s
          AND status = 'Concluído'
        """,
        (id,),
    )

    alteradas = cursor.rowcount
    get_db().commit()
    fechar_cursor(cursor)

    if alteradas:
        flash(
            "Registro arquivado. O histórico foi preservado.",
            "success",
        )
    else:
        flash(
            "O registro não foi excluído. Apenas atividades concluídas podem ser arquivadas.",
            "warning",
        )

    return redirect(request.referrer or url_for("index"))


# ============================================================
# EXCLUIR ITEM DO ESTOQUE
# ============================================================

@app.route(
    "/deletar_estoque/<int:id>",
    methods=["POST", "GET"],
)
def deletar_estoque(id):
    if "usuario" not in session:
        return redirect(url_for("login"))

    cursor = executar(
        """
        DELETE FROM estoque
        WHERE id = %s
        """,
        (id,),
    )

    get_db().commit()
    fechar_cursor(cursor)

    flash(
        "Item removido do estoque.",
        "success",
    )

    return redirect(
        request.referrer
        or url_for("modulo", nome="Estoque")
    )


# ============================================================
# EXCLUIR MELHORIA / PDCA
# ============================================================

@app.route(
    "/deletar_melhoria/<int:id>",
    methods=["POST", "GET"],
)
def deletar_melhoria(id):
    if "usuario" not in session:
        return redirect(url_for("login"))

    cursor = executar(
        """
        DELETE FROM melhorias
        WHERE id = %s
        """,
        (id,),
    )

    get_db().commit()
    fechar_cursor(cursor)

    flash(
        "Melhoria removida.",
        "success",
    )

    return redirect(
        request.referrer
        or url_for("modulo", nome="Melhorias")
    )


# ============================================================
# INICIALIZAÇÃO
# ============================================================

with app.app_context():
    init_db()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )





pa
