from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import get_db, create_tables, User, Task

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
    return {"users": users, "tasks": tasks}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)