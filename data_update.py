"""
Módulo responsável por atualizar e gerenciar dados do quiz relacionados a países, utilizando IA generativa e bancos de dados semânticos.

Principais funcionalidades:
- Atualização de perguntas reportadas com respostas da IA.
- Atualização de lacunas de países com dados de IA.
- Sincronização do banco de dados do quiz com fontes externas (DBpedia, Wikidata).
- Geração de arquivos CSV para auditoria.

Todas as docstrings seguem o padrão Google para facilitar manutenção e colaboração.
"""

from sqlalchemy import create_engine, and_
from sqlalchemy.orm import sessionmaker, scoped_session
from datetime import datetime
import openai
import json
import configparser
import os

config = configparser.ConfigParser()
config.read('quiz.config')

OPENAI_API_KEY = config.get('settings', 'openai_api_key', fallback=os.getenv('OPENAI_API_KEY'))

DATABASE_URI = 'sqlite:///quiz.db'

openai.api_key = OPENAI_API_KEY

AI_CONFIDENCE_THRESHOLD = int(config.get('settings', 'ai_confidence_threshold', fallback=90))

engine = create_engine(DATABASE_URI)
session_factory = sessionmaker(bind=engine)
Session = scoped_session(session_factory)

def determine_prompt(question_text):
    """
    Retorna o prompt adequado para uma pergunta sobre país, com base em palavras-chave identificadas no texto.

    Utiliza palavras-chave como 'capital', 'moeda', 'população', etc., para selecionar o prompt correto a ser enviado à IA generativa.

    Args:
        question_text (str): Texto da pergunta a ser analisada.

    Returns:
        str: Prompt correspondente à palavra-chave encontrada ou 'DEFAULT_PROMPT' se nenhuma corresponder.
    """
    keywords_to_prompts = {
        "capital": "What is the capital of (the) **, without abbreviations, commas, or periods? Give me the answer as currently as possible with only the capital name. If there is more than one, give me only the capital names separated by the word 'or'. Append a '|' immediately followed by your confidence percentage (only numbers between 0 and 100).",
        "currency": "What is the currency of (the) **, without abbreviations, commas, or periods? Give me the answer as currently as possible with only the currency name. If there is more than one, give me only the currency names separated by the word 'or'. Append a '|' immediately followed by your confidence percentage (only numbers between 0 and 100).",
        "population": "What is the exact numeric population of (the) ** in digits, without abbreviations, commas, or periods? Give me the answer as currently as possible in digits; only one number. Append a '|' immediately followed by your confidence percentage (only numbers between 0 and 100).",
        "language": "What is the official language of (the) **, without abbreviations, commas, or periods? Give me the answer as currently as possible with only the language name. If there is more than one, give me only the language names separated by the word 'or'. Append a '|' immediately followed by your confidence percentage (only numbers between 0 and 100).",
        "continent": "Which continent does (the) ** belong to? Without abbreviations, commas, or periods. Give me the answer as currently as possible with only the continent name. If there is more than one, give me only the continent names separated by the word 'or'. Append a '|' immediately followed by your confidence percentage (only numbers between 0 and 100).",
        "highest point": "What is the highest point of (the) **, without abbreviations, commas, or periods? Give me the answer as currently as possible with only the highest point name. If there is more than one, give me only the highest point names separated by the word 'or'. Append a '|' immediately followed by your confidence percentage (only numbers between 0 and 100).",
        "flag": "Provide one URL of the official flag as currently as possible of (the) **. This URL must refer to a web image file such as SVG, JPG, or PNG. Provide only the URL. Append a '|' immediately followed by your confidence percentage (only numbers between 0 and 100).",
        "anthem": "Provide one URL of the official anthem as currently as possible of (the) **. This URL must refer to a web sound file such as OGG. Provide only the URL. Append a '|' immediately followed by your confidence percentage (only numbers between 0 and 100)."
    }
    
    for keyword, prompt in keywords_to_prompts.items():
        if keyword in question_text.lower():
            return prompt
    return "DEFAULT_PROMPT"

# Atualiza perguntas reportadas no banco que ainda não possuem resposta gerada pela IA.
def update_reported_questions_with_ai():
    """
    Atualiza perguntas reportadas sem resposta da IA, consultando o modelo generativo e salvando o resultado.

    Para cada pergunta reportada sem resposta, gera um prompt adequado, envia para a OpenAI, salva a resposta e registra logs.

    Returns:
        None
    """
    from app import ReportedQuestion
    print('[DEBUG] Iniciando update_reported_questions_with_ai')
    session = Session()
    reported_questions = session.query(ReportedQuestion).filter(ReportedQuestion.value_from_ai.is_("")).all()
    print(f'[DEBUG] Encontradas {len(reported_questions)} perguntas reportadas sem resposta da IA')
    for idx, question in enumerate(reported_questions, 1):
        print(f'[DEBUG] ({idx}/{len(reported_questions)}) Processando questão ID {question.id}: {question.question}')
        try:
            prompt = determine_prompt(question.question)
            if prompt == "DEFAULT_PROMPT":
                continue
            else:
                prompt = prompt.replace("**", question.country)
            print(prompt)
            response = openai.chat.completions.create(
                model="gpt-4o", #model="gpt-4-turbo-preview",#
                messages= [{'role': 'user', 'content': prompt}
                ],
                temperature= 0
            )
            print(response.choices[0].message.content.strip())
            question.value_from_ai = response.choices[0].message.content.strip()
            session.commit()
        except Exception as e:
            print(f"Error updating question {question.id}: {e}")
    session.close()

def parse_ai_response(ai_response):
    """
    Extrai o valor e a confiança de uma resposta da IA no formato 'valor|confiança'.

    Se a resposta estiver no formato 'valor|confiança', separa o valor e converte a confiança para inteiro.
    Caso contrário, retorna apenas o valor e None para a confiança.

    Args:
        ai_response (str): Resposta da IA no formato 'valor|confiança' ou apenas 'valor'.

    Returns:
        tuple: (valor (str), confiança (int ou None))
    """
    if "|" in ai_response:
        value, confidence = ai_response.rsplit("|", 1)
        try:
            confidence = int(confidence)
        except ValueError:
            confidence = None
        return value.strip(), confidence
    return ai_response.strip(), None

# Atualiza campos em branco de países no banco usando respostas da IA generativa.
def update_country_blanks_from_semanticdatabase_with_ai():
    """
    Atualiza campos em branco (blanks) de países utilizando respostas geradas por IA.

    Para cada blank pendente (incluindo campos padrão de flag e hino), consulta a IA, avalia a confiança da resposta, aprova automaticamente se atingir o limiar e registra logs de progresso. Caso a confiança não seja suficiente, registra para revisão manual em ReportedQuestion.

    Returns:
        None
    """
    from app import CountryBlanksFromSemanticDatabase, ReportedQuestion, User, CountryQuiz, CountryQuizUpdatesHistory
    print('[DEBUG] Iniciando update_country_blanks_from_semanticdatabase_with_ai')
    session = Session()
    # Inclui também blanks de flag_image e anthem_audio com valores padrão, além dos realmente em branco
    country_data = session.query(CountryBlanksFromSemanticDatabase).filter(
        CountryBlanksFromSemanticDatabase.approved == False,
        CountryBlanksFromSemanticDatabase.value_updated == False,
        (
            (CountryBlanksFromSemanticDatabase.current_value == '') |
            ((CountryBlanksFromSemanticDatabase.key == 'flag_image') & (CountryBlanksFromSemanticDatabase.current_value == './static/images/no_flag.png')) |
            ((CountryBlanksFromSemanticDatabase.key == 'anthem_audio') & (CountryBlanksFromSemanticDatabase.current_value == 'no_audio'))
        )
    ).all()
    for question in country_data:
        try:
            key = question.key
            if question.key == "highest_point_label":
                key = "highest point"
            prompt = determine_prompt(key)
            if prompt == "DEFAULT_PROMPT":
                continue
            else:
                prompt = prompt.replace("**", question.country_label)
            print(prompt)
            response = openai.chat.completions.create(
                model="gpt-4o", #model="gpt-4-turbo-preview",#
                messages= [{'role': 'user', 'content': prompt}
                ],
                temperature= 0
            )

            ai_full_response = response.choices[0].message.content.strip()
            print(ai_full_response)
            ai_value, ai_confidence = parse_ai_response(ai_full_response)

            # Só aprova/atualiza se houver resposta NÃO NULA, NÃO VAZIA e NÃO apenas espaços
            if ai_value and ai_value.strip() and ai_confidence is not None:
                question.value_from_ai = ai_value
                question.ai_confidence = ai_confidence
                if ai_confidence >= AI_CONFIDENCE_THRESHOLD:
                    question.approved = True
                    # NÃO marcar value_updated aqui! Só após incorporar ao quiz.
                    question.current_value = ai_value
                else:
                    question.approved = False
                    question.value_updated = False
                    # Registrar na ReportedQuestion para tratamento manual
                    existing = session.query(ReportedQuestion).filter_by(
                        country=question.country_label,
                        question=question.key,
                        value_from_ai=ai_full_response,
                        approved=False
                    ).first()
                    if not existing:
                        ai_user = session.query(User).filter_by(username="ai").first()
                        if not ai_user:
                            ai_user = User(username="ai", password="ai", email="ai@system", score=0, timestamp=datetime.utcnow())
                            session.add(ai_user)
                            session.commit()
                        reported = ReportedQuestion(
                            user_id=ai_user.id,  # IA/automático
                            question=question.key,
                            country=question.country_label,
                            correct_answer=question.current_value,
                            value_from_ai=ai_full_response,
                            approved=False,
                            value_updated=False,
                            timestamp=datetime.utcnow()
                        )
                        session.add(reported)
            else:
                # Resposta da IA foi nula/vazia: não aprova nem marca como atualizado
                question.value_from_ai = ""
                question.ai_confidence = None
                question.approved = False
                question.value_updated = False
                continue


            # ALERTA: Só setar approved=True automaticamente se ai_confidence >= AI_CONFIDENCE_THRESHOLD
            # (Aprovação automática por IA. Aprovação manual por especialista/admin é livre.)
            # Se confiança >= AI_CONFIDENCE_THRESHOLD, atualiza imediatamente CountryQuiz
            if ai_confidence is not None and ai_confidence >= AI_CONFIDENCE_THRESHOLD:
                country = session.query(CountryQuiz).filter(CountryQuiz.country_label == question.country_label).first()
                if country:
                    country_data = json.loads(country.data) if country.data else {}
                    country_data[question.key] = {"value": ai_value}
                    country.data = json.dumps(country_data)
                    country.timestamp = datetime.utcnow()
                    # Registrar no histórico
                    new_history_record = CountryQuizUpdatesHistory(
                        function_name='update_country_blanks_from_semanticdatabase_with_ai',
                        country_label=question.country_label,
                        key=question.key,
                        old_data="",  # Pode buscar valor anterior se desejar
                        new_data=ai_value,
                        ai_confidence=ai_confidence,
                        timestamp=datetime.utcnow()
                    )
                    session.add(new_history_record)
                    # Não marcar value_updated aqui. A linha será tratada após aprovação.
                    question.approved = True  # Marcar como aprovado automaticamente se confiança >= AI_CONFIDENCE_THRESHOLD
            else:
                # Só registra na ReportedQuestion se confiança for válida (maior que 0)
                if ai_confidence is not None and ai_confidence > 0:
                    # Confiança < 90: registrar na tabela ReportedQuestion para avaliação manual
                    # ALERTA: Não setar approved=True automaticamente se ai_confidence < 90
            # Não marcar value_updated aqui. A linha será tratada após aprovação.
                    # Só marcar value_updated=True se o valor da IA for diferente do valor atual
                    # Não marcar value_updated aqui. A linha será tratada após aprovação.
                    question.approved = False
                    # Evita duplicatas
                    existing = session.query(ReportedQuestion).filter_by(
                        country=question.country_label,
                        question=question.key,
                        value_from_ai=ai_full_response,
                        approved=False
                    ).first()
                    if not existing:
                        # Busca/cria usuário 'ai' para registrar user_id
                        ai_user = session.query(User).filter_by(username="ai").first()
                        if not ai_user:
                            ai_user = User(username="ai", password="ai", email="ai@system", score=0, timestamp=datetime.utcnow())
                            session.add(ai_user)
                            session.commit()
                        reported = ReportedQuestion(
                            user_id=ai_user.id,  # IA/automático
                            question=question.key,
                            country=question.country_label,
                            correct_answer=question.current_value,
                            value_from_ai=ai_full_response,
                            approved=False,
                            value_updated=False,
                            timestamp=datetime.utcnow()
                        )
                        session.add(reported)
            session.commit()
        except Exception as e:
            print(f"Erro ao atualizar a questão {question.id}: {e}")
    session.close()

# Propaga respostas aprovadas de perguntas reportadas para o banco principal do quiz.
def update_countryQuiz_from_approved_questions():
    """
    Atualiza o banco principal do quiz com respostas aprovadas de perguntas reportadas.

    Para cada questão aprovada e não atualizada, atualiza os dados do quiz, registra histórico de alterações e imprime logs de progresso. Aprovação manual por especialista/admin é permitida independentemente da confiança.

    Returns:
        None
    """
    from app import CountryQuiz, ReportedQuestion, CountryQuizUpdatesHistory, CountryBlanksFromSemanticDatabase
    print('[DEBUG] Iniciando update_countryQuiz_from_approved_questions')
    session = Session()
    approved_questions = session.query(ReportedQuestion)\
        .filter(ReportedQuestion.approved == True, ReportedQuestion.value_updated == False).all()
    # ALERTA: approved=True só deve ser atribuído automaticamente se ai_confidence >= 90.
    # Aprovação manual por especialista/admin é permitida independentemente da confiança.
    print(f"[DEBUG] Total approved_questions encontradas: {len(approved_questions)}")
    print(f'[DEBUG] Encontradas {len(approved_questions)} perguntas aprovadas e não atualizadas')
    for idx, question in enumerate(approved_questions, 1):
        print(f'[DEBUG] ({idx}/{len(approved_questions)}) Atualizando questão aprovada ID {question.id}: {question.question}')
        print(f"[DEBUG] Processando ReportedQuestion id={question.id}, country={question.country}, question='{question.question}', value_from_ai='{question.value_from_ai}'")
        json_field = None
        requires_value_key = True  # Flag para indicar se o campo requer "value: " antes do valor
        qstr = question.question.lower().replace("_", " ").replace("label", "").strip()
        # Robust mapeamento para campos conhecidos
        if any(x in qstr for x in ["population"]):
            json_field = "population"
        elif any(x in qstr for x in ["capital"]):
            json_field = "capital_label"
        elif any(x in qstr for x in ["currency"]):
            json_field = "currency_label"
        elif any(x in qstr for x in ["flag"]):
            json_field = "flag_image"
        elif any(x in qstr for x in ["continent"]):
            json_field = "continent_label"
        elif any(x in qstr for x in ["highest point"]):
            json_field = "highest_point_label"
        elif any(x in qstr for x in ["official language", "officiallanguage", "language"]):
            json_field = "official_language_label"
        elif any(x in qstr for x in ["anthem audio", "anthemaudio", "anthem"]):
            json_field = "anthem_audio"
            requires_value_key = True  # Altere para False se o JSON não usar dict
        # Adicione outros campos customizados abaixo seguindo o padrão:
        # elif "nome_do_campo" in question.question:
        #     json_field = "nome_do_campo"
        print(f"[DEBUG] json_field determinado: {json_field}")
        if json_field:
            country = session.query(CountryQuiz).filter(CountryQuiz.country_label == question.country).first()
            if not country:
                print(f"[WARNING] CountryQuiz não encontrado para country_label='{question.country}'")
            else:
                country_data = json.loads(country.data) if country.data else {}
                country_label = question.country
                old_data = question.correct_answer
                # Sempre salve apenas o valor limpo (sem '|confiança')
                value, _ = parse_ai_response(question.value_from_ai)
                print(f"[DEBUG] Valor limpo extraído de value_from_ai: '{value}'")
                if requires_value_key:
                    if json_field not in country_data or not isinstance(country_data[json_field], dict):
                        print(f"[DEBUG] Criando novo dict para campo '{json_field}' em country_data")
                        country_data[json_field] = {"value": value}
                    else:
                        print(f"[DEBUG] Atualizando campo '{json_field}' em country_data para value='{value}'")
                        country_data[json_field]["value"] = value
                else:
                    print(f"[DEBUG] Atualizando campo '{json_field}' em country_data para value='{value}' (sem dict)")
                    country_data[json_field] = value
                country.data = json.dumps(country_data)
                country.timestamp = datetime.utcnow()
                new_history_record = CountryQuizUpdatesHistory(
                    function_name='update_countryQuiz_from_approved_questions',
                    country_label=country_label,
                    key=json_field,
                    old_data=old_data,
                    new_data=value,
                    timestamp=datetime.utcnow()
                )
                session.add(new_history_record)
                question.value_updated = True
                # Atualiza também CountryBlanksFromSemanticDatabase, se existir
                blank = session.query(CountryBlanksFromSemanticDatabase).filter_by(country_label=country_label, key=json_field).first()
                if not blank:
                    print(f"[WARNING] CountryBlanksFromSemanticDatabase não encontrado para country_label='{country_label}', key='{json_field}'")
                else:
                    print(f"[DEBUG] Atualizando CountryBlanksFromSemanticDatabase id={blank.id} para value='{value}'")
                    blank.current_value = value
                    blank.value_from_ai = value
                    blank.approved = True
                    blank.value_updated = True
        else:
            print(f"[WARNING] Não foi possível determinar json_field para question='{question.question}' (id={question.id})")
    session.commit()
    print("[DEBUG] Commit realizado. Fechando sessão.")
    session.close()

# Propaga respostas aprovadas de blanks de países para o banco principal do quiz.
def update_countryQuiz_from_approved_blanks():
    """
    Atualiza o banco principal do quiz com respostas aprovadas de blanks de países.

    Para cada blank aprovado e não atualizado, atualiza os dados do quiz, registra histórico de alterações e imprime logs de progresso. Diferencia origem manual e IA para fins de auditoria.

    Returns:
        None
    """
    from app import CountryQuiz, CountryQuizUpdatesHistory, CountryBlanksFromSemanticDatabase
    print('[DEBUG] Iniciando update_countryQuiz_from_approved_blanks')
    session = Session()
    approved_updates = session.query(CountryBlanksFromSemanticDatabase)\
        .filter(CountryBlanksFromSemanticDatabase.approved == True, CountryBlanksFromSemanticDatabase.value_updated == False).all()
    print(f"[DEBUG] Encontradas {len(approved_updates)} lacunas aprovadas e não atualizadas.")
    print("[DEBUG] Blanks aprovados e não atualizados:")
    for upd in approved_updates:
        print(f"[DEBUG] Blank aprovado: country_label={upd.country_label}, key={upd.key}, value_from_ai={upd.value_from_ai}, approved={upd.approved}, value_updated={upd.value_updated}")
    print(f'[DEBUG] Encontrados {len(approved_updates)} blanks aprovados e não atualizados')
    for idx, update in enumerate(approved_updates, 1):
        print(f'[DEBUG] ({idx}/{len(approved_updates)}) Propagando blank aprovado: country={update.country_label}, key={update.key}')
        print(f"[DEBUG] Processando: country_label={update.country_label}, key={update.key}, current_value={update.current_value}, value_from_ai={update.value_from_ai}, approved={update.approved}")
        country = session.query(CountryQuiz).filter(CountryQuiz.country_label == update.country_label).first()
        if country:
            country_data = json.loads(country.data) if country.data else {}
            old_data = country_data.get(update.key, "")
            # Preferir valor manual se houver, senão o da IA
            if update.current_value:
                new_value = update.current_value
                origem = "manual"
            else:
                new_value = update.value_from_ai
                origem = "ia"
            if isinstance(country_data.get(update.key, ""), dict):
                new_value = {"value": new_value}
            print(f"[DEBUG] old_data={old_data}, new_value={new_value}, origem={origem}")
            # Só atualiza se o valor realmente mudou e não é vazio
            if new_value not in [None, ""]:
                if old_data != new_value:
                    country_data[update.key] = new_value
                    country.data = json.dumps(country_data)
                    country.timestamp = datetime.utcnow()
                    # Serializa dicts para string JSON antes de salvar no histórico
                    old_data_str = json.dumps(old_data) if isinstance(old_data, dict) else old_data
                    new_value_str = json.dumps(new_value) if isinstance(new_value, dict) else new_value
                    new_history_record = CountryQuizUpdatesHistory(
                        function_name=f'update_countryQuiz_from_approved_blanks_{origem}',
                        country_label=update.country_label,
                        key=update.key,
                        old_data=old_data_str,
                        new_data=new_value_str,
                        timestamp=datetime.utcnow()
                    )
                    session.add(new_history_record)
                    print(f"[DEBUG] Atualização registrada no histórico para {update.country_label} - {update.key}")
                else:
                    print(f"[DEBUG] Nenhuma alteração necessária para {update.country_label} - {update.key} (valor já era igual)")
            else:
                print(f"[DEBUG] Ignorando atualização para {update.country_label} - {update.key} pois o valor aprovado está vazio.")
            update.value_updated = True
        else:
            print(f"[WARNING] CountryQuiz não encontrado para country_label={update.country_label}")
    session.commit()
    print("[DEBUG] Commit realizado. Fechando sessão.")
    session.close()


def update_new_country_data_from_semanticdatabase_in_countryQuiz():
    from app import CountryQuiz, CountryFromSemanticDatabase, get_country_data, CountryBlanksFromSemanticDatabase, CountryQuizUpdatesHistory, User, ReportedQuestion
    print('[DEBUG] Iniciando update_new_country_data_from_semanticdatabase_in_countryQuiz')
    """
    Atualiza o quiz com novos dados de países obtidos de fontes semânticas externas (ex: Wikidata).
    Esta função sincroniza a base de dados local com os dados mais recentes das fontes semânticas, realizando as seguintes ações:
    - Adiciona ou atualiza países e suas propriedades.
    - Remove países que não existem mais na fonte.
    - Atualiza lacunas e aprovações conforme necessário.
    - Registra todas as alterações relevantes no histórico.
    Returns:
        None
    """
    session = Session()

    # Teste -- carga da tabela local para teste
#    new_data = [(json.loads(country.data), country.timestamp) for country in CountryFromSemanticDatabase.query.all()]
#    new_countries = {country[0]['country_label']['value'] for country in new_data}
    ##

    # Produção -- consulta Wikidata
    new_data_full = get_country_data()
    new_data = [(country, datetime.utcnow()) for country in new_data_full]
    new_countries = {country['country_label']['value'] for country in new_data_full}
    ##

    # --- Atualiza a tabela CountryFromSemanticDatabase ---
    # Atualiza ou insere países
    for country in new_data_full:
        label = country['country_label']['value']
        existing = session.query(CountryFromSemanticDatabase).filter_by(country_label=label).first()
        if existing:
            if existing.data != json.dumps(country):
                existing.data = json.dumps(country)
                existing.timestamp = datetime.utcnow()
        else:
            new_entry = CountryFromSemanticDatabase(
                country_label=label,
                data=json.dumps(country),
                timestamp=datetime.utcnow()
            )
            session.add(new_entry)
    # Remove países que não existem mais
    all_existing_labels = {c.country_label for c in session.query(CountryFromSemanticDatabase).all()}
    labels_to_remove = all_existing_labels - new_countries
    for label in labels_to_remove:
        to_remove = session.query(CountryFromSemanticDatabase).filter_by(country_label=label).first()
        if to_remove:
            session.delete(to_remove)
    # --- Fim atualização CountryFromSemanticDatabase ---

    # --- Ajusta a tabela CountryBlanksFromSemanticDatabase ---
    blanks = session.query(CountryBlanksFromSemanticDatabase).all()
    blanks_index = {(b.country_label, b.key): b for b in blanks}
    all_blanks_to_check = set()
    # 1. Adiciona novas lacunas (propriedades em branco)
    for country in new_data_full:
        label = country['country_label']['value']
        for key, value in country.items():
            if key == 'country_label':
                continue
            # Considera blank se for None, string vazia, ou valor especial
            if isinstance(value, dict) and value.get('value', None) in [None, '']:
                if (label, key) not in blanks_index:
                    new_blank = CountryBlanksFromSemanticDatabase(
                        country_label=label,
                        key=key,
                        current_value="",
                        value_from_ai="",
                        ai_confidence=None,
                        approved=False,
                        value_updated=False,
                        timestamp=datetime.utcnow()
                    )
                    session.add(new_blank)
                all_blanks_to_check.add((label, key))
            else:
                # Se havia blank e agora foi preenchido, verifica se é valor padrão de ausência
                if (label, key) in blanks_index:
                    blank = blanks_index[(label, key)]
                    new_filled_value = value['value'] if isinstance(value, dict) and 'value' in value else value
                    blank.current_value = new_filled_value
                    if key in ["flag_image", "anthem_audio"] and new_filled_value in ["./static/images/no_flag.png", "no_audio"]:
                        blank.value_updated = False  # NÃO marcar como atualizado
                        blank.approved = False      # NÃO marcar como aprovado
                    else:
                        blank.value_updated = True
                        blank.approved = True
                    blank.timestamp = datetime.utcnow()
    # 2. Marcar como atualizadas lacunas de países removidos
    all_country_labels = {country['country_label']['value'] for country in new_data_full}
    for blank in blanks:
        if blank.country_label not in all_country_labels:
            if blank.ai_confidence != -1:
                blank.value_updated = False
                blank.approved = False
                blank.timestamp = datetime.utcnow()
    # --- Fim ajuste CountryBlanksFromSemanticDatabase ---

    current_countries = {country.country_label for country in CountryFromSemanticDatabase.query.all()}

    countries_to_remove = current_countries - new_countries
    for country_label in countries_to_remove:
        print(f"Procurando por: {country_label} em CountryFromSemanticDatabase")
        # Remove da tabela 'CountryFromSemanticDatabase'
        country_to_remove = session.query(CountryFromSemanticDatabase).filter(CountryFromSemanticDatabase.country_label == country_label).one_or_none()
        if country_to_remove:
          print(f"Removendo: {country_to_remove} em CountryFromSemanticDatabase")
          session.delete(country_to_remove)

          # Adiciona registro em 'CountryQuizUpdatesHistory'
          removal_history = CountryQuizUpdatesHistory(
              country_label=country_label,
              timestamp=datetime.utcnow(),
              function_name='update_new_country_data_from_semanticdatabase_in_countryQuiz -> ancient country removed in CountryFromSemanticDatabase',
              key="",
              old_data="",
              new_data="",
          )
          session.add(removal_history)
          session.commit()
        else:
          print(f"Não encontrado: {country_label}") 

    current_countries_updated = {country.country_label for country in CountryFromSemanticDatabase.query.all()}
    current_CountryQuiz_countries = {country.country_label for country in CountryQuiz.query.all()}
    CountryQuiz_countries_to_remove = current_CountryQuiz_countries - current_countries_updated
    for country_label in CountryQuiz_countries_to_remove:
        print(f"Procurando por: {country_label} em CountryQuiz")
        # Remove da tabela 'CountryQuiz'
        CountryQuiz_country_to_remove = session.query(CountryQuiz).filter(CountryQuiz.country_label == country_label).one_or_none()
        if CountryQuiz_country_to_remove:
          print(f"Removendo: {CountryQuiz_country_to_remove} em CountryQuiz")
          session.delete(CountryQuiz_country_to_remove)

          # Adiciona registro em 'CountryQuizUpdatesHistory'
          removal_history = CountryQuizUpdatesHistory(
              country_label=country_label,
              timestamp=datetime.utcnow(),
              function_name='update_new_country_data_from_semanticdatabase_in_countryQuiz -> ancient country removed in CountryQuiz',
              key="",
              old_data="",
              new_data="",
          )
          session.add(removal_history)
          session.commit()
        else:
          print(f"Não encontrado: {country_label}")

    existing_data = {item.country_label: (json.loads(item.data), item.timestamp) for item in session.query(CountryQuiz).all()}
    updates_count = 0
    for new_country, new_timestamp in new_data:
        label = new_country['country_label']['value']
        new_values = {k: v['value'] for k, v in new_country.items() if 'value' in v}
        if label in existing_data:
            current_data, current_timestamp = existing_data[label]
            updated_data = current_data.copy()
            update_needed = False
            for key, new_value in new_values.items():
                if new_value in ["./static/images/no_flag.png", "no_audio"]:
                    continue
                # Só atualiza se o valor novo NÃO for vazio
                if new_value not in [None, '']:
                    old_value = current_data.get(key, {}).get('value', None)
                    if old_value != new_value and new_timestamp > current_timestamp:
                        updated_data[key] = {'value': new_value}
                        update_needed = True
                        key_history = key
                        old_value_history = old_value if old_value is not None else ""
                        new_value_history = new_value if new_value is not None else ""
                        existing_entry = CountryBlanksFromSemanticDatabase.query.filter_by(country_label=label, key=key).first()
                        if existing_entry:
                          session.query(CountryBlanksFromSemanticDatabase).filter(and_(CountryBlanksFromSemanticDatabase.country_label == label, CountryBlanksFromSemanticDatabase.key == key)).update({
                            'value_updated': True
                          })
                # Se o valor novo for vazio, mantém o valor atual (não sobrescreve)
                # Nenhuma ação é tomada nesse caso
            if update_needed:
                session.query(CountryQuiz).filter(CountryQuiz.country_label == label).update({
                    'data': json.dumps(updated_data),
                    'timestamp': new_timestamp  # Atualiza com o timestamp mais recente
                })
                new_history_record = CountryQuizUpdatesHistory(
                    function_name='update_new_country_data_from_semanticdatabase_in_countryQuiz -> data updated',
                    country_label=label,
                    key=key_history,
                    old_data=old_value_history,
                    new_data=new_value_history,
                    timestamp=datetime.utcnow()
                )
                session.add(new_history_record)
                updates_count += 1
        else:
            new_country_record = CountryQuiz(country_label=label, data=json.dumps(new_country), timestamp=new_timestamp) # Utiliza o timestamp do novo dado
            session.add(new_country_record)
            for key, value in new_values.items():
                    new_history_record = CountryQuizUpdatesHistory(
                        function_name='update_new_country_data_from_semanticdatabase_in_countryQuiz -> new country',
                        country_label=label,
                        key=key,
                        old_data="",
                        new_data=value,
                        timestamp=datetime.utcnow()
                    )
    session.commit()  # Commit das alterações
    session.close()   # Encerramento da sessão com o banco de dados
    print(f"Updated {updates_count} fields in CountryQuiz.")

# Gera um arquivo CSV com todas as respostas da IA para blanks de países, para auditoria externa.
def generate_csv_from_country_blanks_of_semanticdatabase():
    """
    Gera um arquivo CSV contendo todas as respostas da IA generativa para lacunas de países.

    O arquivo gerado inclui as colunas: key, country, value, ai_confidence. Utiliza vírgula como delimitador e salva o arquivo para análise ou auditoria externa.

    Returns:
        None
    """
    session = Session()
    # Seleciona os registros com valor vazio para a resposta da IA
    country_data = session.query(CountryBlanksFromSemanticDatabase).filter(
        CountryBlanksFromSemanticDatabase.value_from_ai.is_("")
    ).all()

    output_file = "country_quiz.csv"
    with open(output_file, "w", encoding="utf-8") as csv_file:
        # Escreve o cabeçalho do CSV
        csv_file.write("key,country,value,ai_confidence\n")
        
        for question in country_data:
            try:
                # Caso especial para a chave 'highest_point_label'
                key = question.key
                if question.key == "highest_point_label":
                    key = "highest point"
                
                # Determina o prompt com base na chave e insere o nome do país no lugar dos '**'
                prompt = determine_prompt(key)
                if prompt == "DEFAULT_PROMPT":
                    continue
                else:
                    prompt = prompt.replace("**", question.country_label)
                
                print(prompt)
                
                response = openai.chat.completions.create(
                    model="gpt-4o",  # ou "gpt-4-turbo-preview"
                    messages=[{'role': 'user', 'content': prompt}],
                    temperature=0
                )
                
                # Obtém e trata a resposta da IA, que já deve vir no formato: <value>|<ai_confidence>
                full_response = response.choices[0].message.content.strip()
                if '|' in full_response:
                    # Separa a resposta do percentual de confiança usando a última ocorrência do delimitador
                    answer, confidence = full_response.rsplit("|", 1)
                    answer = answer.strip()
                    confidence = confidence.strip()
                else:
                    answer = full_response
                    confidence = ""
                
                # Exibe no padrão: key|country|value|ai_confidence
                output_line = f"{question.key},{question.country_label},{answer},{confidence}"
                print(output_line)
                
                # Grava a linha no CSV
                csv_file.write(output_line + "\n")
            
            except Exception as e:
                print(f"Erro ao processar a questão {question.id}: {e}")
    
    session.close()

if __name__ == "__main__":
    pass
    #update_new_country_data_from_semanticdatabase_in_countryQuiz()
    #update_country_blanks_from_semanticdatabase_with_ai()
    #update_reported_questions_with_ai()
    #update_countryQuiz_from_approved_questions()
    #update_countryQuiz_from_approved_blanks()
    #generate_csv_from_country_blanks_of_semanticdatabase()