from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import os

class Settings(BaseSettings):
    """
    [안재현 전담] 애플리케이션 전역 설정 관리 클래스
    .env 파일에서 환경변수를 로드하며, 기본값이 지정되어 있어 설정 파일 없이도 기본 동작 가능
    """
    # 기본 프로젝트 정보
    PROJECT_NAME: str = "Codyssey B7-1 AI Chatbot"
    DEBUG: bool = True
    
    # 데이터베이스 설정 (SQLite 기본 연결)
    DATABASE_URL: str = "sqlite:///./chat_service.db"
    
    # 보안 및 인증 설정 (신재은 Auth 모듈에서 사용)
    SECRET_KEY: str = "temporary-secret-key-for-development-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24시간
    
    # AI 챗봇 API 설정 (조명환 AI 모듈에서 사용)
    AI_API_KEY: str = ""
    AI_BASE_URL: str = ""  # 커스텀/프록시 엔드포인트 (코디세이 콘솔 등)
    AI_MODEL_NAME: str = "gpt-4o-mini"
    AI_TIMEOUT_SECONDS: float = 10.0  # 타임아웃 기본 10초 명시

    # 전체 대화 로그 조회 키 (권태현 로그 API의 GET /api/logs/admin에서 사용, 비어 있으면 기능 꺼짐)
    ADMIN_API_KEY: str = ""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

# 싱글톤 설정 인스턴스
settings = Settings()
