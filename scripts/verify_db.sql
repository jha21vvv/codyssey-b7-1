-- ==============================================================================
-- [Codyssey B7-1] SQLite 대화 로그 및 사용자 검증 SQL 스크립트
-- ==============================================================================

-- 1. 전체 등록 사용자 조회
SELECT id, username, created_at 
FROM users 
ORDER BY id ASC;

-- 2. 전체 대화 로그 최신순 조회 (사용자 정보 JOIN)
SELECT 
    c.id AS log_id,
    u.username,
    c.prompt,
    c.response,
    c.status,
    c.created_at
FROM chat_logs c
JOIN users u ON c.user_id = u.id
ORDER BY c.created_at DESC, c.id DESC
LIMIT 20;

-- 3. 특정 사용자의 대화 이력 카운트 및 상태별 통계
SELECT 
    u.username,
    c.status,
    COUNT(*) as total_count
FROM chat_logs c
JOIN users u ON c.user_id = u.id
GROUP BY u.username, c.status;

-- 4. [권태현] 실패한 대화와 실패 종류·AI 응답 시간 (최근 20건)
SELECT
    c.id AS log_id,
    u.username,
    c.prompt,
    c.error_type,
    c.latency_ms,
    c.request_id,
    c.created_at
FROM chat_logs c
JOIN users u ON c.user_id = u.id
WHERE c.status = 'FAILED'
ORDER BY c.created_at DESC, c.id DESC
LIMIT 20;

-- 5. [권태현] 최근 요청 로그 20건 (request_id로 server.log와 대조)
SELECT
    r.request_id,
    r.method,
    r.path,
    r.status_code,
    r.duration_ms,
    u.username,
    r.error_code,
    r.created_at
FROM request_logs r
LEFT JOIN users u ON r.user_id = u.id
ORDER BY r.id DESC
LIMIT 20;

-- 6. [권태현] 상태 코드별 요청 수와 응답 시간 (오류율·느린 요청 확인)
SELECT
    status_code,
    COUNT(*) AS total,
    ROUND(AVG(duration_ms)) AS avg_ms,
    MAX(duration_ms) AS max_ms
FROM request_logs
GROUP BY status_code
ORDER BY status_code;
