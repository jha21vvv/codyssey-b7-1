import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.core.config import settings
from app.core.database import Base, get_db
from app.models.user import User
from app.models.chat_log import ChatLog
from app.services.log_service import save_chat_log, get_user_chat_logs, get_all_chat_logs

"""
[권태현 전담] 대화 로그 저장·조회 서비스와 로그 조회 API(/api/logs) 검증 테스트
"""

# test_auth.py와 같은 StaticPool 인메모리 DB를 쓰되, 엔진을 따로 만들어 두 파일의 데이터가 섞이지 않게 함
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

ADMIN_KEY = "test-admin-key"

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    # test_auth.py가 파일 전체에 걸어 둔 get_db 교체를 덮어쓰지 않도록, 테스트마다 바꿨다가 원래대로 되돌림
    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    yield
    if previous_override is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous_override
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()

def create_user(db, username: str) -> int:
    """서비스 테스트용 사용자를 DB에 바로 만들고 id를 반환"""
    user = User(username=username, hashed_password="not-used-in-log-tests")
    db.add(user)
    db.commit()
    return user.id

def login_as(username: str):
    """회원가입 후 로그인하여 (인증 헤더, user_id)를 반환"""
    client.post("/api/auth/register", json={"username": username, "password": "password123"})
    data = client.post("/api/auth/login", json={"username": username, "password": "password123"}).json()
    return {"Authorization": f"Bearer {data['access_token']}"}, data["user"]["id"]

# -------------------------------------------------------------
# 1. 대화 로그 저장·조회 서비스 (log_service)
# -------------------------------------------------------------
def test_save_chat_log_stores_all_fields(db):
    user_id = create_user(db, "alice")
    before = datetime.now(timezone.utc).replace(tzinfo=None)

    log = save_chat_log(user_id=user_id, prompt="안녕?", response="안녕하세요!", status="SUCCESS", db=db)

    after = datetime.now(timezone.utc).replace(tzinfo=None)
    assert log.id is not None
    assert (log.user_id, log.prompt, log.response, log.status) == (user_id, "안녕?", "안녕하세요!", "SUCCESS")
    # 생성 시각은 timezone 정보 없는 UTC로 저장 (웹 UI가 UTC로 읽어 한국 시간으로 바꿔 보여줌)
    assert log.created_at.tzinfo is None
    assert before <= log.created_at <= after
    assert db.query(ChatLog).count() == 1

def test_save_chat_log_rolls_back_on_failure(db):
    user_id = create_user(db, "alice")

    with pytest.raises(IntegrityError):
        save_chat_log(user_id=user_id, prompt=None, response="답변", status="SUCCESS", db=db)

    # 롤백되었으므로 같은 세션으로 다음 저장이 정상 동작해야 함
    save_chat_log(user_id=user_id, prompt="다시 질문", response="답변", status="SUCCESS", db=db)
    assert [log.prompt for log in db.query(ChatLog).all()] == ["다시 질문"]

def test_get_user_chat_logs_returns_own_recent_logs_newest_first(db):
    alice_id = create_user(db, "alice")
    bob_id = create_user(db, "bob")
    for i in range(3):
        save_chat_log(user_id=alice_id, prompt=f"alice 질문 {i}", response="답변", status="SUCCESS", db=db)
    save_chat_log(user_id=bob_id, prompt="bob 질문", response="답변", status="FAILED", db=db)

    logs = get_user_chat_logs(user_id=alice_id, limit=10, db=db)
    assert [log.prompt for log in logs] == ["alice 질문 2", "alice 질문 1", "alice 질문 0"]

    recent = get_user_chat_logs(user_id=alice_id, limit=2, db=db)
    assert [log.prompt for log in recent] == ["alice 질문 2", "alice 질문 1"]

def test_get_user_chat_logs_orders_same_time_by_id(db):
    user_id = create_user(db, "alice")
    same_time = datetime(2026, 10, 21, 0, 0, 0)
    for i in range(3):
        db.add(ChatLog(user_id=user_id, prompt=f"질문 {i}", response="답변", status="SUCCESS", created_at=same_time))
    db.commit()

    logs = get_user_chat_logs(user_id=user_id, limit=10, db=db)
    assert [log.prompt for log in logs] == ["질문 2", "질문 1", "질문 0"]

def test_get_all_chat_logs_pages_all_users_newest_first(db):
    alice_id = create_user(db, "alice")
    bob_id = create_user(db, "bob")
    save_chat_log(user_id=alice_id, prompt="첫 질문", response="답변", status="SUCCESS", db=db)
    save_chat_log(user_id=bob_id, prompt="두 번째 질문", response="답변", status="FAILED", db=db)
    save_chat_log(user_id=alice_id, prompt="세 번째 질문", response="답변", status="SUCCESS", db=db)

    logs = get_all_chat_logs(skip=0, limit=100, db=db)
    assert [log.prompt for log in logs] == ["세 번째 질문", "두 번째 질문", "첫 질문"]

    page = get_all_chat_logs(skip=1, limit=1, db=db)
    assert [log.prompt for log in page] == ["두 번째 질문"]

# -------------------------------------------------------------
# 2. 내 대화 이력 조회 API (GET /api/logs/me)
# -------------------------------------------------------------
def test_my_logs_without_token_fail():
    response = client.get("/api/logs/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "로그인이 필요한 서비스입니다."

def test_my_logs_with_invalid_token_fail():
    response = client.get("/api/logs/me", headers={"Authorization": "Bearer invalid-token"})
    assert response.status_code == 401

def test_my_logs_returns_only_my_logs_newest_first(db):
    alice_headers, alice_id = login_as("alice")
    _, bob_id = login_as("bob")
    save_chat_log(user_id=alice_id, prompt="alice 첫 질문", response="답변 1", status="SUCCESS", db=db)
    save_chat_log(user_id=bob_id, prompt="bob 질문", response="답변", status="SUCCESS", db=db)
    save_chat_log(user_id=alice_id, prompt="alice 두 번째 질문", response="응답 시간이 초과되었습니다.", status="FAILED", db=db)

    response = client.get("/api/logs/me", headers=alice_headers)
    assert response.status_code == 200
    data = response.json()
    assert [log["prompt"] for log in data] == ["alice 두 번째 질문", "alice 첫 질문"]
    assert set(data[0]) == {"id", "user_id", "prompt", "response", "status", "created_at"}
    assert data[0]["user_id"] == alice_id
    assert data[0]["status"] == "FAILED"

def test_my_logs_limit(db):
    headers, user_id = login_as("alice")
    for i in range(3):
        save_chat_log(user_id=user_id, prompt=f"질문 {i}", response="답변", status="SUCCESS", db=db)

    response = client.get("/api/logs/me?limit=2", headers=headers)
    assert response.status_code == 200
    assert [log["prompt"] for log in response.json()] == ["질문 2", "질문 1"]

    # 범위를 벗어난 limit(1~500)은 422로 거부
    assert client.get("/api/logs/me?limit=0", headers=headers).status_code == 422
    assert client.get("/api/logs/me?limit=501", headers=headers).status_code == 422

# -------------------------------------------------------------
# 3. 전체 대화 로그 조회 API (GET /api/logs/admin)
# -------------------------------------------------------------
def test_admin_logs_disabled_when_key_not_set(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_API_KEY", "")

    response = client.get("/api/logs/admin", headers={"X-Admin-Key": "anything"})
    assert response.status_code == 403
    assert response.json()["detail"] == "전체 로그 조회 기능이 꺼져 있습니다."

def test_admin_logs_with_missing_or_wrong_key_fail(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_API_KEY", ADMIN_KEY)
    user_headers, _ = login_as("alice")

    wrong_requests = [
        {},                                       # 헤더 없음
        {"X-Admin-Key": "wrong-key"},             # 틀린 키
        {"X-Admin-Key": "é".encode("latin-1")},   # ASCII가 아닌 값도 500이 아닌 403
        user_headers,                             # 일반 사용자 로그인 토큰으로는 볼 수 없음
    ]
    for headers in wrong_requests:
        response = client.get("/api/logs/admin", headers=headers)
        assert response.status_code == 403
        assert response.json()["detail"] == "관리자 키가 올바르지 않습니다."

def test_admin_logs_returns_all_users_logs(monkeypatch, db):
    monkeypatch.setattr(settings, "ADMIN_API_KEY", ADMIN_KEY)
    alice_id = create_user(db, "alice")
    bob_id = create_user(db, "bob")
    save_chat_log(user_id=alice_id, prompt="alice 질문", response="답변", status="SUCCESS", db=db)
    save_chat_log(user_id=bob_id, prompt="bob 질문", response="답변", status="FAILED", db=db)

    response = client.get("/api/logs/admin", headers={"X-Admin-Key": ADMIN_KEY})
    assert response.status_code == 200
    assert [(log["user_id"], log["prompt"]) for log in response.json()] == [(bob_id, "bob 질문"), (alice_id, "alice 질문")]

def test_admin_logs_paging(monkeypatch, db):
    monkeypatch.setattr(settings, "ADMIN_API_KEY", ADMIN_KEY)
    user_id = create_user(db, "alice")
    for i in range(5):
        save_chat_log(user_id=user_id, prompt=f"질문 {i}", response="답변", status="SUCCESS", db=db)
    headers = {"X-Admin-Key": ADMIN_KEY}

    response = client.get("/api/logs/admin?skip=1&limit=2", headers=headers)
    assert response.status_code == 200
    assert [log["prompt"] for log in response.json()] == ["질문 3", "질문 2"]

    # 범위를 벗어난 skip(0 이상)·limit(1~500)은 422로 거부
    assert client.get("/api/logs/admin?skip=-1", headers=headers).status_code == 422
    assert client.get("/api/logs/admin?limit=501", headers=headers).status_code == 422
