@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo First-time setup is required. Follow README.md to create .venv and install requirements.txt.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m streamlit run app.py
if errorlevel 1 pause
