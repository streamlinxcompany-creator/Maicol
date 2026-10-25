# El núcleo de Maicol como administrador, sin la ventana de UAC.
# Registra la tarea programada «Maicol Nucleo»: arranca el núcleo al iniciar sesión con los permisos más altos.
# Lo que lanza el núcleo también es administrador (Claude Code, ejecutar_comando, habilidades), así que Maicol
# puede tocar el arranque, discos, servicios o el registro sin que alguien acepte la ventana en el PC.
# La pestaña lateral y el panel (Edge) siguen siendo de usuario normal: solo el núcleo sube de nivel.
#
#   powershell -ExecutionPolicy Bypass -File scripts\instalar_admin.ps1           instalar (pide permiso una vez)
#   powershell -ExecutionPolicy Bypass -File scripts\instalar_admin.ps1 -Quitar   volver a usuario normal
param([switch]$Quitar)

$nombre = "Maicol Nucleo"
$raiz = Split-Path $PSScriptRoot -Parent
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    $argumentos = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    if ($Quitar) { $argumentos += "-Quitar" }
    Start-Process powershell -Verb RunAs -ArgumentList $argumentos -Wait
    exit
}

# el núcleo que esté corriendo se reinicia con los permisos nuevos
function Detener-Nucleo {
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
        Where-Object { $_.CommandLine -match '-m jarvis' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

if ($Quitar) {
    Unregister-ScheduledTask -TaskName $nombre -Confirm:$false -ErrorAction SilentlyContinue
    Detener-Nucleo
    Start-Process "$raiz\.venv\Scripts\pythonw.exe" -ArgumentList "-m", "jarvis" -WorkingDirectory $raiz
    Write-Output "Listo: el núcleo vuelve a correr como usuario normal."
    exit
}

$usuario = "$env:USERDOMAIN\$env:USERNAME"
$accion = New-ScheduledTaskAction -Execute "$raiz\.venv\Scripts\pythonw.exe" -Argument "-m jarvis" -WorkingDirectory $raiz
$disparo = New-ScheduledTaskTrigger -AtLogOn -User $usuario
$quien = New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Highest
# sin límite de tiempo (por defecto Windows la mataría a los 3 días) y también con batería
$ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $nombre -Action $accion -Trigger $disparo -Principal $quien -Settings $ajustes `
    -Description "Núcleo de Maicol (jarvis) con permisos de administrador" -Force | Out-Null

Detener-Nucleo
Start-Sleep -Seconds 1
Start-ScheduledTask -TaskName $nombre
Write-Output "Listo: el núcleo de Maicol corre como administrador y arranca solo al iniciar sesión."
