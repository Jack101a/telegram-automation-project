"""
Part 1: Database Setup (db.py)

This module handles all database interactions for the automation bot.
It uses SQLAlchemy for the ORM, SQLite as the database backend for the MVP,
and the 'cryptography' library for securing sensitive user data.

Key Features:
- Defines data models (User, Session, Log, Artifact).
- Manages a secure encryption layer for sensitive fields like 'serial_no'.
- Provides a set of CRUD (Create, Read, Update, Delete) functions to abstract
  database operations from the main application logic.
- Includes a function to initialize the database schema.
- Designed to be compatible with migration tools like Alembic.
"""

import os
import uuid
import logging
from datetime import date, datetime
from typing import Optional, Dict, Any, Tuple

# Third-party libraries - ensure you have run:
# pip install sqlalchemy cryptography
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    DateTime,
    Date,
    ForeignKey,
    Text,
    BigInteger,
)
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from sqlalchemy.sql import func
from cryptography.fernet import Fernet, InvalidToken

# --- Configuration ---
DATABASE_URL = "sqlite:///automation_bot.db"
# For production, this key MUST be securely managed (e.g., env variables, secrets manager)
# It's loaded from an environment variable for security.
ENCRYPTION_KEY_ENV_VAR = "BOT_ENCRYPTION_KEY"

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- SQLAlchemy ORM Setup ---
# This serves as a starting point for Alembic migrations.
# Alembic revision --autogenerate -m "Initial schema"
Base = declarative_base()
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# --- Encryption Manager ---
class EncryptionManager:
    """Handles encryption and decryption of sensitive data using Fernet."""

    def __init__(self, key: bytes):
        if not key:
            raise ValueError("An encryption key must be provided.")
        self.fernet = Fernet(key)

    def encrypt(self, data: str) -> str:
        """Encrypts a string and returns it as a string."""
        return self.fernet.encrypt(data.encode('utf-8')).decode('utf-8')

    def decrypt(self, encrypted_data: str) -> Optional[str]:
        """Decrypts a string and returns it. Returns None on failure."""
        try:
            return self.fernet.decrypt(encrypted_data.encode('utf-8')).decode('utf-8')
        except (InvalidToken, TypeError, ValueError) as e:
            logger.error(f"Failed to decrypt data: {e}")
            return None

def get_encryption_key() -> bytes:
    """
    Retrieves the encryption key from environment variables.
    If not found, generates a new one and warns the user.
    """
    key = os.environ.get(ENCRYPTION_KEY_ENV_VAR)
    if key:
        return key.encode('utf-8')
    
    logger.warning(
        f"'{ENCRYPTION_KEY_ENV_VAR}' not found in environment variables. "
        "Generating a temporary key. "
        "IMPORTANT: For production, set this environment variable to persist data."
    )
    new_key = Fernet.generate_key()
    logger.info(f"Generated Key (set as '{ENCRYPTION_KEY_ENV_VAR}'): {new_key.decode('utf-8')}")
    # Set it for the current session to ensure consistency
    os.environ[ENCRYPTION_KEY_ENV_VAR] = new_key.decode('utf-8')
    return new_key

# Initialize the encryption manager globally
try:
    encryption_manager = EncryptionManager(get_encryption_key())
except ValueError as e:
    logger.critical(f"CRITICAL: Encryption Manager could not be initialized. {e}")
    # In a real app, you might exit here.
    encryption_manager = None


# --- ORM Models / Database Schema ---

class User(Base):
    """Represents a user interacting with the bot."""
    __tablename__ = 'users'
    # Alembic revision: alembic revision -m "Add User model"
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    # Serial number is encrypted in the database
    encrypted_serial_no = Column(String(255), nullable=True)
    dob = Column(Date, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(telegram_id={self.telegram_id})>"

class Session(Base):
    """Represents a single automation session for a user."""
    __tablename__ = 'sessions'
    # Alembic revision: alembic revision -m "Add Session model"
    session_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_telegram_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    state = Column(String(50), nullable=False) # e.g., AWAITING_CAPTCHA, COMPLETED
    started_at = Column(DateTime, server_default=func.now())
    ended_at = Column(DateTime, nullable=True)
    result = Column(String(50), nullable=True) # e.g., SUCCESS, FAILURE_CAPTCHA

    user = relationship("User", back_populates="sessions")
    logs = relationship("Log", back_populates="session", cascade="all, delete-orphan")
    artifacts = relationship("Artifact", back_populates="session", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Session(id={self.session_id}, user={self.user_telegram_id}, state={self.state})>"

class Log(Base):
    """Represents a log entry for a specific session."""
    __tablename__ = 'logs'
    # Alembic revision: alembic revision -m "Add Log model"
    log_id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey('sessions.session_id'), nullable=False)
    timestamp = Column(DateTime, server_default=func.now())
    level = Column(String(20), nullable=False) # e.g., INFO, WARNING, ERROR
    message = Column(Text, nullable=False)

    session = relationship("Session", back_populates="logs")

    def __repr__(self):
        return f"<Log(session_id={self.session_id}, level={self.level}, msg='{self.message[:30]}...')>"

class Artifact(Base):
    """Represents a file artifact associated with a session (e.g., screenshot)."""
    __tablename__ = 'artifacts'
    # Alembic revision: alembic revision -m "Add Artifact model"
    artifact_id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey('sessions.session_id'), nullable=False)
    type = Column(String(50), nullable=False) # e.g., CAPTCHA_SCREENSHOT, FINAL_PDF
    path = Column(String(255), nullable=False)

    session = relationship("Session", back_populates="artifacts")

    def __repr__(self):
        return f"<Artifact(session_id={self.session_id}, type={self.type}, path={self.path})>"


# --- Database Initialization ---
def initialize_database():
    """Creates all database tables if they don't already exist."""
    logger.info("Initializing database and creating tables if they don't exist...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialization complete.")


# --- CRUD Functions ---

def add_or_update_user(telegram_id: int, serial_no: str, dob: date) -> None:
    """Adds a new user or updates their details if they already exist."""
    if not encryption_manager:
        logger.error("Encryption manager not available. Cannot save user data.")
        return

    encrypted_serial = encryption_manager.encrypt(serial_no)
    
    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if user:
            logger.info(f"Updating existing user {telegram_id}.")
            user.encrypted_serial_no = encrypted_serial
            user.dob = dob
        else:
            logger.info(f"Creating new user {telegram_id}.")
            new_user = User(
                telegram_id=telegram_id,
                encrypted_serial_no=encrypted_serial,
                dob=dob
            )
            session.add(new_user)
        session.commit()

def get_user_data(telegram_id: int) -> Optional[Dict[str, Any]]:
    """
    Retrieves user data, decrypting the serial number.
    Returns a dictionary or None if user not found.
    """
    if not encryption_manager:
        logger.error("Encryption manager not available. Cannot retrieve user data.")
        return None

    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            return None
        
        decrypted_serial = encryption_manager.decrypt(user.encrypted_serial_no)
        if decrypted_serial is None:
            logger.error(f"Could not decrypt serial_no for user {telegram_id}. Data may be corrupt.")
        
        return {
            "telegram_id": user.telegram_id,
            "serial_no": decrypted_serial,
            "dob": user.dob,
            "created_at": user.created_at
        }

def create_session(telegram_id: int, initial_state: str) -> str:
    """Creates a new session for a user and returns the session_id."""
    with SessionLocal() as session:
        new_session = Session(
            user_telegram_id=telegram_id,
            state=initial_state
        )
        session.add(new_session)
        session.commit()
        logger.info(f"Created new session {new_session.session_id} for user {telegram_id}.")
        return new_session.session_id

def update_session_state(session_id: str, new_state: str, result: Optional[str] = None) -> bool:
    """Updates the state and optionally the result of a session."""
    with SessionLocal() as session:
        db_session = session.query(Session).filter_by(session_id=session_id).first()
        if not db_session:
            logger.warning(f"Attempted to update non-existent session {session_id}.")
            return False
            
        db_session.state = new_state
        if result:
            db_session.result = result
            db_session.ended_at = datetime.utcnow() # Final state implies session ended
            logger.info(f"Session {session_id} ended with result: {result}.")

        session.commit()
        logger.info(f"Updated session {session_id} state to '{new_state}'.")
        return True

def get_active_session(telegram_id: int) -> Optional[Session]:
    """Retrieves the most recent session for a user that has not ended."""
    with SessionLocal() as session:
        active_session = session.query(Session).filter(
            Session.user_telegram_id == telegram_id,
            Session.ended_at.is_(None)
        ).order_by(Session.started_at.desc()).first()
        return active_session

def log_event(session_id: str, level: str, message: str) -> None:
    """Logs an event message for a given session."""
    with SessionLocal() as session:
        new_log = Log(
            session_id=session_id,
            level=level.upper(),
            message=message
        )
        session.add(new_log)
        session.commit()

def add_artifact(session_id: str, artifact_type: str, file_path: str) -> None:
    """Adds a file artifact record to a session."""
    with SessionLocal() as session:
        new_artifact = Artifact(
            session_id=session_id,
            type=artifact_type,
            path=file_path
        )
        session.add(new_artifact)
        session.commit()
        logger.info(f"Added artifact '{artifact_type}' at '{file_path}' for session {session_id}.")


# --- Sample Usage Snippet ---
if __name__ == '__main__':
    print("Running database module sample usage...")
    
    # 1. Initialize the database (creates the .db file and tables)
    initialize_database()
    
    # Check if encryption is working
    if not encryption_manager:
        print("\nCRITICAL: Encryption is not configured. Exiting.")
        exit(1)
        
    print("\n--- Database Initialized ---")
    
    # 2. Define some sample data
    TEST_TELEGRAM_ID = 123456789
    TEST_SERIAL_NO = "ABC-12345-XYZ"
    TEST_DOB = date(1990, 5, 15)
    
    print(f"\n--- Simulating User {TEST_TELEGRAM_ID} ---")
    
    # 3. Add a new user
    add_or_update_user(
        telegram_id=TEST_TELEGRAM_ID,
        serial_no=TEST_SERIAL_NO,
        dob=TEST_DOB
    )
    print(f"User {TEST_TELEGRAM_ID} added/updated.")
    
    # 4. Retrieve and verify the user's data
    user_data = get_user_data(TEST_TELEGRAM_ID)
    print(f"Retrieved User Data: {user_data}")
    assert user_data and user_data['serial_no'] == TEST_SERIAL_NO, "Decryption check failed!"
    print("User data decryption verified.")
    
    # 5. Create a new session for the user
    session_id = create_session(telegram_id=TEST_TELEGRAM_ID, initial_state="STARTED")
    print(f"New session created with ID: {session_id}")
    
    # 6. Log some events during the session
    log_event(session_id, "INFO", "User started the form submission process.")
    log_event(session_id, "INFO", "Navigated to the target website.")
    print("Logged two events for the session.")
    
    # 7. Update the session state
    update_session_state(session_id, new_state="AWAITING_CAPTCHA")
    print("Session state updated to 'AWAITING_CAPTCHA'.")
    
    # 8. Add an artifact (e.g., a captcha screenshot)
    # In a real run, this path would point to an actual file
    captcha_path = f"artifacts/{session_id}/captcha.png"
    add_artifact(session_id, "CAPTCHA_SCREENSHOT", captcha_path)
    print(f"Added artifact record: {captcha_path}")
    
    # 9. Check for an active session
    active_session = get_active_session(TEST_TELEGRAM_ID)
    if active_session:
        print(f"Found active session: ID={active_session.session_id}, State={active_session.state}")
        assert active_session.session_id == session_id
    else:
        print("No active session found (this would be unexpected).")

    # 10. Finalize the session
    update_session_state(session_id, new_state="COMPLETED", result="SUCCESS")
    print("Session finalized with result 'SUCCESS'.")
    
    # 11. Verify there are no more active sessions
    active_session_after_close = get_active_session(TEST_TELEGRAM_ID)
    if not active_session_after_close:
        print("Verified that there are no more active sessions for the user.")
    else:
        print("Error: Session still appears active after closing.")

    print("\n--- Sample Usage Complete ---")


