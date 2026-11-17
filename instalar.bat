@echo off
rem Instala o CS2 Coach: prepara o Python, monta a interface e cria os atalhos.
rem Precisa de: Python 3.12 ou mais novo (python.org) e Node.js 20 ou mais novo (nodejs.org).
setlocal
cd /d "%~dp0"
echo.
echo  ===== CS2 Coach: instalacao =====
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo  [x] Python nao encontrado.
  echo      Baixe em https://www.python.org/downloads/ e marque "Add python.exe to PATH" na instalacao.
  goto :fim
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)"
if errorlevel 1 (
  echo  [x] Seu Python e antigo. Instale o 3.12 ou mais novo: https://www.python.org/downloads/
  goto :fim
)
where npm >nul 2>nul
if errorlevel 1 (
  echo  [x] Node.js nao encontrado. Baixe a versao LTS em https://nodejs.org/ e rode este arquivo de novo.
  goto :fim
)

echo  [1/4] Preparando o Python (pode levar alguns minutos na primeira vez)...
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv || goto :erro
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip || goto :erro
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :erro

echo  [2/4] Montando a interface...
pushd frontend
call npm install --no-audit --no-fund --loglevel=error || (popd & goto :erro)
call npm run build --silent || (popd & goto :erro)
popd

echo  [3/4] Criando os atalhos "CS2 Coach" na Area de Trabalho e no Menu Iniciar...
powershell -NoProfile -ExecutionPolicy Bypass -File tools\criar_atalhos.ps1 >nul || goto :erro

echo  [4/4] Abrindo o app...
start "" ".venv\Scripts\pythonw.exe" -m coach.app
echo.
echo  Pronto! Daqui pra frente, abra pelo atalho "CS2 Coach".
echo  No app, siga o "Comece por aqui" da tela inicial.
goto :fim

:erro
echo.
echo  [x] Algo deu errado no passo acima. Leia a mensagem, corrija e rode este arquivo de novo.

:fim
echo.
pause
