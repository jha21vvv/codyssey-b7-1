from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool
from app.core.database import Base
from app.core.migrations import upgrade_schema
from app.models import chat_log, request_log, user  # noqa: F401  (Base에 모든 테이블 등록)

"""
[권태현 전담] 이전 버전 DB에 새 컬럼을 추가하는 스키마 업그레이드(마이그레이션) 검증 테스트
"""

def memory_engine():
    return create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

def test_upgrade_adds_missing_chat_log_columns():
    engine = memory_engine()
    with engine.begin() as conn:
        # PR #9 머지 시점의 chat_logs 구조 (추적 컬럼 없음)
        conn.execute(text("""
            CREATE TABLE chat_logs (
                id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, prompt TEXT NOT NULL,
                response TEXT NOT NULL, status VARCHAR(20) NOT NULL, created_at DATETIME NOT NULL
            )
        """))
        conn.execute(text(
            "INSERT INTO chat_logs (user_id, prompt, response, status, created_at) "
            "VALUES (1, '예전 질문', '예전 답변', 'SUCCESS', '2026-10-22 07:51:05')"
        ))

    added = upgrade_schema(engine)

    assert added == ["chat_logs.request_id", "chat_logs.latency_ms", "chat_logs.error_type"]
    inspector = inspect(engine)
    assert {"request_id", "latency_ms", "error_type"} <= {c["name"] for c in inspector.get_columns("chat_logs")}
    assert "ix_chat_logs_request_id" in {i["name"] for i in inspector.get_indexes("chat_logs")}
    with engine.connect() as conn:
        row = conn.execute(text("SELECT prompt, request_id FROM chat_logs")).one()
    assert tuple(row) == ("예전 질문", None)  # 기존 기록은 그대로

def test_upgrade_does_nothing_on_current_schema():
    engine = memory_engine()
    Base.metadata.create_all(bind=engine)
    assert upgrade_schema(engine) == []
    assert upgrade_schema(engine) == []  # 여러 번 실행해도 안전

def test_upgrade_skips_missing_tables():
    # 빈 DB에서는 아무것도 하지 않고, 테이블은 create_all이 새 구조로 만듦
    assert upgrade_schema(memory_engine()) == []

def test_upgrade_adds_user_role_with_default():
    engine = memory_engine()
    with engine.begin() as conn:
        # 역할(role) 컬럼이 없던 이전 버전의 users 구조
        conn.execute(text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY, username VARCHAR(50) NOT NULL UNIQUE,
                hashed_password VARCHAR(255) NOT NULL, created_at DATETIME NOT NULL
            )
        """))
        conn.execute(text(
            "INSERT INTO users (username, hashed_password, created_at) VALUES ('alice', 'x', '2026-10-22 07:51:05')"
        ))

    assert upgrade_schema(engine) == ["users.role"]
    with engine.begin() as conn:
        # 기존 사용자는 일반 사용자가 되고, 이후 역할 없이 넣는 사용자도 기본값 user
        conn.execute(text("INSERT INTO users (username, hashed_password, created_at) VALUES ('bob', 'x', '2026-10-31 00:00:00')"))
        rows = conn.execute(text("SELECT username, role FROM users ORDER BY id")).all()
    assert [tuple(row) for row in rows] == [("alice", "user"), ("bob", "user")]
