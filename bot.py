"""
Part 2: Telegram Bot Core (bot.py)

This module contains the core logic for the Telegram bot using the aiogram library.
It handles user interactions, manages state using FSM (Finite State Machine),
and orchestrates the user-facing side of the automation process.

Key Features:
- Handles user registration (/start) and submission requests (/submit).
- Uses FSMContext to manage multi-step conversations (e.g., collecting serial no, DOB).
- Interacts with the database module (db.py) to store and retrieve user data.
- Defines states for waiting on user input for CAPTCHA and OTP.
- Includes basic validation for user inputs.
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional
from orchestrator import USER_INPUT_QUEUES


# Third-party libraries - ensure you have run:
# pip install aiogram python-dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardRemove
from dotenv import load_dotenv

# Local application imports
import db
from db import get_user_data, add_or_update_user, create_session, get_active_session

# --- Configuration ---
load_dotenv() # Load environment variables from .env file

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")

# We need the encryption key for the DB module to work
if not os.getenv("BOT_ENCRYPTION_KEY"):
    # db.py will generate a temporary one and warn, which is fine for dev.
    logging.warning("BOT_ENCRYPTION_KEY is not set. A temporary key will be used.")

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Bot and Dispatcher Initialization ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- FSM State Definitions ---

class UserRegistration(StatesGroup):
    """States for the initial user registration process."""
    getting_serial_no = State()
    getting_dob = State()

class AutomationFlow(StatesGroup):
    """
    States for an active automation session.
    The orchestrator will put the user into these states.
    """
    awaiting_captcha = State()
    awaiting_otp = State()


# --- Command Handlers ---

@dp.message(CommandStart())
async def handle_start(message: Message, state: FSMContext):
    """
    Handles the /start command.
    Greets the user and starts the registration process if they are new.
    """
    telegram_id = message.from_user.id
    logger.info(f"User {telegram_id} initiated /start command.")
    
    await state.clear() # Clear any previous state
    
    user_data = get_user_data(telegram_id)
    
    if user_data:
        await message.answer(
            "Welcome back! You are already registered.\n"
            f"Your saved Serial No is: `{user_data['serial_no']}`\n"
            f"Your saved DOB is: `{user_data['dob'].strftime('%Y-%m-%d')}`\n\n"
            "You can start a new submission with the /submit command or re-register with /start to update your details.",
            parse_mode="Markdown"
        )
        # Fall through to registration again if they want to update
    else:
        await message.answer("Welcome to the Automation Bot! Let's get you set up.")

    await message.answer("Please enter your Serial Number:")
    await state.set_state(UserRegistration.getting_serial_no)


@dp.message(Command("submit"))
async def handle_submit(message: Message, state: FSMContext):
    """
    Handles the /submit command.
    Checks for registration and an active session, then queues a new one.
    """
    telegram_id = message.from_user.id
    logger.info(f"User {telegram_id} initiated /submit command.")
    
    # 1. Check if user is registered
    if not get_user_data(telegram_id):
        await message.answer("You are not registered yet. Please use the /start command to register first.")
        return
        
    # 2. Check if there's already an active session for this user
    active_session = get_active_session(telegram_id)
    if active_session:
        await message.answer(
            "You already have an active session running.\n"
            f"Session ID: `{active_session.session_id}`\n"
            f"Current State: `{active_session.state}`\n\n"
            "Please wait for it to complete before starting a new one.",
            parse_mode="Markdown"
        )
        return

    # 3. Create a new session in the database
    try:
        session_id = create_session(telegram_id=telegram_id, initial_state="QUEUED")
        logger.info(f"Successfully queued session {session_id} for user {telegram_id}.")
        await message.answer(
            "Your submission has been successfully queued!\n"
            f"Your Session ID is: `{session_id}`\n\n"
            "The automation will begin shortly. You will be notified here if any input (like a CAPTCHA or OTP) is required.",
            parse_mode="Markdown"
        )
        # --- ORCHESTRATION HOOK ---
        # In a real system, you would now trigger the orchestrator, e.g., by adding
        # the session_id to an asyncio.Queue that the orchestrator is monitoring.
        # For now, this just creates the DB record.
        
    except Exception as e:
        logger.error(f"Failed to create session for user {telegram_id}: {e}", exc_info=True)
        await message.answer("An internal error occurred while trying to queue your submission. Please try again later.")


# --- Message Handlers for FSM States ---

@dp.message(UserRegistration.getting_serial_no)
async def process_serial_no(message: Message, state: FSMContext):
    """Processes the Serial Number provided by the user."""
    serial_no = message.text.strip()
    
    # Basic validation: check if it's not empty and is alphanumeric (allowing dashes)
    if not serial_no or not serial_no.replace('-', '').isalnum():
        await message.answer("Invalid format. The Serial Number should be alphanumeric. Please try again.")
        return
        
    await state.update_data(serial_no=serial_no)
    await message.answer("Great! Now, please enter your Date of Birth in YYYY-MM-DD format (e.g., 1995-03-27).")
    await state.set_state(UserRegistration.getting_dob)


@dp.message(UserRegistration.getting_dob)
async def process_dob(message: Message, state: FSMContext):
    """Processes the Date of Birth and completes registration."""
    dob_text = message.text.strip()
    
    try:
        # Validate and parse the date
        dob_date = datetime.strptime(dob_text, "%Y-%m-%d").date()
    except ValueError:
        await message.answer("Invalid date format. Please use YYYY-MM-DD (e.g., 1995-03-27).")
        return
        
    user_data = await state.get_data()
    serial_no = user_data.get('serial_no')
    telegram_id = message.from_user.id
    
    try:
        # Save the validated and encrypted data to the database
        add_or_update_user(telegram_id=telegram_id, serial_no=serial_no, dob=dob_date)
        logger.info(f"Successfully registered/updated user {telegram_id}.")
        await message.answer(
            "Registration complete! Your data has been securely saved.\n"
            "You can now start a submission using the /submit command.",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.clear()
    except Exception as e:
        logger.error(f"Failed to save user data for {telegram_id}: {e}", exc_info=True)
        await message.answer("An error occurred while saving your data. Please try the /start command again.")
        await state.clear()


# In bot.py, replace the existing process_captcha_response

@dp.message(AutomationFlow.awaiting_captcha)
async def process_captcha_response(message: Message, state: FSMContext):
    """
    Handles user's response for a CAPTCHA and passes it to the orchestrator.
    """
    captcha_text = message.text.strip()
    state_data = await state.get_data()
    session_id = state_data.get("session_id")

    if not session_id:
        await message.answer("An error occurred, I don't know which session this is for. Please try /submit again.")
        await state.clear()
        return

    # Find the queue for this session and put the user's input in it
    if session_id in USER_INPUT_QUEUES:
        await USER_INPUT_QUEUES[session_id].put(captcha_text)
        await message.answer("Thank you. Submitting your CAPTCHA solution...")
        await state.clear()
    else:
        logger.warning(f"Received CAPTCHA for session {session_id}, but no active queue was found.")
        await message.answer("It seems this session has timed out or is no longer active.")
        await state.clear()


# In bot.py, replace the existing process_otp_response

@dp.message(AutomationFlow.awaiting_otp)
async def process_otp_response(message: Message, state: FSMContext):
    """
    Handles user's response for an OTP and passes it to the orchestrator.
    """
    otp_code = message.text.strip()
    state_data = await state.get_data()
    session_id = state_data.get("session_id")

    if not session_id:
        await message.answer("An error occurred, I don't know which session this is for. Please try /submit again.")
        await state.clear()
        return

    # Find the queue for this session and put the user's input in it
    if session_id in USER_INPUT_QUEUES:
        await USER_INPUT_QUEUES[session_id].put(otp_code)
        await message.answer("Thank you. Submitting your OTP code...")
        await state.clear()
    else:
        logger.warning(f"Received OTP for session {session_id}, but no active queue was found.")
        await message.answer("It seems this session has timed out or is no longer active.")
        await state.clear()
    

# --- Main Execution ---
async def main():
    """The main function to initialize the database and start the bot."""
    # Initialize the database and create tables if they don't exist
    db.initialize_database()
    
    logger.info("Starting bot polling...")
    # The 'allowed_updates' parameter helps in ignoring updates the bot is not interested in.
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    # Note: A timeout could be implemented by launching a separate asyncio task
    # after setting a state, which sleeps for 5 minutes and then clears the state
    # if it's still active. e.g., asyncio.create_task(state_timeout(state, 300))
    asyncio.run(main())


