import os
from datetime import datetime
import logging

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
import db
from shared import Registration, AutomationFlow, USER_INPUT_QUEUES

# --- CRITICAL FIX: Bot and Dispatcher Setup ---
# These two variables, 'bot' and 'dp', MUST be defined here at the top level.
# This makes them available to be imported by other files like main.py.
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")

storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN, parse_mode="Markdown")
dp = Dispatcher(storage=storage)
logger = logging.getLogger(__name__)
# -----------------------------------------------


@dp.message(CommandStart())
async def handle_start(message: Message, state: FSMContext):
    """Handles the /start command, beginning the registration process if needed."""
    user_id = message.from_user.id
    if db.get_user_data(user_id):
        await message.answer("Welcome back! Your details are already registered.\nUse /submit to start a new application.")
    else:
        await message.answer("Welcome! To begin, please enter your **DL No.** (e.g., `MH14 20200012345`)")
        await state.set_state(Registration.getting_dl_no)

@dp.message(Command("submit"))
async def handle_submit(message: Message):
    """Handles the /submit command, queuing a new automation session."""
    if not db.get_user_data(message.from_user.id):
        await message.answer("You need to register first. Please use /start.")
        return
    session_id = db.create_session(message.from_user.id)
    # Using Markdown for formatting the session_id as code
    await message.answer(f"✅ Your application has been queued!\n**Session ID:** `{session_id}`")
    logger.info(f"New session {session_id} created for user {message.from_user.id}")

@dp.message(Registration.getting_dl_no)
async def process_dl_no(message: Message, state: FSMContext):
    """Processes the user's DL No. and asks for their DOB."""
    await state.update_data(dl_no=message.text.strip())
    await message.answer("Great! Now, please enter your **Date of Birth** in `DD-MM-YYYY` format.")
    await state.set_state(Registration.getting_dob)

@dp.message(Registration.getting_dob)
async def process_dob(message: Message, state: FSMContext):
    """Processes the DOB, saves the user's data, and concludes registration."""
    try:
        dob_date = datetime.strptime(message.text.strip(), "%d-%m-%Y").date()
        user_data = await state.get_data()
        dl_no = user_data['dl_no']
        db.add_or_update_user(message.from_user.id, dl_no, dob_date)
        await state.clear()
        await message.answer("✅ Registration complete! You can now use /submit to begin.")
    except ValueError:
        await message.answer("Invalid date format. Please use `DD-MM-YYYY`.")

@dp.message(AutomationFlow.awaiting_captcha)
async def process_captcha_response(message: Message, state: FSMContext):
    """Handles the user's text response to a CAPTCHA prompt."""
    data = await state.get_data()
    session_id = data.get("session_id")
    if session_id and session_id in USER_INPUT_QUEUES:
        await USER_INPUT_QUEUES[session_id].put(message.text.strip())
        await message.answer("Thanks, processing...")
        await state.clear()
    else:
        await message.answer("Sorry, that session has expired or is invalid.")

@dp.message(AutomationFlow.awaiting_otp)
async def process_otp_response(message: Message, state: FSMContext):
    """Handles the user's text response to an OTP prompt."""
    data = await state.get_data()
    session_id = data.get("session_id")
    if session_id and session_id in USER_INPUT_QUEUES:
        await USER_INPUT_QUEUES[session_id].put(message.text.strip())
        await message.answer("Thanks, processing...")
        await state.clear()
    else:
        await message.answer("Sorry, that session has expired or is invalid.")


