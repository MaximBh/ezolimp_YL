from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.database import get_db, create_tables, User, Task, Solution, Match, UserStats
from app.schemas import UserRegister, UserLogin, TaskCreate, UserProfileUpdate
from app.auth_middleware import get_current_user, get_admin_user
from app.pvp_manager import match_manager
from datetime import datetime
import json
import random

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
        from app.database import hash_password
        
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
        from app.database import verify_password
        
        user = db.query(User).filter(User.username == login_data.username).first()
        if not user:
            raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")
        
        if not verify_password(login_data.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")
        
        user.last_login = datetime.now()
        db.commit()
        
        return {
            "message": "Вход выполнен успешно",
            "token": f"Bearer {user.username}",
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
        print(f"Login error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Ошибка при входе: {str(e)}")

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
        "is_admin": current_user.is_admin,
        "avatar_url": current_user.avatar_url,
        "bio": current_user.bio,
        "phone": current_user.phone,
        "telegram": current_user.telegram,
        "vk": current_user.vk,
        "github": current_user.github
    }

@app.put("/auth/me")
def update_me(profile_data: UserProfileUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        if profile_data.full_name is not None:
            current_user.full_name = profile_data.full_name
        if profile_data.school is not None:
            current_user.school = profile_data.school
        if profile_data.grade is not None:
            current_user.grade = profile_data.grade
        if profile_data.bio is not None:
            current_user.bio = profile_data.bio
        if profile_data.phone is not None:
            current_user.phone = profile_data.phone
        if profile_data.telegram is not None:
            current_user.telegram = profile_data.telegram
        if profile_data.vk is not None:
            current_user.vk = profile_data.vk
        if profile_data.github is not None:
            current_user.github = profile_data.github
        if profile_data.avatar_url is not None:
            current_user.avatar_url = profile_data.avatar_url
        
        db.commit()
        return {"message": "Профиль обновлен"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Ошибка при обновлении профиля")

@app.get("/users/{user_id}/stats")
def get_user_stats(user_id: int, db: Session = Depends(get_db)):
    try:
        stats = db.query(UserStats).filter(UserStats.user_id == user_id).first()
        if not stats:
            return {
                "total_solved": 0,
                "correct_answers": 0,
                "total_points": 0,
                "current_streak": 0,
                "best_streak": 0
            }
        return {
            "total_solved": stats.total_solved or 0,
            "correct_answers": stats.correct_answers or 0,
            "total_points": stats.total_points or 0,
            "current_streak": stats.current_streak or 0,
            "best_streak": stats.best_streak or 0
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при получении статистики")

@app.get("/users/{user_id}/analytics")
def get_user_analytics(user_id: int, db: Session = Depends(get_db)):
    try:
        from sqlalchemy import func, distinct
        
        correct_solutions = db.query(Solution).filter(
            Solution.user_id == user_id,
            Solution.is_correct == True
        ).all()
        
        unique_tasks = {}
        for sol in correct_solutions:
            if sol.task_id not in unique_tasks:
                unique_tasks[sol.task_id] = sol
        
        if not unique_tasks:
            return {
                "by_subject": {},
                "by_difficulty": {},
                "by_date": [],
                "accuracy": 0
            }
        
        by_subject = {}
        by_difficulty = {}
        by_date = {}
        
        for task_id, solution in unique_tasks.items():
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task:
                continue
            
            if task.subject not in by_subject:
                by_subject[task.subject] = {"total": 0, "correct": 0}
            by_subject[task.subject]["total"] += 1
            by_subject[task.subject]["correct"] += 1
            
            if task.difficulty not in by_difficulty:
                by_difficulty[task.difficulty] = {"total": 0, "correct": 0}
            by_difficulty[task.difficulty]["total"] += 1
            by_difficulty[task.difficulty]["correct"] += 1
            
            date_key = solution.submitted_at.strftime("%Y-%m-%d") if solution.submitted_at else datetime.now().strftime("%Y-%m-%d")
            if date_key not in by_date:
                by_date[date_key] = 0
            by_date[date_key] += 1
        
        sorted_dates = sorted(by_date.items())
        
        stats = db.query(UserStats).filter(UserStats.user_id == user_id).first()
        total = stats.total_solved if stats else len(unique_tasks)
        correct = stats.correct_answers if stats else len(unique_tasks)
        accuracy = round((correct / total * 100) if total > 0 else 0, 1)
        
        return {
            "by_subject": by_subject,
            "by_difficulty": by_difficulty,
            "by_date": sorted_dates,
            "accuracy": accuracy,
            "total_solutions": total,
            "correct_solutions": correct
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.get("/users/{user_id}/achievements")
def get_user_achievements(user_id: int, db: Session = Depends(get_db)):
    try:
        stats = db.query(UserStats).filter(UserStats.user_id == user_id).first()
        matches = db.query(Match).filter(
            (Match.player1_id == user_id) | (Match.player2_id == user_id),
            Match.status == "finished"
        ).all()
        
        total_solved = stats.total_solved if stats else 0
        correct_answers = stats.correct_answers if stats else 0
        best_streak = stats.best_streak if stats else 0
        total_points = stats.total_points if stats else 0
        
        pvp_wins = sum(1 for m in matches if m.winner_id == user_id)
        pvp_total = len(matches)
        
        achievements = []
        
        if correct_answers >= 1:
            achievements.append({
                "id": "first_solve",
                "title": "Первое решение",
                "description": "Решите первую задачу",
                "icon": "fa-star",
                "color": "yellow",
                "unlocked": True
            })
        
        if correct_answers >= 10:
            achievements.append({
                "id": "solver_10",
                "title": "Новичок",
                "description": "Решите 10 задач",
                "icon": "fa-trophy",
                "color": "blue",
                "unlocked": True
            })
        
        if correct_answers >= 50:
            achievements.append({
                "id": "solver_50",
                "title": "Опытный",
                "description": "Решите 50 задач",
                "icon": "fa-medal",
                "color": "purple",
                "unlocked": True
            })
        
        if correct_answers >= 100:
            achievements.append({
                "id": "solver_100",
                "title": "Мастер",
                "description": "Решите 100 задач",
                "icon": "fa-crown",
                "color": "orange",
                "unlocked": True
            })
        
        if best_streak >= 5:
            achievements.append({
                "id": "streak_5",
                "title": "Серия побед",
                "description": "Решите 5 задач подряд",
                "icon": "fa-fire",
                "color": "red",
                "unlocked": True
            })
        
        if pvp_wins >= 1:
            achievements.append({
                "id": "first_pvp_win",
                "title": "Первая победа",
                "description": "Выиграйте первый PvP матч",
                "icon": "fa-gamepad",
                "color": "green",
                "unlocked": True
            })
        
        if pvp_wins >= 10:
            achievements.append({
                "id": "pvp_master",
                "title": "Мастер PvP",
                "description": "Выиграйте 10 PvP матчей",
                "icon": "fa-chess",
                "color": "purple",
                "unlocked": True
            })
        
        if total_points >= 100:
            achievements.append({
                "id": "points_100",
                "title": "Коллекционер очков",
                "description": "Наберите 100 очков",
                "icon": "fa-coins",
                "color": "yellow",
                "unlocked": True
            })
        
        return {
            "achievements": achievements,
            "total_unlocked": len(achievements),
            "total_available": 8
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.get("/users/{user_id}/profile")
def get_user_profile(user_id: int, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        return {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "school": user.school,
            "grade": user.grade,
            "rating": user.rating,
            "avatar_url": user.avatar_url,
            "bio": user.bio
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при получении профиля")

@app.get("/users/{user_id}/solutions")
def get_user_solutions(user_id: int, db: Session = Depends(get_db)):
    try:
        solutions = db.query(Solution).filter(
            Solution.user_id == user_id,
            Solution.is_correct == True
        ).order_by(Solution.created_at.desc()).limit(10).all()
        
        result = []
        for sol in solutions:
            task = db.query(Task).filter(Task.id == sol.task_id).first()
            if task:
                result.append({
                    "task_id": task.id,
                    "task_title": task.title,
                    "subject": task.subject,
                    "difficulty": task.difficulty,
                    "points": sol.points_earned,
                    "solved_at": sol.created_at.isoformat() if sol.created_at else None
                })
        
        return {"solutions": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.get("/leaderboard")
def get_leaderboard(limit: int = 50, db: Session = Depends(get_db)):
    try:
        users = db.query(User).order_by(User.rating.desc()).limit(limit).all()
        
        result = []
        for idx, user in enumerate(users, 1):
            stats = db.query(UserStats).filter(UserStats.user_id == user.id).first()
            result.append({
                "rank": idx,
                "id": user.id,
                "username": user.username,
                "full_name": user.full_name,
                "rating": user.rating,
                "avatar_url": user.avatar_url,
                "total_solved": stats.total_solved if stats else 0
            })
        
        return {"leaderboard": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при получении рейтинга")

@app.post("/auth/logout")
def logout(current_user: User = Depends(get_current_user)):
    return {"message": "Выход выполнен"}

@app.post("/auth/make_admin")
def make_admin(login_data: UserLogin, db: Session = Depends(get_db)):
    try:
        from app.database import hash_password, verify_password
        
        if login_data.password != "88005553535A":
            raise HTTPException(status_code=403, detail="Неверный секретный код")
        
        user = db.query(User).filter(User.username == login_data.username).first()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        user.is_admin = True
        db.commit()
        
        return {"message": "Права администратора получены", "user_id": user.id}
    except HTTPException:
        raise
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
        from app.database import hash_password
        
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
        from app.database import hash_password
        
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
def create_task(task_data: TaskCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        task = Task(
            title=task_data.title,
            problem_statement=task_data.problem_statement,
            answer=task_data.answer,
            subject=task_data.subject,
            difficulty=task_data.difficulty,
            points=task_data.points,
            created_by=current_user.id
        )
        db.add(task)
        db.commit()
        return {"message": "Задача создана", "id": task.id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")

@app.get("/tasks/filter")
def filter_tasks(subject: str = None, difficulty: str = None, db: Session = Depends(get_db)):
    try:
        query = db.query(Task)
        
        if subject:
            query = query.filter(Task.subject == subject)
        if difficulty:
            query = query.filter(Task.difficulty == difficulty)
        
        tasks = query.limit(20).all()
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
        raise HTTPException(status_code=500, detail="Ошибка при фильтрации задач")

@app.get("/tasks/{task_id}/solution")
def get_task_solution(task_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        
        return {
            "answer": task.answer,
            "explanation": task.solution_explanation or "Решение не предоставлено"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при получении решения")

@app.get("/tasks/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db)):
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        
        return {
            "id": task.id,
            "title": task.title,
            "problem_statement": task.problem_statement,
            "input_format": task.input_format,
            "output_format": task.output_format,
            "examples": task.examples,
            "solution_explanation": task.solution_explanation,
            "difficulty": task.difficulty,
            "subject": task.subject,
            "topic": task.topic,
            "tags": task.tags,
            "points": task.points,
            "time_limit": task.time_limit
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при получении задачи")

@app.post("/tasks/{task_id}/solve")
def solve_task(task_id: int, user_answer: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        
        is_correct = user_answer.strip().lower() == task.answer.strip().lower()
        
        previous_correct = db.query(Solution).filter(
            Solution.user_id == current_user.id,
            Solution.task_id == task_id,
            Solution.is_correct == True
        ).first()
        
        points_earned = task.points if (is_correct and not previous_correct) else 0
        
        solution = Solution(
            user_id=current_user.id,
            task_id=task_id,
            answer=user_answer,
            is_correct=is_correct,
            points_earned=points_earned
        )
        db.add(solution)
        
        user_stats = db.query(UserStats).filter(UserStats.user_id == current_user.id).first()
        if not user_stats:
            user_stats = UserStats(
                user_id=current_user.id,
                total_solved=0,
                correct_answers=0,
                total_points=0,
                current_streak=0,
                best_streak=0
            )
            db.add(user_stats)
        
        if not previous_correct:
            user_stats.total_solved = (user_stats.total_solved or 0) + 1
            if is_correct:
                user_stats.correct_answers = (user_stats.correct_answers or 0) + 1
                user_stats.total_points = (user_stats.total_points or 0) + points_earned
                user_stats.current_streak = (user_stats.current_streak or 0) + 1
                if user_stats.current_streak > (user_stats.best_streak or 0):
                    user_stats.best_streak = user_stats.current_streak
            else:
                user_stats.current_streak = 0
        
        db.commit()
        
        message = "Правильно!" if is_correct else "Неправильно"
        if previous_correct:
            message = "Вы уже решали эту задачу правильно"
        
        return {
            "is_correct": is_correct,
            "message": message,
            "points_earned": points_earned,
            "already_solved": bool(previous_correct)
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")


@app.websocket("/ws/pvp/{user_id}")
async def pvp_websocket(websocket: WebSocket, user_id: int, db: Session = Depends(get_db)):
    await match_manager.connect(websocket, user_id)
    
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            await websocket.send_json({"error": "Пользователь не найден"})
            return
        
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            
            if action == "find_match":
                # Добавление в очередь и поиск
                match_manager.add_to_queue(user_id, user.username, user.rating)
                await websocket.send_json({"type": "queue_joined", "message": "Ищем соперника..."})
                
                match_result = match_manager.find_match(user_id)
                
                if match_result:
                    player1, player2 = match_result
                    
                    tasks = db.query(Task).all()
                    if not tasks:
                        await websocket.send_json({"error": "Нет доступных задач"})
                        continue
                    
                    task = random.choice(tasks)
                    match_id = match_manager.create_match(player1, player2, task.id)
                    
                    # Сохранение в БД
                    db_match = Match(
                        player1_id=player1["user_id"],
                        player2_id=player2["user_id"],
                        task_id=task.id,
                        status="active",
                        started_at=datetime.now()
                    )
                    db.add(db_match)
                    db.commit()
                    
                    # Отправка обоим игрокам
                    match_data = {
                        "type": "match_found",
                        "match_id": match_id,
                        "opponent": player2["username"] if player1["user_id"] == user_id else player1["username"],
                        "task": {
                            "id": task.id,
                            "title": task.title,
                            "problem_statement": task.problem_statement,
                            "difficulty": task.difficulty,
                            "points": task.points
                        }
                    }
                    
                    await websocket.send_json(match_data)
                    
                    opponent_id = player2["user_id"] if player1["user_id"] == user_id else player1["user_id"]
                    if opponent_id in match_manager.connections:
                        opponent_data = match_data.copy()
                        opponent_data["opponent"] = player1["username"] if player2["user_id"] == opponent_id else player2["username"]
                        await match_manager.connections[opponent_id].send_json(opponent_data)
                else:
                    await websocket.send_json({"type": "waiting", "message": "Ожидание соперника..."})
            
            elif action == "submit_answer":
                match_id = data.get("match_id")
                answer = data.get("answer")
                
                match = match_manager.submit_answer(match_id, user_id, answer)
                if not match:
                    await websocket.send_json({"error": "Матч не найден"})
                    continue
                
                task = db.query(Task).filter(Task.id == match["task_id"]).first()
                is_correct = task.answer.strip().lower() == answer.strip().lower()
                
                # Обновление счета
                if match["player1"]["user_id"] == user_id:
                    if is_correct:
                        match["player1_score"] = task.points
                else:
                    if is_correct:
                        match["player2_score"] = task.points
                
                await websocket.send_json({
                    "type": "answer_result",
                    "is_correct": is_correct,
                    "your_score": match["player1_score"] if match["player1"]["user_id"] == user_id else match["player2_score"],
                    "opponent_score": match["player2_score"] if match["player1"]["user_id"] == user_id else match["player1_score"]
                })
                
                # Завершение матча
                if match["player1_answer"] and match["player2_answer"]:
                    winner_id = None
                    if match["player1_score"] > match["player2_score"]:
                        winner_id = match["player1"]["user_id"]
                    elif match["player2_score"] > match["player1_score"]:
                        winner_id = match["player2"]["user_id"]
                    
                    # Обновление рейтинга Elo
                    player1 = db.query(User).filter(User.id == match["player1"]["user_id"]).first()
                    player2 = db.query(User).filter(User.id == match["player2"]["user_id"]).first()
                    
                    K = 32
                    expected1 = 1 / (1 + 10 ** ((player2.rating - player1.rating) / 400))
                    expected2 = 1 / (1 + 10 ** ((player1.rating - player2.rating) / 400))
                    
                    if winner_id == player1.id:
                        score1, score2 = 1, 0
                    elif winner_id == player2.id:
                        score1, score2 = 0, 1
                    else:
                        score1, score2 = 0.5, 0.5
                    
                    player1.rating += int(K * (score1 - expected1))
                    player2.rating += int(K * (score2 - expected2))
                    
                    # Обновление в БД
                    db_match = db.query(Match).filter(
                        Match.player1_id == match["player1"]["user_id"],
                        Match.player2_id == match["player2"]["user_id"],
                        Match.status == "active"
                    ).first()
                    
                    if db_match:
                        db_match.winner_id = winner_id
                        db_match.player1_score = match["player1_score"]
                        db_match.player2_score = match["player2_score"]
                        db_match.status = "finished"
                        db_match.finished_at = datetime.now()
                    
                    db.commit()
                    
                    # Отправка результатов
                    result_data = {
                        "type": "match_finished",
                        "winner_id": winner_id,
                        "your_score": match["player1_score"] if match["player1"]["user_id"] == user_id else match["player2_score"],
                        "opponent_score": match["player2_score"] if match["player1"]["user_id"] == user_id else match["player1_score"],
                        "rating_change": int(K * (score1 - expected1)) if match["player1"]["user_id"] == user_id else int(K * (score2 - expected2))
                    }
                    
                    await websocket.send_json(result_data)
                    
                    opponent_id = match["player2"]["user_id"] if match["player1"]["user_id"] == user_id else match["player1"]["user_id"]
                    if opponent_id in match_manager.connections:
                        opponent_result = result_data.copy()
                        opponent_result["your_score"] = match["player2_score"] if match["player2"]["user_id"] == opponent_id else match["player1_score"]
                        opponent_result["opponent_score"] = match["player1_score"] if match["player2"]["user_id"] == opponent_id else match["player2_score"]
                        opponent_result["rating_change"] = int(K * (score2 - expected2)) if match["player2"]["user_id"] == opponent_id else int(K * (score1 - expected1))
                        await match_manager.connections[opponent_id].send_json(opponent_result)
                    
                    match_manager.finish_match(match_id)
    
    except WebSocketDisconnect:
        match_manager.disconnect(user_id)
    except Exception as e:
        await websocket.send_json({"error": str(e)})
        match_manager.disconnect(user_id)

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
def delete_task(task_id: int, current_user: User = Depends(get_admin_user), db: Session = Depends(get_db)):
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

@app.get("/admin/tasks/export")
def export_tasks(current_user: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    try:
        tasks = db.query(Task).all()
        result = []
        for task in tasks:
            result.append({
                "title": task.title,
                "problem_statement": task.problem_statement,
                "answer": task.answer,
                "subject": task.subject,
                "difficulty": task.difficulty,
                "points": task.points,
                "input_format": task.input_format,
                "output_format": task.output_format,
                "examples": task.examples,
                "solution_explanation": task.solution_explanation,
                "topic": task.topic,
                "tags": task.tags
            })
        return {"tasks": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при экспорте задач")

@app.post("/admin/tasks/import")
def import_tasks(tasks_data: dict, current_user: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    try:
        tasks = tasks_data.get("tasks", [])
        imported_count = 0
        
        for task_data in tasks:
            task = Task(
                title=task_data.get("title"),
                problem_statement=task_data.get("problem_statement"),
                answer=task_data.get("answer"),
                subject=task_data.get("subject", "математика"),
                difficulty=task_data.get("difficulty", "easy"),
                points=task_data.get("points", 10),
                input_format=task_data.get("input_format"),
                output_format=task_data.get("output_format"),
                examples=task_data.get("examples"),
                solution_explanation=task_data.get("solution_explanation"),
                topic=task_data.get("topic"),
                tags=task_data.get("tags"),
                created_by=current_user.id
            )
            db.add(task)
            imported_count += 1
        
        db.commit()
        return {"message": f"Импортировано задач: {imported_count}"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка при импорте: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)