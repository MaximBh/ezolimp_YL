# EzOlimp

Local setup for the EzOlimp frontend/backend with Ollama (`deepseek-r1:8b`).

## Why One Model File Is Not In Git

One Ollama blob is intentionally not committed:

`.ollama/models/blobs/sha256-e6a7edc1a4d7d9b2de136a221a57336b76316cfe53a252aeba814496c5ae439d`

Reason: GitHub rejects this object due size limits.

## Restore The Missing Model File

Run one of these installers from the project root:

- Windows: `install_model.bat`
- Linux/macOS: `bash install_model.sh`

Both scripts:

- set `OLLAMA_MODELS` to `<project>/.ollama/models`
- run `ollama pull deepseek-r1:8b`
- restore the missing blob locally

## Run The Project

- Windows: `start.bat`
- Linux/macOS: `bash run.sh`

Default ports:

- backend: `http://localhost:8001`
- frontend: `http://localhost:3000`
- Ollama API: `http://localhost:11434`
