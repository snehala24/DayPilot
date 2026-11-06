$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$backendRoot = "C:\Users\SNEHALA A\Documents\12 projects 12 weeks\Day Pilot\backend"
$frontendRoot = "C:\Users\SNEHALA A\Documents\12 projects 12 weeks\Day Pilot\frontend"
$screenshotsDir = "C:\Users\SNEHALA A\Documents\12 projects 12 weeks\Day Pilot\docs\screenshots"

Write-Host "Starting Backend server..."
$backendProcess = Start-Process -FilePath "$backendRoot\.venv\Scripts\python.exe" -ArgumentList "-m uvicorn app.main:app --port 8000" -WorkingDirectory $backendRoot -PassThru -NoNewWindow

Write-Host "Starting Next.js Frontend server..."
$frontendProcess = Start-Process -FilePath "npx.cmd" -ArgumentList "next start -p 3000" -WorkingDirectory $frontendRoot -PassThru -NoNewWindow

Start-Sleep -Seconds 6

$urls = @(
    @{ name = "01_today.png"; url = "http://localhost:3000/" },
    @{ name = "02_inbox.png"; url = "http://localhost:3000/inbox" },
    @{ name = "03_approvals.png"; url = "http://localhost:3000/approvals" },
    @{ name = "04_commitments.png"; url = "http://localhost:3000/commitments" },
    @{ name = "05_history.png"; url = "http://localhost:3000/history" }
)

foreach ($item in $urls) {
    $outPath = Join-Path $screenshotsDir $item.name
    Write-Host "Capturing $($item.url) -> $outPath"
    & $edge --headless --disable-gpu --screenshot="$outPath" --window-size="1280,820" --hide-scrollbars "$($item.url)"
    Start-Sleep -Seconds 1
}

Write-Host "Tearing down servers..."
Stop-Process -Id $backendProcess.Id -Force -ErrorAction SilentlyContinue
Stop-Process -Id $frontendProcess.Id -Force -ErrorAction SilentlyContinue

Write-Host "Screenshots captured successfully."
