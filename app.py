import os
import sqlite3
import psycopg2
import psycopg2.extras
from flask import Flask, render_template, request, redirect, url_for, g, session

app = Flask(__name__)
app.secret_key = 'valenet_sistema_operacional_2026'

# Lê a variável de ambiente do Render para o PostgreSQL
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        if DATABASE_URL:
            # Se houver URL do Render, liga-se ao PostgreSQL
            db = g._database = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            # Caso contrário, continua a usar o SQLite local para testes
            db = g._database = sqlite3.connect('database.db')
            db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
    db = get_db()
    cur = db.cursor()
    cur.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY SERIAL,
                nome TEXT UNIQUE NOT NULL,
                senha TEXT NOT NULL
            )
        ''')
    cur = db.cursor()
    cur.execute('''
            CREATE TABLE IF NOT EXISTS atividades (
                id INTEGER PRIMARY KEY SERIAL,
                num_requisicao TEXT,
                prioridade TEXT NOT NULL,
                atividade TEXT NOT NULL,
                categoria TEXT NOT NULL,
                responsavel TEXT NOT NULL,
                prazo TEXT NOT NULL,
                status TEXT DEFAULT 'Pendente'
            )
        ''')
    cur = db.cursor()
    cur.execute('''
            CREATE TABLE IF NOT EXISTS chat (
                id INTEGER PRIMARY KEY SERIAL,
                remetente TEXT NOT NULL,
                mensagem TEXT NOT NULL,
                horario TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    cur = db.cursor()
    cur.execute('''
            CREATE TABLE IF NOT EXISTS melhorias (
                id INTEGER PRIMARY KEY SERIAL,
                titulo TEXT NOT NULL,
                descricao TEXT NOT NULL,
                autor TEXT NOT NULL,
                etapa TEXT DEFAULT 'Planejar (Plan)',
                status TEXT DEFAULT 'Em Andamento'
            )
        ''')
    cur = db.cursor()
    cur.execute('''
            CREATE TABLE IF NOT EXISTS estoque (
                id INTEGER PRIMARY KEY SERIAL,
                rua TEXT,
                prateleira TEXT,
                codigo_material TEXT,
                descricao TEXT,
                quantidade INTEGER
            )
        ''')
        
    cur.execute('SELECT COUNT(*) FROM usuarios')
    user_count = cur.fetchone()[0]
    if user_count == 0:
    cur.execute("INSERT INTO usuarios (nome, senha) VALUES ('Wanderson Fernandes', 'sua_senha_aqui')")
    db.commit()

    cur.close()
@app.route('/login', methods=['GET', 'POST'])
def login():
    erro = None
    db = get_db()
    if request.method == 'POST':
        nome = request.form.get('nome')
        senha = request.form.get('senha')
        user = db.execute("SELECT * FROM usuarios WHERE nome = ? AND senha = ?", (nome, senha)).fetchone()
        if user:
            session['usuario'] = user['nome']
            return redirect(url_for('index'))
        else:
            erro = "Usuário ou senha inválidos!"
    return render_template('login.html', erro=erro)

@app.route('/cadastro_usuario', methods=['GET', 'POST'])
def cadastro_usuario():
    erro = None
    db = get_db()
    if request.method == 'POST':
        nome = request.form.get('nome')
        senha = request.form.get('senha')
        try:
            db.execute("INSERT INTO usuarios (nome, senha) VALUES (?, ?)", (nome, senha))
            db.commit()
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            erro = "Este usuário já está cadastrado!"
    return render_template('cadastro_usuario.html', erro=erro)

@app.route('/logout')
def logout():
    session.pop('usuario', None)
    return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
def index():
    if 'usuario' not in session:
        return redirect(url_for('login'))
        
    db = get_db()
    usuario_atual = session['usuario']

    if request.method == 'POST':
        acao_chat = request.form.get('acao_chat')
        if acao_chat == 'enviar':
            mensagem = request.form.get('mensagem')
            if mensagem:
                db.execute("INSERT INTO chat (remetente, mensagem) VALUES (?, ?)", (usuario_atual, mensagem))
                db.commit()
            return redirect(url_for('index'))
        
        num_requisicao = request.form.get('num_requisicao')
        prioridade = request.form.get('prioridade')
        atividade = request.form.get('atividade')
        categoria = request.form.get('categoria')
        responsavel = request.form.get('responsavel')
        prazo = request.form.get('prazo')
        
        if atividade:
            db.execute('''
                INSERT INTO atividades (num_requisicao, prioridade, atividade, categoria, responsavel, prazo, status)
                VALUES (?, ?, ?, ?, ?, ?, 'Pendente')
            ''', (num_requisicao, prioridade, atividade, categoria, responsavel, prazo))
            db.commit()
            return redirect(url_for('index'))

    busca = request.args.get('q', '')
    if busca:
        atividades = db.execute("SELECT * FROM atividades WHERE (atividade LIKE ? OR categoria LIKE ? OR responsavel LIKE ? OR num_requisicao LIKE ?) AND status = 'Pendente' ORDER BY id DESC", (f'%{busca}%', f'%{busca}%', f'%{busca}%', f'%{busca}%')).fetchall()
    else:
        atividades = db.execute("SELECT * FROM atividades WHERE status = 'Pendente' ORDER BY id DESC").fetchall()

    mensagens_chat = db.execute("SELECT * FROM chat ORDER BY id DESC LIMIT 15").fetchall()

    # Contagens para os Cards do Topo
    total_req = db.execute("SELECT COUNT(*) FROM atividades WHERE categoria = 'Separação' AND status = 'Pendente'").fetchone()[0]
    
    inv_total_reg = db.execute("SELECT COUNT(*) FROM atividades WHERE categoria = 'Inventário'").fetchone()[0]
    inv_conc = db.execute("SELECT COUNT(*) FROM atividades WHERE categoria = 'Inventário' AND status = 'Concluído'").fetchone()[0]
    inv_total = 5 if inv_total_reg < 5 else inv_total_reg # Mantém a base 5 exigida
    
    exp_pend = db.execute("SELECT COUNT(*) FROM atividades WHERE categoria = 'Expedição' AND status = 'Pendente'").fetchone()[0]
    rec_pend = db.execute("SELECT COUNT(*) FROM atividades WHERE categoria = 'Recebimento' AND status = 'Pendente'").fetchone()[0]
    total_oco = db.execute("SELECT COUNT(*) FROM atividades WHERE prioridade = 'Alta' AND status = 'Pendente'").fetchone()[0]

    # Percentuais para os círculos à direita
    total_ativ = db.execute("SELECT COUNT(*) FROM atividades").fetchone()[0]
    total_conc = db.execute("SELECT COUNT(*) FROM atividades WHERE status = 'Concluído'").fetchone()[0]
    perc_atendidas = int((total_conc / total_ativ) * 100) if total_ativ > 0 else 0

    perc_inventario = int((inv_conc / inv_total) * 100) if inv_total > 0 else 0

    exp_total = db.execute("SELECT COUNT(*) FROM atividades WHERE categoria = 'Expedição'").fetchone()[0]
    exp_conc = db.execute("SELECT COUNT(*) FROM atividades WHERE categoria = 'Expedição' AND status = 'Concluído'").fetchone()[0]
    perc_expedicao = int((exp_conc / exp_total) * 100) if exp_total > 0 else 0

    usuarios = db.execute("SELECT * FROM usuarios").fetchall()

    return render_template('index.html', 
                           atividades=atividades, 
                           mensagens_chat=mensagens_chat,
                           total_req=total_req,
                           inv_conc=inv_conc,
                           inv_total=inv_total,
                           exp_pend=exp_pend,
                           rec_pend=rec_pend,
                           total_oco=total_oco,
                           perc_atendidas=perc_atendidas,
                           perc_inventario=perc_inventario,
                           perc_expedicao=perc_expedicao,
                           usuarios=usuarios,
                           usuario_atual=usuario_atual,
                           busca=busca)

@app.route('/modulo/<path:nome>', methods=['GET', 'POST'])
def modulo(nome):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    db = get_db()
    nome_limpo = nome.replace('%20', ' ')
    
    if 'Configurações' in nome_limpo:
        return render_template('configuracoes.html')
    elif 'Indicadores' in nome_limpo:
        total_geral = db.execute("SELECT COUNT(*) FROM atividades").fetchone()[0]
        concluidas = db.execute("SELECT COUNT(*) FROM atividades WHERE status = 'Concluído'").fetchone()[0]
        pendentes = db.execute("SELECT COUNT(*) FROM atividades WHERE status = 'Pendente'").fetchone()[0]
        return render_template('indicadores.html', total_geral=total_geral, concluidas=concluidas, pendentes=pendentes)
    elif 'PDCA' in nome_limpo or 'Melhorias' in nome_limpo:
        if request.method == 'POST':
            titulo = request.form.get('titulo')
            descricao = request.form.get('descricao')
            etapa = request.form.get('etapa')
            autor = session['usuario']
            if titulo:
                db.execute("INSERT INTO melhorias (titulo, descricao, autor, etapa) VALUES (?, ?, ?, ?)", (titulo, descricao, autor, etapa))
                db.commit()
            return redirect(url_for('modulo', nome='Melhorias / PDCA'))
        
        melhorias = db.execute("SELECT * FROM melhorias ORDER BY id DESC").fetchall()
        return render_template('pdca.html', melhorias=melhorias)
    elif 'Relatórios' in nome_limpo:
        itens = db.execute("SELECT * FROM atividades ORDER BY id DESC").fetchall()
        return render_template('relatorios.html', itens=itens)
    elif 'Estoque' in nome_limpo or 'Cadastros' in nome_limpo:
        if request.method == 'POST':
            acao = request.form.get('acao_estoque')
            if acao == 'cadastrar_manual':
                rua = request.form.get('rua')
                prateleira = request.form.get('prateleira')
                codigo = request.form.get('codigo_material')
                descricao = request.form.get('descricao')
                try:
                    qtd = int(request.form.get('quantidade', 0))
                except ValueError:
                    qtd = 0
                
                db.execute("INSERT INTO estoque (rua, prateleira, codigo_material, descricao, quantidade) VALUES (?, ?, ?, ?, ?)",
                           (rua, prateleira, codigo, descricao, qtd))
                db.commit()
                return redirect(url_for('modulo', nome='Estoque'))
                
            elif acao == 'importar_excel' and 'arquivo_excel' in request.files:
                file = request.files['arquivo_excel']
                if file and file.filename.endswith(('.xlsx', '.xls', '.csv')):
                    try:
                        if file.filename.endswith('.csv'):
                            df = pd.read_csv(file)
                        else:
                            df = pd.read_excel(file)
                        
                        for _, row in df.iterrows():
                            rua = str(row.get('Rua', ''))
                            prateleira = str(row.get('Prateleira', ''))
                            codigo = str(row.get('Codigo', row.get('Código', '')))
                            descricao = str(row.get('Descricao', row.get('Descrição', '')))
                            val_qtd = row.get('Quantidade', row.get('Qtd', 0))
                            qtd = int(float(val_qtd)) if pd.notna(val_qtd) else 0
                            
                            db.execute("INSERT INTO estoque (rua, prateleira, codigo_material, descricao, quantidade) VALUES (?, ?, ?, ?, ?)",
                                       (rua, prateleira, codigo, descricao, qtd))
                        db.commit()
                    except Exception as e:
                        print(f"Erro ao importar Excel: {e}")
                    return redirect(url_for('modulo', nome='Estoque'))

        usuarios = db.execute("SELECT * FROM usuarios").fetchall()
        estoque_itens = db.execute("SELECT * FROM estoque ORDER BY id DESC").fetchall()
        return render_template('estoque.html', usuarios=usuarios, estoque_itens=estoque_itens)
    
    categoria_map = {
        'Requisições': 'Separação',
        'Inventário': 'Inventário',
        'Expedição': 'Expedição',
        'Recebimento': 'Recebimento'
    }
    cat_filtro = categoria_map.get(nome_limpo)
    if cat_filtro:
        itens = db.execute("SELECT * FROM atividades WHERE categoria = ? ORDER BY id DESC", (cat_filtro,)).fetchall()
        return render_template('modulo_especifico.html', nome=nome_limpo, itens=itens)
        
    return render_template('modulo.html', nome=nome_limpo)

@app.route('/deletar/<int:id>')
def deletar(id):
    db = get_db()
    db.execute("UPDATE atividades SET status = 'Concluído' WHERE id = ?", (id,))
    db.commit()
    return redirect(request.referrer or url_for('index'))

@app.route('/deletar_estoque/<int:id>')
def deletar_estoque(id):
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM estoque WHERE id = %s", (id,))
    db.commit()
    cur.close()
    return redirect(url_for('modulo', nome='Estoque'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
