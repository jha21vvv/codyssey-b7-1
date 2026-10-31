import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.core.database import get_db

"""
[안재현 전담] 기반 인프라 및 헬스체크, 로깅 미들웨어 검증 테스트
"""

client = TestClient(app)

# [권태현] 헬스체크가 DB에 실제로 질의하므로, 실제 DB 파일 대신 메모리 DB를 쓰도록 테스트마다 바꿨다가 되돌림
engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture(autouse=True)
def use_test_db():
    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    yield
    if previous_override is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous_override

def test_health_check_success():
    """GET /health 엔드포인트 200 OK 및 필수 필드 응답 검증"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "project" in data
    assert "database" in data

def test_logging_middleware_header_injection():
    """모든 응답에 X-Request-ID 헤더가 정상 주입되는지 검증"""
    response = client.get("/health")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) > 0

def test_logging_middleware_reverse_proxy_headers():
    """역방향 프록시 헤더(X-Forwarded-For, X-Real-IP) 전송 시 정상 로깅 및 동작 검증"""
    response = client.get("/health", headers={"X-Forwarded-For": "203.0.113.195, 10.0.0.1"})
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers

    response_real = client.get("/health", headers={"X-Real-IP": "198.51.100.42"})
    assert response_real.status_code == 200
    assert "X-Request-ID" in response_real.headers

def test_logging_middleware_non_existent_route():
    """존재하지 않는 경로 요청 시에도 X-Request-ID 주입 및 미들웨어 정상 동작 검증"""
    response = client.get("/non-existent-route-404")
    assert response.status_code == 404
    assert "X-Request-ID" in response.headers

def test_health_check_reports_database_and_runtime():
    """[권태현] 헬스체크가 DB 연결을 실제로 확인하고 버전·가동 시간·AI 설정 여부를 알려 주는지 검증"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["database"]["status"] == "ok"
    assert data["version"] == app.version
    assert data["uptime_seconds"] >= 0
    assert isinstance(data["ai"]["configured"], bool)
    assert data["checked_at"].endswith("Z")

def test_health_check_returns_503_when_database_fails():
    """[권태현] DB 질의가 실패하면 503과 unhealthy를 돌려줘 외부 모니터링이 장애를 알아채는지 검증"""
    broken_db = MagicMock()
    broken_db.execute.side_effect = RuntimeError("database is locked")

    def broken_get_db():
        yield broken_db

    app.dependency_overrides[get_db] = broken_get_db
    response = client.get("/health")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "unhealthy"
    assert data["database"]["status"] == "error"
