$OutputEncoding = [Console]::OutputEncoding = [Text.Encoding]::UTF8

Write-Host ""
Write-Host "==========================================="
Write-Host "   TOPSHIRIQ BOTI - ISHGA TUSHIRISH"
Write-Host "==========================================="
Write-Host ""

Set-Location $PSScriptRoot

# cloudflared tekshirish
if (-not (Test-Path "cloudflared.exe")) {
    Write-Host "[XATO] cloudflared.exe topilmadi!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Quyidagi linkdan yuklab, shu papkaga qo'ying:"
    Write-Host "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    Write-Host "Va faylni 'cloudflared.exe' deb nomlang."
    Write-Host ""
    Read-Host "Enter bosing..."
    exit 1
}

# .env tekshirish
if (-not (Test-Path ".env")) {
    Write-Host "[XATO] .env fayli topilmadi!" -ForegroundColor Red
    Write-Host "install.bat ni avval ishga tushiring."
    Read-Host "Enter bosing..."
    exit 1
}

# Eski log faylni o'chirish
$logFile = "$PSScriptRoot\cf-tunnel.log"
if (Test-Path $logFile) { Remove-Item $logFile -Force }

# Cloudflare Tunnel ishga tushirish (background)
Write-Host "[1/3] Cloudflare Tunnel ishga tushmoqda..."
$cfArgs = "tunnel --url http://localhost:8080 --logfile `"$logFile`""
$cfProcess = Start-Process -FilePath ".\cloudflared.exe" `
    -ArgumentList $cfArgs `
    -WindowStyle Hidden -PassThru

# URL ni kutish (max 60 sekund)
$url = ""
Write-Host "      Tunnel URL kutilmoqda" -NoNewline
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    Write-Host "." -NoNewline
    if (Test-Path $logFile) {
        $content = Get-Content $logFile -Raw -ErrorAction SilentlyContinue
        if ($content -match "https://[a-z0-9\-]+\.trycloudflare\.com") {
            $url = $Matches[0]
            break
        }
    }
}
Write-Host ""

if (-not $url) {
    Write-Host "[XATO] Tunnel URL aniqlanmadi!" -ForegroundColor Red
    Write-Host "Internet bor-yo'qligini tekshiring va qayta urining."
    $cfProcess | Stop-Process -ErrorAction SilentlyContinue
    Read-Host "Enter bosing..."
    exit 1
}

Write-Host "[2/3] Tunnel URL: $url" -ForegroundColor Green

# .env faylini avtomatik yangilash
Write-Host "[3/3] .env yangilanmoqda..."
$envContent = Get-Content ".env" -Raw -Encoding UTF8
if ($envContent -match "(?m)^WEBAPP_URL=") {
    $envContent = [Regex]::Replace($envContent, "(?m)^WEBAPP_URL=.*$", "WEBAPP_URL=$url")
} else {
    $envContent = $envContent.TrimEnd() + "`r`nWEBAPP_URL=$url`r`n"
}
[IO.File]::WriteAllText("$PSScriptRoot\.env", $envContent, [Text.Encoding]::UTF8)
Write-Host "      .env yangilandi!" -ForegroundColor Green

Write-Host ""
Write-Host "==========================================="
Write-Host "  Bot ishga tushmoqda..."
Write-Host "  To'xtatish uchun: Ctrl+C"
Write-Host "==========================================="
Write-Host ""

# Botni ishga tushirish
& ".\venv\Scripts\python.exe" run.py

# Bot to'xtaganda cloudflared ham to'xtatish
$cfProcess | Stop-Process -ErrorAction SilentlyContinue
