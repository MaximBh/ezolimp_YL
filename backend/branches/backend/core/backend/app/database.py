from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import bcrypt

# SQLite база для разработки
DATABASE_URL = "sqlite:///./olimpiada.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Пользователи
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True)
    email = Column(String(100), unique=True, index=True)
    password_hash = Column(String(255))  # хеш пароля
    full_name = Column(String(100))
    school = Column(String(100))
    grade = Column(Integer)
    rating = Column(Integer, default=1000)  # рейтинг Elo
    is_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)

# Задачи
class Task(Base):
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), index=True)
    problem_statement = Column(Text)  # условие задачи
    input_format = Column(Text)  # формат входных данных
    output_format = Column(Text)  # формат выходных данных
    examples = Column(Text)  # примеры входа/выхода (JSON)
    answer = Column(String(500))  # правильный ответ
    solution_explanation = Column(Text)  # объяснение решения
    difficulty = Column(String(20), default="easy", index=True)  # easy/medium/hard
    subject = Column(String(50), index=True)  # предмет
    topic = Column(String(100))
    tags = Column(String(200))  # теги через запятую
    points = Column(Integer, default=10)
    time_limit = Column(Integer, default=300)  # секунд
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

# Решения
class Solution(Base):
    __tablename__ = "solutions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), index=True)
    answer = Column(String(500))
    is_correct = Column(Boolean, default=False)
    solve_time = Column(Integer)  # секунд
    points_earned = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

# PvP матчи
class Match(Base):
    __tablename__ = "matches"
    
    id = Column(Integer, primary_key=True, index=True)
    player1_id = Column(Integer, ForeignKey("users.id"), index=True)
    player2_id = Column(Integer, ForeignKey("users.id"), index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"))
    winner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    player1_score = Column(Integer, default=0)
    player2_score = Column(Integer, default=0)
    status = Column(String(20), default="waiting")  # waiting, active, finished, cancelled
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

# Статистика пользователей
class UserStats(Base):
    __tablename__ = "user_stats"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True)
    total_solved = Column(Integer, default=0)
    correct_answers = Column(Integer, default=0)
    total_points = Column(Integer, default=0)
    avg_solve_time = Column(Integer, default=0)
    matches_played = Column(Integer, default=0)
    matches_won = Column(Integer, default=0)
    current_streak = Column(Integer, default=0)
    best_streak = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow)

# Функции для работы с паролями
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def create_tables():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()