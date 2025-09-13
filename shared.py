import asyncio
from typing import Dict
from aiogram.fsm.state import State, StatesGroup

# --- FSM State Definitions ---

class Registration(StatesGroup):
    """FSM States for the initial user registration."""
    getting_dl_no = State()
    getting_dob = State()

class AutomationFlow(StatesGroup):
    """FSM States for when automation is running and needs input."""
    awaiting_captcha = State()
    awaiting_otp = State()

# --- Communication Bridge ---

# This dictionary acts as a bridge between the orchestrator (producer)
# and the bot handlers (consumer of prompts, producer of user input).
# Key: session_id (str), Value: asyncio.Queue
USER_INPUT_QUEUES: Dict[str, asyncio.Queue] = {}


