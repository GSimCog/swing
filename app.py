"""
Quiz App Backend (Flask)

- Inicialização do app Flask, banco de dados, autenticação e principais dependências.
- Define modelos de dados, rotas de quiz, login, administração e histórico.
- Integração com fontes externas (Wikidata/DBpedia) e IA (OpenAI) para preenchimento automático de dados faltantes.
- Implementa lógica de confiança da IA (ai_confidence_threshold): respostas da IA com confiança >= threshold são propagadas diretamente; abaixo disso, vão para revisão manual (ReportedQuestions).
- Diferencia fluxos para usuários comuns e administradores, com painel admin, histórico e ações batch.
- Todas as docstrings seguem padrão Google para facilitar manutenção e colaboração.
"""

import os
import json
import random
import configparser
import requests
from flask import Flask, render_template, redirect, url_for, request, session, flash, jsonify
import sys, io
from data_update import update_new_country_data_from_semanticdatabase_in_countryQuiz, update_country_blanks_from_semanticdatabase_with_ai, update_reported_questions_with_ai, update_countryQuiz_from_approved_questions, update_countryQuiz_from_approved_blanks
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import sessionmaker, scoped_session
from flask_login import UserMixin, LoginManager, login_user, login_required, logout_user, current_user
from datetime import datetime
from werkzeug.security import check_password_hash, generate_password_hash

# Tipos de perguntas possíveis para o quiz
OPTIONS = [
    "flag_label",
    "capital_label",
    "official_Language_label",
    "currency_label",
    "population",
    "continent_label",
    "highest_point_label"
]


config = configparser.ConfigParser()
config.read('quiz.config')
DBPEDIA_SPARQL_QUERY = config.get('settings', 'dbpedia_sparql_query')
WIKIDATA_SPARQL_QUERY = config.get('settings', 'wikidata_sparql_query')

# Carregar configuração do banco de dados
database = config.get('settings', 'database', fallback='WIKIDATA').upper()

# Criação do aplicativo Flask
app = Flask(__name__)

# Configuração da chave secreta do aplicativo
app.config['SECRET_KEY'] = os.urandom(24)

# --- HISTÓRICO ADMINISTRATIVO ---
from math import ceil

@app.route('/admin/history')
@login_required
def admin_history():
    if current_user.username != 'admin':
        return redirect(url_for('home'))
    # Paginação
    try:
        page = int(request.args.get('page', 1))
    except Exception:
        page = 1
    per_page = 25
    max_entries = 150
    # Buscar as 150 últimas operações
    entries = CountryQuizUpdatesHistory.query.order_by(CountryQuizUpdatesHistory.timestamp.desc()).limit(max_entries).all()
    total_entries = len(entries)
    total_pages = ceil(total_entries / per_page)
    start = (page - 1) * per_page
    end = start + per_page
    history_entries = entries[start:end]
    return render_template(
        'admin_history.html',
        history_entries=history_entries,
        page=page,
        total_pages=total_pages
    )

# Configuração da URI do banco de dados
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///quiz.db?check_same_thread=False'

# Inicialização do banco de dados SQLAlchemy
db = SQLAlchemy(app)

# Criação de uma fábrica de sessões para o banco de dados
session_factory = sessionmaker(bind=db.engine)

# Criação de uma sessão para o banco de dados
Session = scoped_session(session_factory)

"""
Modelos de dados para o banco de dados SQLAlchemy.
"""

class User(UserMixin, db.Model):
    """
    Modelo de usuário do sistema.

    Atributos:
        id (int): Identificador único do usuário.
        username (str): Nome de usuário.
        password (str): Senha do usuário (hash).
        email (str): E-mail do usuário.
        score (int): Pontuação acumulada.
        timestamp (datetime): Data/hora de criação ou atualização.
    """
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    score = db.Column(db.Integer, default=0)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

class ReportedQuestion(db.Model):
    """
    Modelo para perguntas reportadas ou sugestões da IA para revisão manual.

    Atributos:
        id (int): Identificador da questão reportada/sugestão.
        user_id (int): ID do usuário que reportou ou 'ai' para sugestões automáticas.
        user (User): Usuário associado.
        question (str): Pergunta reportada ou campo sugerido.
        country (str): País relacionado.
        correct_answer (str): Resposta correta conhecida (se houver).
        value_from_ai (str): Valor sugerido pela IA.
        approved (bool): Se a sugestão foi aprovada manualmente pelo admin.
        value_updated (bool): Se a sugestão foi propagada ao quiz após aprovação manual.
        timestamp (datetime): Data/hora do registro.
    Observação:
        Entradas são criadas quando a confiança da IA é menor que ai_confidence_threshold.
    """
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref=db.backref('reported_questions', lazy=True))
    question = db.Column(db.String, nullable=False)
    country = db.Column(db.String, nullable=False)
    correct_answer = db.Column(db.String, nullable=False)
    value_from_ai = db.Column(db.String(255), nullable=False)
    approved = db.Column(db.Boolean, nullable=False, default=False)
    value_updated = db.Column(db.Boolean, nullable=False, default=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

class CountryQuiz(db.Model):
    """
    Modelo para dados de quiz de países.

    Atributos:
        id (int): Identificador do quiz.
        country_label (str): Nome/label do país.
        data (str): Dados do país em JSON.
        timestamp (datetime): Data/hora de criação ou atualização.
    """
    id = db.Column(db.Integer, primary_key=True)
    country_label = db.Column(db.String(255), unique=True, nullable=False)
    data = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<CountryQuiz {self.country_label}>'

class CountryFromSemanticDatabase(db.Model):
    """
    Modelo para armazenar dados de países vindos de bases semânticas externas.

    Atributos:
        id (int): Identificador do país.
        country_label (str): Nome/label do país.
        data (str): Dados do país em JSON.
        timestamp (datetime): Data/hora de criação ou atualização.
    """
    id = db.Column(db.Integer, primary_key=True)
    country_label = db.Column(db.String(255), unique=True, nullable=False)
    data = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

class CountryBlanksFromSemanticDatabase(db.Model):
    """
    Modelo para gerenciar lacunas (blanks) nos dados de países, preenchidas via IA ou manualmente.

    Atributos:
        id (int): Identificador da lacuna.
        country_label (str): Nome/label do país.
        key (str): Campo da lacuna.
        current_value (str): Valor atual do campo.
        value_from_ai (str): Valor sugerido pela IA.
        ai_confidence (int): Confiança da IA (0-100). Se >= ai_confidence_threshold, pode ser aprovado automaticamente.
        approved (bool): Se o valor foi aprovado (automaticamente pela IA ou manualmente pelo admin).
        value_updated (bool): Se o valor aprovado já foi propagado ao CountryQuiz.
        timestamp (datetime): Data/hora da última atualização.
    Observação:
        Fluxo automático/manual depende do threshold de confiança da IA.
    """
    id = db.Column(db.Integer, primary_key=True)
    country_label = db.Column(db.String(255), nullable=False)
    key = db.Column(db.String(255), nullable=False)
    current_value = db.Column(db.String(255), nullable=True)
    value_from_ai = db.Column(db.String(255), nullable=True)
    ai_confidence = db.Column(db.Integer, nullable=True)
    approved = db.Column(db.Boolean, default=False)
    value_updated = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class CountryQuizUpdatesHistory(db.Model):
    """
    Modelo para registrar o histórico de atualizações dos quizzes de países.

    Atributos:
        id (int): Identificador da atualização.
        function_name (str): Nome da função que realizou a atualização.
        country_label (str): Nome/label do país.
        key (str): Campo atualizado.
        old_data (str): Valor antigo.
        new_data (str): Novo valor.
        ai_confidence (int): Confiança da IA (se aplicável).
        timestamp (datetime): Data/hora da atualização.
    """
    id = db.Column(db.Integer, primary_key=True)
    function_name = db.Column(db.String(255), nullable=False)
    country_label = db.Column(db.String(255), nullable=False)
    key = db.Column(db.String(255), nullable=False)
    old_data = db.Column(db.Text, nullable=False)
    new_data = db.Column(db.Text, nullable=False)
    ai_confidence = db.Column(db.Integer, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# Criação das tabelas do banco de dados
with app.app_context():
    db.create_all()

@app.route('/admin/tools')
@login_required
def admin_tools():
    """
    Rota para exibição das ferramentas administrativas do quiz.
    Apenas usuários autenticados como admin podem acessar.
    Exibe painel para histórico, aprovação de sugestões, atualizações batch e logs em tempo real.
    """
    if not current_user.is_authenticated or current_user.username != 'admin':
        return redirect(url_for('home'))
    return render_template('admin_tools.html')

@app.route('/admin/run_update/<action>', methods=['POST'])
@login_required
def run_update(action):
    print('[DEBUG] Iniciando run_update')
    if not current_user.is_authenticated or current_user.username != 'admin':
        print('[DEBUG] Usuário não autorizado')
        return jsonify({'output': 'Acesso negado.'}), 403
    log = io.StringIO()
    sys_stdout = sys.stdout
    output = ''
    try:
        print(f'[DEBUG] Redirecionando sys.stdout para log')
        sys.stdout = log
        try:
            print(f'[DEBUG] Executando ação: {action}')
            if action == 'update_new_country_data':
                update_new_country_data_from_semanticdatabase_in_countryQuiz()
            elif action == 'update_blanks_with_ai':
                update_country_blanks_from_semanticdatabase_with_ai()
            elif action == 'update_reported_questions_with_ai':
                update_reported_questions_with_ai()
            elif action == 'update_approved_questions':
                update_countryQuiz_from_approved_questions()
            elif action == 'update_approved_blanks':
                update_countryQuiz_from_approved_blanks()
            elif action == 'reload_quiz_data':
                try:
                    request_or_load_country_data()
                    print('CountryQuiz data reloaded successfully.')
                except Exception as e:
                    print(f'Error reloading CountryQuiz data: {e}')
            else:
                print('Ação desconhecida.')
            print(f'[DEBUG] Execução da ação {action} finalizada')
        except Exception as e:
            print(f'[DEBUG] Erro durante execução da ação: {e}')
        output = log.getvalue()
        print(f'[DEBUG] Conteúdo do log capturado:\n{output}')
    finally:
        sys.stdout = sys_stdout
        print('[DEBUG] sys.stdout restaurado')
    print('[DEBUG] Retornando resposta para o frontend')
    return jsonify({'output': output})

# Inicialização do gerenciador de login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    """
    Carrega um usuário pelo ID para integração com Flask-Login.

    Args:
        user_id (int): ID do usuário.

    Returns:
        User: Usuário carregado do banco de dados.
    """
    return User.query.get(int(user_id))


def unify_country_data(data):
    """
    Unifica dados de entrada para um país, combinando entradas duplicadas ou fragmentadas.
    Usado para normalizar dados vindos de múltiplas fontes externas.

    Args:
        data (list of dict): Lista de dicionários contendo dados de países.

    Returns:
        list: Lista de dicionários com dados unificados por país.
    """
    unified_data = {}
    for entry in data:
        country_label = entry['country_label']['value']
        if country_label not in unified_data:
            unified_data[country_label] = entry.copy()  # Use uma cópia para evitar a modificação do original
        else:
            for key in entry:
                if key == 'country_label':
                    continue
                new_value = entry[key]['value']
                if key in unified_data[country_label]:
                    existing_value = unified_data[country_label][key]['value']
                    # Unifica todos os valores já existentes, separando por vírgula e ' or '
                    # Junta tudo em uma lista, remove duplicatas e monta de volta no formato original
                    sep_candidates = [', ', ' or ']
                    temp = [existing_value]
                    for sep in sep_candidates:
                        temp = sum([v.split(sep) for v in temp], [])
                    temp = [v.strip() for v in temp]
                    if new_value not in temp:
                        temp.append(new_value)
                    # Remove duplicatas preservando ordem
                    seen = set()
                    unique_values = []
                    for v in temp:
                        if v not in seen and v != '':
                            seen.add(v)
                            unique_values.append(v)
                    if len(unique_values) > 1:
                        unified_data[country_label][key]['value'] = " or ".join(unique_values)
                    else:
                        unified_data[country_label][key]['value'] = unique_values[0] if unique_values else ''
                else:
                    unified_data[country_label][key] = {'value': new_value}
    return list(unified_data.values())

def request_or_load_country_data():
    """
    Carrega dados de países do banco de dados ou os solicita de fontes externas se o banco estiver vazio.

    Returns:
        list: Lista de dicionários contendo dados de países carregados ou solicitados.
    """
    if CountryQuiz.query.first() is None:
        data = get_country_data()
        for country in data:
            new_country_quiz = CountryQuiz(country_label=country['country_label']['value'], data=json.dumps(country), timestamp=datetime.utcnow())
            new_country_semanticdatabase = CountryFromSemanticDatabase(country_label=country['country_label']['value'], data=json.dumps(country), timestamp=datetime.utcnow())
            db.session.add(new_country_quiz)
            db.session.add(new_country_semanticdatabase)
        db.session.commit()
    stored_countries = CountryQuiz.query.all()
    country_data = [json.loads(country.data) for country in stored_countries]
    return country_data

def join_data(data1, data2):
    """
    Combina dois conjuntos de dados de países, atualizando o primeiro com informações do segundo.

    Args:
        data1 (list): Lista principal de dados de países a ser atualizada.
        data2 (list): Lista secundária de dados de países para atualização.

    Returns:
        list: Lista atualizada de dados de países.
    """
    data1_map = {item['country_label']['value']: item for item in data1 if 'country_label' in item}
    combined_count = 0  # Contador para itens combinados ou atualizados (no caso de vazio em data1)
    for item2 in data2:
        country2 = item2.get('country_label', {}).get('value', '')
        if country2 in data1_map:
            for key in ['capital_label', 'currency_label', 'population', 'flag_image', 'anthem_audio', 'official_Language_label', 'continent_label', 'highest_point_label']:
                if key in item2 and item2[key].get('value', '') and (key not in data1_map[country2] or not data1_map[country2][key].get('value', '')):
                    data1_map[country2][key] = item2[key]
                    combined_count += 1
        else:
            data1.append(item2)
            combined_count += 1
    print(f"Number of items from 'data2' combined or updated: {combined_count}")
    return data1

def format_population(number):
    """
    Formata números grandes de população para um formato mais legível com sufixos 'M' ou 'K'.

    Args:
        number (int): Número da população a ser formatado.

    Returns:
        str: População formatada como string.
    """
    if number >= 1000000:
        return f"{number/1000000:.3f}M"
    elif number >= 1000:
        return f"{number/1000:.3f}K"
    else:
        return str(number)

def get_country_data():
    """
    Recupera dados de países usando consultas SPARQL de fontes externas como DBpedia e Wikidata.

    Returns:
        list: Lista de dicionários contendo dados de países.
    """
    query_dbpedia = DBPEDIA_SPARQL_QUERY
    query_wikidata = WIKIDATA_SPARQL_QUERY
    if database == "DBPEDIA":
        url = "https://dbpedia.org/sparql"
        query = query_dbpedia
    if database == "WIKIDATA":
        url = "https://query.wikidata.org/sparql"
        query = query_wikidata
    if database == "BOTH":
        url = "https://query.wikidata.org/sparql"
        query = query_wikidata
    response = requests.get(url, params={"query": query, "format": "json"})
    data = response.json()["results"]["bindings"]
    if database == "BOTH":
        url = "https://dbpedia.org/sparql"
        query = query_dbpedia
        response2 = requests.get(url, params={"query": query, "format": "json"})
        data2 = response2.json()["results"]["bindings"]
        combined_data = join_data(data, data2)
        data = combined_data
    for country in data:
        if 'flag_image' in country:
            if not country['flag_image']['value']:
                country['flag_image']['value'] = "./static/images/no_flag.png"
        else:
            country['flag_image'] = {'value': './static/images/no_flag.png'}
        if 'currency_label' in country:
            if not country['currency_label']['value']:
                country['currency_label']['value'] = ''
        else:
            country['currency_label'] = {'value': ''}
        if 'population' in country:
            if not country['population']['value']:
                country['population']['value'] = ''
        else:
            country['population'] = {'value': ''}
        if 'capital_label' in country:
            if not country['capital_label']['value']:
                country['capital_label']['value'] = ''
        else:
            country['capital_label'] = {'value': ''}
        if 'anthem_audio' in country:
            if not country['anthem_audio']['value']:
                country['anthem_audio']['value'] = "no_audio"
        else:
            country['anthem_audio'] = {'value': 'no_audio'}
        if 'official_Language_label' in country:
            if not country['official_Language_label']['value']:
                country['official_Language_label']['value'] = ''
        else:
            country['official_Language_label'] = {'value': ''}
        if 'continent_label' in country:
            if not country['continent_label']['value']:
                country['continent_label']['value'] = ''
        else:
            country['continent_label'] = {'value': ''}
        if 'highest_point_label' in country:
            if not country['highest_point_label']['value']:
                country['highest_point_label']['value'] = ''
        else:
            country['highest_point_label'] = {'value': ''}
    unified_country_data = unify_country_data(data)
    country_data = unified_country_data
    counters = {
        'flag_image': 0,
        'currency_label': 0,
        'population': 0,
        'capital_label': 0,
        'anthem_audio': 0,
        'official_Language_label': 0,
        'continent_label': 0,
        'highest_point_label': 0,
    }
    countries_found = set()
    duplicates_count = 0
    for country in country_data:
        country_name = country.get('country_label', {}).get('value', '')
        if country_name in countries_found:
            duplicates_count += 1
        else:
            countries_found.add(country_name)
        for key in counters.keys():
            if key == 'flag_image':
                if key in country and (not country[key]['value'] or country[key]['value'] == "./static/images/no_flag.png"):
                    existing_entry = CountryBlanksFromSemanticDatabase.query.filter_by(country_label=country_name, key=key, current_value=country[key]['value']).first()
                    if not existing_entry:
                      review = CountryBlanksFromSemanticDatabase(country_label=country_name, key=key, current_value=country[key]['value'], value_from_ai="", approved=False, value_updated=False, timestamp=datetime.utcnow())
                      db.session.add(review)
                      counters[key] += 1
            elif key == 'anthem_audio':
                if key in country and (not country[key]['value'] or country[key]['value'] == "no_audio"):
                    existing_entry = CountryBlanksFromSemanticDatabase.query.filter_by(country_label=country_name, key=key, current_value=country[key]['value']).first()
                    if not existing_entry:                    
                      review = CountryBlanksFromSemanticDatabase(country_label=country_name, key=key, current_value=country[key]['value'], value_from_ai="", approved=False, value_updated=False, timestamp=datetime.utcnow())
                      db.session.add(review)
                      counters[key] += 1
            else:
                if key in country and not country[key]['value']:
                    existing_entry = CountryBlanksFromSemanticDatabase.query.filter_by(country_label=country_name, key=key, current_value=country[key]['value']).first()
                    if not existing_entry:                    
                      review = CountryBlanksFromSemanticDatabase(country_label=country_name, key=key, current_value=country[key]['value'], value_from_ai="", approved=False, value_updated=False, timestamp=datetime.utcnow())
                      db.session.add(review)
                      counters[key] += 1
            db.session.commit()
    return country_data
    
def select_country_data(all_data_int, kind_of_questions_int):
    """
    Seleciona dados específicos de um conjunto maior de dados de países para uso em quizzes.

    Args:
        all_data_int (list): Lista completa de dados de países.
        kind_of_questions_int (str): Tipo de questão para a qual os dados são selecionados.

    Returns:
        list: Lista de tuplas contendo dados específicos selecionados para o quiz.
    """
    def extract_url(value):
        if isinstance(value, str) and '|' in value:
            return value.split('|')[0]
        return value
    country_data_int = [
        (entry["country_label"]["value"],
         entry[kind_of_questions_int]["value"],
         extract_url(entry["flag_image"]["value"]),
         extract_url(entry["anthem_audio"]["value"]))
        for entry in all_data_int
    ]
    return country_data_int

all_data = request_or_load_country_data()

def get_unique_alternatives(country_data, correct_answer, kind_of_questions, n_alternatives=4):
    """
    Retorna uma lista de alternativas únicas para a questão, incluindo a resposta correta e alternativas erradas distintas.
    As alternativas são embaralhadas e não repetem a correta.
    """
    # Extrai todas as possíveis respostas únicas (ignorando vazios)
    all_options = list(set([item[1] for item in country_data if item[1] != '']))
    # Remove a correta
    wrong_options = [opt for opt in all_options if opt != correct_answer]
    # Sorteia alternativas erradas
    sampled_wrongs = random.sample(wrong_options, min(n_alternatives-1, len(wrong_options)))
    # Junta a correta e embaralha
    final_options = sampled_wrongs + [correct_answer]
    random.shuffle(final_options)
    return final_options

def generate_quiz():
    """
    Gera um conjunto de perguntas para um quiz a partir de dados de países.

    - Garante 4 alternativas únicas por pergunta (1 correta + 3 erradas).
    - Não repete perguntas já acertadas na sessão (session["answered_correctly"]).
    - Limita tentativas para evitar loops infinitos.

    Returns:
        list: Lista de perguntas geradas para o quiz.
    """
    quiz = []
    already_answered = set(session.get("answered_correctly", []))
    attempts = 0
    max_attempts = 100
    while len(quiz) < 6 and attempts < max_attempts:
        if database == "DBPEDIA":
            kind_of_questions = OPTIONS[random.randint(0, 4)]
        else:
            kind_of_questions = OPTIONS[random.randint(0, 6)]
        country_data = select_country_data(all_data, kind_of_questions)
        # Filtra perguntas já acertadas nesta sessão e evita repetição na mesma rodada
        filtered_data = [q for q in country_data if (q[0], kind_of_questions) not in already_answered and (q, kind_of_questions) not in [(item[0], item[1]) for item in quiz]]
        if not filtered_data:
            attempts += 1
            continue
        question = random.choice(filtered_data)
        # Filtros de validade para garantir perguntas válidas
        if kind_of_questions == "flag_label":
            # Filtro para ignorar países com bandeira padrão
            filtered_data = [q for q in filtered_data if q[2] != "./static/images/no_flag.png"]
            if not filtered_data:
                attempts += 1
                continue
            question = random.choice(filtered_data)
        elif kind_of_questions in ["currency_label", "population", "capital_label", "official_Language_label", "continent_label", "highest_point_label"]:
            while (question[1] == '') or ((question, kind_of_questions) in quiz):
                question = random.choice(filtered_data)
        # Geração das alternativas únicas
        alternatives = get_unique_alternatives(country_data, question[1], kind_of_questions, n_alternatives=4)
        quiz.append((question, kind_of_questions, alternatives))
        attempts += 1
    return quiz

@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    Rota para login de usuários.

    Se o usuário estiver autenticado, redireciona para a rota de quiz.
    Se o método for POST, verifica as credenciais do usuário e, se válidas, loga o usuário e redireciona para a rota de quiz.
    Se o método for GET, exibe a página de login.

    Returns:
        redirect: Redireciona para a rota de quiz se o usuário estiver autenticado ou se as credenciais forem válidas.
        render_template: Exibe a página de login se o método for GET.
    """
    if current_user.is_authenticated:
        if "quiz_data" not in session or not session["quiz_data"]:
            session["quiz_data"] = generate_quiz()
        if "score" not in session or not session["score"]:
            session["score"] = 0
        if "before_question_text" not in session or not session["before_question_text"]:
            session["before_question_text"] = ""
        if "before_country" not in session or not session["before_country"]:
            session["before_country"] = ""
        if "user_answers" not in session or not session["user_answers"]:
            session["user_answers"] = []
        return redirect(url_for('quiz'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            login_user(user)
            if "quiz_data" not in session or not session["quiz_data"]:
                session["quiz_data"] = generate_quiz()
            if "score" not in session or not session["score"]:
                session["score"] = 0
            if "before_question_text" not in session or not session["before_question_text"]:
                session["before_question_text"] = ""
            if "before_country" not in session or not session["before_country"]:
                session["before_country"] = ""            
            if "user_answers" not in session or not session["user_answers"]:
                session["user_answers"] = []
            return redirect(url_for('quiz'))
        flash('Invalid username or password')
    top_scores = User.query.filter(~User.username.in_(['admin', 'ai'])).order_by(User.score.desc()).limit(10).all()
    return render_template('login.html', top_scores=top_scores)

@app.route('/register', methods=['GET', 'POST'])
def register():
    """
    Rota para registro de novos usuários.

    Se o método for POST, verifica as credenciais do usuário e, se válidas, cria um novo usuário e redireciona para a rota de login.
    Se o método for GET, exibe a página de registro.

    Returns:
        redirect: Redireciona para a rota de login se as credenciais forem válidas.
        render_template: Exibe a página de registro se o método for GET.
    """
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email')  # Email do formulário
        user_by_email = User.query.filter_by(email=email).first()
        if user_by_email:
            flash('Email already exists')
            return redirect(url_for('register'))
        user = User.query.filter_by(username=username).first()
        if not user:
            new_user = User(username=username,
                            password=generate_password_hash(password),
                            email=email,
                            timestamp=datetime.utcnow())
            db.session.add(new_user)
            db.session.commit()
            flash('Registration successful, please log in')
            return redirect(url_for('login'))
        flash('Username already exists')
    return render_template('register.html')

@app.route('/logout')
def logout():
    """
    Rota para logout de usuários.

    Remove as variáveis de sessão e redireciona para a rota de login.

    Returns:
        redirect: Redireciona para a rota de login.
    """
    session.pop("quiz_data", [])
    session.pop('user_id', None)
    logout_user()
    return redirect(url_for('login'))

@app.route("/home")
def home():
    """
    Rota para a página inicial.

    Se o usuário estiver autenticado, redireciona para a rota de quiz.
    Se o usuário não estiver autenticado, redireciona para a rota de login.

    Returns:
        redirect: Redireciona para a rota de quiz se o usuário estiver autenticado ou para a rota de login se não estiver.
    """
    if current_user.is_authenticated:
        if "quiz_data" not in session or not session["quiz_data"]:
            session["quiz_data"] = generate_quiz()
        if "score" not in session or not session["score"]:
            session["score"] = 0
        if "before_question_text" not in session or not session["before_question_text"]:
            session["before_question_text"] = ""
        if "before_country" not in session or not session["before_country"]:
            session["before_country"] = ""
        if "user_answers" not in session or not session["user_answers"]:
            session["user_answers"] = []
        return redirect(url_for("quiz"))
    return redirect(url_for("login"))

@app.route("/", methods=["GET", "POST"])
@login_required
def quiz():
    """
    Rota para o quiz.

    Se o método for POST, verifica a resposta do usuário e atualiza a pontuação.
    Se o método for GET, exibe a página do quiz.

    Returns:
        redirect: Redireciona para a rota de resultado se o quiz estiver completo.
        render_template: Exibe a página do quiz se o método for GET.
    """
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    else:
        if "quiz_data" not in session or not session["quiz_data"]:
            session["quiz_data"] = generate_quiz()
        if "score" not in session or not session["score"]:
            session["score"] = 0
        if "before_question_text" not in session or not session["before_question_text"]:
            session["before_question_text"] = ""
        if "before_country" not in session or not session["before_country"]:
            session["before_country"] = ""
        if "user_answers" not in session or not session["user_answers"]:
            session["user_answers"] = []
    quiz_data = session["quiz_data"]
    score = session["score"]
    before_question_text = session["before_question_text"]
    before_country = session["before_country"]
    user_answers = session["user_answers"]
    if request.method == "POST":
        user_answer = request.form.get("answer")
        if (not user_answer and request.form.get("wrong_answers")):
            user_answer = "None"
        ca = quiz_data[0][0]
        if "flag" in before_question_text.lower():
            correct_value = ca[2]
        else:
            correct_value = ca[1]
        user_answers.append(
            (before_question_text, user_answer, ca[1]))
        if user_answer == ca[1]:
            score += 1
        if request.form.get("wrong_answers"):
            reported_question = ReportedQuestion(
                user_id=current_user.id, question=before_question_text, country=before_country, correct_answer=correct_value, value_from_ai="", approved=False, value_updated=False, timestamp=datetime.utcnow())
            db.session.add(reported_question)
            db.session.commit()
        quiz_data.pop(0)
        if not quiz_data:
            session["quiz_data"] = quiz_data
            session["score"] = score
            session["before_question_text"] = before_question_text
            session["before_country"] = before_country
            session["user_answers"] = user_answers
            return redirect(url_for("result"))
    if not quiz_data:
        quiz_data = generate_quiz()
    def extract_url(value):
        """
        Extrai apenas o primeiro conteúdo antes de '|' e antes de ' or '.
        Args:
            value (str): String contendo uma ou mais URLs/valores.
        Returns:
            str: Apenas o primeiro valor extraído.
        """
        if isinstance(value, str):
            if '|' in value:
                value = value.split('|')[0]
            if ' or ' in value:
                value = value.split(' or ')[0]
        return value

    (question, kind_of_questions, alternatives) = quiz_data[0]
    country_label, correct_answer, flag_image_url, anthem_audio = question
    # Corrige flag_image_url e anthem_audio para extrair apenas a primeira URL
    flag_image_url = extract_url(flag_image_url)
    anthem_audio_url = extract_url(anthem_audio)
    if anthem_audio_url == "no_audio":
        anthem_audio = ""
    elif anthem_audio_url:
        anthem_audio = f"<audio controls='controls'><source src='{anthem_audio_url}' type='audio/ogg' />seu navegador não suporta HTML5</audio>"
    else:
        anthem_audio = ""
    # Agora as opções já estão em alternatives (lista de 4 alternativas únicas)
    options = alternatives
    if kind_of_questions == "population" and all(" or " not in option for option in options):
        options_with_format = [{"value": option, "display": format_population(int(option))} for option in options]
    else:
        options_with_format = [{"value": option, "display": option} for option in options]
    random.shuffle(options_with_format)
    if kind_of_questions == "capital_label":
        question_text = f"What is the capital of (the) {country_label}?"
    elif kind_of_questions == "currency_label":
        question_text = f"What is the currency of (the) {country_label}?"
    elif kind_of_questions == "population":
        question_text = f"What is the population of (the) {country_label}?"
    elif kind_of_questions == "official_Language_label":
        question_text = f"What is the official language of (the) {country_label}?"
    elif kind_of_questions == "continent_label":
        question_text = f"Which continent does (the) {country_label} belong to?"
    elif kind_of_questions == "highest_point_label":
        question_text = f"What is the highest point in (the) {country_label}?"
    else:
        question_text = f"Which country does this flag belong to?"
    before_question_text = question_text
    before_country = question
    # Atualiza perguntas acertadas na sessão
    if "answered_correctly" not in session:
        session["answered_correctly"] = []
    # Se o usuário acertou a questão anterior, registra
    if request.method == "POST":
        user_answer = request.form.get("answer")
        if user_answer == correct_answer:
            session["answered_correctly"].append((country_label, kind_of_questions))
            session.modified = True
    session["quiz_data"] = quiz_data
    session["score"] = score
    session["before_question_text"] = before_question_text
    session["before_country"] = before_country
    session["user_answers"] = user_answers
    return render_template("quiz.html", question=question_text, options_with_format=options_with_format, correct_answer=correct_answer, flag_image_url=flag_image_url, anthem_audio=anthem_audio)

@app.route("/result")
@login_required
def result():
    """
    Rota para exibir o resultado do quiz.

    Atualiza a pontuação do usuário e exibe a página de resultado.

    Returns:
        render_template: Exibe a página de resultado.
    """
    user = User.query.get(session['user_id'])
    total_score = session["score"]
    user.score += total_score
    db.session.commit()
    result_data = session["user_answers"].copy()
    session.pop("score", 0)
    session.pop("quiz_data", [])
    session.pop("before_question_text", None)
    session.pop("before_country", None)
    session.pop("user_answers", [])
    return render_template("result.html", score=total_score, user_answers=result_data)

@app.route('/admin/reported_questions')
@login_required
def reported_questions():
    """
    Rota para exibir questões reportadas.

    Exibe a página de questões reportadas.

    Returns:
        render_template: Exibe a página de questões reportadas.
    """
    if current_user.username != 'admin':
        return redirect(url_for('home'))
    reported_questions = ReportedQuestion.query.filter(ReportedQuestion.value_from_ai.isnot(None), ReportedQuestion.approved == False, ReportedQuestion.value_updated == False).all()
    return render_template('reported_questions.html', reported_questions=reported_questions)

@app.route('/admin/approve_question/<int:question_id>', methods=['POST'])
@login_required
def approve_question(question_id):
    """
    Rota para aprovar uma questão reportada.

    Aprova a questão reportada e redireciona para a página de questões reportadas.

    Args:
        question_id (int): ID da questão reportada.

    Returns:
        redirect: Redireciona para a página de questões reportadas.
    """
    if current_user.username != 'admin':
        return redirect(url_for('home'))
    question = ReportedQuestion.query.get_or_404(question_id)
    question.approved = True
    db.session.commit()
    return redirect(url_for('reported_questions'))

@app.route('/admin/bypass_question/<int:question_id>', methods=['POST'])
@login_required
def bypass_question(question_id):
    """
    Rota para ignorar uma questão reportada.

    Ignora a questão reportada e redireciona para a página de questões reportadas.

    Args:
        question_id (int): ID da questão reportada.

    Returns:
        redirect: Redireciona para a página de questões reportadas.
    """
    if current_user.username != 'admin':
        return redirect(url_for('home'))
    question = ReportedQuestion.query.get_or_404(question_id)
    question.value_updated = True
    db.session.commit()
    return redirect(url_for('reported_questions'))

@app.route('/admin/country_updates_debug')
@login_required
def country_updates_debug():
    """
    Rota de depuração para exibir atualizações de países com todos os detalhes.
    """
    session = Session()
    country_updates = session.query(CountryBlanksFromSemanticDatabase)\
        .filter(CountryBlanksFromSemanticDatabase.approved == False, CountryBlanksFromSemanticDatabase.value_updated == False).all()
    print("[DEBUG] Blanks enviados ao template country_updates_debug.html:")
    for blank in country_updates:
        print(f"[DEBUG] id={blank.id}, country_label={blank.country_label}, key={blank.key}, current_value={blank.current_value}, value_from_ai={blank.value_from_ai}, approved={blank.approved}, value_updated={blank.value_updated}")
    session.close()
    return render_template('country_updates_debug.html', country_updates=country_updates)

@app.route('/admin/country_updates')
@login_required
def country_updates():
    """
    Rota para exibir atualizações de países.

    Exibe a página de atualizações de países.

    Returns:
        render_template: Exibe a página de atualizações de países.
    """
    if current_user.username != 'admin':
        return redirect(url_for('home'))
    from sqlalchemy import or_
    session = Session()
    country_updates = session.query(CountryBlanksFromSemanticDatabase)\
        .filter(or_(
            CountryBlanksFromSemanticDatabase.current_value == None,
            CountryBlanksFromSemanticDatabase.current_value == "",
            CountryBlanksFromSemanticDatabase.current_value == "no_audio",
            CountryBlanksFromSemanticDatabase.current_value == "./static/images/no_flag.png"
        ),
        or_(
            CountryBlanksFromSemanticDatabase.value_from_ai == None,
            CountryBlanksFromSemanticDatabase.value_from_ai == ""
        ),
        CountryBlanksFromSemanticDatabase.value_updated == False,
        CountryBlanksFromSemanticDatabase.approved == False
    ).all()
    return render_template('country_updates.html', country_updates=country_updates)

@app.route('/admin/approve_country_update/<int:country_id>', methods=['POST'])
@login_required
def approve_country_update(country_id):
    """
    Rota para aprovar uma atualização de país.

    Aprova a atualização de país e redireciona para a página de atualizações de países.

    Args:
        country_id (int): ID da atualização de país.

    Returns:
        redirect: Redireciona para a página de atualizações de países.
    """
    if current_user.username != 'admin':
        return redirect(url_for('home'))
    country_update = CountryBlanksFromSemanticDatabase.query.get_or_404(country_id)
    country_update.approved = True
    # Não marcar value_updated aqui! Apenas após batch de atualização (update_countryQuiz_from_approved_blanks)
    db.session.commit()
    return redirect(url_for('country_updates'))

@app.route('/admin/bypass_country_update/<int:country_id>', methods=['POST'])
@login_required
def bypass_country_update(country_id):
    """
    Rota para ignorar uma atualização de país.

    Ignora a atualização de país e redireciona para a página de atualizações de países.

    Args:
        country_id (int): ID da atualização de país.

    Returns:
        redirect: Redireciona para a página de atualizações de países.
    """
    if current_user.username != 'admin':
        return redirect(url_for('home'))
    country_update = CountryBlanksFromSemanticDatabase.query.get_or_404(country_id)
    country_update.value_updated = True
    db.session.commit()
    return redirect(url_for('country_updates'))

@app.route('/admin/manual_update_country_blank/<int:blank_id>', methods=['POST'])
@login_required
def manual_update_country_blank(blank_id):
    """
    Rota para atualizar manualmente um campo de país.
    Atualiza o campo de país e redireciona para a página de atualizações de países.
    Args:
        blank_id (int): ID do campo de país.
    Returns:
        redirect: Redireciona para a página de atualizações de países.
    """
    if current_user.username != 'admin':
        print(f"[DEBUG] Usuário não autorizado tentou acessar manual_update_country_blank")
        return redirect(url_for('home'))

    print(f"[DEBUG] POST recebido para blank_id={blank_id}")
    print(f"[DEBUG] Dados do formulário: {dict(request.form)}")
    new_value = request.form.get('new_value')
    blank = CountryBlanksFromSemanticDatabase.query.get_or_404(blank_id)
    print(f"[DEBUG] Blank antes da atualização: id={blank.id}, country_label={blank.country_label}, key={blank.key}, current_value={blank.current_value}, value_from_ai={blank.value_from_ai}, approved={blank.approved}, value_updated={blank.value_updated}")
    blank.current_value = new_value
    blank.value_from_ai = new_value  # Garante que o campo usado no template seja atualizado
    blank.approved = True  # Marca como aprovado após edição manual
    db.session.commit()
    print(f"[DEBUG] Blank depois da atualização: id={blank.id}, country_label={blank.country_label}, key={blank.key}, current_value={blank.current_value}, value_from_ai={blank.value_from_ai}, approved={blank.approved}, value_updated={blank.value_updated}")
    return redirect(url_for('country_updates'))

@app.route('/admin/reload_country_quiz', methods=['POST'])
@login_required
def reload_country_quiz():
    """
    Rota para recarregar o quiz de países.

    Recarrega o quiz de países e exibe uma mensagem de sucesso.

    Returns:
        redirect: Redireciona para a página de quiz.
    """
    if current_user.username != 'admin':
        return redirect(url_for('home'))
    try:
        request_or_load_country_data()
        flash('CountryQuiz data reloaded successfully.')
    except Exception as e:
        flash(f'Error reloading CountryQuiz data: {e}')
    return redirect(url_for('quiz'))

if __name__ == "__main__":
    app.run(debug=True)
#    app.run(debug=True, port=8080)