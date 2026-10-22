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

---

### 🤖 AI 챗봇 API 명세 및 파이프라인 설계

- **AI 질문 및 답변 생성 (`POST /api/chat`)**
  - **인증 헤더**: `Authorization: Bearer <access_token>` 필수 (미인증 시 `401 Unauthorized` 즉시 차단)
  - **요청**:
    ```json
    {
      "prompt": "FastAPI의 비동기 처리 장점을 설명해줘."
    }
    ```
  - **응답 (`200 OK`)**:
    ```json
    {
      "prompt": "FastAPI의 비동기 처리 장점을 설명해줘.",
      "response": "FastAPI는 async/await 기반 비동기 I/O를 통해 높은 동시성을 처리할 수 있습니다.",
      "status": "SUCCESS",
      "context_used_count": 2
    }
    ```
  - **입력 검증 실패 (`422 Unprocessable Entity`)**: 빈 문자열, 공백만 있는 문자열(`"   "`), 또는 1,000자 초과 입력 시 외부 AI API를 호출하지 않고 사전 차단합니다.

- **대화 컨텍스트 유지 전략 (`build_chat_context`)**
  - 로그인한 사용자의 직전 대화 이력을 최대 3개까지 최신순으로 조회한 뒤 시간순(오래된 대화부터 최근 대화 순)으로 역정렬하여 시스템 프롬프트 하단에 주입합니다.
  - 이전 대화 중 `status="FAILED"`인 장애 이력은 컨텍스트에서 제외하고 정상 응답(`status="SUCCESS"`)만 포함하여 문맥 품질을 유지합니다.

- **타임아웃 방어 및 비정상 종료 방지 (`call_ai_api` & `chat_router`)**
  - `httpx.AsyncClient(timeout=settings.AI_TIMEOUT_SECONDS)`(기본 10초)를 설정하여 외부 AI API 지연 시 무한 대기를 방지합니다.
  - 타임아웃(`httpx.TimeoutException`), API 키 누락, 외부 API 5xx 에러, 또는 DB 저장 예외가 발생하더라도 백엔드 서버는 절대 `500 Internal Server Error`로 비정상 종료되지 않고 `200 OK`(`status="FAILED"`)와 사용자 친화적 Fallback 안내 문구를 반환합니다.
  - 파이프라인 전 과정에서 `[AI 호출]`, `[AI 응답 수신]`, `[AI 응답 실패]`, `[DB 저장 성공]`, `[DB 저장 실패]` 표준 로깅 태그를 기록합니다.
