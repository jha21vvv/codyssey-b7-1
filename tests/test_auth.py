import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool  # 👈 StaticPool 임포트 추가
from app.main import app
from app.core.database import Base, get_db
from app.models.user import User  # User 모델 미리 로드

# StaticPool을 적용하여 인메모리 DB 세션이 유지되도록 설정
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # 👈 커넥션이 닫혀도 DB가 사라지지 않게 고정
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

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
    client.post("/api/auth/register", json={"username": "testuser", "password": "password123"})
    
    response = client.post("/api/auth/register", json={"username": "testuser", "password": "password123"})
    assert response.status_code == 409
    assert response.json()["detail"] == "이미 존재하는 아이디입니다."

def test_login_invalid_credentials_fail():
    client.post("/api/auth/register", json={"username": "testuser", "password": "password123"})
    
    response = client.post("/api/auth/login", json={"username": "testuser", "password": "wrongpassword"})
    assert response.status_code == 401
    assert response.json()["detail"] == "아이디 또는 비밀번호가 올바르지 않습니다."

def test_protected_route_without_token():
    response = client.get("/api/auth/me")
    assert response.status_code == 401

def test_protected_route_with_valid_token():
    client.post("/api/auth/register", json={"username": "testuser", "password": "password123"})
    login_resp = client.post("/api/auth/login", json={"username": "testuser", "password": "password123"})
    token = login_resp.json()["access_token"]

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["username"] == "testuser"