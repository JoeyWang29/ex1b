@echo off
chcp 65001 >nul
setlocal
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set ROOT=D:\work buddy\2026-11-17-23-12-15\ex1b\securefile
set PY=C:\Users\29166\AppData\Local\Programs\Python\Python313\python.exe
title SecureFile 1B - deploy and test
cd /d "%ROOT%"
ping -n 3 127.0.0.1 >nul
cls

echo.
echo  ================================================================
echo   SecureFile 1B  -  build, deploy and test
echo   SFAP/1 over mutual TLS  -  19 automated cases
echo  ================================================================
ping -n 4 127.0.0.1 >nul

echo.
echo  [1/6] BUILD  -  byte-compile every module
echo  ----------------------------------------------------------------
"%PY%" -m py_compile protocol.py server.py auth.py sandbox.py ratelimit.py client_core.py client_gui.py tests\e2e.py
if errorlevel 1 goto fail
echo  [ok] 8 modules compiled
ping -n 5 127.0.0.1 >nul

echo.
echo  [2/6] PKI  -  private CA issues server and client certificates
echo  ----------------------------------------------------------------
echo   script : scripts/gen_certs.sh  (root CA signs server and one cert per account)
echo.
openssl x509 -in run/certs/ca-cert.pem -noout -subject
openssl x509 -in run/certs/server-cert.pem -noout -subject -ext subjectAltName
openssl x509 -in run/certs/client-alice-cert.pem -noout -subject
ping -n 6 127.0.0.1 >nul

echo.
echo  [3/6] USERS  -  scrypt hashes only, never plaintext
echo  ----------------------------------------------------------------
"%PY%" auth.py --db run/state/users.db --init
"%PY%" -c "import sqlite3;c=sqlite3.connect('run/state/users.db');print('  table users ->',[r[1] for r in c.execute('PRAGMA table_info(users)')]);print('  rows:',list(c.execute('SELECT name,role,length(pwhash) FROM users')))"
ping -n 6 127.0.0.1 >nul

echo.
echo  [4/6] SERVER  -  mutual TLS, sandbox, per-role bandwidth
echo  ----------------------------------------------------------------
echo   command: python server.py --config config.server.json
echo   status : running in background (recorder started it)
"%PY%" -c "import socket,os;print('  listen :', [l.split()[1] for l in os.popen('netstat -ano').read().splitlines() if ':9443' in l and 'LISTENING' in l][:1])"
"%PY%" -c "print(''.join(open('run/server.log',encoding='utf-8').readlines()[-2:]))"
ping -n 5 127.0.0.1 >nul

echo.
echo  [5/6] TEST  -  19 functional and security cases
echo  ----------------------------------------------------------------
"%PY%" tests\e2e.py --port 9443
ping -n 5 127.0.0.1 >nul

echo.
echo  [6/6] BANDWIDTH  -  role based throttling (vip vs normal)
echo  ----------------------------------------------------------------
"%PY%" tests\benchmark.py --port 9443 --rounds 1 --size 16
ping -n 7 127.0.0.1 >nul

echo.
echo  ================================================================
echo   deploy finished, server is listening on 127.0.0.1:9443
echo   next: graphical client demo
echo  ================================================================
ping -n 13 127.0.0.1 >nul
exit /b 0

:fail
echo  [FAILED] build step returned an error
pause
exit /b 1
