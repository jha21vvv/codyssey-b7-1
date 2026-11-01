import io
import logging
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.core.database import Base, get_db
from app.core.logger import logger, RequestIdFilter
from app.models.request_log import RequestLog

"""
[권태현 전담] 요청 로그(request_logs) 저장과 서버 로그의 요청 ID 검증 테스트
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
    # 다른 테스트 파일이 걸어 둔 get_db 교체를 덮어쓰지 않도록, 테스트마다 바꿨다가 원래대로 되돌림
    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    yield
    if previous_override is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous_override
    Base.metadata.drop_all(bind=engine)

def saved_logs():
    db = TestingSessionLocal()
    try:
        return db.query(RequestLog).order_by(RequestLog.id).all()
    finally:
        db.close()

def login_headers(username: str = "alice1"):
    client.post("/api/auth/register", json={"username": username, "password": "password123"})
    token = client.post("/api/auth/login", json={"username": username, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

def test_api_request_saved_with_request_id():
    response = client.post("/api/auth/register", json={"username": "alice1", "password": "password123"})
    assert response.status_code == 201

    logs = saved_logs()
    assert len(logs) == 1
    log = logs[0]
    assert log.request_id == response.headers["X-Request-ID"]
    assert (log.method, log.path, log.status_code) == ("POST", "/api/auth/register", 201)
    assert log.duration_ms >= 0
    assert log.user_id is None
    assert log.error_code is None
    assert log.created_at is not None

def test_logged_in_requests_record_user():
    headers = login_headers("alice1")
    assert client.get("/api/auth/me", headers=headers).status_code == 200

    by_path = {log.path: log for log in saved_logs()}
    user_id = by_path["/api/auth/me"].user_id
    assert user_id is not None
    assert by_path["/api/auth/login"].user_id == user_id
    assert by_path["/api/auth/register"].user_id is None

def test_error_request_records_error_code():
    response = client.get("/api/logs/me")
    assert response.status_code == 401

    log = saved_logs()[-1]
    assert (log.status_code, log.error_code) == (401, "AUTH_REQUIRED")
    assert log.request_id == response.json()["request_id"]

def test_non_api_requests_not_saved():
    for path in ["/", "/health", "/static/css/style.css"]:
        assert client.get(path).status_code == 200
    assert saved_logs() == []

def test_request_log_failure_does_not_break_request():
    # 요청 로그 테이블이 없어도 사용자 요청은 정상 처리되어야 함
    RequestLog.__table__.drop(bind=engine)
    response = client.post("/api/auth/register", json={"username": "alice1", "password": "password123"})
    assert response.status_code == 201

def test_every_log_line_has_request_id():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(logging.Formatter("[%(request_id)s] %(message)s"))
    logger.addHandler(handler)
    try:
        response = client.post("/api/auth/register", json={"username": "alice1", "password": "password123"})
    finally:
        logger.removeHandler(handler)

    request_id = response.headers["X-Request-ID"]
    lines = [line for line in stream.getvalue().splitlines() if line]
    assert any("[요청 수신]" in line for line in lines)
    assert any("[회원가입 성공]" in line for line in lines)
    assert all(line.startswith(f"[{request_id}]") for line in lines)
