import asyncio
import logging
from playwright.async_api import Browser, TimeoutError
from aiogram import Bot, Dispatcher
from aiogram.fsm.context import FSMContext

import db
import automation
from shared import AutomationFlow, USER_INPUT_QUEUES

# --- Logging Setup ---
logger = logging.getLogger(__name__)

# --- State Management ---
ACTIVE_SESSIONS = set()
_dispatcher: Dispatcher = None

def set_dispatcher(dp: Dispatcher):
    global _dispatcher
    _dispatcher = dp

# --- Orchestration Main Loop ---
async def session_manager(bot: Bot, browser: Browser):
    logger.info("Session manager started.")
    while True:
        with db.SessionLocal() as session:
            queued_sessions = session.query(db.Session).filter(
                db.Session.state == "QUEUED",
                db.Session.session_id.notin_(ACTIVE_SESSIONS)
            ).all()

            for sess in queued_sessions:
                if sess.session_id not in ACTIVE_SESSIONS:
                    ACTIVE_SESSIONS.add(sess.session_id)
                    logger.info(f"Starting orchestration for new session: {sess.session_id}")
                    asyncio.create_task(orchestrate_session(sess.session_id, bot, browser))
        await asyncio.sleep(2)

async def orchestrate_session(session_id: str, bot: Bot, browser: Browser):
    page = None
    context = None
    user_id = None
    try:
        with db.SessionLocal() as session:
            db_session = session.query(db.Session).filter(db.Session.session_id == session_id).first()
            if not db_session:
                raise ValueError(f"Session {session_id} not found.")
            user_id = db_session.user.user_id
            user_data = db.get_user_data(user_id)
            if not user_data:
                raise ValueError(f"User data for {user_id} not found.")

        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        
        # --- CHANGE START: POP-UP HANDLING ---
        # This function will run automatically whenever a dialog appears.
        async def handle_dialog(dialog):
            logger.info(f"[{session_id}] Auto-accepting dialog: '{dialog.message}'")
            await dialog.accept()
        
        # We attach the handler to the 'dialog' event for the entire session.
        context.on("dialog", handle_dialog)
        # --- CHANGE END ---
        
        page = await context.new_page()

        current_state = "QUEUED"
        while current_state not in ["COMPLETED", "FAILED"]:
            result = await automation.execute_automation_step(
                page=page,
                session_id=session_id,
                current_state=current_state,
                user_data=user_data
            )

            current_state = result["next_state"]
            db.update_session_state(session_id, current_state)

            if result["status"] == "PAUSE_FOR_CAPTCHA":
                await bot.send_photo(chat_id=user_id, photo=open(result["captcha_path"], "rb"), caption="Please solve this CAPTCHA.")
                fsm_context = FSMContext(_dispatcher.storage, chat_id=user_id, bot_id=bot.id)
                await fsm_context.set_state(AutomationFlow.awaiting_captcha)
                await fsm_context.update_data(session_id=session_id)
                captcha_input = await USER_INPUT_QUEUES[session_id].get()
                await page.locator(result["target_selector"]).fill(captcha_input)

            elif result["status"] == "PAUSE_FOR_OTP":
                await bot.send_message(user_id, "Please enter the OTP sent to your device.")
                fsm_context = FSMContext(_dispatcher.storage, chat_id=user_id, bot_id=bot.id)
                await fsm_context.set_state(AutomationFlow.awaiting_otp)
                await fsm_context.update_data(session_id=session_id)
                otp_input = await USER_INPUT_QUEUES[session_id].get()
                await page.locator(result["target_selector"]).fill(otp_input)

        final_result = result.get("details", "Session finished.")
        db.update_session_state(session_id, current_state, result=final_result)
        await bot.send_message(user_id, f"Session {session_id} finished with state: {current_state}\nDetails: {final_result}")

    except (Exception, TimeoutError) as e:
        logger.error(f"Session {session_id} failed critically: {e}", exc_info=True)
        db.update_session_state(session_id, "FAILED", result=str(e))
        if user_id:
            await bot.send_message(user_id, f"Sorry, your session {session_id} failed with an unexpected error.")
    
    finally:
        if page: await page.close()
        if context: await context.close()
        if session_id in ACTIVE_SESSIONS: ACTIVE_SESSIONS.remove(session_id)
        if session_id in USER_INPUT_QUEUES: del USER_INPUT_QUEUES[session_id]
        logger.info(f"Finished and cleaned up session: {session_id}")


