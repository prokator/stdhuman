@echo off
if not exist .venv\Scripts\activate.bat (
    python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
if "%PORT%"=="" (
    set PORT=18081
)
uvicorn app.main:app --host 127.0.0.1 --port %PORT%
