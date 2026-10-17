import pytest
from fastapi.testclient import TestClient
from app.main import app

"""
[안재현 전담] 기반 인프라 및 헬스체크, 로깅 미들웨어 검증 테스트
"""

client = TestClient(app)

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
