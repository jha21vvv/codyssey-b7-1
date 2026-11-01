from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime
from app.core.database import Base

# [권태현] 사용자 역할 값 (관리자는 scripts/create_admin.py로 지정)
USER_ROLE = "user"
ADMIN_ROLE = "admin"

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # [권태현] 사용자 역할: 일반 사용자(user) 또는 관리자(admin)
    # 이전 버전 DB에는 app/core/migrations.py가 컬럼을 추가하고, 기존 사용자는 모두 일반 사용자가 됨
    role = Column(String(20), nullable=False, default=USER_ROLE, server_default=USER_ROLE)
