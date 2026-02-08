#!/bin/bash
cd "$(dirname "$0")/frontend"
echo "Фронтенд запущен на http://127.0.0.1:3000"
echo "Открой в браузере: http://127.0.0.1:3000/main.html"
python3 -m http.server 3000
