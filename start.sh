#!/bin/bash
cd "$(dirname "$0")/backend"
python3 -c "from app.database import create_tables; create_tables()" 2>/dev/null
python3 -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
