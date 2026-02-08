from pydantic import BaseModel, validator
from typing import Optional

class UserRegister(BaseModel):
    username: str
    email: str
    password: str
    full_name: str
    school: str
    grade: int

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

class TaskCreate(BaseModel):
    title: str
    problem_statement: str
    answer: str
    subject: str
    difficulty: Optional[str] = "easy"
    points: Optional[int] = 10