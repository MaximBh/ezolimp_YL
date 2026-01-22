from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

DATABASE_URL = "sqlite:///./app.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True) # Уникальный id пользователя
    username = Column(String(50), unique=True, index=True) # Уникальное имя пользователя
    email = Column(String(100), unique=True, index=True) # Уникальная почта пользователя
    password_hash = Column(String(255))  # зашифр. пароль
    rating = Column(Integer, default=1000)  # рейтинг Elo
    created_at = Column(DateTime, default=datetime.utcnow) # когда создан аккаунт

class Task(Base):
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, index=True) # Уникальный id задачи
    title = Column(String(200)) # название
    description = Column(Text) # описание
    answer = Column(String(500))  # правильный ответ
    difficulty = Column(String(20), default="easy")  # easy/medium/hard, сложность типо
    subject = Column(String(50))  # предмет
    created_at = Column(DateTime, default=datetime.utcnow) # время создания

def create_tables():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()