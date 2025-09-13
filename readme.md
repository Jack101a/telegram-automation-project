Telegram Driving Licence Automation Bot
This project allows a user to initiate a Driving Licence renewal process via a Telegram bot. It automates the form-filling on the Sarathi Parivahan website and uses a human-in-the-loop approach to handle CAPTCHAs and OTPs by asking the user for input in real-time.
How It Works
 * /start: The user starts the bot and is prompted to register their Driving Licence Number and Date of Birth.
 * /submit: The user requests to start a new application. A session is created and queued.
 * Orchestrator: A background process picks up the queued session and starts the browser automation.
 * Automation: The bot navigates the website, fills the user's details, and pauses when it encounters a CAPTCHA or OTP prompt. The flow meticulously follows all steps, including confirmation dialogs, popups, and self-declarations.
 * User Interaction: A screenshot of the CAPTCHA (or a text prompt for OTP) is sent to the user on Telegram.
 * Resume: The user replies with the required information, and the automation continues from where it left off.
 * Completion: The user is notified of the final success or failure of the session, with logs and screenshots saved for review.
Project Structure
 * main.py: The main entry point to start the application.
 * db.py: Handles all database operations (SQLite).
 * bot.py: Defines all Telegram bot commands and message handlers.
 * shared.py: Contains shared state (FSM states, queues) to prevent circular imports.
 * orchestrator.py: Manages the lifecycle of an automation session, coordinating between the bot and browser.
 * automation.py: Contains the detailed Playwright logic for browser interaction, based on the full website flow.
 * requirements.txt: Lists all Python dependencies.
 * .env.example: Template for environment variables.
Setup Instructions
1. Clone the repository:
git clone <your-repo-url>
cd telegram-automation-project

2. Create a virtual environment:
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

3. Create the .env file:
Copy .env.example to .env and add your Telegram Bot Token.
cp .env.example .env
# Now edit .env with your token

4. Install dependencies:
pip install -r requirements.txt
playwright install chromium

5. Run the bot:
python main.py




python3 -m venv venv311
source venv311/bin/activate
python3 main.py
