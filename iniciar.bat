@echo off
rem Abre o CS2 Coach (mesmo que o atalho da Area de Trabalho).
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m coach.app
