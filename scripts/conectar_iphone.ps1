# Conecta a Maicol con tu iPhone (o cualquier celular) desde cualquier lugar, por Tailscale: una red privada
# entre tus dispositivos. Nada queda abierto a internet y además se pide clave (o el pase del QR).
#
# Antes: instala Tailscale en el PC y en el iPhone e inicia sesión con la MISMA cuenta.
#   powershell -ExecutionPolicy Bypass -File scripts\conectar_iphone.ps1
# Al final se abre un QR: escanéalo con la cámara del iPhone, ábrelo en Safari y toca Compartir → «Agregar a inicio».

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
$envArchivo = Join-Path $raiz ".env"
$puerto = 8765

# 1) Tailscale instalado y con sesión iniciada
$ts = @("$env:ProgramFiles\Tailscale\tailscale.exe", "${env:ProgramFiles(x86)}\Tailscale\tailscale.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $ts) {
    Write-Host "No encuentro Tailscale. Instálalo, inicia sesión y vuelve a ejecutar este script." -ForegroundColor Yellow
    Start-Process "https://tailscale.com/download/windows"
    exit 1
}
$estado = & $ts status --json | ConvertFrom-Json
if ($estado.BackendState -ne "Running") {
    Write-Host "Tailscale no tiene sesión iniciada: ábrelo (ícono junto al reloj) → Log in, y vuelve a ejecutar." -ForegroundColor Yellow
    exit 1
}
$nombre = $estado.Self.DNSName.TrimEnd(".")
$url = "https://$nombre"
Write-Host "Tu PC en Tailscale: $nombre" -ForegroundColor Cyan

# 2) Publicar Maicol SOLO dentro de tu red de Tailscale, con HTTPS (Safari lo exige para el micrófono).
#    Queda guardado: vuelve solo cada vez que prendes el PC. La primera vez Tailscale puede pedirte activar HTTPS con un enlace.
Write-Host "Publicando Maicol en tu red privada…"
& $ts serve --bg --https=443 "http://127.0.0.1:$puerto"

# 3) Clave larga y dirección del celular en .env (sin tocar lo demás)
#    Antes, una copia de respaldo; y se edita con python-dotenv, que cambia solo esas líneas y deja el resto igual.
if (Test-Path $envArchivo) {
    Copy-Item $envArchivo (Join-Path $raiz ("data\env_respaldo_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".txt")) -Force
}
$py = Join-Path $raiz ".venv\Scripts\python.exe"
$codigo = @'
import secrets, sys
from dotenv import dotenv_values, set_key
ruta, url = sys.argv[1], sys.argv[2]
antes = dotenv_values(ruta)
if not (antes.get("JARVIS_CLAVE") or "").strip():
    set_key(ruta, "JARVIS_CLAVE", secrets.token_urlsafe(24), quote_mode="never")
set_key(ruta, "JARVIS_CELULAR_URL", url, quote_mode="never")
despues = dotenv_values(ruta)
perdidas = [k for k, v in antes.items() if v and despues.get(k) != v and k != "JARVIS_CELULAR_URL"]
if perdidas:
    sys.exit("Algo cambió de más en .env: " + ", ".join(perdidas))
'@
$tmp = Join-Path $env:TEMP "maicol_env.py"  # en un archivo: PowerShell 5.1 estropea las comillas al pasar código con -c
[IO.File]::WriteAllText($tmp, $codigo, (New-Object Text.UTF8Encoding $false))
& $py $tmp $envArchivo $url
$resultado = $LASTEXITCODE
Remove-Item $tmp -ErrorAction SilentlyContinue
if ($resultado -ne 0) { Write-Host "No toqué nada más: revisa data\env_respaldo_*.txt" -ForegroundColor Red; exit 1 }

# 4) Reiniciar el núcleo para que tome la configuración
& (Join-Path $raiz "scripts\detener.bat") | Out-Null
Start-Sleep 2
Start-Process -FilePath (Join-Path $raiz ".venv\Scripts\pythonw.exe") -ArgumentList "-m", "jarvis" -WorkingDirectory $raiz
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep 1
    try { Invoke-RestMethod "http://127.0.0.1:$puerto/api/ping" -TimeoutSec 2 | Out-Null; break } catch {}
}

# 5) QR de un solo uso (vale 15 min): el iPhone queda emparejado un año sin teclear la clave
try {
    $qr = Invoke-RestMethod "http://127.0.0.1:$puerto/api/qr_celular"
} catch {
    Write-Host "No pude generar el QR: $($_.ErrorDetails.Message)" -ForegroundColor Red
    exit 1
}
$png = Join-Path $raiz "data\qr_iphone.png"
[IO.File]::WriteAllBytes($png, [Convert]::FromBase64String($qr.png))
Start-Process $png
Write-Host ""
Write-Host "Listo. Escanea el QR con la cámara del iPhone (vale 15 minutos)." -ForegroundColor Green
if ($qr.pin) { Write-Host ("O escribe este código en la pantalla de Maicol: " + $qr.pin.Substring(0, 3) + " " + $qr.pin.Substring(3)) -ForegroundColor Cyan }
Write-Host "En Safari: Compartir → «Agregar a inicio» para tener a Maicol como app."
Write-Host "Dirección: $url"
