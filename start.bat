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
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies.
    pause
    exit /b 1
)

echo Installing Playwright Chromium runtime...
.venv\Scripts\python.exe -m playwright install chromium
if errorlevel 1 (
    echo Failed to install Playwright Chromium.
    pause
    exit /b 1
)

if exist "frontend\package.json" (
    echo.
    echo Building console frontend...
    where npm >nul 2>nul
    if errorlevel 1 (
        echo npm was not found. Please install Node.js before building the console frontend.
        pause
        exit /b 1
    )
    pushd frontend
    echo Installing console frontend dependencies...
    call npm install
    if errorlevel 1 (
        popd
        echo Failed to install frontend dependencies.
        pause
        exit /b 1
    )
    call npm run build
    if errorlevel 1 (
        popd
        echo Failed to build console frontend.
        pause
        exit /b 1
    )
    if not exist "dist\index.html" (
        popd
        echo Console frontend build finished, but dist\index.html was not found.
        pause
        exit /b 1
    )
    popd
)

echo.
echo LegadoHub source import URL:
echo   Local: http://127.0.0.1:8765/api/subscribe/legado/source
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ips = @(); try { $ips = @([System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() | Where-Object { $_.OperationalStatus -eq [System.Net.NetworkInformation.OperationalStatus]::Up -and $_.NetworkInterfaceType -ne [System.Net.NetworkInformation.NetworkInterfaceType]::Loopback } | ForEach-Object { $_.GetIPProperties().UnicastAddresses } | Where-Object { $_.Address.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and -not [System.Net.IPAddress]::IsLoopback($_.Address) -and $_.Address.ToString() -notlike '169.254.*' } | ForEach-Object { $_.Address.ToString() } | Sort-Object -Unique) } catch { $ips = @() }; foreach ($ip in $ips) { Write-Host ('  LAN:   http://' + $ip + ':8765/api/subscribe/legado/source') }; if ($ips.Count -eq 0) { Write-Host '  LAN:   No active LAN IPv4 address detected.' }; Write-Host ''; Write-Host 'LegadoHub console URL:'; Write-Host '  Local: http://127.0.0.1:8765/console'; foreach ($ip in $ips) { Write-Host ('  LAN:   http://' + $ip + ':8765/console') }; if ($ips.Count -eq 0) { Write-Host '  LAN:   No active LAN IPv4 address detected.' }"
echo.
echo Source Access Bridge:
powershell -NoProfile -ExecutionPolicy Bypass -Command "$provider = $env:LEGADOHUB_BROWSER_PROVIDER; if ([string]::IsNullOrWhiteSpace($provider)) { $provider = 'chromium' }; $enabled = $env:LEGADOHUB_BROWSER_ENABLED; if ($enabled -match '^(0|false|no|off)$') { Write-Host '  Source Access Bridge: disabled' } elseif ($provider -eq 'browserless') { $ws = $env:LEGADOHUB_BROWSERLESS_WS; if ([string]::IsNullOrWhiteSpace($ws)) { Write-Host '  Source Access Bridge: browserless selected but endpoint is empty' } else { Write-Host '  Source Access Bridge: browserless'; try { $uri = [Uri]$ws; $hostName = $uri.Host; $port = if ($uri.Port -gt 0) { $uri.Port } elseif ($uri.Scheme -eq 'wss') { 443 } else { 80 }; $ok = Test-NetConnection -ComputerName $hostName -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue; if ($ok) { Write-Host ('  Browserless: reachable ' + $hostName + ':' + $port) } else { Write-Host ('  Browserless: not reachable ' + $hostName + ':' + $port) } } catch { Write-Host '  Browserless: configured but URL could not be parsed' } } } else { Write-Host '  Source Access Bridge: embedded Chromium' }; $base = $env:LEGADOHUB_BROWSER_PUBLIC_BASE_URL; if ([string]::IsNullOrWhiteSpace($base)) { Write-Host '  Public base URL: request host / relative actions' } else { Write-Host ('  Public base URL: ' + $base.TrimEnd('/')) }"
echo.
echo Import one of the URLs above in Legado after the server starts.
echo If Legado runs on a phone, use a LAN URL instead of 127.0.0.1.
echo Open the console URL above to manage sources, settings, and plugins.
echo.

echo Checking for an existing LegadoHub server on port 8765...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'SilentlyContinue'; function Test-LegadoHubPort { try { $info = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/info' -TimeoutSec 2; return $info.name -eq 'LegadoHub' } catch { return $false } }; function Stop-LegadoHubListener($listenerPid) { Write-Host ('Stopping existing LegadoHub server PID ' + $listenerPid); if (Get-Process -Id $listenerPid) { Stop-Process -Id $listenerPid -Force; if (Get-NetTCPConnection -LocalPort 8765 -State Listen) { & taskkill /PID $listenerPid /T /F | Out-Null } } else { Write-Host ('PID ' + $listenerPid + ' is not exposed by Windows process list.') }; for ($i = 0; $i -lt 20; $i++) { Start-Sleep -Milliseconds 250; if (-not (Get-NetTCPConnection -LocalPort 8765 -State Listen)) { return $true } }; return $false }; $listeners = Get-NetTCPConnection -LocalPort 8765 -State Listen; foreach ($listener in $listeners) { $listenerPid = $listener.OwningProcess; $proc = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $listenerPid); $isLegadoHub = $false; if ($proc -and $proc.CommandLine -like '*uvicorn*app.main:app*' -and $proc.CommandLine -like '*8765*') { $isLegadoHub = $true } else { $isLegadoHub = Test-LegadoHubPort }; if ($isLegadoHub) { if (Stop-LegadoHubListener $listenerPid) { continue }; if (Test-LegadoHubPort) { Write-Host 'Existing LegadoHub is still reachable; reusing it.'; exit 3 }; Write-Host ('Existing LegadoHub was detected, but port 8765 did not close after stopping PID ' + $listenerPid); exit 2 }; Write-Host ('Port 8765 is used by another process PID ' + $listenerPid + ': ' + $proc.CommandLine); exit 2 }"
if errorlevel 3 (
    echo LegadoHub is already running on port 8765. Use the URLs above.
    exit /b 0
)
if errorlevel 2 (
    echo Port 8765 is occupied by a non-LegadoHub process. Please close it manually or change the port.
    pause
    exit /b 1
)

echo Starting LegadoHub...
pushd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765
set SERVER_EXIT=%ERRORLEVEL%
popd
if not "%SERVER_EXIT%"=="0" (
    echo Server exited with error.
    pause
    exit /b 1
)

endlocal
