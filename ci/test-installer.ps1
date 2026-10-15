# Silent install -> start hidden -> check -> stop -> uninstall, on a real Windows machine.
$ErrorActionPreference = "Continue"
$notes = @(); $fail = $false
function Check($name, $ok, $extra = "") { $script:notes += ("{0}: {1} {2}" -f ($(if ($ok) {"OK  "} else {"FAIL"}), $name, $extra)); if (-not $ok) { $script:fail = $true } }

$setup = "installer-out\FaceAttendance-Setup.exe"
$p = Start-Process $setup -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/TASKS=autostart" -Wait -PassThru
Check "installer exit code 0" ($p.ExitCode -eq 0) "($($p.ExitCode))"
$app = "C:\Program Files\Face Attendance"
Check "FaceAttendance.exe installed" (Test-Path "$app\FaceAttendance.exe")
Check "installed.flag present" (Test-Path "$app\installed.flag")
$su = "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp\Face Attendance (server).lnk"
Check "auto-start shortcut created" (Test-Path $su)
Check "Start Menu shortcuts" (Test-Path "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\Face Attendance\Admin panel.lnk")
$fw = (netsh advfirewall firewall show rule name="Face Attendance") -join " "
Check "firewall rule added" ($fw -match "Face Attendance")

$port = 8123
Start-Process "$app\FaceAttendance.exe" -ArgumentList "--background","--port","$port"
$sw = [Diagnostics.Stopwatch]::StartNew(); $ready = $false
while ($sw.Elapsed.TotalSeconds -lt 90 -and -not $ready) { try { $r = Invoke-WebRequest "http://127.0.0.1:$port/api/status" -UseBasicParsing -TimeoutSec 2; $ready = $true } catch { Start-Sleep -Milliseconds 700 } }
Check "server up (hidden, background)" $ready "after $([math]::Round($sw.Elapsed.TotalSeconds,1))s"
$ps = Get-Process FaceAttendance -ErrorAction SilentlyContinue
Check "console window hidden" (($ps | Where-Object { $_.MainWindowHandle -ne 0 }).Count -eq 0)
Check "data in ProgramData (not Program Files)" (Test-Path "$env:ProgramData\FaceAttendance\data\attendance.db")
Check "nothing written to Program Files\data" (-not (Test-Path "$app\data"))
Check "setup + status API" ($r.Content -match "has_password")
try { $k = Invoke-WebRequest "http://localhost:$port/kiosk" -UseBasicParsing -TimeoutSec 5; Check "localhost kiosk page" ($k.StatusCode -eq 200) } catch { Check "localhost kiosk page" $false $_.Exception.Message }

# starting a second copy must not break or duplicate
Start-Process "$app\FaceAttendance.exe" -ArgumentList "--background","--port","$port" -Wait
Start-Sleep -Seconds 2
Check "second start is harmless" ((Get-Process FaceAttendance -ErrorAction SilentlyContinue | Measure-Object).Count -ge 1)

# stop
Start-Process "$app\FaceAttendance.exe" -ArgumentList "--stop" -Wait
Start-Sleep -Seconds 4
$still = $true; try { Invoke-WebRequest "http://127.0.0.1:$port/api/status" -UseBasicParsing -TimeoutSec 2 | Out-Null } catch { $still = $false }
Check "--stop shuts the server down" (-not $still)

# uninstall
$u = Start-Process "$app\unins000.exe" -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART" -Wait -PassThru
Start-Sleep -Seconds 3
Check "uninstall removed the program" (-not (Test-Path "$app\FaceAttendance.exe"))
Check "uninstall kept customer data" (Test-Path "$env:ProgramData\FaceAttendance\data\attendance.db")

if (Test-Path "$env:ProgramData\FaceAttendance\logs\app.log") { $notes += "APP LOG: " + ((Get-Content "$env:ProgramData\FaceAttendance\logs\app.log" -Tail 8) -join " | ") }
$msg = ($notes -join "`n") -replace "%","%25" -replace "`r","" -replace "`n","%0A"
Write-Host "::notice title=INSTALLER TEST::$msg"
if ($fail) { exit 1 }
