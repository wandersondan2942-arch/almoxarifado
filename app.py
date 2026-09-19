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
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
                id SERIAL PRIMARY KEY,
                nome TEXT UNIQUE NOT NULL,
                senha TEXT NOT NULL
            )
        ''')
    cur = db.cursor()
    cur.execute('''
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
        ''')
    cur = db.cursor()
    cur.execute('''
            CREATE TABLE IF NOT EXISTS chat (
                id SERIAL PRIMARY KEY,
                remetente TEXT NOT NULL,
                mensagem TEXT NOT NULL,
                horario TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    cur = db.cursor()
    cur.execute('''
            CREATE TABLE IF NOT EXISTS melhorias (
                id SERIAL PRIMARY KEY,
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
                id SERIAL PRIMARY KEY,
                rua TEXT,
                prateleira TEXT,
                codigo_material TEXT,
                descricao TEXT,
                quantidade INTEGER
            )
        ''')
    cur.execute('SELECT COUNT(*) FROM usuarios')
    resultado = cur.fetchone()
    user_count = resultado['count'] if isinstance(resultado, dict) else resultado[0]
    
    if user_count == 0:
        cur.execute("INSERT INTO usuarios (nome, senha) VALUES ('Wanderson Fernandes', '1234')")
        db.commit()

    cur.close()
@app.route('/login', methods=['GET', 'POST'])
def login():
    erro = None
    db = get_db()
    cur = db.cursor()
    
    if request.method == 'POST':
        nome = request.form.get('nome')
        senha = request.form.get('senha')
        
        cur.execute("SELECT * FROM usuarios WHERE nome = %s AND senha = %s", (nome, senha))
        user = cur.fetchone()
        cur.close()
        
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
            cur = db.cursor()
            cur.execute("INSERT INTO usuarios (nome, senha) VALUES (%s, %s)", (nome, senha))
            db.commit()
            cur.close()
            return redirect(url_for('login'))
        except psycopg2.IntegrityError:
            erro = "Este utilizador já está cadastrado!"
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
    cur = db.cursor()

    if request.method == 'POST':
        acao_chat = request.form.get('acao_chat')
        
        if acao_chat == 'enviar':
            mensagem = request.form.get('mensagem')
            if mensagem:
                cur.execute("INSERT INTO chat (remetente, mensagem) VALUES (%s, %s)", (usuario_atual, mensagem))
                db.commit()
                cur.close()
                return redirect(url_for('index'))
        else:
            # Lógica para adicionar nova atividade (se vier deste formulário)
            num_requisicao = request.form.get('num_requisicao')
            prioridade = request.form.get('prioridade')
            atividade = request.form.get('atividade')
            categoria = request.form.get('categoria')
            responsavel = request.form.get('responsavel')
            prazo = request.form.get('prazo')
            
            if atividade:
                cur.execute('''
                    INSERT INTO atividades (num_requisicao, prioridade, atividade, categoria, responsavel, prazo, status)
                    VALUES (%s, %s, %s, %s, %s, %s, 'Pendente')
                ''', (num_requisicao, prioridade, atividade, categoria, responsavel, prazo))
                db.commit()
                cur.close()
                return redirect(url_for('index'))

    # Método GET (ou carregamento padrão da página)
    busca = request.args.get('q', '')
    if busca:
        cur.execute("SELECT * FROM atividades WHERE (atividade LIKE %s OR categoria LIKE %s OR responsavel LIKE %s OR num_requisicao LIKE %s)", 
                    (f'%{busca}%', f'%{busca}%', f'%{busca}%', f'%{busca}%'))
        atividades = cur.fetchall()
    else:
        cur.execute("SELECT * FROM atividades WHERE status = 'Pendente' ORDER BY id DESC")
        atividades = cur.fetchall()

    cur.execute("SELECT * FROM chat ORDER BY id DESC LIMIT 15")
    mensagens_chat = cur.fetchall()
    
    cur.close()
    return render_template('index.html', atividades=atividades, mensagens_chat=mensagens_chat)
@app.route('/modulo/<path:nome>', methods=['GET', 'POST'])
def modulo(nome):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    db = get_db()
    nome_limpo = nome.replace('%20', ' ')
    
    if 'Configurações' in nome_limpo:
        return render_template('configuracoes.html')
    elif 'Indicadores' in nome_limpo:
        db = get_db()
        cur = db.cursor()
        nome_limpo = nome.replace('%20', ' ')

    if 'Configurações' in nome_limpo:
        return render_template('configuracoes.html')
    elif 'Indicadores' in nome_limpo:
        cur.execute("SELECT COUNT(*) FROM atividades")
        total_geral = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM atividades WHERE status = 'Concluído'")
        concluidas = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM atividades WHERE status = 'Pendente'")
        pendentes = cur.fetchone()[0]
        
        return render_template('indicadores.html', total_geral=total_geral, concluidas=concluidas, pendentes=pendentes)
        return render_template('indicadores.html', total_geral=total_geral, concluidas=concluidas, pendentes=pendentes)
    elif 'PDCA' in nome_limpo or 'Melhorias' in nome_limpo:
        if request.method == 'POST':
            titulo = request.form.get('titulo')
            descricao = request.form.get('descricao')
            etapa = request.form.get('etapa')
            autor = session['usuario']
            if titulo:
                cur.execute("INSERT INTO melhorias (titulo, descricao, autor, etapa) VALUES (%s, %s, %s, %s, %s)", (titulo, descricao, autor, etapa))
                db.commit()
                cur.close()
            return redirect(url_for('modulo', nome='Melhorias / PDCA'))
        
        melhorias = cur.execute("SELECT * FROM melhorias ORDER BY id DESC").fetchall()
        return render_template('pdca.html', melhorias=melhorias)
    elif 'Relatórios' in nome_limpo:
        itens = cur.execute("SELECT * FROM atividades ORDER BY id DESC").fetchall()
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
                
                cur.execute("INSERT INTO estoque (rua, prateleira, codigo_material, descricao, quantidade) VALUES (%s,%s,%s,%s,%s)",
                           (rua, prateleira, codigo, descricao, qtd))
                db.commit()
                cur.close()
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
                            
                            cur.execute("INSERT INTO estoque (rua, prateleira, codigo_material, descricao, quantidade) VALUES (%s,%s,%s,%s,%s)",
                                       (rua, prateleira, codigo, descricao, qtd))
                        db.commit()
                        cur.close()
                    except Exception as e:
                        print(f"Erro ao importar Excel: {e}")
                    return redirect(url_for('modulo', nome='Estoque'))
                    cur.execute("SELECT * FROM usuarios")
                    usuarios = cur.fetchall()
                    cur.execute("SELECT * FROM estoque ORDER BY id DESC")
                    estoque_items = cur.fetchall()
        return render_template('estoque.html', usuarios=usuarios, estoque_itens=estoque_itens)
    
    categoria_map = {
        'Requisições': 'Separação',
        'Inventário': 'Inventário',
        'Expedição': 'Expedição',
        'Recebimento': 'Recebimento'
    }
    cat_filtro = categoria_map.get(nome_limpo)
    if cat_filro:
        cur.execute("SELECT * FROM atividades WHERE categoria = %s ORDER BY id DESC", (cat_filtro,))
        itens = cur.fetchall()
        
    return render_template('modulo.html', nome=nome_limpo)
    cur.execute("SELECT COUNT(*) FROM atividades WHERE categoria = 'Separação' AND status = 'Pendente'")
    total_req = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM atividades WHERE categoria = 'Inventário'")
    inv_total_reg = cur.fetchone()[0]

    
    cur.execute("SELECT COUNT(*) FROM atividades WHERE categoria = 'Inventário' AND status = 'Concluído'")
    inv_conc = cur.fetchone()[0]
    
    # Se tiveres outras categorias (Expedição, Recebimentos, etc.), podes calcular aqui também:
    cur.execute("SELECT COUNT(*) FROM atividades WHERE categoria = 'Expedição' AND status = 'Em andamento'")
    exp_andamento = cur.fetchone()[0]

    cur.execute("SELECT * FROM chat ORDER BY id DESC LIMIT 15")
    mensagens_chat = cur.fetchall()
    
    cur.close()
    
    # Passa todas estas variáveis para o HTML:
    return render_template(
        'index.html', 
        atividades=atividades, 
        mensagens_chat=mensagens_chat,
        total_req=total_req,
        inv_conc=inv_conc,
        inv_total=inv_total_reg,
        exp_andamento=exp_andamento
    )

@app.route('/deletar/<int:id>')
def deletar(id):
    db = get_db()
    cur.execute("UPDATE atividades SET status = 'Concluído' WHERE id = %s,", (id,))
    db.commit()
    cur.close()
    return redirect(request.referrer or url_for('index'))

@app.route('/deletar_estoque/<int:id>')
def deletar_estoque(id):
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM estoque WHERE id = %s", (id,))
    db.commit()
    cur.close()
    return redirect(url_for('modulo', nome='Estoque'))

with app.app_context():
    init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
