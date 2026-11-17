# Cria os atalhos "CS2 Coach" na Area de Trabalho e no Menu Iniciar.
# Uso: powershell -ExecutionPolicy Bypass -File tools\criar_atalhos.ps1 [-Startup]
#   -Startup  tambem inicia o app (escondido na bandeja) junto com o Windows
param([switch]$Startup)

$root = Split-Path -Parent $PSScriptRoot
$ws = New-Object -ComObject WScript.Shell

function New-Shortcut($path, $cmdArgs) {
    $s = $ws.CreateShortcut($path)
    $s.TargetPath = Join-Path $root ".venv\Scripts\pythonw.exe"
    $s.Arguments = $cmdArgs
    $s.WorkingDirectory = $root
    $s.IconLocation = (Join-Path $root "assets\icon.ico") + ",0"
    $s.Description = "CS2 Coach - analise pos-partida"
    $s.Save()
    Write-Output "Atalho: $path"
}

New-Shortcut (Join-Path ([Environment]::GetFolderPath("Desktop")) "CS2 Coach.lnk") "-m coach.app"
New-Shortcut (Join-Path ([Environment]::GetFolderPath("Programs")) "CS2 Coach.lnk") "-m coach.app"
if ($Startup) {
    New-Shortcut (Join-Path ([Environment]::GetFolderPath("Startup")) "CS2 Coach.lnk") "-m coach.app --tray"
}
