from fastapi import HTTPException, Depends, Header
from sqlalchemy.orm import Session
from database import get_db, User
from typing import Optional

def get_current_user(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    
    try:
        # Простая схема: "Bearer username"
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Неверный формат авторизации")
        
        username = authorization.replace("Bearer ", "")
        user = db.query(User).filter(User.username == username).first()
        
        if not user:
            raise HTTPException(status_code=401, detail="Пользователь не найден")
        
        if not user.is_active:
            raise HTTPException(status_code=401, detail="Пользователь заблокирован")
            
        return user
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Ошибка авторизации")

def get_admin_user(current_user: User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Нужны права администратора")
    return current_user