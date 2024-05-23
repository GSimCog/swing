from app import ReportedQuestion, CountryBlanksFromSemanticDatabase, CountryQuiz, CountryQuizUpdatesHistory, CountryFromSemanticDatabase, get_country_data
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

engine = create_engine(DATABASE_URI)
session_factory = sessionmaker(bind=engine)
Session = scoped_session(session_factory)

def determine_prompt(question_text):
    """Determina o prompt adequado para uma pergunta com base em palavras-chave específicas.

    Args:
        question_text (str): Texto da pergunta a partir do qual o prompt é gerado.

    Returns:
        str: Prompt selecionado para a pergunta.
    """
    keywords_to_prompts = {
        "capital": "What is the capital of (the) **, without abbreviations, commas, or periods? Give me the answer as currently as possible with only the capital name. If there is more than one, give me only the capital names separated by the word 'or'.",
        "currency": "What is the currency of (the) **, without abbreviations, commas, or periods? Give me the answer as currently as possible with only the currency name. If there is more than one, give me only the currency names separated by the word 'or'.",
        "population": "What is the exact numeric population of (the) ** in digits, without abbreviations, commas, or periods? Give me the answer as currently as possible in digits; only one number.",
        "language": "What is the official language of (the) **, without abbreviations, commas, or periods? Give me the answer as currently as possible with only the language name. If there is more than one, give me only the language names separated by the word 'or'.",
        "continent": "Which continent does (the) ** belong to? Without abbreviations, commas, or periods. Give me the answer as currently as possible with only the continent name. If there is more than one, give me only the continent names separated by the word 'or'.",
        "highest point": "What is the highest point of (the) **, without abbreviations, commas, or periods? Give me the answer as currently as possible with only the highest point name. If there is more than one, give me only the highest point names separated by the word 'or'.",
        "flag": "Provide one URL of the official flag as currently as possible of (the) **. This URL must refer to a web image file such as SVG, JPG, or PNG. Provide only the URL.",
        "anthem": "Provide one URL of the official anthem as currently as possible of (the) **. This URL must refer to a web sound file such as OGG. Provide only the URL.",
    }
    for keyword, prompt in keywords_to_prompts.items():
        if keyword in question_text.lower():
            return prompt
    return "DEFAULT_PROMPT"

def update_reported_questions_with_ai():
    """Atualiza perguntas reportadas usando respostas geradas pela API OpenAI.

    Usa prompts determinados para cada pergunta e salva as respostas no banco de dados.
    """
    session = Session()
    reported_questions = session.query(ReportedQuestion).filter(ReportedQuestion.value_from_ai.is_("")).all()
    for question in reported_questions:
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

def update_country_blanks_from_semanticdatabase_with_ai():
    """Atualiza entradas de país com dados faltantes usando respostas da API OpenAI.

    Identifica lacunas nos dados, usa a IA para gerar preenchimentos e atualiza o banco de dados.
    """
    session = Session()
    country_data = session.query(CountryBlanksFromSemanticDatabase).filter(CountryBlanksFromSemanticDatabase.value_from_ai.is_("")).all()
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
            print(response.choices[0].message.content.strip())
            question.value_from_ai = response.choices[0].message.content.strip()
            session.commit()

            # Teste -- apenas uma consulta na OpenAI API
            #break
        
        except Exception as e:
            print(f"Erro ao atualizar a questão {question.id}: {e}")
    session.close()

def update_countryQuiz_from_approved_questions():
    """Atualiza o quiz com respostas aprovadas de perguntas reportadas.

    Verifica questões aprovadas que ainda não foram atualizadas, atualiza os dados do quiz e registra o histórico.
    """
    session = Session()
    approved_questions = session.query(ReportedQuestion)\
        .filter(ReportedQuestion.approved == True, ReportedQuestion.value_updated == False).all()
    for question in approved_questions:
        json_field = None
        requires_value_key = True  # Flag para indicar se o campo requer "value: " antes do valor
        if "population" in question.question:
            json_field = "population"
        elif "capital" in question.question:
            json_field = "capital_label"
        elif "currency" in question.question:
            json_field = "currency_label"
        elif "flag" in question.question:
            json_field = "flag_image"
        elif "continent" in question.question:
            json_field = "continent_label"
        elif "highest point" in question.question:
            json_field = "highest_point_label"
        elif "language" in question.question:
            json_field = "official_language_label"
        if json_field:
            country = session.query(CountryQuiz).filter(CountryQuiz.country_label == question.country).first()
            if country:
                country_data = json.loads(country.data) if country.data else {}
                country_label = question.country
                old_data = question.correct_answer
                if requires_value_key:
                    if json_field not in country_data or not isinstance(country_data[json_field], dict):
                        country_data[json_field] = {"value": question.value_from_ai}
                    else:
                        country_data[json_field]["value"] = question.value_from_ai
                else:
                    country_data[json_field] = question.value_from_ai
                country.data = json.dumps(country_data)
                country.timestamp = datetime.utcnow()
                new_history_record = CountryQuizUpdatesHistory(
                    function_name='update_countryQuiz_from_approved_questions',
                    country_label=country_label,
                    key=json_field,
                    old_data=old_data,
                    new_data=question.value_from_ai,
                    timestamp=datetime.utcnow()
                )
                session.add(new_history_record)
                question.value_updated = True
    session.commit()
    session.close()

def update_countryQuiz_from_approved_blanks():
    """Atualiza o quiz com dados aprovados que estavam em branco.

    Busca por atualizações aprovadas, aplica as atualizações no quiz e registra o histórico das mudanças.
    """
    session = Session()
    approved_updates = session.query(CountryBlanksFromSemanticDatabase)\
        .filter(CountryBlanksFromSemanticDatabase.approved == True, CountryBlanksFromSemanticDatabase.value_updated == False).all()
    for update in approved_updates:
        country = session.query(CountryQuiz).filter(CountryQuiz.country_label == update.country_label).first()
        if country:
            country_data = json.loads(country.data) if country.data else {}
            country_label = update.country_label
            old_data = update.current_value
            update_value = update.value_from_ai
            if isinstance(country_data.get(update.key, ""), dict):
                update_value = {"value": update.value_from_ai}
            country_data[update.key] = update_value
            country.data = json.dumps(country_data)
            country.timestamp = datetime.utcnow()
            new_history_record = CountryQuizUpdatesHistory(
                function_name='update_countryQuiz_from_approved_blanks',
                country_label=country_label,
                key=update.key,
                old_data=old_data,
                new_data=update.value_from_ai,
                timestamp=datetime.utcnow()
            )
            session.add(new_history_record)
            update.value_updated = True
    session.commit()
    session.close()

def update_new_country_data_from_semanticdatabase_in_countryQuiz():
    """Atualiza o quiz com novos dados de países obtidos de fontes semânticas.

    Exclui países não informados na nova consulta. Compara novos dados com os existentes, atualiza conforme necessário e registra as mudanças no histórico.
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
        new_values = {k: v['value'] for k, v in new_country.items() if 'value' in v}  # Ajuste para extrair valores corretos
        if label in existing_data:
            current_data, current_timestamp = existing_data[label]
            updated_data = current_data.copy()
            update_needed = False
            for key, new_value in new_values.items():
                if new_value in ["./static/images/no_flag.png", "no_audio"]:
                    continue
                old_value = current_data.get(key, {}).get('value', None)
                if old_value != new_value and new_value not in [None, ''] and new_timestamp > current_timestamp:
                    updated_data[key] = {'value': new_value}
                    update_needed = True
                    key_history = key
                    old_value_history = old_value
                    new_value_history = new_value
                    existing_entry = CountryBlanksFromSemanticDatabase.query.filter_by(country_label=label, key=key).first()
                    if existing_entry:
                      session.query(CountryBlanksFromSemanticDatabase).filter(and_(CountryBlanksFromSemanticDatabase.country_label == label, CountryBlanksFromSemanticDatabase.key == key)).update({
                        'value_updated': True
                      })
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
                    session.add(new_history_record)
                    updates_count += 1
    session.commit()  # Commit das alterações
    session.close()   # Encerramento da sessão com o banco de dados
    print(f"Updated {updates_count} fields in CountryQuiz.")

if __name__ == "__main__":
    pass
    update_reported_questions_with_ai()
    update_country_blanks_from_semanticdatabase_with_ai()
    update_countryQuiz_from_approved_questions()
    update_countryQuiz_from_approved_blanks()
    update_new_country_data_from_semanticdatabase_in_countryQuiz()