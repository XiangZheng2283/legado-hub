@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )
)

echo Installing dependencies...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo LegadoHub source import URL:
echo   Local: http://127.0.0.1:8765/api/legado/source
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ips = @(); try { $ips = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Select-Object -ExpandProperty IPAddress -Unique } catch { $ips = @() }; foreach ($ip in $ips) { Write-Host ('  LAN:   http://' + $ip + ':8765/api/legado/source') }; if (-not $ips) { Write-Host '  LAN:   No active LAN IPv4 address detected.' }"
echo.
echo LegadoHub web admin URL:
echo   Local: http://127.0.0.1:8765/admin
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ips = @(); try { $ips = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Select-Object -ExpandProperty IPAddress -Unique } catch { $ips = @() }; foreach ($ip in $ips) { Write-Host ('  LAN:   http://' + $ip + ':8765/admin') }; if (-not $ips) { Write-Host '  LAN:   No active LAN IPv4 address detected.' }"
echo.
echo Import one of the URLs above in Legado after the server starts.
echo If Legado runs on a phone, use a LAN URL instead of 127.0.0.1.
echo Open the web admin URL above to manage sources, settings, and rule engines.
echo.

echo Checking for an existing LegadoHub server on port 8765...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'SilentlyContinue'; $listeners = Get-NetTCPConnection -LocalPort 8765 -State Listen; foreach ($listener in $listeners) { $proc = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $listener.OwningProcess); if ($proc -and $proc.CommandLine -like '*uvicorn*app.main:app*' -and $proc.CommandLine -like '*8765*') { Write-Host ('Stopping existing LegadoHub server PID ' + $listener.OwningProcess); Stop-Process -Id $listener.OwningProcess -Force } else { Write-Host ('Port 8765 is used by another process PID ' + $listener.OwningProcess + ': ' + $proc.CommandLine); exit 2 } }"
if errorlevel 2 (
    echo Port 8765 is occupied by a non-LegadoHub process. Please close it manually or change the port.
    pause
    exit /b 1
)

echo Starting LegadoHub...
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765
if errorlevel 1 (
    echo Server exited with error.
    pause
    exit /b 1
)

endlocal
