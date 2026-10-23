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
