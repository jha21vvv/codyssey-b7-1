import logging
import sys
import uuid
import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

"""
[안재현 전담] 표준 로깅 모듈 및 Request-ID 추적 미들웨어
과제 필수 요구사항(서버 로그에 [요청 수신] 이벤트 필수 기록)을 충족합니다.
"""

# 로거 생성 및 포맷 설정
LOGGER_NAME = "codyssey_logger"
logger = logging.getLogger(LOGGER_NAME)
logger.setLevel(logging.INFO)

# 기존 핸들러 중복 방지
if not logger.handlers:
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # 콘솔 표준 출력 핸들러
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 파일 출력 핸들러 (server.log 에도 영구 기록)
    file_handler = logging.FileHandler("server.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

class LoggingMiddleware(BaseHTTPMiddleware):
    """
    모든 들어오는 HTTP 요청에 Request-ID를 부여하고,
    과제 필수 요구사항인 [요청 수신] 이벤트 및 응답 소요 시간을 자동 로깅합니다.
    """
    async def dispatch(self, request: Request, call_next):
        # 고유 Request-ID 생성 (추적용)
        req_id = str(uuid.uuid4())[:8]
        request.state.req_id = req_id
        start_time = time.time()
        
        # 클라이언트 IP 추출 (역방향 프록시 및 터널 환경의 X-Forwarded-For, X-Real-IP 우선 지원)
        forwarded_for = request.headers.get("x-forwarded-for")
        real_ip = request.headers.get("x-real-ip")
        if forwarded_for:
            client_host = forwarded_for.split(",")[0].strip()
        elif real_ip:
            client_host = real_ip.strip()
        elif request.client:
            client_host = request.client.host
        else:
            client_host = "unknown"

        path = request.url.path
        method = request.method
        
        # 🚨 [과제 필수 요구조건: 요청 수신 이벤트 기록]
        logger.info(f"[{req_id}] [요청 수신] {method} {path} (from {client_host})")
        
        try:
            response: Response = await call_next(request)
            duration_ms = round((time.time() - start_time) * 1000, 2)
            
            # 응답 헤더에 Request-ID 주입 (클라이언트 디버깅용)
            response.headers["X-Request-ID"] = req_id
            
            logger.info(f"[{req_id}] [응답 완료] {method} {path} -> status={response.status_code} ({duration_ms}ms)")
            return response
        except Exception as exc:
            duration_ms = round((time.time() - start_time) * 1000, 2)
            logger.error(f"[{req_id}] [서버 예외 발생] {method} {path} ({duration_ms}ms) - {str(exc)}")
            raise exc
