@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "..\build\runtime\python.exe" (
  "..\build\runtime\python.exe" bootstrap.py
) else (
  python bootstrap.py
)
if errorlevel 1 pause
