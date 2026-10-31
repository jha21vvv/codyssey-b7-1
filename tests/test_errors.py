import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.core.database import Base, get_db
from app.core.errors import register_error_handlers, validation_message
from app.core.logger import LoggingMiddleware

"""
[권태현 전담] 공통 오류 응답({detail, code, request_id}) 검증 테스트
"""

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    yield
    if previous_override is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous_override
    Base.metadata.drop_all(bind=engine)

def assert_error_format(response, status_code, code):
    assert response.status_code == status_code
    body = response.json()
    assert body["code"] == code
    assert isinstance(body["detail"], str) and body["detail"]
    # 응답 본문과 헤더의 요청 ID가 같아야 서버 로그·요청 로그에서 찾을 수 있음
    assert body["request_id"] == response.headers["X-Request-ID"]
    return body

def test_auth_error_format():
    response = client.get("/api/logs/me")
    body = assert_error_format(response, 401, "AUTH_REQUIRED")
    assert body["detail"] == "로그인이 필요한 서비스입니다."
    assert response.headers["WWW-Authenticate"] == "Bearer"

def test_conflict_error_format():
    client.post("/api/auth/register", json={"username": "alice1", "password": "password123"})
    response = client.post("/api/auth/register", json={"username": "alice1", "password": "password123"})
    body = assert_error_format(response, 409, "CONFLICT")
    assert body["detail"] == "이미 존재하는 아이디입니다."

def test_not_found_and_method_not_allowed_in_korean():
    body = assert_error_format(client.get("/api/nothing"), 404, "NOT_FOUND")
    assert body["detail"] == "요청한 주소를 찾을 수 없습니다."
    body = assert_error_format(client.get("/api/chat"), 405, "METHOD_NOT_ALLOWED")
    assert body["detail"] == "허용되지 않은 요청 방식입니다."

def test_validation_error_in_korean_without_echoing_input():
    response = client.post("/api/auth/register", json={"username": "ab", "password": "abc"})
    body = assert_error_format(response, 422, "VALIDATION_ERROR")
    assert body["detail"] == "아이디는 3자 이상이어야 합니다.\n비밀번호는 4자 이상이어야 합니다."
    assert [error["field"] for error in body["errors"]] == ["username", "password"]
    # 입력한 비밀번호가 응답에 다시 실리지 않아야 함
    assert "abc" not in response.text

def test_custom_validator_message_kept():
    response = client.post("/api/auth/register", json={"username": "alice1", "password": "     "})
    body = assert_error_format(response, 422, "VALIDATION_ERROR")
    assert body["detail"] == "비밀번호는 공백으로만 구성될 수 없습니다."

def test_broken_json_error():
    response = client.post("/api/auth/login", content="{bad", headers={"Content-Type": "application/json"})
    body = assert_error_format(response, 422, "VALIDATION_ERROR")
    assert body["detail"] == "요청 본문(JSON) 형식이 올바르지 않습니다."
    assert body["errors"][0]["field"] == "body"

def test_unhandled_exception_hides_internal_detail():
    # 실제 앱에 테스트용 경로를 남기지 않도록 같은 처리기를 단 작은 앱으로 확인
    boom_app = FastAPI()
    boom_app.add_middleware(LoggingMiddleware)
    register_error_handlers(boom_app)

    @boom_app.get("/boom")
    def boom():
        raise RuntimeError("secret-internal-detail")

    response = TestClient(boom_app, raise_server_exceptions=False).get("/boom")
    body = assert_error_format(response, 500, "INTERNAL_ERROR")
    assert body["detail"] == "서버 내부 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
    assert "secret-internal-detail" not in response.text

def test_validation_message_uses_correct_particle():
    assert validation_message({"loc": ("body", "prompt"), "type": "string_too_long", "ctx": {"max_length": 1000}}) == "질문은 1000자 이하여야 합니다."
    assert validation_message({"loc": ("body", "username"), "type": "missing"}) == "아이디는 필수 항목입니다."
    assert validation_message({"loc": ("query", "limit"), "type": "greater_than_equal", "ctx": {"ge": 1}}) == "limit은(는) 1 이상이어야 합니다."
