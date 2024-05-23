from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import login_required, current_user, LoginManager, login_user, logout_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import random
import requests
import os
import json
import configparser
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.exc import IntegrityError

config = configparser.ConfigParser()
config.read('quiz.config')

DATABASE = config.get('settings', 'database', fallback=os.getenv('DATABASE', 'WIKIDATA'))
DBPEDIA_SPARQL_QUERY = config.get('settings', 'dbpedia_sparql_query', fallback=os.getenv('DBPEDIA_SPARQL_QUERY'))
WIKIDATA_SPARQL_QUERY = config.get('settings', 'wikidata_sparql_query', fallback=os.getenv('WIKIDATA_SPARQL_QUERY'))
OPENAI_API_KEY = config.get('settings', 'openai_api_key', fallback=os.getenv('OPENAI_API_KEY'))

OPTIONS = ["capital_label", "currency_label",
           "population", "flag_label", 
           "official_Language_label", "continent_label", "highest_point_label"]

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///quiz.db'

db = SQLAlchemy(app)
session_factory = sessionmaker(bind=db.engine)
Session = scoped_session(session_factory)

class User(UserMixin, db.Model):
    """Modelo de usuário para o banco de dados SQLAlchemy."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    score = db.Column(db.Integer, default=0)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

class ReportedQuestion(db.Model):
    """Modelo para perguntas reportadas no quiz."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref=db.backref(
        'reported_questions', lazy=True))
    question = db.Column(db.String, nullable=False)
    country = db.Column(db.String, nullable=False)
    correct_answer = db.Column(db.String, nullable=False)  # Resposta que o aplicativo diz ser a correta
    value_from_ai = db.Column(db.String(255), nullable=False)
    approved = db.Column(db.Boolean, nullable=False, default=False)
    value_updated = db.Column(db.Boolean, nullable=False, default=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
class CountryQuiz(db.Model):
    """Modelo para quizzes relacionados a dados de países."""
    id = db.Column(db.Integer, primary_key=True)
    country_label = db.Column(db.String(255), unique=True, nullable=False)
    data = db.Column(db.Text, nullable=False)  # Dados JSON
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<CountryQuiz {self.country_label}>'

class CountryFromSemanticDatabase(db.Model):
    """Modelo para armazenar dados de países obtidos de bases de dados semânticas."""
    id = db.Column(db.Integer, primary_key=True)
    country_label = db.Column(db.String(255), unique=True, nullable=False)
    data = db.Column(db.Text, nullable=False)  # Dados JSON
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

class CountryBlanksFromSemanticDatabase(db.Model):
    """Modelo para gerenciar lacunas de informação nos dados de países que podem ser preenchidas via IA."""
    id = db.Column(db.Integer, primary_key=True)
    country_label = db.Column(db.String(255), nullable=False)
    key = db.Column(db.String(255), nullable=False)
    current_value = db.Column(db.String(255), nullable=True)
    value_from_ai = db.Column(db.String(255), nullable=True)
    approved = db.Column(db.Boolean, default=False)
    value_updated = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class CountryQuizUpdatesHistory(db.Model):
    """Modelo para registrar histórico de atualizações dos quizzes de países."""
    id = db.Column(db.Integer, primary_key=True)
    function_name = db.Column(db.String(255), nullable=False)
    country_label = db.Column(db.String(255), nullable=False)
    key = db.Column(db.String(255), nullable=False)
    old_data = db.Column(db.Text, nullable=False)
    new_data = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

database = DATABASE

def unify_country_data(data):
    """Unifica dados de entrada para um país, combinando entradas duplicadas ou fragmentadas.

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
                    values_list = existing_value.split(", ")
                    if new_value not in values_list:
                        values_list.append(new_value)
                    if len(values_list) > 1:
                        unified_data[country_label][key]['value'] = ", ".join(values_list[:-1]) + " or " + values_list[-1]
                    else:
                        unified_data[country_label][key]['value'] = values_list[0]
                else:
                    unified_data[country_label][key] = {'value': new_value}
    return list(unified_data.values())

def request_or_load_country_data():
    """Carrega dados de países do banco de dados ou os solicita de fontes externas se o banco estiver vazio.

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
    """Combina dois conjuntos de dados de países, atualizando o primeiro com informações do segundo.

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
    """Formata números grandes de população para um formato mais legível com sufixos 'M' ou 'K'.

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
    """Recupera dados de países usando consultas SPARQL de fontes externas como DBpedia e Wikidata.

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
    """Seleciona dados específicos de um conjunto maior de dados de países para uso em quizzes.

    Args:
        all_data_int (list): Lista completa de dados de países.
        kind_of_questions_int (str): Tipo de questão para a qual os dados são selecionados.

    Returns:
        list: Lista de tuplas contendo dados específicos selecionados para o quiz.
    """
    country_data_int = [
        (entry["country_label"]["value"], entry[kind_of_questions_int]["value"], 
         entry["flag_image"]["value"], entry["anthem_audio"]["value"]) for entry in all_data_int
    ]
    return country_data_int

all_data = request_or_load_country_data()

def generate_quiz():
    """Gera um conjunto de perguntas para um quiz a partir de dados de países.

    Returns:
        list: Lista de perguntas geradas para o quiz.
    """
    quiz = []
    for _ in range(6):
        if database == "DBPEDIA":
          kind_of_questions = OPTIONS[random.randint(0, 4)]
        else:
            kind_of_questions = OPTIONS[random.randint(0, 6)]
        country_data = select_country_data(all_data, kind_of_questions)
        question = random.choice(country_data)
        if kind_of_questions == "flag_label":
          while (question[2] == ("./static/images/no_flag.png" or './static/images/no_flag.png')) or ((question, kind_of_questions) in quiz):
            question = random.choice(country_data)
        if kind_of_questions == "currency_label":
          while (question[1] == '') or ((question, kind_of_questions) in quiz):
            question = random.choice(country_data)
        if kind_of_questions == "population":
          while (question[1] == '') or ((question, kind_of_questions) in quiz):
            question = random.choice(country_data)
        if kind_of_questions == "capital_label":
          while (question[1] == '') or ((question, kind_of_questions) in quiz):
            question = random.choice(country_data)
        if kind_of_questions == "official_Language_label":
          while (question[1] == '') or ((question, kind_of_questions) in quiz):
            question = random.choice(country_data)
        if kind_of_questions == "continent_label":
          while (question[1] == '') or ((question, kind_of_questions) in quiz):
            question = random.choice(country_data)
        if kind_of_questions == "highest_point_label":
          while (question[1] == '') or ((question, kind_of_questions) in quiz):
            question = random.choice(country_data)
        quiz.append((question, kind_of_questions))
    return quiz

@app.route('/login', methods=['GET', 'POST'])
def login():
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
    top_scores = User.query.order_by(User.score.desc()).limit(10).all()
    return render_template('login.html', top_scores=top_scores)

@app.route('/register', methods=['GET', 'POST'])
def register():
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
    session.pop("quiz_data", [])
    session.pop('user_id', None)
    logout_user()
    return redirect(url_for('login'))

@app.route("/home")
def home():
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
    (question, correct_answer, flag_image_url, anthem_audio), kind_of_questions = quiz_data[0]
    if anthem_audio == "no_audio":
        anthem_audio = ""
    else:
        anthem_audio = "<audio controls='controls'><source src='" + anthem_audio + "' type='audio/ogg' />seu navegador não suporta HTML5</audio>"
    country_data = select_country_data(all_data, kind_of_questions)
    country_data = [t for t in country_data if t[1] != '']
    wrong_options = random.sample(
        list(set([country[1] for country in country_data if (country[1] != correct_answer) and (country[0] != question)])), 2)
    options = wrong_options + [correct_answer]
    if kind_of_questions == "population" and all(" or " not in option for option in options):
        options_with_format = [{"value": option, "display": format_population(int(option))} for option in options]
    else:
        options_with_format = [{"value": option, "display": option} for option in options]
    random.shuffle(options_with_format)
    if kind_of_questions == "capital_label":
        question_text = f"What is the capital of (the) {question}?"
    elif kind_of_questions == "currency_label":
        question_text = f"What is the currency of (the) {question}?"
    elif kind_of_questions == "population":
        question_text = f"What is the population of (the) {question}?"
    elif kind_of_questions == "official_Language_label":
        question_text = f"What is the official language of (the) {question}?"
    elif kind_of_questions == "continent_label":
        question_text = f"Which continent does (the) {question} belong to?"
    elif kind_of_questions == "highest_point_label":
        question_text = f"What is the highest point in (the) {question}?"
    else:
        question_text = f"Which country does this flag belong to?"
    before_question_text = question_text
    before_country = question
    session["quiz_data"] = quiz_data
    session["score"] = score
    session["before_question_text"] = before_question_text
    session["before_country"] = before_country
    session["user_answers"] = user_answers
    return render_template("quiz.html", question=question_text, options_with_format=options_with_format, correct_answer=correct_answer, flag_image_url=flag_image_url, anthem_audio=anthem_audio)

@app.route("/result")
@login_required
def result():
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
    if current_user.username != 'admin':
        return redirect(url_for('home'))
    reported_questions = ReportedQuestion.query.filter(ReportedQuestion.value_from_ai.isnot(None), ReportedQuestion.approved == False, ReportedQuestion.value_updated == False).all()
    return render_template('reported_questions.html', reported_questions=reported_questions)

@app.route('/admin/approve_question/<int:question_id>', methods=['POST'])
@login_required
def approve_question(question_id):
    if current_user.username != 'admin':
        return redirect(url_for('home'))
    question = ReportedQuestion.query.get_or_404(question_id)
    question.approved = True
    db.session.commit()
    return redirect(url_for('reported_questions'))

@app.route('/admin/bypass_question/<int:question_id>', methods=['POST'])
@login_required
def bypass_question(question_id):
    if current_user.username != 'admin':
        return redirect(url_for('home'))
    question = ReportedQuestion.query.get_or_404(question_id)
    question.value_updated = True
    db.session.commit()
    return redirect(url_for('reported_questions'))

@app.route('/admin/country_updates')
@login_required
def country_updates():
    if current_user.username != 'admin':
        return redirect(url_for('home'))
    country_updates = CountryBlanksFromSemanticDatabase.query.filter(CountryBlanksFromSemanticDatabase.value_from_ai.isnot(None), CountryBlanksFromSemanticDatabase.value_from_ai.isnot(""), CountryBlanksFromSemanticDatabase.approved == False, CountryBlanksFromSemanticDatabase.value_updated == False).all()
    return render_template('country_updates.html', country_updates=country_updates)

@app.route('/admin/approve_country_update/<int:country_id>', methods=['POST'])
@login_required
def approve_country_update(country_id):
    if current_user.username != 'admin':
        return redirect(url_for('home'))
    country_update = CountryBlanksFromSemanticDatabase.query.get_or_404(country_id)
    country_update.approved = True
    db.session.commit()
    return redirect(url_for('country_updates'))

@app.route('/admin/bypass_country_update/<int:country_id>', methods=['POST'])
@login_required
def bypass_country_update(country_id):
    if current_user.username != 'admin':
        return redirect(url_for('home'))
    country_update = CountryBlanksFromSemanticDatabase.query.get_or_404(country_id)
    country_update.value_updated = True
    db.session.commit()
    return redirect(url_for('country_updates'))

@app.route('/admin/reload_country_quiz', methods=['POST'])
@login_required
def reload_country_quiz():
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