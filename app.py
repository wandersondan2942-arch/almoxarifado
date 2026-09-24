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
    "chave-temporaria-apenas-para-desenvolvimento"
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
        g.db = sqlite3.connect("database.db")
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
        cursor.execute(sql, parametros)

        if commit:
            db.commit()

        return cursor

    except Exception:
        cursor.close()
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
    return [linha_para_dict(linha) for linha in linhas]


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
    cursor = executar(sql, parametros)

    linha = cursor.fetchone()

    fechar_cursor(cursor)

    if linha is None:
        return 0

    return int(obter_valor(linha, "total", 0) or 0)


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
    return agora_utc_naive().isoformat(timespec="seconds")


def data_brasil():
    return agora_brasil().strftime("%d/%m/%Y")


def converter_para_brasil(valor):
    if not valor:
        return None

    if isinstance(valor, datetime):
        dt = valor
    else:
        texto = str(valor).strip()

        try:
            dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        except Exception:
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
                except Exception:
                    continue

            if dt is None:
                return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(FUSO_BRASIL)


def formatar_data_hora(valor):
    dt = converter_para_brasil(valor)

    if not dt:
        return ""

    return dt.strftime("%d/%m/%Y %H:%M")


def formatar_hora(valor):
    dt = converter_para_brasil(valor)

    if not dt:
        return ""

    return dt.strftime("%H:%M")


def calcular_duracao(inicio, fim=None):
    if not inicio:
        return ""

    dt_inicio = converter_para_brasil(inicio)

    if not dt_inicio:
        return ""

    dt_fim = converter_para_brasil(fim) if fim else agora_brasil()

    if not dt_fim:
        return ""

    segundos = int((dt_fim - dt_inicio).total_seconds())

    if segundos < 0:
        segundos = 0

    horas = segundos // 3600
    minutos = (segundos % 3600) // 60

    if horas:
        return f"{horas}h {minutos}min"

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
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%d/%m/%Y %H:%M",
        ]

        dt = None

        for formato in formatos:
            try:
                dt = datetime.strptime(texto, formato)
                break
            except Exception:
                continue

        if dt is None:
            try:
                dt = datetime.fromisoformat(
                    texto.replace("Z", "+00:00")
                )
            except Exception:
                return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=FUSO_BRASIL)

    return dt.astimezone(FUSO_BRASIL)


def prazo_atrasado(valor):
    dt = prazo_em_datetime(valor)

    if not dt:
        return False

    return dt < agora_brasil()


def texto_atraso(valor):
    dt = prazo_em_datetime(valor)

    if not dt:
        return ""

    diferenca = agora_brasil() - dt

    minutos = int(diferenca.total_seconds() // 60)

    if minutos <= 0:
        return ""

    dias = minutos // 1440
    horas = (minutos % 1440) // 60
    mins = minutos % 60

    if dias:
        return f"{dias}d {horas}h atrasado"

    if horas:
        return f"{horas}h {mins}min atrasado"

    return f"{mins}min atrasado"


# ============================================================
# PREPARAÇÃO DOS DADOS
# ============================================================

def preparar_atividade(atividade):
    atividade = linha_para_dict(atividade)

    if not atividade:
        return atividade

    atividade["prazo_formatado"] = formatar_data_hora(
        atividade.get("prazo")
    )

    atividade["inicio_formatado"] = formatar_data_hora(
        atividade.get("inicio_em")
    )

    atividade["concluido_formatado"] = formatar_data_hora(
        atividade.get("concluido_em")
    )

    atividade["criado_formatado"] = formatar_data_hora(
        atividade.get("criado_em")
    )

    atividade["prazo_atrasado"] = prazo_atrasado(
        atividade.get("prazo")
    )

    atividade["texto_atraso"] = texto_atraso(
        atividade.get("prazo")
    )

    atividade["duracao"] = calcular_duracao(
        atividade.get("inicio_em"),
        atividade.get("concluido_em")
    )

    atividade["num_requisicao"] = (
        atividade.get("num_requisicao") or ""
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
            item["data_formatada"] = formatar_data_hora(
                item.get("criado_em")
            )

            resultado.append(item)

    return resultado


# ============================================================
# REQUISIÇÃO DUPLICADA
# ============================================================

def requisicao_duplicada(num_requisicao, ignorar_id=None):
    numero = normalizar_requisicao(num_requisicao)

    if not numero:
        return False

    if ignorar_id:
        sql = """
            SELECT id
            FROM atividades
            WHERE UPPER(TRIM(num_requisicao)) = %s
              AND status NOT IN ('Concluído', 'Arquivado')
              AND id <> %s
            LIMIT 1
        """

        cursor = executar(
            sql,
            (numero, ignorar_id)
        )

    else:
        sql = """
            SELECT id
            FROM atividades
            WHERE UPPER(TRIM(num_requisicao)) = %s
              AND status NOT IN ('Concluído', 'Arquivado')
            LIMIT 1
        """

        cursor = executar(sql, (numero,))

    linha = cursor.fetchone()

    fechar_cursor(cursor)

    return linha is not None


# ============================================================
# CRIAÇÃO / MIGRAÇÃO DO BANCO
# ============================================================

def init_db():
    db = get_db()

    if usando_postgresql():

        cursor = db.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id SERIAL PRIMARY KEY,
                nome TEXT NOT NULL,
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
                responsavel TEXT,
                prazo TEXT,
                status TEXT NOT NULL DEFAULT 'Pendente',
                inicio_em TIMESTAMP,
                concluido_em TIMESTAMP,
                encerrado_por TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat (
                id SERIAL PRIMARY KEY,
                usuario TEXT NOT NULL,
                mensagem TEXT NOT NULL,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS melhorias (
                id SERIAL PRIMARY KEY,
                titulo TEXT NOT NULL,
                descricao TEXT,
                status TEXT DEFAULT 'A Fazer',
                responsavel TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS estoque (
                id SERIAL PRIMARY KEY,
                codigo TEXT,
                descricao TEXT,
                categoria TEXT,
                quantidade NUMERIC DEFAULT 0,
                localizacao TEXT,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Migrações
        colunas_atividades = {
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

        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'atividades'
        """)

        existentes = {
            linha["column_name"]
            for linha in cursor.fetchall()
        }

        for coluna, tipo in colunas_atividades.items():
            if coluna not in existentes:
                cursor.execute(
                    f"ALTER TABLE atividades ADD COLUMN {coluna} {tipo}"
                )

        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_atividades_req_ativa
            ON atividades (UPPER(TRIM(num_requisicao)))
            WHERE num_requisicao IS NOT NULL
              AND TRIM(num_requisicao) <> ''
              AND status NOT IN ('Concluído', 'Arquivado')
        """)

        db.commit()
        cursor.close()

    else:

        cursor = db.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
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
                responsavel TEXT,
                prazo TEXT,
                status TEXT NOT NULL DEFAULT 'Pendente',
                inicio_em TEXT,
                concluido_em TEXT,
                encerrado_por TEXT,
                criado_em TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT NOT NULL,
                mensagem TEXT NOT NULL,
                criado_em TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS melhorias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                descricao TEXT,
                status TEXT DEFAULT 'A Fazer',
                responsavel TEXT,
                criado_em TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS estoque (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT,
                descricao TEXT,
                categoria TEXT,
                quantidade REAL DEFAULT 0,
                localizacao TEXT,
                criado_em TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Migração SQLite
        cursor.execute("PRAGMA table_info(atividades)")

        existentes = {
            linha["name"]
            for linha in cursor.fetchall()
        }

        colunas_atividades = {
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

        for coluna, tipo in colunas_atividades.items():
            if coluna not in existentes:
                cursor.execute(
                    f"ALTER TABLE atividades ADD COLUMN {coluna} {tipo}"
                )

        db.commit()

        try:
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS
                idx_atividades_req_ativa
                ON atividades (
                    UPPER(TRIM(num_requisicao))
                )
                WHERE num_requisicao IS NOT NULL
                  AND TRIM(num_requisicao) <> ''
                  AND status NOT IN ('Concluído', 'Arquivado')
            """)

            db.commit()

        except Exception:
            db.rollback()

        cursor.close()

    # Usuário inicial
    cursor = executar(
        "SELECT id FROM usuarios WHERE nome = %s LIMIT 1",
        ("Wanderson Fernandes",)
    )

    usuario = cursor.fetchone()

    fechar_cursor(cursor)

    if usuario is None:
        executar(
            """
            INSERT INTO usuarios (nome, senha)
            VALUES (%s, %s)
            """,
            ("Wanderson Fernandes", "1234"),
            commit=True
        )


# ============================================================
# ARQUIVAMENTO AUTOMÁTICO
# ============================================================

def arquivar_atividades_expiradas():
    limite = agora_utc() - timedelta(hours=24)

    if usando_postgresql():
        limite_valor = limite.replace(tzinfo=None)
    else:
        limite_valor = limite.replace(tzinfo=None).isoformat(
            timespec="seconds"
        )

    executar(
        """
        UPDATE atividades
        SET status = 'Arquivado'
        WHERE status = 'Concluído'
          AND concluido_em IS NOT NULL
          AND concluido_em < %s
        """,
        (limite_valor,),
        commit=True
    )


# ============================================================
# LOGIN
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        nome = request.form.get("usuario", "").strip()
        senha = request.form.get("senha", "").strip()

        cursor = executar(
            """
            SELECT *
            FROM usuarios
            WHERE nome = %s
              AND senha = %s
            LIMIT 1
            """,
            (nome, senha)
        )

        usuario = linha_para_dict(cursor.fetchone())

        fechar_cursor(cursor)

        if usuario:

            session["usuario_atual"] = usuario["nome"]

            return redirect(url_for("index"))

        flash("Usuário ou senha inválidos.", "danger")

    return render_template("login.html")


# ============================================================
# CADASTRO DE USUÁRIO
# ============================================================

@app.route("/cadastro_usuario", methods=["GET", "POST"])
def cadastro_usuario():

    if request.method == "POST":

        nome = request.form.get("nome", "").strip()
        senha = request.form.get("senha", "").strip()

        if not nome or not senha:
            flash(
                "Preencha nome e senha.",
                "warning"
            )

            return redirect(
                url_for("cadastro_usuario")
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
                url_for("cadastro_usuario")
            )

        executar(
            """
            INSERT INTO usuarios (nome, senha)
            VALUES (%s, %s)
            """,
            (nome, senha),
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
        "cadastro_usuario.html"
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
# DASHBOARD PRINCIPAL
# ============================================================

@app.route("/", methods=["GET", "POST"])
def index():

    if "usuario_atual" not in session:
        return redirect(
            url_for("login")
        )

    arquivar_atividades_expiradas()

    usuario_atual = session["usuario_atual"]

    # --------------------------------------------------------
    # CHAT
    # --------------------------------------------------------

    if request.method == "POST":

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

        if num_requisicao and requisicao_duplicada(
            num_requisicao
        ):

            flash(
                f"A requisição {num_requisicao} "
                "já possui uma atividade ativa.",
                "warning"
            )

            return redirect(
                url_for("index")
            )

        status = "Pendente"

        inicio_em = None

        if categoria == "Separação":
            inicio_em = (
                agora_utc_naive()
                if usando_postgresql()
                else agora_sqlite()
            )

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
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s
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
                status,
                inicio_em,
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
    # PESQUISA
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
                termo,
            )
        )

    else:

        cursor = executar(
            """
            SELECT *
            FROM atividades
            WHERE status NOT IN ('Concluído', 'Arquivado')
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

    chats = preparar_chat(
        cursor.fetchall()
    )

    fechar_cursor(cursor)

    chats.reverse()

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
        WHERE status NOT IN ('Arquivado')
        """
    )

    total_atrasados = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE status NOT IN ('Concluído', 'Arquivado')
          AND prazo IS NOT NULL
        """
    )

    # Corrigindo atrasados considerando data real
    cursor = executar(
        """
        SELECT prazo
        FROM atividades
        WHERE status NOT IN ('Concluído', 'Arquivado')
          AND prazo IS NOT NULL
        """
    )

    prazos = cursor.fetchall()

    fechar_cursor(cursor)

    total_atrasados = sum(
        1
        for linha in prazos
        if prazo_atrasado(
            obter_valor(linha, "prazo")
        )
    )

    inv_total_indicador = contar(
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
          AND status = 'Concluído'
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
          AND status = 'Concluído'
        """
    )

    exp_pend = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = 'Expedição'
          AND status NOT IN ('Concluído', 'Arquivado')
        """
    )

    rec_pend = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE categoria = 'Recebimento'
          AND status NOT IN ('Concluído', 'Arquivado')
        """
    )

    total_oco = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE prioridade = 'Alta'
          AND status NOT IN ('Concluído', 'Arquivado')
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
        WHERE status = 'Concluído'
        """
    )

    atividades_arquivadas = contar(
        """
        SELECT COUNT(*) AS total
        FROM atividades
        WHERE status = 'Arquivado'
        """
    )

    if total_atividades:
        perc_atendidas = round(
            (
                atividades_concluidas
                / total_atividades
            ) * 100
        )
    else:
        perc_atendidas = 0

    if inv_total_indicador:
        perc_inventario = round(
            (
                inv_concluido
                / inv_total_indicador
            ) * 100
        )
    else:
        perc_inventario = 0

    if exp_total:
        perc_expedicao = round(
            (
                exp_concluido
                / exp_total
            ) * 100
        )
    else:
        perc_expedicao = 0

    return render_template(
        "dashboard.html",
        usuario_atual=usuario_atual,
        atividades=atividades,
        chats=chats,
        usuarios=usuarios,
        busca=busca,
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

    if "usuario_atual" not in session:
        return redirect(
            url_for("login")
        )

    cursor = executar(
        """
        SELECT *
        FROM atividades
        WHERE status NOT IN ('Concluído', 'Arquivado')
          AND prazo IS NOT NULL
        ORDER BY id DESC
        """
    )

    lista = preparar_lista_atividades(
        cursor.fetchall()
    )

    fechar_cursor(cursor)

    lista = [
        item
        for item in lista
        if item.get("prazo_atrasado")
    ]

    return render_template(
        "atrasados.html",
        atividades=lista,
        usuario_atual=session["usuario_atual"]
    )


# ============================================================
# MÓDULOS
# ============================================================

@app.route("/modulo/<path:nome>")
def modulo(nome):

    if "usuario_atual" not in session:
        return redirect(
            url_for("login")
        )

    nome = nome.strip().lower()

    if nome == "configuracoes":
        titulo = "Configurações"

    elif nome == "indicadores":
        titulo = "Indicadores"

    elif nome in ("melhorias", "pdca"):
        titulo = "Melhorias / PDCA"

    elif nome == "relatorios":
        titulo = "Relatórios"

    elif nome == "cadastros":
        titulo = "Cadastros"

    elif nome == "estoque":
        titulo = "Estoque"

    elif nome == "requisicoes":
        titulo = "Requisições"

    elif nome == "inventario":
        titulo = "Inventário"

    elif nome == "expedicao":
        titulo = "Expedição"

    elif nome == "recebimento":
        titulo = "Recebimento"

    else:
        titulo = nome.title()

    return render_template(
        "modulo.html",
        titulo=titulo,
        modulo=nome,
        usuario_atual=session["usuario_atual"]
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
        ]
    ]

    for item in atividades:

        dados.append(
            [
                str(item.get("id", "")),
                str(item.get("num_requisicao", "")),
                str(item.get("atividade", "")),
                str(item.get("categoria", "")),
                str(item.get("responsavel", "")),
                str(item.get("prioridade", "")),
                str(item.get("status", "")),
                str(item.get("prazo_formatado", "")),
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
                ),
            ]
        )
    )

    elementos.append(tabela)

    documento.build(elementos)

    buffer.seek(0)

    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="relatorio_almoxarifado.pdf"
    )


# ============================================================
# EDITAR ATIVIDADE
# ============================================================

@app.route("/editar/<int:id>", methods=["GET", "POST"])
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
            atividade.get("status", "Pendente")
        ).strip()

        prioridades_validas = {
            "Baixa",
            "Média",
            "Alta",
        }

        categorias_validas = {
            "Separação",
            "Inventário",
            "Expedição",
            "Recebimento",
        }

        status_validos = {
            "Pendente",
            "Em andamento",
            "Concluído",
            "Arquivado",
        }

        if prioridade not in prioridades_validas:
            prioridade = "Baixa"

        if categoria not in categorias_validas:
            categoria = "Separação"

        if status not in status_validos:
            status = "Pendente"

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

        if num_requisicao and requisicao_duplicada(
            num_requisicao,
            ignorar_id=id
        ):

            flash(
                f"A requisição {num_requisicao} "
                "já está em outra atividade ativa.",
                "warning"
            )

            return render_template(
                "editar.html",
                atividade=atividade,
                usuarios=usuarios,
                prazo_form=prazo
            )

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
                status = %s
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
                id,
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

    prazo_form = atividade.get("prazo") or ""

    if "T" not in prazo_form:
        try:
            dt = prazo_em_datetime(prazo_form)

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
# CONCLUIR ATIVIDADE
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

    status_atual = atividade.get("status")

    if status_atual not in (
        "Pendente",
        "Em andamento"
    ):

        flash(
            "Essa atividade não pode ser concluída.",
            "warning"
        )

        return redirect(
            url_for("index")
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
        """,
        (
            agora,
            session["usuario_atual"],
            id
        ),
        commit=True
    )

    # --------------------------------------------------------
    # CRIA EXPEDIÇÃO AUTOMATICAMENTE
    # --------------------------------------------------------

    if atividade.get("categoria") == "Separação":

        requisicao = atividade.get(
            "num_requisicao"
        )

        if requisicao:

            cursor = executar(
                """
                SELECT id
                FROM atividades
                WHERE num_requisicao = %s
                  AND categoria = 'Expedição'
                  AND status NOT IN (
                      'Concluído',
                      'Arquivado'
                  )
                LIMIT 1
                """,
                (requisicao,)
            )

            expedicao_existente = cursor.fetchone()

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
                        f"Expedição da requisição {requisicao}",
                        (
                            "Expedição criada "
                            "automaticamente após "
                            "conclusão da separação."
                        ),
                        "Expedição",
                        "",
                        None,
                        "Pendente",
                        agora,
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
# ROTA ANTIGA DE DELETAR
# ============================================================

@app.route("/deletar/<int:id>")
def deletar(id):

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
        "Registro arquivado.",
        "success"
    )

    return redirect(
        url_for("index")
    )


# ============================================================
# ESTOQUE
# ============================================================

@app.route("/deletar_estoque/<int:id>")
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
        url_for("modulo", nome="estoque")
    )


# ============================================================
# MELHORIAS / PDCA
# ============================================================

@app.route("/deletar_melhoria/<int:id>")
def deletar_melhoria(id):

    if "usuario_atual" not in session:
        return redirect(
            url_for("login")
        )

    executar(
        """
        DELETE FROM melhorias
        WHERE id = %s
        """,
        (id,),
        commit=True
    )

    flash(
        "Melhoria removida.",
        "success"
    )

    return redirect(
        url_for("modulo", nome="melhorias")
    )


# ============================================================
# INICIALIZAÇÃO
# ============================================================

with app.app_context():
    init_db()


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
