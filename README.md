# codyssey-b7-1
웹 기반 AI 챗봇 서비스 개발 프로젝트

### 🔐 인증 API 명세

- **회원가입 (`POST /api/auth/register`)**
  - **요청**: `{"username": "id", "password": "pw"}`
  - **응답 (성공)**: `201 Created` - `{"message": "회원가입이 완료되었습니다."}`
  - **응답 (실패)**: `409 Conflict` (아이디 중복), `422 Unprocessable Entity` (입력 규칙 위반)

- **로그인 (`POST /api/auth/login`)**
  - **요청**: `{"username": "id", "password": "pw"}`
  - **응답 (성공)**: `200 OK` - `access_token`, `token_type`, `user(id, username)` 반환
  - **응답 (실패)**: `401 Unauthorized` (아이디 또는 비밀번호 불일치)