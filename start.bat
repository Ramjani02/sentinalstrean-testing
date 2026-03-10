@echo off
REM SentinelStream - Windows Quick Start Script
REM Run this from the sentinelstream project root directory.

echo =====================================================
echo   SentinelStream - Starting Up
echo =====================================================

REM Step 1: Copy .env if it doesn't exist
if not exist .env (
    echo [1/5] Creating .env from .env.example...
    copy .env.example .env
    echo       IMPORTANT: Edit .env and set your SECRET_KEY values before production use!
) else (
    echo [1/5] .env already exists - skipping copy
)

REM Step 2: Build containers
echo [2/5] Building Docker containers (first run may take 3-5 minutes)...
docker compose build

REM Step 3: Start all services
echo [3/5] Starting all services...
docker compose up -d

REM Step 4: Wait for services to be healthy
echo [4/5] Waiting for services to become healthy...
timeout /t 15 /nobreak >nul

REM Step 5: Show status
echo [5/5] Service status:
docker compose ps

echo.
echo =====================================================
echo   SentinelStream is running!
echo =====================================================
echo.
echo   API:          http://localhost:8000
echo   Swagger UI:   http://localhost:8000/docs
echo   ReDoc:        http://localhost:8000/redoc
echo   Health Check: http://localhost:8000/health
echo   RabbitMQ UI:  http://localhost:15672  (sentinel / rabbit_secret)
echo   Flower UI:    http://localhost:5555
echo.
echo   To view logs:    docker compose logs -f api
echo   To stop:         docker compose down
echo =====================================================
pause
