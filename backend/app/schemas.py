from pydantic import BaseModel, EmailStr, validator
from typing import Optional

class UserRegister(BaseModel):
    username: str
    email: str
    password: str
    full_name: str
    school: str
    grade: int
    
    @validator('username')
    def username_must_be_valid(cls, v):
        if len(v) < 3:
            raise ValueError('Имя пользователя должно быть минимум 3 символа')
        if len(v) > 50:
            raise ValueError('Имя пользователя не может быть длиннее 50 символов')
        return v
    
    @validator('email')
    def email_must_be_valid(cls, v):
        if '@' not in v:
            raise ValueError('Email должен содержать @')
        if '.' not in v.split('@')[1]:
            raise ValueError('Email должен содержать домен')
        return v
    
    @validator('password')
    def password_must_be_valid(cls, v):
        if len(v) < 6:
            raise ValueError('Пароль должен быть минимум 6 символов')
        return v
    
    @validator('grade')
    def grade_must_be_valid(cls, v):
        if v < 1 or v > 11:
            raise ValueError('Класс должен быть от 1 до 11')
        return v

class UserLogin(BaseModel):
    username: str
    password: str

class TaskCreate(BaseModel):
    title: str
    problem_statement: str
    answer: str
    subject: str
    difficulty: Optional[str] = "easy"
    points: Optional[int] = 10
    
    @validator('title')
    def title_must_be_valid(cls, v):
        if len(v) < 5:
            raise ValueError('Название задачи должно быть минимум 5 символов')
        return v