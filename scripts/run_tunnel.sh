#!/usr/bin/env bash
# ==============================================================================
# [안재현 전담] Codyssey B7-1 배포 및 외부 접속 터널 구동 스크립트
#
# FastAPI 백엔드 서버(uvicorn)와 Cloudflare Tunnel(cloudflared)을 실행하여
# 평가자가 외부 네트워크에서 웹 서비스에 접속할 수 있는 퍼블릭 URL을 발급받습니다.
#
# 실행 방법:
#   chmod +x scripts/run_tunnel.sh
#   ./scripts/run_tunnel.sh
# ==============================================================================

set -e

PORT=${PORT:-8000}
HOST="0.0.0.0"

echo "======================================================================"
echo " [Codyssey B7-1] 웹 AI 챗봇 배포 및 Cloudflare 터널 실행기"
echo "======================================================================"

# 1. 가상환경 활성화 검사
if [ -d ".venv" ]; then
    echo ">> 로컬 가상환경(.venv) 활성화 중..."
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    elif [ -f ".venv/Scripts/activate" ]; then
        source .venv/Scripts/activate
    fi
fi

# 2. cloudflared 바이너리 설치 여부 점검
CLOUDFLARED_CMD="cloudflared"
if ! command -v cloudflared &> /dev/null; then
    echo ">> [주의] 시스템 PATH에 cloudflared가 발견되지 않았습니다."
    
    # OS별 자동 바이너리 다운로드 시도
    OS_TYPE="$(uname -s)"
    if [ "$OS_TYPE" = "Linux" ]; then
        echo ">> Linux용 cloudflared 바이너리 다운로드 중..."
        curl -sL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o ./cloudflared
        chmod +x ./cloudflared
        CLOUDFLARED_CMD="./cloudflared"
    elif [ "$OS_TYPE" = "Darwin" ]; then
        echo ">> macOS 환경입니다. 'brew install cloudflared' 설치를 권장합니다."
    else
        echo ">> 수동 설치 가이드:"
        echo "   - Windows: winget install --id Cloudflare.cloudflared"
        echo "   - Linux: sudo apt install cloudflared 또는 GitHub 릴리즈 참조"
        echo "   - macOS: brew install cloudflared"
    fi
fi

echo ">> 1. FastAPI 백엔드 서버 기동 (http://${HOST}:${PORT})..."
uvicorn app.main:app --host "${HOST}" --port "${PORT}" &
SERVER_PID=$!

cleanup() {
    echo ""
    echo ">> 서비스 종료 중... (PID: $SERVER_PID)"
    kill $SERVER_PID 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# 서버 준비 대기
sleep 2

echo ">> 2. Cloudflare 터널 기동 중... (외부 접속 URL 발급 대기)"
echo "----------------------------------------------------------------------"
echo "아래 로그에 출력되는 'https://*.trycloudflare.com' 주소로 접속하세요!"
echo "----------------------------------------------------------------------"

if command -v $CLOUDFLARED_CMD &> /dev/null || [ -x "$CLOUDFLARED_CMD" ]; then
    $CLOUDFLARED_CMD tunnel --url "http://localhost:${PORT}"
else
    echo ">> cloudflared를 실행할 수 없어 로컬 서버만 유지합니다."
    echo ">> 외부 접속을 위해 별도 터미널에서 터널링 도구를 실행해주세요."
    wait $SERVER_PID
fi
