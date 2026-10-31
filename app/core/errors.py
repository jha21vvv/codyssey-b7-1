from typing import Any, Dict, Optional
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.core.logger import logger

"""
[권태현] 공통 오류 응답
모든 오류를 같은 형식으로 돌려줍니다: {"detail": 한국어 안내, "code": 오류 코드, "request_id": 요청 ID}
- detail: 사용자에게 보여줄 문장 (기존 응답과 같은 키라 화면과 기존 테스트가 그대로 동작)
- code: 프로그램이 오류 종류를 구분하는 값 (README의 오류 코드표 참고)
- request_id: 응답 헤더 X-Request-ID, 서버 로그, 요청 로그와 같은 값이라 문의·추적에 사용
"""

# raise 할 때 code를 따로 주지 않으면 상태 코드에 맞는 기본 코드를 씀
DEFAULT_ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "AUTH_REQUIRED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    500: "INTERNAL_ERROR",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
    504: "GATEWAY_TIMEOUT",
}

# 프레임워크가 영어로 만드는 기본 문구는 한국어로 바꿔서 보냄
FRAMEWORK_DETAILS = {"Not Found", "Method Not Allowed", "Internal Server Error"}
DEFAULT_MESSAGES = {
    404: "요청한 주소를 찾을 수 없습니다.",
    405: "허용되지 않은 요청 방식입니다.",
    500: "서버 내부 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
}

# 입력값 검증(422) 안내에 쓰는 항목 이름
FIELD_LABELS = {"username": "아이디", "password": "비밀번호", "prompt": "질문"}


class ApiError(StarletteHTTPException):
    """오류 코드(code)를 함께 지정하는 HTTP 예외. 예: raise ApiError(403, "ADMIN_REQUIRED", "관리자만 ...")"""
    def __init__(self, status_code: int, code: str, detail: str, headers: Optional[Dict[str, str]] = None):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code


class ErrorResponse(BaseModel):
    """Swagger 문서에 보여줄 오류 응답 형식"""
    detail: str
    code: str
    request_id: Optional[str] = None


def error_response(
    request: Request,
    status_code: int,
    detail: str,
    code: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **extra: Any,
) -> JSONResponse:
    """공통 형식의 오류 응답을 만들고, 오류 코드를 요청 로그에 남기도록 표시"""
    code = code or DEFAULT_ERROR_CODES.get(status_code, "ERROR")
    request_id = getattr(request.state, "req_id", None)
    request.state.error_code = code
    response_headers = dict(headers or {})
    if request_id:
        response_headers["X-Request-ID"] = request_id
    body = {"detail": detail, "code": code, "request_id": request_id, **extra}
    return JSONResponse(status_code=status_code, content=body, headers=response_headers)


def _with_topic(label: str) -> str:
    """받침에 맞춰 '은/는'을 붙임 (한글로 끝나지 않으면 '은(는)')"""
    last = label[-1]
    if "가" <= last <= "힣":
        return label + ("은" if (ord(last) - ord("가")) % 28 else "는")
    return label + "은(는)"


def error_field(error: Dict[str, Any]) -> str:
    """오류가 난 항목 이름 (JSON 자체가 깨진 경우처럼 위치가 숫자면 body)"""
    loc = error.get("loc") or ()
    if not loc:
        return ""
    return loc[-1] if isinstance(loc[-1], str) else str(loc[0])


def validation_message(error: Dict[str, Any]) -> str:
    """Pydantic 검증 오류 한 건을 한국어 안내 문장으로 바꿈"""
    field = error_field(error)
    label = FIELD_LABELS.get(field, field or "입력값")
    kind = error.get("type", "")
    ctx = error.get("ctx") or {}
    if kind == "value_error":
        # 직접 만든 검사(field_validator)는 이미 한국어 문구라 그대로 사용
        return str(error.get("msg", "")).removeprefix("Value error, ")
    if field == "username" and kind == "string_pattern_mismatch":
        return "아이디는 영문과 숫자만 사용할 수 있습니다."
    if kind == "missing":
        return f"{_with_topic(label)} 필수 항목입니다."
    if kind == "string_too_short":
        return f"{_with_topic(label)} {ctx.get('min_length')}자 이상이어야 합니다."
    if kind == "string_too_long":
        return f"{_with_topic(label)} {ctx.get('max_length')}자 이하여야 합니다."
    if kind == "string_pattern_mismatch":
        return f"{label} 형식이 올바르지 않습니다."
    if kind == "greater_than_equal":
        return f"{_with_topic(label)} {ctx.get('ge')} 이상이어야 합니다."
    if kind == "less_than_equal":
        return f"{_with_topic(label)} {ctx.get('le')} 이하여야 합니다."
    if kind in ("int_parsing", "int_type"):
        return f"{_with_topic(label)} 숫자여야 합니다."
    if kind == "json_invalid":
        return "요청 본문(JSON) 형식이 올바르지 않습니다."
    return f"{label} 값이 올바르지 않습니다."


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    if detail in FRAMEWORK_DETAILS:
        detail = DEFAULT_MESSAGES.get(exc.status_code, detail)
    return error_response(request, exc.status_code, detail, getattr(exc, "code", None), headers=exc.headers)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # 입력한 값(input)은 응답에 다시 싣지 않음 (비밀번호가 그대로 돌아가는 것을 막음)
    errors = []
    for error in exc.errors():
        errors.append({"field": error_field(error), "message": validation_message(error)})
    messages = list(dict.fromkeys(item["message"] for item in errors))  # 같은 문장은 한 번만
    detail = "\n".join(messages) or "입력값이 올바르지 않습니다."
    return error_response(request, 422, detail, "VALIDATION_ERROR", errors=errors)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # 내부 오류 내용은 서버 로그에만 남기고, 사용자에게는 요청 ID만 알려 줌
    request_id = getattr(request.state, "req_id", "-")
    logger.error(f"[처리되지 않은 예외] request_id={request_id} {type(exc).__name__}", exc_info=exc)
    return error_response(request, 500, DEFAULT_MESSAGES[500], "INTERNAL_ERROR")


def register_error_handlers(app: FastAPI) -> None:
    """main.py에서 호출: 모든 오류를 공통 형식으로 바꾸는 처리기 등록"""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
