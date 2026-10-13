param([string]$Exe, [string]$Label, [string]$Port = "8123")
$ErrorActionPreference = "Continue"
$notes = @()
$p = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "$Exe --port $Port --no-browser" -PassThru -RedirectStandardOutput "$Label-out.txt" -RedirectStandardError "$Label-err.txt" -WorkingDirectory (Get-Location)
$sw = [Diagnostics.Stopwatch]::StartNew(); $ready = $null
while ($sw.Elapsed.TotalSeconds -lt 120) {
  try { $r = Invoke-WebRequest "http://127.0.0.1:$Port/api/status" -UseBasicParsing -TimeoutSec 2; $ready = [math]::Round($sw.Elapsed.TotalSeconds,1); break } catch { Start-Sleep -Milliseconds 700 }
}
if ($ready) { $notes += "127.0.0.1 ready after ${ready}s: $($r.Content)" } else { $notes += "NEVER became ready on 127.0.0.1" }
foreach ($h in @("localhost","[::1]")) {
  try { $x = Invoke-WebRequest "http://${h}:$Port/api/status" -UseBasicParsing -TimeoutSec 4; $notes += "$h OK" } catch { $notes += "$h FAILED: $($_.Exception.Message)" }
}
foreach ($pg in @("/","/kiosk","/admin","/static/app.css")) {
  try { $x = Invoke-WebRequest "http://127.0.0.1:$Port$pg" -UseBasicParsing -TimeoutSec 5; $notes += "$pg -> $($x.StatusCode)" } catch { $notes += "$pg FAILED: $($_.Exception.Message)" }
}
# engine test: post a blank jpeg to the recognizer (loads detection model)
try {
  python -c "import cv2,numpy as np; cv2.imwrite('blank.jpg', np.full((480,640,3),120,np.uint8))"
  $x = Invoke-WebRequest "http://127.0.0.1:$Port/api/kiosk/frame" -Method Post -InFile blank.jpg -ContentType image/jpeg -UseBasicParsing -TimeoutSec 20
  $notes += "kiosk/frame -> $($x.StatusCode) $($x.Content)"
} catch { $notes += "kiosk/frame FAILED: $($_.Exception.Message)" }
Start-Sleep -Seconds 1
$out = (Get-Content "$Label-out.txt" -Raw -ErrorAction SilentlyContinue); $err = (Get-Content "$Label-err.txt" -Raw -ErrorAction SilentlyContinue)
if ($out) { $notes += "STDOUT: " + $out.Substring(0,[math]::Min(900,$out.Length)) }
if ($err) { $notes += "STDERR: " + $err.Substring(0,[math]::Min(900,$err.Length)) }
if (Test-Path logs\error.log) { $notes += "ERRORLOG: " + (Get-Content logs\error.log -Raw) }
Get-CimInstance Win32_Process | Where-Object { $_.Name -like "FaceAttendance*" -or $_.CommandLine -like "*run.py*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
$msg = ($notes -join "`n") -replace "%","%25" -replace "`r","" -replace "`n","%0A"
Write-Host "::notice title=SMOKE $Label::$msg"
if (-not $ready) { exit 1 }
