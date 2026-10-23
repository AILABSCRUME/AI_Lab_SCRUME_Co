@echo off
rem Каталог моделей Polza.ai по возрастанию цены — компактный JSON в stdout.
rem Вызывается плагином polza-models через gateway RPC shell.exec.
rem Версия python НЕ зашита: имя каталога содержит дату сборки и меняется при
rem обновлении, поэтому берём единственный подходящий каталог по маске.
rem ВАЖНО: переводы строк только CRLF. С LF-файлом cmd.exe разбирает кириллицу
rem в rem-строках как команды и падает.
setlocal
set "PY="
for /d %%D in ("%LOCALAPPDATA%\hermes\tools\python-*") do set "PY=%%D\python.exe"
if not exist "%PY%" (
  echo {"ok":false,"err":"python не найден в %LOCALAPPDATA%\hermes\tools"}
  exit /b 1
)
"%PY%" "%LOCALAPPDATA%\hermes\.polza-models\polza_models.py" %*
endlocal
