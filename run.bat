@echo off
setlocal enabledelayedexpansion
title OmniKeep - Multimodal Knowledge Radar & Second Brain

echo ======================================================================
echo   OmniKeep - Multimodal Knowledge Radar & Second Brain
echo ======================================================================
echo.

cd /d "%~dp0"

:: 1. Check Python
where py >nul 2>nul
if %errorlevel% equ 0 (
    set "PYTHON_EXE=py -3"
) else (
    where python >nul 2>nul
    if %errorlevel% equ 0 (
        set "PYTHON_EXE=python"
    ) else (
        echo [ERROR] 系統未偵測到 Python 3 環境！
        echo 請至 https://www.python.org/downloads/ 安裝 Python 3.10+ 並勾選 "Add Python to PATH"。
        pause
        exit /b 1
    )
)

:: 2. Setup Virtual Environment
if not exist ".venv" (
    echo [*] 正在建立 Python 虛擬環境 (.venv)...
    %PYTHON_EXE% -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] 虛擬環境建立失敗！
        pause
        exit /b 1
    )
    echo [*] 正在安裝相依套件 (首次執行約需 1-2 分鐘)...
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ERROR] 相依套件安裝失敗！
        pause
        exit /b 1
    )
)

:: 3. Setup .env if missing
if not exist ".env" (
    if exist ".env.example" (
        echo [*] 正在由 .env.example 建立預設 .env 設定檔...
        copy ".env.example" ".env" >nul
    )
)

:: 4. Detect Port and Start Server
set "OMNI_PORT=5000"
if exist ".env" (
    for /f "tokens=1,2 delims==" %%A in (.env) do (
        if "%%A"=="PORT" set "OMNI_PORT=%%B"
    )
)

echo.
echo [*] 正在啟動 OmniKeep 伺服器...
echo [*] 本機存取儀表板: http://localhost:!OMNI_PORT!
echo [*] API 規格文件:   http://localhost:!OMNI_PORT!/docs
echo.

start "" "http://localhost:!OMNI_PORT!"

.venv\Scripts\python.exe run.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] OmniKeep 執行中斷或異常退出。
    pause
)
