@echo off
setlocal
cd /d "%~dp0"
echo =========================================
echo     HanaV Stock Analyzer v1.0
 echo =========================================
where py >nul 2>nul
if %errorlevel%==0 (
  set "PYCMD=py -3"
) else (
  set "PYCMD=python"
)
if not exist ".venv\Scripts\python.exe" (
  echo Creating Python environment...
  %PYCMD% -m venv .venv
  if errorlevel 1 goto :fail
)
call ".venv\Scripts\activate.bat"
python -m pip install -r requirements.txt
if errorlevel 1 goto :fail
echo Starting app. Browser opens at http://localhost:8501
python -m streamlit run app.py
pause
exit /b 0
:fail
echo.
echo Installation failed. Verify Python 3.11/3.12 and your internet connection.
pause
exit /b 1
