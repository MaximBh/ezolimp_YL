import re
from pydantic import BaseModel, field_validator, EmailStr
from typing import Optional, Any


class UserRegister(BaseModel):
    username: str
    email: str
    password: str
    full_name: str
    school: str
    grade: int

    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        v = v.strip()
        if len(v) < 3 or len(v) > 32:
            raise ValueError("Имя пользователя: от 3 до 32 символов")
        if not re.match(r"^[a-zA-Z0-9_\-а-яА-ЯёЁ]+$", v):
            raise ValueError("Имя пользователя содержит недопустимые символы")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if len(v) < 6 or len(v) > 128:
            raise ValueError("Пароль: от 6 до 128 символов")
        return v

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        v = v.strip().lower()
        if len(v) > 254 or "@" not in v:
            raise ValueError("Некорректный email")
        return v

    @field_validator("grade")
    @classmethod
    def validate_grade(cls, v):
        if v < 1 or v > 11:
            raise ValueError("Класс: от 1 до 11")
        return v

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v):
        if len(v.strip()) > 100:
            raise ValueError("Имя слишком длинное")
        return v.strip()


class UserLogin(BaseModel):
    username: str
    password: str


class UserProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    school: Optional[str] = None
    grade: Optional[int] = None
    bio: Optional[str] = None
    phone: Optional[str] = None
    telegram: Optional[str] = None
    vk: Optional[str] = None
    github: Optional[str] = None
    avatar_url: Optional[str] = None

    @field_validator("grade")
    @classmethod
    def validate_grade(cls, v):
        if v is not None and (v < 1 or v > 11):
            raise ValueError("Класс: от 1 до 11")
        return v

    @field_validator("bio")
    @classmethod
    def validate_bio(cls, v):
        if v is not None and len(v) > 500:
            raise ValueError("Биография: не более 500 символов")
        return v


class TaskCreate(BaseModel):
    title: str
    problem_statement: str
    answer: str
    subject: str
    grade: Optional[int] = None
    difficulty: Optional[str] = "easy"
    points: Optional[int] = 10
    input_format: Optional[str] = None
    output_format: Optional[str] = None
    examples: Optional[str] = None
    solution_explanation: Optional[str] = None
    topic: Optional[str] = None
    tags: Optional[str] = None
    attachments: Optional[Any] = None
    source_pdf_url: Optional[str] = None
    source_solution_pdf_url: Optional[str] = None
    source_page_start: Optional[int] = None
    source_page_end: Optional[int] = None
    source_fragments: Optional[Any] = None
    full_problem_statement: Optional[str] = None
    official_solution_text: Optional[str] = None
    free_ai_explanation: Optional[str] = None
    free_ai_status: Optional[str] = None

    @field_validator("grade")
    @classmethod
    def validate_grade(cls, v):
        if v is not None and (v < 1 or v > 11):
            raise ValueError("Класс: от 1 до 11")
        return v

    @field_validator("points")
    @classmethod
    def validate_points(cls, v):
        if v is not None and (v < 1 or v > 100):
            raise ValueError("Баллы: от 1 до 100")
        return v
