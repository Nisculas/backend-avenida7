import os
import sqlite3
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash



# Obrigatório: o nome da variável precisa ser exatamente 'app'
app = Flask(__name__)

@app.route("/")
def home():
    return "Olá, Mundo! O Flask está funcionando."

CORS(app, resources={r"/api/*": {"origins": "*"}})

if __name__ == "__main__":
    app.run(debug=True)

# O CORS é obrigatório para que o seu arquivo HTML consiga enviar dados para o Python
 

DATABASE = 'avenida7.db'

def obter_conexao():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def configurar_banco():
    conn = obter_conexao()
    cursor = conn.cursor()
    
    # 1. Tabela de usuários (Admin/Master e Operador)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            login TEXT UNIQUE NOT NULL,
            senha TEXT NOT NULL,
            perfil TEXT NOT NULL
        )
    ''')
    
    # 2. Tabela de Produtos cadastrados
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS produtos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE NOT NULL,
            nome TEXT NOT NULL,
            categoria TEXT,
            unidade TEXT NOT NULL,
            minimo INTEGER DEFAULT 0
        )
    ''')
    
    # 3. Tabela de Estoque Físico por Cidade (Numerários)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS estoque_cidades (
            produto_id INTEGER,
            cidade TEXT NOT NULL,
            quantidade INTEGER NOT NULL DEFAULT 0,
            valor_unitario REAL DEFAULT 0.0,
            PRIMARY KEY (produto_id, cidade),
            FOREIGN KEY(produto_id) REFERENCES produtos(id)
        )
    ''')
    
    # 4. Tabela de Histórico Geral (Auditoria)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS movimentacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL, -- 'Entrada', 'Saída', 'Transferência'
            data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            produto_id INTEGER,
            quantidade INTEGER NOT NULL,
            valor_unitario REAL,
            local TEXT NOT NULL, -- Cidade Origem
            destino TEXT,        -- Cidade Destino
            responsavel TEXT NOT NULL, -- Quem entregou / logistica
            recebedor TEXT,            -- Quem recebeu na obra
            obs TEXT,                  -- Motivo da obra
            status_entrega TEXT NOT NULL, -- 'Pendente' ou 'Entregue'
            FOREIGN KEY(produto_id) REFERENCES produtos(id)
        )
    ''')
    
    # Cria o usuário Master padrão se o banco for novo
    cursor.execute("SELECT * FROM usuarios WHERE login='admin'")
    if not cursor.fetchone():
        senha_crip = generate_password_hash('1234')
        cursor.execute("INSERT INTO usuarios (nome, login, senha, perfil) VALUES (?, ?, ?, ?)",
                       ('Diretor Master', 'admin', senha_crip, 'admin'))
        
    conn.commit()
    conn.close()

# --- ROTAS DA API ---

@app.route('/api/login', methods=['POST'])
def login():
    dados = request.json
    u = dados.get('login')
    s = dados.get('senha')
    
    conn = obter_conexao()
    user = conn.execute("SELECT * FROM usuarios WHERE login=?", (u,)).fetchone()
    conn.close()
    
    if user and check_password_hash(user['senha'], s):
        return jsonify({
            "sucesso": True,
            "usuario": {"nome": user['nome'], "perfil": user['perfil']}
        })
    return jsonify({"sucesso": False, "mensagem": "Usuário ou senha incorretos."}), 401

@app.route('/api/dashboard', methods=['GET'])
def dados_dashboard():
    conn = obter_conexao()
    
    # Valor total do estoque
    estoques = conn.execute("SELECT quantidade, valor_unitario FROM estoque_cidades").fetchall()
    valor_total = sum(e['quantidade'] * e['valor_unitario'] for e in estoques)
    
    # Total de produtos cadastrados
    total_prod = conn.execute("SELECT COUNT(*) as total FROM produtos").fetchone()['total']
    
    # Entregas pendentes
    pendentes = conn.execute("SELECT COUNT(*) as total FROM movimentacoes WHERE tipo='Saída' AND status_entrega='Pendente'").fetchone()['total']
    
    conn.close()
    return jsonify({
        "valor_total_estoque": valor_total,
        "total_produtos": total_prod,
        "entregas_pendentes": pendentes
    })

@app.route('/api/produtos', methods=['GET', 'POST'])
def gerenciar_produtos():
    conn = obter_conexao()
    if request.method == 'GET':
        prods = conn.execute("SELECT * FROM produtos").fetchall()
        conn.close()
        return jsonify([dict(p) for p in prods])
        
    elif request.method == 'POST':
        dados = request.json
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO produtos (codigo, nome, categoria, unidade, minimo) VALUES (?, ?, ?, ?, ?)",
                           (dados['codigo'], dados['nome'], dados['categoria'], dados['unidade'], int(dados['minimo'])))
            conn.commit()
            return jsonify({"sucesso": True})
        except sqlite3.IntegrityError:
            return jsonify({"sucesso": False, "mensagem": "Código já cadastrado!"}), 400
        finally:
            conn.close()

@app.route('/api/estoque', methods=['GET'])
def listar_estoque():
    conn = obter_conexao()
    produtos = conn.execute("SELECT * FROM produtos").fetchall()
    cidades = ['Barreirinhas', 'Tutoia', 'Paulino Neves']
    lista = []
    
    for p in produtos:
        for c in cidades:
            est = conn.execute("SELECT quantidade, valor_unitario FROM estoque_cidades WHERE produto_id=? AND cidade=?", (p['id'], c)).fetchone()
            qtd = est['quantidade'] if est else 0
            val = est['valor_unitario'] if est else 0.0
            lista.append({
                "produto_id": p['id'], "nome": p['nome'], "codigo": p['codigo'],
                "unidade": p['unidade'], "minimo": p['minimo'], "cidade": c, "quantidade": qtd, "valor_unitario": val
            })
    conn.close()
    return jsonify(lista)

@app.route('/api/entrada', methods=['POST'])
def entrada_material():
    dados = request.json
    p_id = int(dados['produto_id'])
    qtd = int(dados['quantidade'])
    val = float(dados['valor_unitario'])
    cidade = dados['cidade']
    resp = dados['responsavel']
    
    conn = obter_conexao()
    cursor = conn.cursor()
    
    est = cursor.execute("SELECT quantidade FROM estoque_cidades WHERE produto_id=? AND cidade=?", (p_id, cidade)).fetchone()
    if est:
        cursor.execute("UPDATE estoque_cidades SET quantidade=?, valor_unitario=? WHERE produto_id=? AND cidade=?", (est['quantidade'] + qtd, val, p_id, cidade))
    else:
        cursor.execute("INSERT INTO estoque_cidades (produto_id, cidade, quantidade, valor_unitario) VALUES (?, ?, ?, ?)", (p_id, cidade, qtd, val))
        
    cursor.execute("INSERT INTO movimentacoes (tipo, produto_id, quantidade, valor_unitario, local, destino, responsavel, status_entrega) VALUES (?,?,?,?,?,?,?,?)",
                   ('Entrada', p_id, qtd, val, cidade, cidade, resp, 'Entregue'))
    conn.commit()
    conn.close()
    return jsonify({"sucesso": True})

@app.route('/api/saida', methods=['POST'])
def saida_material():
    dados = request.json
    p_id = int(dados['produto_id'])
    qtd = int(dados['quantidade'])
    cidade = dados['cidade']
    resp = dados['responsavel']
    receb = dados['recebedor']
    motivo = dados['motivo']
    status = dados['status_entrega']
    
    conn = obter_conexao()
    cursor = conn.cursor()
    
    est = cursor.execute("SELECT quantidade FROM estoque_cidades WHERE produto_id=? AND cidade=?", (p_id, cidade)).fetchone()
    
    # TRAVA CONTRA ESTOQUE NEGATIVO REAL NO BANCO
    if not est or est['quantidade'] < qtd:
        conn.close()
        return jsonify({"sucesso": False, "mensagem": f"Erro! Saldo insuficiente em {cidade}."}), 400
        
    cursor.execute("UPDATE estoque_cidades SET quantidade=? WHERE produto_id=? AND cidade=?", (est['quantidade'] - qtd, p_id, cidade))
    cursor.execute("INSERT INTO movimentacoes (tipo, produto_id, quantidade, local, destino, responsavel, recebedor, obs, status_entrega) VALUES (?,?,?,?,?,?,?,?,?)",
                   ('Saída', p_id, qtd, cidade, cidade, resp, receb, motivo, status))
    conn.commit()
    conn.close()
    return jsonify({"sucesso": True})

@app.route('/api/historico', methods=['GET'])
def historico():
    conn = obter_conexao()
    movs = conn.execute('''
        SELECT m.*, p.nome as nome_produto, p.unidade FROM movimentacoes m 
        JOIN produtos p ON m.produto_id = p.id ORDER BY m.id DESC
    ''').fetchall()
    conn.close()
    return jsonify([dict(m) for m in movs])

@app.route('/api/marcar-entregue/<int:id>', methods=['PUT'])
def marcar_entregue(id):
    conn = obter_conexao()
    conn.execute("UPDATE movimentacoes SET status_entrega='Entregue' WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return jsonify({"sucesso": True})

@app.route('/api/desfazer/<int:id>', methods=['POST'])
def desfazer(id):
    conn = obter_conexao()
    cursor = conn.cursor()
    m = cursor.execute("SELECT * FROM movimentacoes WHERE id=?", (id,)).fetchone()
    if not m:
        conn.close()
        return jsonify({"sucesso": False, "mensagem": "Movimentação não encontrada."}), 404
        
    p_id, qtd, cidade, tipo = m['produto_id'], m['quantidade'], m['local'], m['tipo']
    
    if tipo == 'Entrada':
        est = cursor.execute("SELECT quantidade FROM estoque_cidades WHERE produto_id=? AND cidade=?", (p_id, cidade)).fetchone()
        if not est or est['quantidade'] < qtd:
            conn.close()
            return jsonify({"sucesso": False, "mensagem": "Estorno negado: O material já foi consumido."}), 400
        cursor.execute("UPDATE estoque_cidades SET quantidade=? WHERE produto_id=? AND cidade=?", (est['quantidade'] - qtd, p_id, cidade))
    elif tipo == 'Saída':
        est = cursor.execute("SELECT quantidade FROM estoque_cidades WHERE produto_id=? AND cidade=?", (p_id, cidade)).fetchone()
        qtd_atual = est['quantidade'] if est else 0
        cursor.execute("INSERT OR REPLACE INTO estoque_cidades (produto_id, cidade, quantidade, valor_unitario) VALUES (?, ?, ?, (SELECT valor_unitario FROM estoque_cidades WHERE produto_id=? LIMIT 1))", (p_id, cidade, qtd_atual + qtd, p_id))

    cursor.execute("DELETE FROM movimentacoes WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return jsonify({"sucesso": True})

if __name__ == '__main__':
    configurar_banco()
    app.run(debug=True, host='0.0.0.0', port=5000)

