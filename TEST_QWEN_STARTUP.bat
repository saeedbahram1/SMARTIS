@echo off
setlocal
cd /d "%~dp0backend"
py -c "from agent.ollama_model import model_status; from agent.chat import warm_up; import json; print('BEFORE'); print(json.dumps(model_status(),ensure_ascii=False,indent=2)); print('WARMUP'); print(json.dumps(warm_up(),ensure_ascii=False,indent=2)); print('AFTER'); print(json.dumps(model_status(),ensure_ascii=False,indent=2))"
echo.
echo Exit code: %ERRORLEVEL%
pause
