from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import get_db, create_tables, User, Task, Solution, Match, UserStats

app = FastAPI(title="Predolimp")


# Как я понял, это: "Сервер, разрешай всем сайтам к тебе обращаться". Без этого не будет по ПБ, блокирует тварь такая.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Создание таблиц в бд при запуске.
@app.on_event("startup")
def startup():
    create_tables()

# Основной хендлер.
@app.get("/")
def root():
    return {"message": "Все ворк"}

@app.get("/stats")
# Проверка доступа к бд.
def stats(db: Session = Depends(get_db)):
    users = db.query(User).count()
    tasks = db.query(Task).count()
    solutions = db.query(Solution).count()
    matches = db.query(Match).count()
    return {
        "users": users, 
        "tasks": tasks,
        "solutions": solutions,
        "matches": matches
    }

@app.get("/users")
def get_users(db: Session = Depends(get_db)):
    users = db.query(User).limit(10).all()
    result = []
    for user in users:
        result.append({
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "school": user.school,
            "grade": user.grade,
            "rating": user.rating,
            "is_admin": user.is_admin
        })
    return {"users": result}

@app.get("/tasks")
def get_tasks(db: Session = Depends(get_db)):
    tasks = db.query(Task).limit(10).all()
    result = []
    for task in tasks:
        result.append({
            "id": task.id,
            "title": task.title,
            "problem_statement": task.problem_statement,
            "difficulty": task.difficulty,
            "subject": task.subject,
            "points": task.points
        })
    return {"tasks": result}

# Создание тестовых данных
@app.post("/test/create_sample_data")
def create_sample_data(db: Session = Depends(get_db)):
    from database import hash_password
    
    # Тестовый пользователь
    if not db.query(User).filter(User.username == "test_user").first():
        user = User(
            username="test_user",
            email="test@example.com",
            password_hash=hash_password("123456"),
            full_name="Тестовый Пользователь",
            school="Школа №123",
            grade=10
        )
        db.add(user)
    
    # Тестовая задача
    if not db.query(Task).filter(Task.title == "Тестовая задача").first():
        task = Task(
            title="Тестовая задача",
            problem_statement="Найдите сумму двух чисел.",
            input_format="Два целых числа a и b через пробел.",
            output_format="Одно целое число - сумма a и b.",
            examples='{"input": "2 2", "output": "4"}',
            answer="4",
            solution_explanation="Просто сложить два числа: 2 + 2 = 4",
            difficulty="easy",
            subject="математика",
            topic="арифметика",
            tags="сложение,основы",
            points=5
        )
        db.add(task)
    
    db.commit()
    return {"message": "Тестовые данные созданы"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)