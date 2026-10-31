import importlib.util
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.core.database import Base, get_db
from app.core.timeutil import utc_now
from app.models.chat_log import ChatLog
from app.models.request_log import RequestLog
from app.models.user import ADMIN_ROLE, USER_ROLE, User
from app.services.ai_service import AIResult, FALLBACK_TIMEOUT_MESSAGE
from app.services.auth_service import verify_password

"""
[권태현 전담] 관리자 계정(역할)·관리자 API(/api/admin)·관리자 지정 스크립트 검증 테스트
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

ADMIN_PATHS = [
    "/api/admin/summary",
    "/api/admin/requests",
    "/api/admin/requests/abcd1234",
    "/api/admin/chat-logs",
]

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

def run_in_db(work):
    """테스트 DB 세션에서 work(db)를 실행하고 커밋"""
    db = TestingSessionLocal()
    try:
        result = work(db)
        db.commit()
        return result
    finally:
        db.close()

def login(username: str):
    """회원가입 후 로그인하여 (인증 헤더, user_id)를 반환"""
    client.post("/api/auth/register", json={"username": username, "password": "password123"})
    data = client.post("/api/auth/login", json={"username": username, "password": "password123"}).json()
    return {"Authorization": f"Bearer {data['access_token']}"}, data["user"]["id"]

def set_role(user_id: int, role: str):
    run_in_db(lambda db: db.query(User).filter(User.id == user_id).update({"role": role}))

def login_admin(username: str = "admin1"):
    headers, user_id = login(username)
    set_role(user_id, ADMIN_ROLE)
    return headers, user_id

def clear_request_logs():
    """회원가입·로그인 요청 기록을 지워, 테스트가 넣은 요청 로그만 남김"""
    run_in_db(lambda db: db.query(RequestLog).delete())

def add_request_log(minutes_ago=0, **fields):
    values = {
        "request_id": "req00000",
        "method": "GET",
        "path": "/api/logs/me",
        "status_code": 200,
        "duration_ms": 10,
        "created_at": utc_now() - timedelta(minutes=minutes_ago),
    }
    values.update(fields)
    run_in_db(lambda db: db.add(RequestLog(**values)))

def add_chat_log(user_id: int, minutes_ago=0, **fields):
    values = {
        "user_id": user_id,
        "prompt": "질문",
        "response": "답변",
        "status": "SUCCESS",
        "created_at": utc_now() - timedelta(minutes=minutes_ago),
    }
    values.update(fields)
    run_in_db(lambda db: db.add(ChatLog(**values)))

def assert_error(response, status_code, code):
    assert response.status_code == status_code
    body = response.json()
    assert body["code"] == code
    assert body["request_id"] == response.headers["X-Request-ID"]
    return body

# -------------------------------------------------------------
# 1. 역할과 권한 검사
# -------------------------------------------------------------
def test_new_user_is_normal_user():
    headers, _ = login("alice")
    assert client.get("/api/auth/me", headers=headers).json()["role"] == USER_ROLE

def test_admin_role_in_login_response():
    _, user_id = login("alice")
    set_role(user_id, ADMIN_ROLE)
    data = client.post("/api/auth/login", json={"username": "alice", "password": "password123"}).json()
    # 웹 화면은 이 값으로 관리자에게만 관리자 화면 링크를 보여줌
    assert data["user"]["role"] == ADMIN_ROLE

def test_admin_api_requires_login():
    for path in ADMIN_PATHS:
        assert_error(client.get(path), 401, "AUTH_REQUIRED")
        assert_error(client.get(path, headers={"Authorization": "Bearer invalid-token"}), 401, "AUTH_REQUIRED")

def test_admin_api_rejects_normal_user():
    headers, user_id = login("alice")
    for path in ADMIN_PATHS:
        body = assert_error(client.get(path, headers=headers), 403, "ADMIN_REQUIRED")
        assert body["detail"] == "관리자만 사용할 수 있는 기능입니다."

    # 거부된 요청도 누가 시도했는지 요청 로그에 남음
    denied = run_in_db(lambda db: [
        (log.path, log.status_code, log.user_id)
        for log in db.query(RequestLog).filter(RequestLog.error_code == "ADMIN_REQUIRED").order_by(RequestLog.id)
    ])
    assert denied == [(path, 403, user_id) for path in ADMIN_PATHS]

def test_admin_role_checked_on_every_request():
    headers, user_id = login("alice")
    set_role(user_id, ADMIN_ROLE)
    assert client.get("/api/admin/summary", headers=headers).status_code == 200

    # 역할은 토큰이 아니라 DB에서 매번 확인하므로, 권한을 해제하면 같은 토큰으로도 바로 막힘
    set_role(user_id, USER_ROLE)
    assert_error(client.get("/api/admin/summary", headers=headers), 403, "ADMIN_REQUIRED")

def test_old_admin_key_endpoint_removed():
    headers, _ = login_admin()
    assert client.get("/api/logs/admin", headers={**headers, "X-Admin-Key": "anything"}).status_code == 404

# -------------------------------------------------------------
# 2. 요청 로그 목록 (GET /api/admin/requests)
# -------------------------------------------------------------
def seed_request_logs(alice_id: int):
    clear_request_logs()
    add_request_log(minutes_ago=6, request_id="r1", path="/api/auth/login", method="POST", status_code=200, duration_ms=30)
    add_request_log(minutes_ago=5, request_id="r2", path="/api/chat", method="POST", status_code=200, duration_ms=1500, user_id=alice_id)
    add_request_log(minutes_ago=4, request_id="r3", path="/api/logs/me", status_code=401, duration_ms=5, error_code="AUTH_REQUIRED")
    add_request_log(minutes_ago=3, request_id="r4", path="/api/chat", method="POST", status_code=504, duration_ms=10003, user_id=alice_id, error_code="AI_TIMEOUT")
    add_request_log(minutes_ago=2, request_id="r5", path="/api/nothing", status_code=404, duration_ms=2, error_code="NOT_FOUND")
    add_request_log(minutes_ago=1, request_id="r6", path="/api/admin/summary", status_code=200, duration_ms=15)

def request_ids(response):
    assert response.status_code == 200
    return [item["request_id"] for item in response.json()["items"]]

def test_request_logs_newest_first_with_username():
    headers, _ = login_admin()
    _, alice_id = login("alice")
    seed_request_logs(alice_id)

    response = client.get("/api/admin/requests", headers=headers)
    body = response.json()
    assert request_ids(response) == ["r6", "r5", "r4", "r3", "r2", "r1"]
    assert (body["total"], body["skip"], body["limit"]) == (6, 0, 50)
    by_id = {item["request_id"]: item for item in body["items"]}
    assert by_id["r4"]["username"] == "alice"
    assert by_id["r4"]["error_code"] == "AI_TIMEOUT"
    assert by_id["r3"]["username"] is None  # 로그인하지 않은 요청

    # 방금 보낸 관리자 요청도 응답 뒤에 기록되어 다음 조회의 맨 위에 보임
    response = client.get("/api/admin/requests?limit=1", headers=headers)
    assert response.json()["items"][0]["path"] == "/api/admin/requests"

def test_request_logs_status_filters():
    headers, _ = login_admin()
    _, alice_id = login("alice")
    seed_request_logs(alice_id)
    query = "/api/admin/requests?exclude_admin=true&status="

    assert request_ids(client.get(query + "errors", headers=headers)) == ["r5", "r4", "r3"]
    assert request_ids(client.get(query + "4xx", headers=headers)) == ["r5", "r3"]
    assert request_ids(client.get(query + "5xx", headers=headers)) == ["r4"]
    assert request_ids(client.get(query + "2xx", headers=headers)) == ["r2", "r1"]
    assert_error(client.get(query + "teapot", headers=headers), 422, "VALIDATION_ERROR")

def test_request_logs_path_user_slow_and_error_code_filters():
    headers, _ = login_admin()
    _, alice_id = login("alice")
    seed_request_logs(alice_id)
    base = "/api/admin/requests?exclude_admin=true"

    assert request_ids(client.get(base + "&path=/api/chat", headers=headers)) == ["r4", "r2"]
    # 검색어의 %는 아무 글자가 아니라 % 글자 그대로 찾음
    assert request_ids(client.get(base + "&path=%25", headers=headers)) == []
    assert request_ids(client.get(base + "&username=alice", headers=headers)) == ["r4", "r2"]
    assert request_ids(client.get(base + "&username=nobody", headers=headers)) == []
    assert request_ids(client.get(base + "&min_duration_ms=1000", headers=headers)) == ["r4", "r2"]
    assert request_ids(client.get(base + "&status=errors&path=/api/chat", headers=headers)) == ["r4"]
    # 관리자 화면의 "많이 난 오류 코드"를 누르면 그 코드가 난 요청만 보여줌
    assert request_ids(client.get(base + "&error_code=AUTH_REQUIRED", headers=headers)) == ["r3"]
    assert request_ids(client.get(base + "&error_code=NO_SUCH_CODE", headers=headers)) == []

def test_request_logs_exclude_admin_and_paging():
    headers, _ = login_admin()
    _, alice_id = login("alice")
    seed_request_logs(alice_id)

    response = client.get("/api/admin/requests?exclude_admin=true&skip=1&limit=2", headers=headers)
    assert request_ids(response) == ["r4", "r3"]
    assert response.json()["total"] == 5  # 페이지와 상관없는 전체 건수 (r6 관리자 요청 제외)

    response = client.get("/api/admin/requests?exclude_admin=true&limit=200", headers=headers)
    assert all(not item["path"].startswith("/api/admin") for item in response.json()["items"])

    assert_error(client.get("/api/admin/requests?limit=201", headers=headers), 422, "VALIDATION_ERROR")
    assert_error(client.get("/api/admin/requests?skip=-1", headers=headers), 422, "VALIDATION_ERROR")

# -------------------------------------------------------------
# 3. 요청 ID 추적 (GET /api/admin/requests/{request_id})
# -------------------------------------------------------------
def test_trace_links_request_log_and_chat_log():
    admin_headers, _ = login_admin()
    alice_headers, alice_id = login("alice")
    with patch("app.api.chat_router.call_ai_api", new=AsyncMock(return_value=AIResult("답변입니다", "SUCCESS"))):
        chat = client.post("/api/chat", json={"prompt": "안녕?"}, headers=alice_headers)
    request_id = chat.headers["X-Request-ID"]

    response = client.get(f"/api/admin/requests/{request_id}", headers=admin_headers)
    assert response.status_code == 200
    trace = response.json()
    assert trace["request_id"] == request_id
    assert (trace["request"]["method"], trace["request"]["path"], trace["request"]["status_code"]) == ("POST", "/api/chat", 200)
    assert trace["request"]["username"] == "alice"
    assert trace["chat_log"]["request_id"] == request_id
    assert (trace["chat_log"]["prompt"], trace["chat_log"]["response"]) == ("안녕?", "답변입니다")
    assert trace["chat_log"]["user_id"] == alice_id
    assert trace["chat_log"]["latency_ms"] is not None

def test_trace_shows_ai_failure_cause():
    admin_headers, _ = login_admin()
    alice_headers, _ = login("alice")
    timeout = AIResult(FALLBACK_TIMEOUT_MESSAGE, "FAILED", "TIMEOUT")
    with patch("app.api.chat_router.call_ai_api", new=AsyncMock(return_value=timeout)):
        chat = client.post("/api/chat", json={"prompt": "느린 질문"}, headers=alice_headers)
    assert chat.status_code == 504

    trace = client.get(f"/api/admin/requests/{chat.headers['X-Request-ID']}", headers=admin_headers).json()
    assert (trace["request"]["status_code"], trace["request"]["error_code"]) == (504, "AI_TIMEOUT")
    assert (trace["chat_log"]["status"], trace["chat_log"]["error_type"]) == ("FAILED", "TIMEOUT")

def test_trace_with_only_chat_log():
    headers, admin_id = login_admin()
    # 요청 로그 저장에 실패한 경우처럼 대화 로그에만 요청 ID가 있어도 추적됨
    add_chat_log(admin_id, request_id="deadbeef", prompt="기록된 질문")

    trace = client.get("/api/admin/requests/deadbeef", headers=headers).json()
    assert trace["request"] is None
    assert trace["chat_log"]["prompt"] == "기록된 질문"
    assert trace["chat_log"]["username"] == "admin1"

def test_trace_not_found_and_invalid_id():
    headers, _ = login_admin()
    body = assert_error(client.get("/api/admin/requests/abcd1234", headers=headers), 404, "REQUEST_NOT_FOUND")
    assert body["detail"] == "해당 요청 ID의 기록이 없습니다."

    body = assert_error(client.get("/api/admin/requests/abc$", headers=headers), 422, "VALIDATION_ERROR")
    assert body["detail"] == "요청 ID 형식이 올바르지 않습니다."
    assert_error(client.get("/api/admin/requests/" + "a" * 17, headers=headers), 422, "VALIDATION_ERROR")

# -------------------------------------------------------------
# 4. 대화 로그 목록 (GET /api/admin/chat-logs)
# -------------------------------------------------------------
def test_chat_logs_list_with_trace_fields_and_filters():
    headers, _ = login_admin()
    _, alice_id = login("alice")
    _, bob_id = login("bob")
    add_chat_log(alice_id, minutes_ago=3, prompt="alice 성공", request_id="c1", latency_ms=800)
    add_chat_log(bob_id, minutes_ago=2, prompt="bob 실패", status="FAILED", response="안내 문구", request_id="c2", latency_ms=10002, error_type="TIMEOUT")
    add_chat_log(alice_id, minutes_ago=1, prompt="alice 실패", status="FAILED", response="안내 문구", request_id="c3", latency_ms=40, error_type="UPSTREAM_ERROR")

    response = client.get("/api/admin/chat-logs", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert [item["prompt"] for item in body["items"]] == ["alice 실패", "bob 실패", "alice 성공"]
    assert body["items"][1] == {
        **body["items"][1],
        "username": "bob",
        "status": "FAILED",
        "request_id": "c2",
        "latency_ms": 10002,
        "error_type": "TIMEOUT",
    }

    failed = client.get("/api/admin/chat-logs?status=FAILED", headers=headers).json()
    assert (failed["total"], [item["prompt"] for item in failed["items"]]) == (2, ["alice 실패", "bob 실패"])
    alice = client.get("/api/admin/chat-logs?username=alice&limit=1", headers=headers).json()
    assert (alice["total"], [item["prompt"] for item in alice["items"]]) == (2, ["alice 실패"])
    assert client.get("/api/admin/chat-logs?username=nobody", headers=headers).json()["total"] == 0
    assert_error(client.get("/api/admin/chat-logs?status=failed", headers=headers), 422, "VALIDATION_ERROR")

# -------------------------------------------------------------
# 5. 서비스 상태 요약 (GET /api/admin/summary)
# -------------------------------------------------------------
def test_summary_counts():
    headers, admin_id = login_admin()
    _, alice_id = login("alice")
    two_days = 60 * 48
    run_in_db(lambda db: db.add(User(username="olduser", hashed_password="x", created_at=utc_now() - timedelta(days=2))))

    add_chat_log(alice_id, minutes_ago=3, latency_ms=100)
    add_chat_log(alice_id, minutes_ago=2, latency_ms=300)
    add_chat_log(alice_id, minutes_ago=1, status="FAILED", latency_ms=10001, error_type="TIMEOUT")
    add_chat_log(alice_id, minutes_ago=two_days, status="FAILED", latency_ms=50, error_type="UPSTREAM_ERROR")
    add_chat_log(alice_id, minutes_ago=two_days + 1, status="FAILED")  # 실패 종류를 기록하기 전의 옛 기록

    clear_request_logs()
    # 최근 24시간: 응답 시간 10, 20, ..., 200ms인 요청 20개 (200 15개, 401 3개, 404 1개, 504 1개)
    statuses = [200] * 15 + [401, 401, 401, 404, 504]
    codes = {401: "AUTH_REQUIRED", 404: "NOT_FOUND", 504: "AI_TIMEOUT"}
    for i, status_code in enumerate(statuses):
        add_request_log(minutes_ago=30 - i, request_id=f"s{i}", status_code=status_code, duration_ms=(i + 1) * 10, error_code=codes.get(status_code))
    add_request_log(minutes_ago=two_days, request_id="old500", status_code=500, duration_ms=99999, error_code="INTERNAL_ERROR")

    response = client.get("/api/admin/summary", headers=headers)
    assert response.status_code == 200
    summary = response.json()

    assert summary["users"] == {"total": 3, "admins": 1, "new_24h": 2}
    chats = summary["chats"]
    assert (chats["total"], chats["success"], chats["failed"], chats["failure_rate"]) == (5, 2, 3, 60.0)
    assert (chats["last_24h"], chats["failed_24h"], chats["avg_latency_ms_24h"]) == (3, 1, 200)
    assert {item["code"]: item["count"] for item in chats["failures_by_type"]} == {"TIMEOUT": 1, "UPSTREAM_ERROR": 1, "UNKNOWN": 1}

    requests = summary["requests"]
    assert requests["window_hours"] == 24
    assert (requests["total"], requests["status_2xx"], requests["status_4xx"], requests["status_5xx"]) == (20, 15, 4, 1)
    assert requests["server_error_rate"] == 5.0
    assert requests["avg_duration_ms"] == 105
    assert requests["p95_duration_ms"] == 190  # 20개 중 짧은 순 19번째
    assert requests["top_error_codes"] == [
        {"code": "AUTH_REQUIRED", "count": 3},
        {"code": "AI_TIMEOUT", "count": 1},
        {"code": "NOT_FOUND", "count": 1},
    ]

    # 최근 오류는 기간과 상관없이 최신순 (24시간보다 오래된 500도 포함)
    recent = summary["recent_errors"]
    assert [item["request_id"] for item in recent] == ["s19", "s18", "s17", "s16", "s15", "old500"]

def test_summary_on_empty_service():
    headers, _ = login_admin()
    clear_request_logs()
    summary = client.get("/api/admin/summary", headers=headers).json()
    assert summary["users"] == {"total": 1, "admins": 1, "new_24h": 1}
    assert summary["chats"]["total"] == 0 and summary["chats"]["failure_rate"] == 0.0
    assert summary["chats"]["avg_latency_ms_24h"] is None
    assert summary["requests"]["total"] == 0
    assert summary["requests"]["p95_duration_ms"] is None and summary["requests"]["avg_duration_ms"] is None
    assert summary["recent_errors"] == []

# -------------------------------------------------------------
# 6. 관리자 지정 스크립트 (scripts/create_admin.py)
# -------------------------------------------------------------
SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "create_admin.py"

@pytest.fixture
def script():
    spec = importlib.util.spec_from_file_location("create_admin", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

@pytest.fixture
def db_file(tmp_path):
    """서버가 만든 것과 같은 구조의 DB 파일에 일반 사용자 alice를 넣어 둠"""
    path = tmp_path / "chat_service.db"
    file_engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=file_engine)
    with sessionmaker(bind=file_engine)() as db:
        db.add(User(username="alice", hashed_password="x"))
        db.commit()
    file_engine.dispose()
    return path

def read_users(path):
    file_engine = create_engine(f"sqlite:///{path}")
    try:
        with sessionmaker(bind=file_engine)() as db:
            return {user.username: user for user in db.query(User).all()}
    finally:
        file_engine.dispose()

def test_script_grants_and_revokes_admin(script, db_file, capsys):
    assert script.main(["alice", "--db", str(db_file)]) == 0
    assert read_users(db_file)["alice"].role == ADMIN_ROLE

    assert script.main(["--list", "--db", str(db_file)]) == 0
    assert "alice" in capsys.readouterr().out

    assert script.main(["alice", "--revoke", "--db", str(db_file)]) == 0
    assert read_users(db_file)["alice"].role == USER_ROLE
    assert script.main(["nobody", "--revoke", "--db", str(db_file)]) == 1

def test_script_creates_new_admin_account(script, db_file, monkeypatch):
    monkeypatch.setattr(script.getpass, "getpass", lambda prompt="": "secret12")
    assert script.main(["root1", "--db", str(db_file)]) == 0
    user = read_users(db_file)["root1"]
    assert user.role == ADMIN_ROLE
    assert verify_password("secret12", user.hashed_password)  # 회원가입과 같은 bcrypt 해시

def test_script_rejects_bad_input(script, db_file, monkeypatch, tmp_path, capsys):
    answers = iter(["secret12", "different"])
    monkeypatch.setattr(script.getpass, "getpass", lambda prompt="": next(answers))
    assert script.main(["root1", "--db", str(db_file)]) == 1  # 비밀번호 확인 불일치
    assert "root1" not in read_users(db_file)

    def fail_if_asked(prompt=""):
        raise AssertionError("아이디가 규칙에 맞지 않으면 비밀번호를 묻지 않아야 함")
    monkeypatch.setattr(script.getpass, "getpass", fail_if_asked)
    assert script.main(["ab", "--db", str(db_file)]) == 1  # 회원가입과 같은 아이디 규칙
    assert "아이디는 3자 이상이어야 합니다." in capsys.readouterr().out

    missing = tmp_path / "missing.db"
    assert script.main(["alice", "--db", str(missing)]) == 1
    assert not missing.exists()  # 잘못된 경로에 빈 DB를 만들지 않음

def test_script_upgrades_old_db_before_granting(script, tmp_path):
    path = tmp_path / "old.db"
    old_engine = create_engine(f"sqlite:///{path}")
    with old_engine.begin() as conn:
        # role 컬럼이 없던 이전 버전의 users 테이블
        conn.execute(text(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(50) NOT NULL UNIQUE, "
            "hashed_password VARCHAR(255) NOT NULL, created_at DATETIME NOT NULL)"
        ))
        conn.execute(text("INSERT INTO users (username, hashed_password, created_at) VALUES ('alice', 'x', '2026-10-22 07:51:05')"))
    old_engine.dispose()

    assert script.main(["alice", "--db", str(path)]) == 0
    assert read_users(path)["alice"].role == ADMIN_ROLE
