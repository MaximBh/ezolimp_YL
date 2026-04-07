from pydantic import BaseModel
from typing import Optional, Any

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
