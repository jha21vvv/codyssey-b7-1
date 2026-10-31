from typing import Dict, List, Tuple
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from app.core.logger import logger

"""
[권태현] 간단한 스키마 업그레이드(마이그레이션)
Base.metadata.create_all은 없는 테이블만 만들고, 이미 있는 테이블에 새 컬럼을 추가하지 않습니다.
그래서 이전 버전으로 만든 DB(chat_service.db)에 새 컬럼이 없으면 서버 시작 때 ALTER TABLE로 추가합니다.
- 새 컬럼은 기존 행에 영향이 없도록 NULL을 허용하거나 기본값을 둡니다.
- 여러 번 실행해도 이미 있는 컬럼은 건너뜁니다.
"""

# 테이블별로 나중에 추가된 컬럼: (컬럼 이름, SQL 타입과 기본값)
ADDED_COLUMNS: Dict[str, List[Tuple[str, str]]] = {
    "chat_logs": [
        ("request_id", "VARCHAR(16)"),
        ("latency_ms", "INTEGER"),
        ("error_type", "VARCHAR(30)"),
    ],
}

# 새 컬럼에 필요한 인덱스 (모델의 index=True가 만드는 이름과 같게)
ADDED_INDEXES: List[Tuple[str, str, str]] = [
    ("ix_chat_logs_request_id", "chat_logs", "request_id"),
]


def upgrade_schema(engine: Engine) -> List[str]:
    """빠진 컬럼과 인덱스를 추가하고, 추가한 컬럼 목록을 돌려줌"""
    inspector = inspect(engine)
    added = []
    with engine.begin() as conn:
        for table, columns in ADDED_COLUMNS.items():
            if not inspector.has_table(table):
                continue  # 테이블이 없으면 create_all이 새 구조로 만듦
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, ddl in columns:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    added.append(f"{table}.{name}")
        for index_name, table, column in ADDED_INDEXES:
            if inspector.has_table(table):
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({column})"))
    for item in added:
        logger.info(f"[DB 마이그레이션] 컬럼 추가: {item}")
    return added
