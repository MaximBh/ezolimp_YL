from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db, User, Task, Solution, UserStats, Match
from app.auth_middleware import get_current_user
from app.config import _normalize_subject, _normalize_difficulty
from app.task_helpers import build_task_title

router = APIRouter()


@router.get("/users")
def get_users(db: Session = Depends(get_db)):
    try:
        users = db.query(User).limit(10).all()
        return {"users": [{"id": u.id, "username": u.username, "email": u.email, "full_name": u.full_name,
                           "school": u.school, "grade": u.grade, "rating": u.rating, "is_admin": u.is_admin}
                          for u in users]}
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка при получении пользователей")


@router.get("/users/{user_id}/stats")
def get_user_stats(user_id: int, db: Session = Depends(get_db)):
    try:
        stats = db.query(UserStats).filter(UserStats.user_id == user_id).first()
        if not stats:
            return {"total_solved": 0, "correct_answers": 0, "total_points": 0, "current_streak": 0, "best_streak": 0}
        return {"total_solved": stats.total_solved or 0, "correct_answers": stats.correct_answers or 0,
                "total_points": stats.total_points or 0, "current_streak": stats.current_streak or 0,
                "best_streak": stats.best_streak or 0}
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка при получении статистики")


@router.get("/users/{user_id}/analytics")
def get_user_analytics(user_id: int, db: Session = Depends(get_db)):
    try:
        correct_solutions = db.query(Solution).filter(Solution.user_id == user_id, Solution.is_correct == True).all()
        unique_tasks = {}
        for sol in correct_solutions:
            if sol.task_id not in unique_tasks:
                unique_tasks[sol.task_id] = sol
        if not unique_tasks:
            return {"by_subject": {}, "by_difficulty": {}, "by_date": [], "accuracy": 0}

        by_subject, by_difficulty, by_date = {}, {}, {}
        for task_id, solution in unique_tasks.items():
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task:
                continue
            sk = _normalize_subject(task.subject)
            dk = _normalize_difficulty(task.difficulty)
            by_subject.setdefault(sk, {"total": 0, "correct": 0})
            by_subject[sk]["total"] += 1
            by_subject[sk]["correct"] += 1
            by_difficulty.setdefault(dk, {"total": 0, "correct": 0})
            by_difficulty[dk]["total"] += 1
            by_difficulty[dk]["correct"] += 1
            date_key = solution.submitted_at.strftime("%Y-%m-%d") if solution.submitted_at else datetime.now().strftime("%Y-%m-%d")
            by_date[date_key] = by_date.get(date_key, 0) + 1

        stats = db.query(UserStats).filter(UserStats.user_id == user_id).first()
        total = stats.total_solved if stats else len(unique_tasks)
        correct = stats.correct_answers if stats else len(unique_tasks)
        return {"by_subject": by_subject, "by_difficulty": by_difficulty, "by_date": sorted(by_date.items()),
                "accuracy": round((correct / total * 100) if total > 0 else 0, 1),
                "total_solutions": total, "correct_solutions": correct}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")


@router.get("/users/{user_id}/achievements")
def get_user_achievements(user_id: int, db: Session = Depends(get_db)):
    try:
        stats = db.query(UserStats).filter(UserStats.user_id == user_id).first()
        matches = db.query(Match).filter((Match.player1_id == user_id) | (Match.player2_id == user_id), Match.status == "finished").all()
        ca = stats.correct_answers if stats else 0
        bs = stats.best_streak if stats else 0
        tp = stats.total_points if stats else 0
        pvp_wins = sum(1 for m in matches if m.winner_id == user_id)
        pvp_total = len(matches)
        ALL_ACHIEVEMENTS = [
            {"id": "first_solve", "title": "Первое решение", "description": "Реши первую задачу", "color": "yellow", "emoji": "⭐", "check": ca >= 1},
            {"id": "solver_5", "title": "Начинающий", "description": "5 правильных ответов", "color": "blue", "emoji": "📚", "check": ca >= 5},
            {"id": "solver_10", "title": "Новичок", "description": "10 правильных ответов", "color": "blue", "emoji": "🏅", "check": ca >= 10},
            {"id": "solver_25", "title": "Продвинутый", "description": "25 правильных ответов", "color": "purple", "emoji": "🔮", "check": ca >= 25},
            {"id": "solver_50", "title": "Опытный", "description": "50 правильных ответов", "color": "purple", "emoji": "🥇", "check": ca >= 50},
            {"id": "solver_100", "title": "Мастер", "description": "100 правильных ответов", "color": "orange", "emoji": "👑", "check": ca >= 100},
            {"id": "solver_250", "title": "Легенда", "description": "250 правильных ответов", "color": "orange", "emoji": "🔥", "check": ca >= 250},
            {"id": "streak_3", "title": "Серия x3", "description": "3 задачи подряд", "color": "red", "emoji": "⚡", "check": bs >= 3},
            {"id": "streak_5", "title": "Серия x5", "description": "5 задач подряд", "color": "red", "emoji": "🔥", "check": bs >= 5},
            {"id": "streak_10", "title": "Серия x10", "description": "10 задач подряд", "color": "red", "emoji": "🌩️", "check": bs >= 10},
            {"id": "points_50", "title": "Копилка", "description": "50 очков", "color": "yellow", "emoji": "💰", "check": tp >= 50},
            {"id": "points_100", "title": "Коллекционер", "description": "100 очков", "color": "yellow", "emoji": "💸", "check": tp >= 100},
            {"id": "points_500", "title": "Богач", "description": "500 очков", "color": "orange", "emoji": "💳", "check": tp >= 500},
            {"id": "first_pvp_win", "title": "Первая победа", "description": "Победи в PvP матче", "color": "green", "emoji": "🏆", "check": pvp_wins >= 1},
            {"id": "pvp_5", "title": "Боец", "description": "5 побед в PvP", "color": "green", "emoji": "⚔️", "check": pvp_wins >= 5},
            {"id": "pvp_master", "title": "Мастер PvP", "description": "10 побед в PvP", "color": "purple", "emoji": "💎", "check": pvp_wins >= 10},
            {"id": "pvp_played_10", "title": "Активный игрок", "description": "10 PvP матчей", "color": "blue", "emoji": "🎮", "check": pvp_total >= 10},
        ]
        result = [{"id": a["id"], "title": a["title"], "description": a["description"],
                   "color": a["color"], "emoji": a["emoji"], "unlocked": bool(a["check"])} for a in ALL_ACHIEVEMENTS]
        unlocked = [a for a in result if a["unlocked"]]
        locked = [a for a in result if not a["unlocked"]]
        return {"achievements": unlocked + locked, "total_unlocked": len(unlocked), "total_available": len(ALL_ACHIEVEMENTS)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")


@router.get("/users/{user_id}/profile")
def get_user_profile(user_id: int, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        return {"id": user.id, "username": user.username, "full_name": user.full_name,
                "school": user.school, "grade": user.grade, "rating": user.rating,
                "avatar_url": user.avatar_url, "bio": user.bio}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка при получении профиля")


@router.get("/users/{user_id}/solutions")
def get_user_solutions(user_id: int, db: Session = Depends(get_db)):
    try:
        solutions = db.query(Solution).filter(Solution.user_id == user_id, Solution.is_correct == True).order_by(Solution.created_at.desc()).limit(10).all()
        result = []
        for sol in solutions:
            task = db.query(Task).filter(Task.id == sol.task_id).first()
            if task:
                result.append({
                    "task_id": task.id,
                    "task_title": build_task_title(task.title, _normalize_subject(task.subject), task.grade, task.topic),
                    "subject": _normalize_subject(task.subject),
                    "difficulty": _normalize_difficulty(task.difficulty),
                    "points": sol.points_earned,
                    "solved_at": sol.created_at.isoformat() if sol.created_at else None
                })
        return {"solutions": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")


@router.get("/leaderboard")
def get_leaderboard(limit: int = 50, db: Session = Depends(get_db)):
    try:
        users = db.query(User).order_by(User.rating.desc()).limit(limit).all()
        result = []
        for idx, user in enumerate(users, 1):
            stats = db.query(UserStats).filter(UserStats.user_id == user.id).first()
            result.append({"rank": idx, "id": user.id, "username": user.username, "full_name": user.full_name,
                           "school": user.school or "-", "rating": user.rating, "avatar_url": user.avatar_url,
                           "total_solved": stats.total_solved if stats else 0})
        return {"leaderboard": result}
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка при получении рейтинга")
