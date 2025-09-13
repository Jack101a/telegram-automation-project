"""
Part 5: Main Application (main.py)

This is the main entry point for the Telegram Automation Bot.
It integrates all the modules:
- db.py: For database setup and operations.
- bot.py: For handling Telegram user interactions.
- automation.py: For executing the browser automation logic.
- orchestrator.py: For managing the state and flow of automation sessions.

To run this application:
1. Make sure you have all the other .py files in the same directory.
2. Create a .env file with your BOT_TOKEN and a BOT_ENCRYPTION_KEY.
3. Run `pip install -r requirements.txt`.
4. Run `playwright install chromium`.
5. Run `python main.py`.
"""

import asyncio
import logging
import os

from dotenv import load_dotenv

# --- Local Application Imports ---
# These imports bring in the components we've built.
import db
from bot import dp, bot  # Import the dispatcher and bot instances from bot.py
import orchestrator

# --- Configuration and Setup ---

# 1. Load Environment Variables
# This loads the BOT_TOKEN and BOT_ENCRYPTION_KEY from your .env file.
load_dotenv()
if not os.getenv("BOT_TOKEN") or not os.getenv("BOT_ENCRYPTION_KEY"):
    raise ValueError(
        "Essential environment variables BOT_TOKEN or BOT_ENCRYPTION_KEY are missing. "
        "Please create a .env file based on .env.example."
    )

# 2. Logging Configuration
# A central place to set up logging for the entire application.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("automation_bot.log") # Log to a file
    ]
)
logger = logging.getLogger(__name__)


# --- Main Asynchronous Function ---

async def main():
    """
    The main function that initializes and runs all application components.
    """
    logger.info("Application starting up...")

    # 1. Initialize the Database
    # This creates the SQLite database file and all the necessary tables
    # if they don't already exist.
    db.initialize_database()
    logger.info("Database initialized successfully.")

    # 2. Link the Orchestrator to the Bot's Dispatcher
    # This is a critical step. The orchestrator needs access to the bot's
    # dispatcher to be able to set FSM states for users when it needs
    # to ask for a CAPTCHA or OTP.
    orchestrator.set_dispatcher(dp)
    logger.info("Orchestrator linked with the bot dispatcher.")

    # 3. Create Concurrent Tasks
    # We will run the bot polling and the session manager at the same time.
    # - The bot_polling task listens for new messages from users on Telegram.
    # - The session_manager task polls the database for new 'QUEUED' sessions
    #   and starts processing them.
    bot_polling_task = asyncio.create_task(
        dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    )
    
    session_manager_task = asyncio.create_task(
        orchestrator.session_manager(bot)
    )

    logger.info("Bot polling and session manager are running concurrently.")
    
    # 4. Run the tasks forever
    # asyncio.gather will run both tasks until one of them finishes (which they shouldn't
    # under normal circumstances). If one fails, it will raise the exception.
    await asyncio.gather(
        bot_polling_task,
        session_manager_task
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Application shutting down.")
    except Exception as e:
        logger.critical(f"A critical error caused the application to stop: {e}", exc_info=True)


