from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from database import get_db, create_tables, User, Task, Solution, Match, UserStats
from schemas import UserRegister, UserLogin, TaskCreate
from auth_middleware import get_current_user, get_admin_user
from datetime import datetime

app = FastAPI(title="Predolimp")

# Обработка ошибок
@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"error": "Что-то пошло не так на сервере", "details": str(exc)}
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail}
    )


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
    try:
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
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при получении статистики")

@app.get("/users")
def get_users(db: Session = Depends(get_db)):
    try:
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
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при получении пользователей")

@app.get("/tasks")
def get_tasks(db: Session = Depends(get_db)):
    try:
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
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при получении задач")

# Endpoints авторизации
@app.post("/auth/register")
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    try:
        from database import hash_password
        
        # Проверяем что пользователь не существует
        if db.query(User).filter(User.username == user_data.username).first():
            raise HTTPException(status_code=400, detail="Пользователь с таким именем уже существует")
        if db.query(User).filter(User.email == user_data.email).first():
            raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")
        
        user = User(
            username=user_data.username,
            email=user_data.email,
            password_hash=hash_password(user_data.password),
            full_name=user_data.full_name,
            school=user_data.school,
            grade=user_data.grade
        )
        db.add(user)
        db.commit()
        return {"message": "Регистрация успешна", "user_id": user.id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при регистрации")

@app.post("/auth/login")
def login(login_data: UserLogin, db: Session = Depends(get_db)):
    try:
        from database import verify_password
        
        user = db.query(User).filter(User.username == login_data.username).first()
        if not user:
            raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")
        
        if not verify_password(login_data.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")
        
        # Обновляем время последнего входа
        user.last_login = datetime.utcnow()
        db.commit()
        
        return {
            "message": "Вход выполнен успешно",
            "token": f"Bearer {user.username}",  # Простой токен
            "user": {
                "id": user.id,
                "username": user.username,
                "full_name": user.full_name,
                "is_admin": user.is_admin
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при входе")

# Защищенные endpoints
@app.get("/auth/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "school": current_user.school,
        "grade": current_user.grade,
        "rating": current_user.rating,
        "is_admin": current_user.is_admin
    }

@app.post("/auth/logout")
def logout(current_user: User = Depends(get_current_user)):
    return {"message": "Выход выполнен"}

@app.post("/auth/make_admin")
def make_admin(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        current_user.is_admin = True
        db.commit()
        return {"message": f"Пользователь {current_user.username} теперь админ"}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при назначении админом")

# Админ endpoints
@app.get("/admin/users")
def admin_get_users(current_user: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    users = db.query(User).all()
    return {"users": [{"id": u.id, "username": u.username, "email": u.email, "is_admin": u.is_admin} for u in users]}

# Создание тестовых данных
@app.post("/test/create_sample_data")
def create_sample_data(db: Session = Depends(get_db)):
    try:
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
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при создании тестовых данных")

# CRUD операции для пользователей
@app.post("/users")
def create_user(user_data: UserRegister, db: Session = Depends(get_db)):
    try:
        from database import hash_password
        
        # Проверяем что пользователь не существует
        if db.query(User).filter(User.username == user_data.username).first():
            raise HTTPException(status_code=400, detail="Пользователь с таким именем уже существует")
        if db.query(User).filter(User.email == user_data.email).first():
            raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")
        
        user = User(
            username=user_data.username,
            email=user_data.email,
            password_hash=hash_password(user_data.password),
            full_name=user_data.full_name,
            school=user_data.school,
            grade=user_data.grade
        )
        db.add(user)
        db.commit()
        return {"message": "Пользователь создан", "id": user.id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при создании пользователя")

@app.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        db.delete(user)
        db.commit()
        return {"message": "Пользователь удален"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при удалении пользователя")

# CRUD операции для задач
@app.post("/tasks")
def create_task(title: str, problem_statement: str, answer: str, subject: str, difficulty: str = "easy", points: int = 10, db: Session = Depends(get_db)):
    try:
        task = Task(
            title=title,
            problem_statement=problem_statement,
            answer=answer,
            subject=subject,
            difficulty=difficulty,
            points=points
        )
        db.add(task)
        db.commit()
        return {"message": "Задача создана", "id": task.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при создании задачи")

@app.put("/tasks/{task_id}")
def update_task(task_id: int, title: str = None, problem_statement: str = None, answer: str = None, db: Session = Depends(get_db)):
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        
        if title:
            task.title = title
        if problem_statement:
            task.problem_statement = problem_statement
        if answer:
            task.answer = answer
            
        db.commit()
        return {"message": "Задача обновлена"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при обновлении задачи")

@app.delete("/tasks/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db)):
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        
        db.delete(task)
        db.commit()
        return {"message": "Задача удалена"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при удалении задачи")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)