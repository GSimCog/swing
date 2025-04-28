# 🎉 SWInG - quiz app about countries

Welcome to SWInG, a modern and automated geography quiz platform focused on up-to-date country data and AI-powered validation. The app leverages semantic data sources (mainly Wikidata) and integrates OpenAI (GPT-4o) to fill gaps and validate answers. Everything is designed for reliability, automation, and minimal manual intervention, providing a smooth experience for users and administrators.

## ✨ Key features

- **Diverse questions**: Test your knowledge about capitals, populations, flags, official languages, currencies, continents, and highest points.
- **Automated data loading & updates**: Country data is regularly loaded and updated from semantic sources (Wikidata/DBpedia).
- **AI to complete & validate**: When data is missing from sources, OpenAI generates and validates answers.
- **Automated administration**: Tools for one-click updates, batch propagation of AI suggestions, and real-time logs.
- **Instant feedback**: The admin interface displays detailed logs and live updates.
- **Secure authentication & leaderboard**: Safe registration/login and ranking of top players.
- **Fully documented codebase**: All code is clearly commented (in Portuguese) and follows best practices.

## 🚀 Recent updates

- **Full automation**: All user error checking is now handled by AI. Manual reporting was removed.
- **Consistent logging**: All backend operations log progress and errors, shown live to admins.
- **Admin-only tools**: Only authenticated admins can access update tools and logs.
- **Robust error handling**: All backend routes return standardized JSON for clear frontend feedback.

## 🛠️ Technologies used

- **Backend**: Python 3, Flask, Flask-SQLAlchemy, Flask-Login, SQLAlchemy
- **Database**: SQLite
- **AI integration**: OpenAI API (GPT-4o)
- **Frontend**: HTML5, CSS, JavaScript
- **Configuration**: `quiz.config` for keys and parameters

## 🚦 Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/GSimCog/swing.git
   cd swing
   ```
2. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux/Mac:
   source .venv/bin/activate
   ```
3. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Edit the `quiz.config` file filling in your OpenAI key and other parameters.
5. Start the application:

   ```bash
   python app.py
   ```

## Usage

- **Quiz users**: Register, log in, and start answering country questions. Your score will be tracked and ranked.
- **Admin interface**:
  - Log in as the admin user (configured in the database).
  - Access `/admin/tools` to use the Admin Tools panel.
  - Use the provided buttons to:
    - Update new country data
    - Fill blanks via AI
    - Propagate approved questions/blanks
    - Reload quiz data
  - Real-time logs will appear in the output area, including progress and any errors.
  - Use the "Back" button to return to the main quiz interface.

## Configuration

- Edit `quiz.config` to set your OpenAI API key and other parameters:
  ```ini
  [settings]
  openai_api_key = YOUR_OPENAI_KEY
  ai_confidence_threshold = 90 (example)
  database = WIKIDATA (example)
  ```

## Troubleshooting & Support

- **OpenAI API issues**: Ensure your API key is correct and has sufficient quota.
- **Database errors**: The app uses SQLite by default. If you encounter locking or migration issues, stop the app and try again.
- **Long updates**: Some admin operations may take several minutes depending on data volume and API response times. Progress will be shown in the admin log area.
- **Logs not appearing**: Check the backend console for errors. All backend exceptions are logged and should appear in the admin interface.
- **Further help**: See code comments (in Portuguese) for detailed explanations of each module and function.

## Authors
This research is conducted by a student and a professor from the Instituto Federal do Rio de Janeiro, Brazil.
- **Wagner Luis Cardozo Gomes de Freitas (student)**
- **Jose Ricardo da Silva Junior (research professor and supervisor)**

## Acknowledgments
   - Data sources: [Wikidata](https://www.wikidata.org/), [DBpedia](https://www.dbpedia.org/)
   - Frontend framework: [Simple.css](https://simplecss.org/)
   - [Instituto Federal do Rio de Janeiro](https://www.ifrj.edu.br/)

## Contributing

Contributions are welcome! Please open issues or submit pull requests for improvements or bug fixes.

## License

This project is licensed under the MIT License.

## Usage
- Go to `http://localhost:5000` in your browser.
- Register a new account or log in.
- Play the quiz!
- Admin users can access special routes to review and approve AI suggestions.

## Main File Structure

- `app.py`: Main Flask app, routes, models, and quiz logic.
- `data_update.py`: Scripts for automated data update and validation.
- `quiz.config`: Sensitive settings (API keys, AI parameters, etc).
- `requirements.txt`: Project dependencies.
- `templates/`: HTML templates for the app.

## Security
- **Authentication**: Users and admins are authenticated via Flask-Login.
- **API Keys**: Never expose your OpenAI key publicly.

## Contributing
Open issues or pull requests to suggest improvements!

---

<img src="https://github.com/GSimCog/swing/blob/release/1.0-beta/extra/img01.png" width="300">
<img src="https://github.com/GSimCog/swing/blob/release/1.0-beta/extra/img02.png" width="300">
<img src="https://github.com/GSimCog/swing/blob/release/1.0-beta/extra/img03.png" width="300">
<img src="https://github.com/GSimCog/swing/blob/release/1.0-beta/extra/img04.png" width="800">
<img src="https://github.com/GSimCog/swing/blob/release/1.0-beta/extra/img05.png" width="300">
<img src="https://github.com/GSimCog/swing/blob/release/1.0-beta/extra/img06.png" width="300">
