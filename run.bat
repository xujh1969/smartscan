@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo 未找到 Python，请先安装 Python 3.11 或更高版本，并勾选 "Add Python to PATH"。
  pause
  exit /b 1
)

python -c "import PySide6, cv2, PIL, numpy" >nul 2>&1
if errorlevel 1 (
  echo 首次启动：正在安装依赖，请保持联网...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo 依赖安装失败，请手动执行：python -m pip install -r requirements.txt
    pause
    exit /b 1
  )
)

if /i "%~1"=="--smoke" (
  python run.py --smoke
  exit /b %errorlevel%
)

where pythonw >nul 2>&1
if errorlevel 1 (
  start "" python run.py
) else (
  start "" pythonw run.py
)
exit /b 0
