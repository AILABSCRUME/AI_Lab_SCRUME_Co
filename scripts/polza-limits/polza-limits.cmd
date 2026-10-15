@echo off
rem Суточный лимит Polza.ai по ключу владельца — компактный JSON в stdout.
rem Вызывается плагином polza-limit через gateway RPC shell.exec.
rem Путь %LOCALAPPDATA% раскрывается cmd.exe: у каждого пользователя свой.
setlocal
set "PY=%LOCALAPPDATA%\hermes\tools\python-3.14.7+202****0901-win32-x64\python.exe"
if not exist "%PY%" for /d %%D in ("%LOCALAPPDATA%\hermes\tools\python-*") do set "PY=%%D\python.exe"
"%PY%" "%LOCALAPPDATA%\hermes\.polza-limits\polza_limits.py" %*
endlocal
