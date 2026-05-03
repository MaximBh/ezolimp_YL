from datetime import datetime
import re
from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session
from app.database import get_db, User, hash_password, verify_password
from app.schemas import UserRegister, UserLogin, UserProfileUpdate
from app.auth_middleware import get_current_user, create_token, get_admin_user

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def validate_registration_data(user_data: UserRegister):
    full_name = " ".join(str(user_data.full_name or "").split())
    email = str(user_data.email or "").strip().lower()
    grade = user_data.grade

    if len(full_name.split()) != 2:
        raise HTTPException(status_code=400, detail="Полное имя должно состоять из двух слов")
    if not EMAIL_RE.fullmatch(email):
        raise HTTPException(status_code=400, detail="Введите корректную почту")
    if type(grade) is not int or grade < 1 or grade > 11:
        raise HTTPException(status_code=400, detail="Класс должен быть числом от 1 до 11")

    user_data.full_name = full_name
    user_data.email = email


@router.post("/auth/register")
@limiter.limit("5/minute")
def register(request: Request, user_data: UserRegister, db: Session = Depends(get_db)):
    try:
        validate_registration_data(user_data)
        if db.query(User).filter(User.username == user_data.username).first():
            raise HTTPException(status_code=400, detail="Пользователь с таким именем уже существует")
        if db.query(User).filter(User.email == user_data.email).first():
            raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")
        import hashlib
        avatar_id = int(hashlib.md5(user_data.username.encode()).hexdigest(), 16) % 1000
        user = User(
            username=user_data.username, email=user_data.email,
            password_hash=hash_password(user_data.password),
            full_name=user_data.full_name, school=user_data.school, grade=user_data.grade,
            avatar_url=f"https://i.pravatar.cc/150?img={avatar_id}"
        )
        db.add(user)
        db.commit()
        return {"message": "Регистрация успешна", "user_id": user.id}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка при регистрации")


@router.post("/auth/login")
@limiter.limit("10/minute")
def login(request: Request, login_data: UserLogin, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.username == login_data.username).first()
        if not user or not verify_password(login_data.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")
        user.last_login = datetime.now()
        db.commit()
        return {
            "message": "Вход выполнен успешно",
            "token": f"Bearer {create_token(user.id)}",
            "user": {"id": user.id, "username": user.username, "full_name": user.full_name, "is_admin": user.is_admin}
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка при входе")


@router.get("/auth/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id, "username": current_user.username, "email": current_user.email,
        "full_name": current_user.full_name, "school": current_user.school, "grade": current_user.grade,
        "rating": current_user.rating, "is_admin": current_user.is_admin, "avatar_url": current_user.avatar_url,
        "bio": current_user.bio, "phone": current_user.phone, "telegram": current_user.telegram,
        "vk": current_user.vk, "github": current_user.github
    }


@router.put("/auth/me")
def update_me(profile_data: UserProfileUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        for field in ("full_name", "school", "grade", "bio", "phone", "telegram", "vk", "github", "avatar_url"):
            value = getattr(profile_data, field, None)
            if value is not None:
                setattr(current_user, field, value)
        db.commit()
        return {"message": "Профиль обновлен"}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Ошибка при обновлении профиля")


@router.post("/auth/logout")
def logout(current_user: User = Depends(get_current_user)):
    return {"message": "Выход выполнен"}


@router.post("/users")
@limiter.limit("5/minute")
def create_user(request: Request, user_data: UserRegister, db: Session = Depends(get_db)):
    try:
        validate_registration_data(user_data)
        if db.query(User).filter(User.username == user_data.username).first():
            raise HTTPException(status_code=400, detail="Пользователь с таким именем уже существует")
        if db.query(User).filter(User.email == user_data.email).first():
            raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")
        user = User(username=user_data.username, email=user_data.email,
                    password_hash=hash_password(user_data.password),
                    full_name=user_data.full_name, school=user_data.school, grade=user_data.grade)
        db.add(user)
        db.commit()
        return {"message": "Пользователь создан", "id": user.id}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка при создании пользователя")


@router.delete("/users/{user_id}")
def delete_user(user_id: int, current_user: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        db.delete(user)
        db.commit()
        return {"message": "Пользователь удален"}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка при удалении пользователя")



