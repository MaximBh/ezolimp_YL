#!/bin/bash
cd "$(dirname "$0")"

if [ -f ".env.local" ]; then
  set -a
  source ".env.local"
  set +a
fi

if [ ! -d ".venv" ]; then
  echo "Создание виртуального окружения..."
  python3 -m venv .venv
  source .venv/bin/activate
  pip install fastapi uvicorn sqlalchemy passlib python-multipart websockets bcrypt openai pypdfium2 pillow > /dev/null 2>&1
else
  source .venv/bin/activate
fi

echo "Создание БД..."
cd backend
python3 -c "from app.database import create_tables; create_tables()" 2>/dev/null

echo ""
echo "=========================================="
echo "Запуск серверов..."
echo "=========================================="
echo ""

uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

cd ../frontend
python3 -m http.server 3000 &
FRONTEND_PID=$!

echo ""
echo "=========================================="
echo "Серверы запущены!"
echo "=========================================="
echo "Бэкенд:   http://ezolimp:8000"
echo "Фронтенд: http://ezolimp:3000"
echo "Фронтенд fallback: http://localhost:3000"
echo ""
echo "Открой в браузере: http://ezolimp:3000"
echo "Или: http://localhost:3000"
echo ""
echo "Для остановки нажми Ctrl+C"
echo "=========================================="

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT

wait
