import asyncio
import logging
import os

from dotenv import load_dotenv

# --- CRITICAL FIX: Load environment variables BEFORE other imports ---
load_dotenv()
# --------------------------------------------------------------------

from playwright.async_api import async_playwright

import db
import orchestrator
from bot import bot, dp

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)
# ---------------------

async def main():
    """The main entry point for the application."""
    # This check is now redundant because bot.py does it, but it's good practice
    if not os.getenv("BOT_TOKEN"):
        raise ValueError(
            "Essential environment variable BOT_TOKEN is missing. "
            "Please create a .env file."
        )

    logger.info("Starting application...")

    db.create_db_and_tables()
    logger.info("Database initialized.")

    orchestrator.set_dispatcher(dp)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        logger.info("Browser instance launched.")
        
        session_manager_task = asyncio.create_task(
            orchestrator.session_manager(bot, browser)
        )
        logger.info("Orchestrator session manager started.")
        
        logger.info("Starting bot polling...")
        await asyncio.gather(
            dp.start_polling(bot),
            session_manager_task,
        )

# --- Application Entry Point ---
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Application shutting down gracefully.")


