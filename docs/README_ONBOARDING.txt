# Onboarding Rápido — Quiz App

## 1. Setup do Ambiente
1. Clone o repositório e acesse a pasta `quiz_v3`.
2. Crie e ative um ambiente virtual Python:
   - Linux/Mac: `python -m venv .venv && source .venv/bin/activate`
   - Windows: `python -m venv .venv && .venv\Scripts\activate`
3. Instale as dependências:
   ```
   pip install -r requirements.txt
   ```
4. Configure o arquivo `quiz.config` conforme o exemplo:
   ```
   [settings]
   database = WIKIDATA
   openai_api_key = SUA_CHAVE_OPENAI
   ai_confidence_threshold = 95
   dbpedia_sparql_query = 
   wikidata_sparql_query = 
   ```
5. Execute o app:
   ```
   python app.py
   ```

## 2. Exemplos de Uso de Endpoints
- **Login:**
  ```
  POST /login
  username=admin&password=suasenha
  ```
- **Registrar Usuário:**
  ```
  POST /register
  username=novo_usuario&password=senha123&email=usuario@email.com
  ```
- **Quiz:**
  ```
  GET /
  POST /
  ```
- **Painel Admin:**
  ```
  GET /admin/tools
  GET /admin/history
  POST /admin/run_update/<acao>
  ```

## 3. Rotinas Batch Python
- Atualizar perguntas reportadas com IA:
  ```python
  from data_update import update_reported_questions_with_ai
  update_reported_questions_with_ai()
  ```
- Atualizar blanks de países com IA:
  ```python
  from data_update import update_country_blanks_from_semanticdatabase_with_ai
  update_country_blanks_from_semanticdatabase_with_ai()
  ```

## 4. Diagrama Simplificado

Usuário/Admin
  |
Flask App (app.py)
  |
Banco de Dados (SQLAlchemy/SQLite)
  |
data_update.py <-> OpenAI API
  |
Wikidata/DBpedia (SPARQL)

Painel Admin -> Histórico & Aprovação Manual
Quiz -> Perguntas & Respostas
Rotinas Batch -> Atualização Automática

## 5. Troubleshooting
- Verifique o arquivo `quiz.config`.
- Rode o app com `debug=True` para logs detalhados.
- Cheque a chave OpenAI e conexão de internet.
- Consulte a documentação HTML em `docs/api_documentation.html` para detalhes de modelos e fluxos.
