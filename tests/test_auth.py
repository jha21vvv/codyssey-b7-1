import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.core.database import Base, get_db

# 테스트용 격리된 인메모리 SQLite DB 설정
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

# 실제 DB 대신 테스트용 DB로 의존성 교체
app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

def test_register_and_login_success():
    # 1. 회원가입 성공 테스트
    response = client.post(
        "/api/auth/register",
        json={"username": "testuser", "password": "password123"}
    )
    assert response.status_code == 201
    assert response.json()["message"] == "회원가입이 완료되었습니다."

    # 2. 로그인 성공 테스트
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "password123"}
    )
    assert login_resp.status_code == 200
    data = login_resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["username"] == "testuser"

def test_register_duplicate_username_fail():
    # 첫 번째 회원가입
    client.post("/api/auth/register", json={"username": "testuser", "password": "password123"})
    
    # 동일 아이디 중복 가입 시도 -> 409 Conflict
    response = client.post("/api/auth/register", json={"username": "testuser", "password": "password123"})
    assert response.status_code == 409
    assert response.json()["detail"] == "이미 존재하는 아이디입니다."

def test_login_invalid_credentials_fail():
    client.post("/api/auth/register", json={"username": "testuser", "password": "password123"})
    
    # 잘못된 비밀번호 로그인 시도 -> 401 Unauthorized
    response = client.post("/api/auth/login", json={"username": "testuser", "password": "wrongpassword"})
    assert response.status_code == 401
    assert response.json()["detail"] == "아이디 또는 비밀번호가 올바르지 않습니다."

def test_protected_route_without_token():
    # 토큰 없이 내 정보 조회 시도 -> 401 Unauthorized 차단
    response = client.get("/api/auth/me")
    assert response.status_code == 401

def test_protected_route_with_valid_token():
    client.post("/api/auth/register", json={"username": "testuser", "password": "password123"})
    login_resp = client.post("/api/auth/login", json={"username": "testuser", "password": "password123"})
    token = login_resp.json()["access_token"]

    # Bearer 토큰을 헤더에 넣어서 요청
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["username"] == "testuser"