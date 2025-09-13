"""
Part 4: Orchestration and State Machine (orchestrator.py)

This module is the core of the application, connecting the bot (user interface)
and the automation module (browser actions). It polls the database for new
sessions, manages the state of each active session, and facilitates the
human-in-the-loop interaction for CAPTCHAs and OTPs.

Key Features:
- A session manager that polls for 'QUEUED' jobs and runs them concurrently.
- An orchestrator function that manages the lifecycle of a single session.
- Use of asyncio.Queue for non-blocking communication between the bot and a running session.
- Manages Playwright browser contexts, ensuring each session is isolated.
- Updates the database with the current state of the session.
- Handles timeouts for user input.
"""

import asyncio
import logging
from typing import Dict, Any

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile
from playwright.async_api import async_playwright, Browser, Page

# Local application imports
import db
import automation
from bot import AutomationFlow # Import FSM states from bot

# --- Configuration ---
POLLING_INTERVAL_SECONDS = 5  # How often to check the DB for new sessions
USER_INPUT_TIMEOUT_SECONDS = 300  # 5 minutes to respond to a prompt

# --- Concurrency and Communication Management ---
# This dictionary will hold asyncio Queues, one for each session that is
# actively waiting for user input. The key is the session_id.
USER_INPUT_QUEUES: Dict[str, asyncio.Queue] = {}

# This set tracks the session IDs that are currently being processed
# to prevent the poller from picking up the same job twice.
ACTIVE_SESSIONS = set()

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# --- Core Orchestration Logic ---

async def orchestrate_session(session_id: str, bot: Bot):
    """
    Manages the entire lifecycle of a single automation session.
    """
    if session_id in ACTIVE_SESSIONS:
        logger.warning(f"Attempted to start an already active session: {session_id}")
        return

    ACTIVE_SESSIONS.add(session_id)
    logger.info(f"Starting orchestration for session: {session_id}")

    # 1. Fetch session and user data
    session_data = db.SessionLocal().query(db.Session).filter_by(session_id=session_id).first()
    if not session_data:
        logger.error(f"Session {session_id} not found in database.")
        ACTIVE_SESSIONS.remove(session_id)
        return
        
    user_id = session_data.user_telegram_id
    user_data = db.get_user_data(user_id)
    if not user_data:
        logger.error(f"User data for telegram_id {user_id} not found.")
        db.update_session_state(session_id, "FAILED", "User data not found")
        ACTIVE_SESSIONS.remove(session_id)
        return

    # 2. Setup isolated browser context
    browser: Browser = None
    page: Page = None
    try:
        # NOTE: For production, a shared browser instance is more efficient.
        # Here we launch one per session for maximum isolation.
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True) # Set headless=False for debugging
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            )
            page = await context.new_page()

            current_state = session_data.state
            user_input = None
            
            # 3. Main State Machine Loop
            while current_state not in ["COMPLETED", "FAILED"]:
                db.update_session_state(session_id, f"RUNNING_{current_state}")
                
                # Execute the next step in the automation
                result = await automation.execute_automation_step(
                    page, session_id, user_data, current_state, user_input
                )
                
                status = result.get("status")

                # --- Handle CAPTCHA Pause ---
                if status in ["PAUSE_AWAITING_CAPTCHA", "RETRY_AWAITING_CAPTCHA"]:
                    current_state = result["next_state"]
                    db.update_session_state(session_id, current_state)
                    
                    if status == "RETRY_AWAITING_CAPTCHA":
                        await bot.send_message(user_id, "The previous CAPTCHA was incorrect. Please try this new one.")

                    # Send the CAPTCHA image to the user
                    await bot.send_photo(
                        chat_id=user_id,
                        photo=FSInputFile(result["captcha_path"]),
                        caption="Please solve this CAPTCHA and send the text back to me."
                    )
                    
                    # Wait for the user's response
                    try:
                        fsm_context = FSMContext(storage=dp.storage, key=bot.id, chat_id=user_id, user_id=user_id)
                        await fsm_context.set_state(AutomationFlow.awaiting_captcha)
                        await fsm_context.update_data(session_id=session_id)

                        queue = asyncio.Queue(maxsize=1)
                        USER_INPUT_QUEUES[session_id] = queue
                        user_input = await asyncio.wait_for(queue.get(), timeout=USER_INPUT_TIMEOUT_SECONDS)
                    except asyncio.TimeoutError:
                        logger.warning(f"Session {session_id} timed out waiting for CAPTCHA.")
                        await bot.send_message(user_id, "You took too long to respond. The session has timed out.")
                        current_state = "FAILED"
                        db.update_session_state(session_id, "FAILED", "Timeout on CAPTCHA")
                        continue # Re-enter loop to terminate
                    finally:
                        USER_INPUT_QUEUES.pop(session_id, None)

                # --- Handle OTP Pause ---
                elif status == "PAUSE_AWAITING_OTP":
                    current_state = result["next_state"]
                    db.update_session_state(session_id, current_state)
                    
                    await bot.send_message(user_id, "An OTP has been sent to your registered mobile number. Please send it back to me.")
                    
                    # Wait for OTP response
                    try:
                        fsm_context = FSMContext(storage=dp.storage, key=bot.id, chat_id=user_id, user_id=user_id)
                        await fsm_context.set_state(AutomationFlow.awaiting_otp)
                        await fsm_context.update_data(session_id=session_id)
                        
                        queue = asyncio.Queue(maxsize=1)
                        USER_INPUT_QUEUES[session_id] = queue
                        user_input = await asyncio.wait_for(queue.get(), timeout=USER_INPUT_TIMEOUT_SECONDS)
                    except asyncio.TimeoutError:
                        logger.warning(f"Session {session_id} timed out waiting for OTP.")
                        await bot.send_message(user_id, "You took too long to respond. The session has timed out.")
                        current_state = "FAILED"
                        db.update_session_state(session_id, "FAILED", "Timeout on OTP")
                        continue
                    finally:
                        USER_INPUT_QUEUES.pop(session_id, None)
                
                # --- Handle Success ---
                elif status == "SUCCESS":
                    current_state = "COMPLETED"
                    db.update_session_state(session_id, "COMPLETED", "SUCCESS")
                    await bot.send_message(user_id, "Automation completed successfully!")
                    if result.get("screenshot_path"):
                        await bot.send_photo(
                            chat_id=user_id,
                            photo=FSInputFile(result["screenshot_path"]),
                            caption="Final confirmation."
                        )

                # --- Handle Failure ---
                elif status == "FAILURE":
                    current_state = "FAILED"
                    reason = result.get("reason", "An unknown error occurred.")
                    db.update_session_state(session_id, "FAILED", reason)
                    await bot.send_message(user_id, f"Automation failed. Reason: {reason}")
                    if result.get("screenshot_path"):
                        await bot.send_photo(
                            chat_id=user_id,
                            photo=FSInputFile(result["screenshot_path"]),
                            caption="This was the last screen before the error."
                        )
                else:
                    logger.error(f"Automation for {session_id} returned an unknown status: {status}")
                    current_state = "FAILED"
                    db.update_session_state(session_id, "FAILED", "Unknown automation status")
    
    except Exception as e:
        logger.critical(f"A critical error occurred in orchestrator for session {session_id}: {e}", exc_info=True)
        db.update_session_state(session_id, "FAILED", "Orchestrator critical failure")
        try:
            await bot.send_message(user_id, "A critical system error occurred during your session. It has been terminated.")
        except Exception as bot_err:
            logger.error(f"Failed to notify user {user_id} about critical error: {bot_err}")

    finally:
        # 4. Cleanup
        if page: await page.close()
        if browser: await browser.close()
        ACTIVE_SESSIONS.remove(session_id)
        logger.info(f"Finished orchestration for session: {session_id}")


# --- Session Manager ---

async def session_manager(bot: Bot):
    """
    Continuously polls the database for new sessions and starts orchestration tasks for them.
    """
    logger.info("Session manager started. Polling for new jobs...")
    while True:
        with db.SessionLocal() as session:
            queued_sessions = session.query(db.Session).filter(
                db.Session.state == "QUEUED",
                db.Session.session_id.notin_(ACTIVE_SESSIONS)
            ).all()

        if queued_sessions:
            tasks = []
            for sess in queued_sessions:
                logger.info(f"Found new queued session: {sess.session_id}")
                # Use asyncio.create_task to run orchestrations concurrently
                task = asyncio.create_task(orchestrate_session(sess.session_id, bot))
                tasks.append(task)
            
            await asyncio.gather(*tasks) # This is optional, but can be useful
        
        await asyncio.sleep(POLLING_INTERVAL_SECONDS)

# This needs the dispatcher instance from the bot to set FSM states correctly.
# It will be imported in the final main.py
dp = None

def set_dispatcher(dispatcher):
    global dp
    dp = dispatcher


