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
  .venv/bin/pip install -r requirements.txt -q
fi

fuser -k 8001/tcp 2>/dev/null || true
fuser -k 3000/tcp 2>/dev/null || true

cd backend
python3 -c "from app.database import create_tables; create_tables()" 2>/dev/null

echo ""
echo "=========================================="
echo "Запуск серверов..."
echo "=========================================="
echo ""

# прод: фронт раздаёт FastAPI, один порт
# локалка: фронт на 3000, бэк на 8001
if [ "${PROD:-0}" = "1" ]; then
  ../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8001
else
  ../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload &
  BACKEND_PID=$!

  cd ../frontend
  python3 -m http.server 3000 &
  FRONTEND_PID=$!

  echo ""
  echo "=========================================="
  echo "Серверы запущены!"
  echo "=========================================="
  echo "Бэкенд:   http://localhost:8001"
  echo "Фронтенд: http://localhost:3000"
  echo ""
  echo "Для остановки Ctrl+C"
  echo "=========================================="

  trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
  wait
fi
