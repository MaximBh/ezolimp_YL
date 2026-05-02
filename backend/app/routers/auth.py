from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db, User, hash_password, verify_password
from app.schemas import UserRegister, UserLogin, UserProfileUpdate
from app.auth_middleware import get_current_user

router = APIRouter()


@router.post("/auth/register")
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    try:
        if db.query(User).filter(User.username == user_data.username).first():
            raise HTTPException(status_code=400, detail="Пользователь с таким именем уже существует")
        if db.query(User).filter(User.email == user_data.email).first():
            raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")
        avatar_id = hash(user_data.username) % 1000
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
def login(login_data: UserLogin, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.username == login_data.username).first()
        if not user or not verify_password(login_data.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")
        user.last_login = datetime.now()
        db.commit()
        return {
            "message": "Вход выполнен успешно",
            "token": f"Bearer {user.username}",
            "user": {"id": user.id, "username": user.username, "full_name": user.full_name, "is_admin": user.is_admin}
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при входе: {str(e)}")


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
def create_user(user_data: UserRegister, db: Session = Depends(get_db)):
    try:
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
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка при удалении пользователя")


@router.post("/test/create_sample_data")
def create_sample_data(db: Session = Depends(get_db)):
    try:
        if not db.query(User).filter(User.username == "test_user").first():
            db.add(User(username="test_user", email="test@example.com",
                        password_hash=hash_password("123456"),
                        full_name="Тестовый Пользователь", school="Школа №123", grade=10))
        db.commit()
        return {"message": "Тестовые данные созданы"}
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка при создании тестовых данных")
