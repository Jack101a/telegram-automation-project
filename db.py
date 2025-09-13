import os
import logging
from datetime import date
import uuid  # <-- THIS IS THE FIX. THE MISSING IMPORT.
from sqlalchemy import create_engine, Column, Integer, String, Date, DateTime, ForeignKey, func
from sqlalchemy.orm import sessionmaker, relationship, declarative_base

# --- Logging Setup ---
logger = logging.getLogger(__name__)

# --- Database Engine Setup ---
db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'automation.db')
DATABASE_URL = f"sqlite:///{db_path}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- ORM Models ---
class User(Base):
    __tablename__ = "users"
    user_id = Column(Integer, primary_key=True, index=True)
    serial_no = Column(String, nullable=False)
    dob = Column(Date, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    sessions = relationship("Session", back_populates="user")

class Session(Base):
    __tablename__ = "sessions"
    session_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    state = Column(String, default="QUEUED")
    started_at = Column(DateTime, server_default=func.now())
    ended_at = Column(DateTime, nullable=True)
    result = Column(String, nullable=True)
    user = relationship("User", back_populates="sessions")
    logs = relationship("Log", back_populates="session")
    artifacts = relationship("Artifact", back_populates="session")

class Log(Base):
    __tablename__ = "logs"
    log_id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=False)
    timestamp = Column(DateTime, server_default=func.now())
    level = Column(String, nullable=False)
    message = Column(String, nullable=False)
    session = relationship("Session", back_populates="logs")

class Artifact(Base):
    __tablename__ = "artifacts"
    artifact_id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=False)
    type = Column(String, nullable=False)
    path = Column(String, nullable=False)
    session = relationship("Session", back_populates="artifacts")

def create_db_and_tables():
    logger.info("Initializing database and creating tables if they don't exist...")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialization complete.")

# --- CRUD Functions ---
def add_or_update_user(user_id: int, serial_no: str, dob: date):
    with SessionLocal() as session:
        user = session.query(User).filter(User.user_id == user_id).first()
        if user:
            user.serial_no = serial_no
            user.dob = dob
        else:
            user = User(user_id=user_id, serial_no=serial_no, dob=dob)
            session.add(user)
        session.commit()

def get_user_data(user_id: int):
    with SessionLocal() as session:
        return session.query(User).filter(User.user_id == user_id).first()

def create_session(user_id: int) -> str:
    with SessionLocal() as session:
        new_session = Session(user_id=user_id, state="QUEUED")
        session.add(new_session)
        session.commit()
        return new_session.session_id

def update_session_state(session_id: str, state: str, result: str = None):
    with SessionLocal() as session:
        db_session = session.query(Session).filter(Session.session_id == session_id).first()
        if db_session:
            db_session.state = state
            if result:
                db_session.result = result
            if state in ["COMPLETED", "FAILED"]:
                db_session.ended_at = func.now()
            session.commit()

def log_event(session_id: str, level: str, message: str):
    with SessionLocal() as session:
        log_entry = Log(session_id=session_id, level=level, message=message)
        session.add(log_entry)
        session.commit()

def add_artifact(session_id: str, artifact_type: str, path: str):
    with SessionLocal() as session:
        artifact = Artifact(session_id=session_id, type=artifact_type, path=path)
        session.add(artifact)
        session.commit()


