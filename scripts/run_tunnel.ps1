# ==============================================================================
# [안재현 전담] Codyssey B7-1 배포 및 외부 접속 터널 구동 스크립트 (Windows PowerShell)
#
# FastAPI 백엔드 서버(uvicorn)와 Cloudflare Tunnel(cloudflared)을 실행하여
# 평가자가 외부 네트워크에서 웹 서비스에 접속할 수 있는 퍼블릭 URL을 발급받습니다.
#
# 실행 방법:
#   .\scripts\run_tunnel.ps1
# ==============================================================================

param(
    [int]$Port = 8080
)

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host " [Codyssey B7-1] 웹 AI 챗봇 배포 및 Cloudflare 터널 실행기 (Windows)" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

# 1. 프로젝트 경로 및 가상환경 점검
$ProjectRoot = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { (Get-Location).Path }
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host ">> [경고] .venv 가상환경이 없습니다. 시스템 python을 사용합니다." -ForegroundColor Yellow
    $VenvPython = "python"
}

# 2. cloudflared 바이너리 점검
$CloudflaredCmd = "cloudflared"
$CloudflaredLocal = Join-Path $ProjectRoot "cloudflared.exe"

if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    if (Test-Path $CloudflaredLocal) {
        $CloudflaredCmd = $CloudflaredLocal
    } else {
        Write-Host ">> 시스템 PATH에 cloudflared가 없습니다." -ForegroundColor Yellow
        Write-Host ">> Cloudflare 공식 릴리즈에서 cloudflared.exe 다운로드를 시도합니다..." -ForegroundColor Yellow
        try {
            $DownloadUrl = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
            Invoke-WebRequest -Uri $DownloadUrl -OutFile $CloudflaredLocal -UseBasicParsing
            Write-Host ">> cloudflared.exe 다운로드 완료!" -ForegroundColor Green
            $CloudflaredCmd = $CloudflaredLocal
        } catch {
            Write-Host ">> 자동 다운로드 실패. 'winget install --id Cloudflare.cloudflared'로 설치를 권장합니다." -ForegroundColor Red
        }
    }
}

Write-Host ">> 1. FastAPI 백엔드 서버 기동 중 (Port: $Port, Root: $ProjectRoot)..." -ForegroundColor Green
$ServerJob = Start-Process -FilePath $VenvPython -ArgumentList "-m uvicorn app.main:app --host 0.0.0.0 --port $Port" -WorkingDirectory $ProjectRoot -PassThru -NoNewWindow

Start-Sleep -Seconds 2

if ($ServerJob.HasExited) {
    Write-Host ">> [오류] FastAPI 서버 기동 실패!" -ForegroundColor Red
    exit 1
} else {
    Write-Host ">> [성공] FastAPI 서버 정상 실행 중 (PID: $($ServerJob.Id))" -ForegroundColor Green
}

try {
    Write-Host ">> 2. Cloudflare 터널 기동 중... (외부 접속 퍼블릭 URL 발급 대기)" -ForegroundColor Green
    Write-Host "----------------------------------------------------------------------" -ForegroundColor Yellow
    Write-Host "URL이 발급되면 자동으로 콘솔에 크게 강조 표시되고 브라우저가 열립니다." -ForegroundColor Yellow
    Write-Host "종료하려면 Ctrl + C를 누르세요." -ForegroundColor Yellow
    Write-Host "----------------------------------------------------------------------" -ForegroundColor Yellow

    $UrlOpened = $false
    & $CloudflaredCmd tunnel --url "http://localhost:$Port" 2>&1 | ForEach-Object {
        $line = $_.ToString()
        if (-not $UrlOpened -and $line -match "(https://[a-zA-Z0-9-]+\.trycloudflare\.com)") {
            $UrlOpened = $true
            $FoundUrl = $matches[1]
            Write-Host "`n"
            Write-Host "======================================================================" -ForegroundColor Green
            Write-Host "  🚀 [외부 접속 공인 URL 발급 완료! 아래 주소를 클릭하세요]" -ForegroundColor Green
            Write-Host "  👉 $FoundUrl" -ForegroundColor Yellow
            Write-Host "  💡 웹 브라우저로 위 주소를 자동으로 엽니다..." -ForegroundColor Cyan
            Write-Host "======================================================================`n" -ForegroundColor Green
            try { Start-Process $FoundUrl } catch {}
        }
        Write-Host $line
    }
} finally {
    Write-Host "`n>> 서버 프로세스 종료 중..." -ForegroundColor Gray
    if ($ServerJob -and -not $ServerJob.HasExited) {
        Stop-Process -Id $ServerJob.Id -Force
    }
}
