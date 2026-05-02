from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy.orm import Session

from app.database import get_db, create_tables, User, Task, Solution, Match
from app.task_import import ensure_tasks_schema_columns, import_tasks_from_json, split_compound_tasks_after_import, has_seed_tasks
from app.config import _sync_tasks_on_startup_enabled
from app.routers import auth, users, tasks, admin, pvp

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="EzOlimp")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(tasks.router)
app.include_router(admin.router)
app.include_router(pvp.router)


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    return JSONResponse(status_code=500, content={"error": "Внутренняя ошибка сервера"})


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.on_event("startup")
def startup():
    create_tables()
    ensure_tasks_schema_columns()
    if not has_seed_tasks() or _sync_tasks_on_startup_enabled():
        import_tasks_from_json()
        split_compound_tasks_after_import()
    else:
        print("Skipped tasks.json sync on startup: tasks already exist (set SYNC_TASKS_ON_STARTUP=1 to force)")


@app.get("/")
def root():
    return {"message": "Все ОК"}


@app.get("/stats")
def stats(db: Session = Depends(get_db)):
    try:
        return {
            "users": db.query(User).count(),
            "tasks": db.query(Task).count(),
            "solutions": db.query(Solution).count(),
            "matches": db.query(Match).count(),
        }
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка при получении статистики")
