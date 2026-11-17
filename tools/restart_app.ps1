# Reinicia o app sem perder trabalho: espera a análise ou a dica que está em andamento terminar.
$url = "http://127.0.0.1:31982/api/status"
for ($i = 0; $i -lt 120; $i++) {
    try { $s = (Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 5).Content | ConvertFrom-Json } catch { break }
    if (-not $s.fila -or -not $s.fila.atual) { break }
    Start-Sleep 3
}
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*coach.app*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep 3
Start-Process "$env:USERPROFILE\Desktop\CS2 Coach.lnk"
