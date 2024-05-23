# infosage

This App is a comprehensive tool designed to test and improve your knowledge of countries around the world. The app presents questions about capitals, flags, populations, continents, highest points, and currencies. Additionally, the national anthem of the country in question is played to enhance the user experience. The data for the quiz is sourced from semantic databases such as Wikidata and DBpedia.

## Features

- **User Authentication**: Users can register, log in, and view their scores.
- **Quiz Functionality**: Users are presented with questions about different countries.
- **Dynamic Data**: The app retrieves and updates country data from Wikidata and DBpedia.
- **Review Mistakes**: Users can review their mistakes after completing the quiz.
- **Admin Features**: Admin users can manage reported questions and country updates.

## Files

- `app.py`: Main application file containing the logic for the app.
- `data_update.py`: Script for updating country data from semantic databases.
- `requirements.txt`: List of Python dependencies required for the app.
- HTML Templates:
  - `country_updates.html`: Template for displaying country updates.
  - `login.html`: Template for the login page.
  - `quiz.html`: Template for the quiz page.
  - `register.html`: Template for the registration page.
  - `reported_questions.html`: Template for managing reported questions.
  - `result.html`: Template for displaying quiz results.
- `no_flag.png`: Placeholder image for countries without a flag image.

## Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/GSimCog/infosage.git
   cd country-quiz-app

2. **Create a virtual environment**:
    ```bash
   python -m venv venv
   source venv/bin/activate   # On Windows, use `venv\Scripts\activate`

3. **Install dependencies**:
    ```bash
   pip install -r requirements.txt

4. **Adjust the configuration file `quiz.config`**:
    ``` bash
    [settings]
database = WIKIDATA
dbpedia_sparql_query = PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> PREFIX dbo: <http://dbpedia.org/ontology/> PREFIX dbp: <http://dbpedia.org/property/> PREFIX dbc: <http://dbpedia.org/resource/Category:> PREFIX dct: <http://purl.org/dc/terms/> SELECT ?country_label ?capital_label ?currency_label ?population ?flag_label ?flag_image ?determination_method_label ?flagStatement ?official_Language_label #?continent_label ?highestPoint_label  WHERE { ?country rdf:type dbo:Country ; dct:subject dbc:Member_states_of_the_United_Nations . OPTIONAL { ?country dbp:capital ?capital . } OPTIONAL { ?country dbp:currency ?currency . } OPTIONAL { ?country dbp:populationEstimate ?population . } OPTIONAL { ?country dbo:thumbnail ?flag_image . } OPTIONAL { ?country dbo:officialLanguage ?official_Language . } #OPTIONAL { ?country dbp:continent ?continent. } #OPTIONAL { ?country dbp:highestPoint ?highestPoint. } ?country rdfs:label ?country_label . ?capital rdfs:label ?capital_label . ?currency rdfs:label ?currency_label . ?official_Language rdfs:label ?official_Language_label . #?continent rdfs:label ?continent_label. #?highestPoint rdfs:label ?highestPoint_label. ?country rdfs:label ?flag_label, ?determination_method_label, ?flagStatement . FILTER (((lang(?country_label)) = "en") && ((lang(?capital_label)) = "en") && ((lang(?currency_label)) = "en") && ((lang(?determination_method_label)) = "en") && ((lang(?flagStatement)) = "en") && ((lang(?flag_label)) = "en") && ((lang(?official_Language_label)) = "en")) #&&  #((LANG(?continent_label)) = "en") &&  #((LANG(?highestPoint_label)) = "en")  }
wikidata_sparql_query = PREFIX wd: <http://www.wikidata.org/entity/> PREFIX wdt: <http://www.wikidata.org/prop/direct/> PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> PREFIX p: <http://www.wikidata.org/prop/> PREFIX ps: <http://www.wikidata.org/prop/statement/> PREFIX pq: <http://www.wikidata.org/prop/qualifier/> PREFIX wikibase: <http://wikiba.se/ontology#>  SELECT DISTINCT ?country_label ?capital_label ?currency_label ?population ?flag_label   ?flag_image ?determination_method_label ?flagStatement ?anthem_audio ?official_Language_label   ?continent_label ?highest_point_label WHERE {   ?country wdt:P31 wd:Q3624078 .   FILTER NOT EXISTS {     ?country wdt:P31 wd:Q3024240 .   }   FILTER NOT EXISTS {     ?country wdt:P31 wd:Q28171280 .   }   OPTIONAL {     ?country wdt:P36 ?capital .   }   OPTIONAL {     ?country p:P36 ?capitalStatement .     ?capitalStatement ps:P36 ?capital .     ?capitalStatement pq:P459 ?determination_method .     ?determination_method rdfs:label ?determination_method_label .     FILTER (lang(?determination_method_label) = "en")   }   OPTIONAL {     ?country wdt:P38 ?currency .   }   OPTIONAL {     ?country wdt:P1082 ?population .   }   OPTIONAL {     ?country p:P41 ?flagStatement .     ?flagStatement ps:P41 ?flag_image .     ?flagStatement wikibase:rank wikibase:PreferredRank .     FILTER NOT EXISTS {       ?flagStatement pq:P582 ?endTime .     }   }   OPTIONAL {     ?country wdt:P85 ?anthem .     ?anthem wdt:P51 ?anthem_audio .   }   OPTIONAL {     ?country p:P37 ?official_languageStatement .     ?official_languageStatement ps:P37 ?official_language .     ?official_languageStatement wikibase:rank wikibase:PreferredRank .   }   OPTIONAL {     ?country wdt:P30 ?continent .   }   OPTIONAL {     ?country wdt:P610 ?highest_point .   }   SERVICE wikibase:label {     ?country rdfs:label ?country_label .     ?capital rdfs:label ?capital_label .     ?currency rdfs:label ?currency_label .     ?country rdfs:label ?flag_label .     ?official_language rdfs:label ?official_Language_label .     ?continent rdfs:label ?continent_label .     ?highest_point rdfs:label ?highest_point_label .     bd:serviceParam wikibase:language "en" .   } }
openai_api_key = <your_key>

## Usage

1. **Run the application**:
    ```bash
   python app.py

2. **Access the app**:
   Open your web browser and go to `http://127.0.0.1:5000`.

## Directory Structure

```
infosage/
├── app.py
├── data_update.py
├── requirements.txt
├── templates/
│   ├── country_updates.html
│   ├── login.html
│   ├── quiz.html
│   ├── register.html
│   ├── reported_questions.html
│   ├── result.html
├── static/
│   ├── no_flag.png
└── README.md
```
## License
   This project is licensed under the MIT License. See the LICENSE file for more details.

## Acknowledgments
   - Data sources: Wikidata, DBpedia
   - Frontend framework: Simple.css
