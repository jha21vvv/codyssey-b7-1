import logging
import sys
import uuid
import time
from contextvars import ContextVar
from typing import Any, Callable, Dict, Optional
from fastapi import Request
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

"""
[안재현 전담] 표준 로깅 모듈 및 Request-ID 추적 미들웨어
과제 필수 요구사항(서버 로그에 [요청 수신] 이벤트 필수 기록)을 충족합니다.
"""

# [권태현] 지금 처리 중인 요청의 Request-ID (요청 밖에서 남는 로그는 "-")
# 미들웨어에서 정한 값을 AI 호출·DB 저장 등 모든 로그 줄에 붙여, 요청 하나의 흐름을 이어서 볼 수 있게 함
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

class RequestIdFilter(logging.Filter):
    """로그 줄마다 현재 요청의 Request-ID를 채워 넣음"""
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True

# 로거 생성 및 포맷 설정
LOGGER_NAME = "codyssey_logger"
logger = logging.getLogger(LOGGER_NAME)
logger.setLevel(logging.INFO)

# 기존 핸들러 중복 방지
if not logger.handlers:
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | [%(request_id)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # 콘솔 표준 출력 핸들러
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(RequestIdFilter())
    logger.addHandler(console_handler)

    # 파일 출력 핸들러 (server.log 에도 영구 기록)
    file_handler = logging.FileHandler("server.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(RequestIdFilter())
    logger.addHandler(file_handler)

# [권태현] 요청 로그(DB)는 API 요청만 저장 (화면·정적 파일·헬스체크는 양이 많아 제외)
REQUEST_LOG_PATH_PREFIX = "/api/"

class LoggingMiddleware(BaseHTTPMiddleware):
    """
    모든 들어오는 HTTP 요청에 Request-ID를 부여하고,
    과제 필수 요구사항인 [요청 수신] 이벤트 및 응답 소요 시간을 자동 로깅합니다.
    [권태현] on_request로 저장 함수를 받으면 API 요청마다 요청 로그(DB)도 한 줄씩 남깁니다.
    """
    def __init__(self, app, on_request: Optional[Callable[[Any, Dict[str, Any]], None]] = None):
        super().__init__(app)
        self.on_request = on_request

    async def dispatch(self, request: Request, call_next):
        # 고유 Request-ID 생성 (추적용)
        req_id = str(uuid.uuid4())[:8]
        request.state.req_id = req_id
        request_id_token = request_id_var.set(req_id)
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
        logger.info(f"[요청 수신] {method} {path} (from {client_host})")
        
        try:
            response: Response = await call_next(request)
            duration_ms = round((time.time() - start_time) * 1000, 2)
            
            # 응답 헤더에 Request-ID 주입 (클라이언트 디버깅용)
            response.headers["X-Request-ID"] = req_id
            
            logger.info(f"[응답 완료] {method} {path} -> status={response.status_code} ({duration_ms}ms)")
            await self._record(request, response.status_code, duration_ms, client_host)
            return response
        except Exception as exc:
            duration_ms = round((time.time() - start_time) * 1000, 2)
            logger.error(f"[서버 예외 발생] {method} {path} ({duration_ms}ms) - {str(exc)}")
            await self._record(request, 500, duration_ms, client_host, error_code="INTERNAL_ERROR")
            raise exc
        finally:
            request_id_var.reset(request_id_token)

    async def _record(self, request: Request, status_code: int, duration_ms: float, client_host: str, error_code: Optional[str] = None):
        """[권태현] API 요청을 요청 로그(DB)에 저장 (DB 작업이라 이벤트 루프를 막지 않게 스레드에서 실행)"""
        if self.on_request is None or not request.url.path.startswith(REQUEST_LOG_PATH_PREFIX):
            return
        fields = {
            "request_id": request.state.req_id,
            "method": request.method,
            "path": request.url.path[:255],
            "status_code": status_code,
            "duration_ms": int(round(duration_ms)),
            "user_id": getattr(request.state, "user_id", None),  # get_current_user·로그인에서 채움
            "client_ip": client_host[:64],
            "user_agent": (request.headers.get("user-agent") or "")[:255] or None,
            # 오류 응답이면 오류 처리기가 정한 code (app/core/errors.py)
            "error_code": error_code or getattr(request.state, "error_code", None),
        }
        await run_in_threadpool(self.on_request, request.app, fields)
