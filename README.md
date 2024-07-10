# infosage

This App is a comprehensive tool designed to test and improve your knowledge of countries around the world. The app presents questions about capitals, flags, populations, continents, highest points, and currencies. Additionally, the national anthem of the country in question is played to enhance the user experience. The data for the quiz is sourced from semantic databases such as Wikidata and DBpedia.

## Authors
This research is conducted by a student and a professor from the Instituto Federal do Rio de Janeiro, Brazil.
- **Wagner Luis Cardozo Gomes de Freitas (student)**
- **Jose Ricardo da Silva Junior (research professor and supervisor)**

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
- `quiz.config`: The app configuration file.
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
   cd infosage

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
   dbpedia_sparql_query = PREFIX rdf...
   wikidata_sparql_query = PREFIX wd...
   openai_api_key = <your_key>

## Usage

1. **Run the application**:
    ```bash
   python app.py
   python data_update.py # To manually update the local database

2. **Access the app**:
   ```
   Open your web browser and go to `http://127.0.0.1:5000`.

## Directory Structure

```
infosage/
├── app.py
├── data_update.py
├── quiz.config
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
   This project is licensed under the [MIT License](https://www.mit.edu/~amini/LICENSE.md). See the LICENSE file for more details.

## Acknowledgments
   - Data sources: [Wikidata](https://www.wikidata.org/), [DBpedia](https://www.dbpedia.org/)
   - Frontend framework: [Simple.css](https://simplecss.org/)
