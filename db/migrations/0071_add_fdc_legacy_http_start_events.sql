-- legacy FDC(mode="full") 경로에서 실제 Gemini `client.post()` 직전
-- 시각을 관측하기 위한 append-only 이벤트 로그(2026-09-05).
--
-- 배경: actual-dispatch는 `fdc_provider_attempts.http_started_at`으로
-- `client.post()` 직전 시각을 이미 기록하지만, legacy 경로에는 이에
-- 대응하는 기록이 전혀 없다 — provider 전체(legacy+actual) 실제
-- HTTP-start 기준 60초 sliding window를 계산하려면 legacy 쪽에도
-- 동일 정의의 timestamp가 필요하다.
--
-- 기존 `fdc_quota_state`/`fdc_queue_jobs`/`fdc_provider_attempts`를
-- 재사용하지 않는 이유: 그 테이블들은 actual-dispatch coordinator의
-- reservation/attempt lifecycle(quota_scope·reservation_id 기반 window
-- 판정)에 강하게 결합돼 있다. legacy는 reservation 개념 자체가 없고
-- (permit은 파일 기반 `fdc_rate_limiter`가 별도로 관리), 이 로그는
-- 순수 관측(read-only 집계) 목적이므로 quota 소비/판정에 관여하지
-- 않는 완전히 별도 append-only 테이블로 분리한다(0070의 global gate
-- 테이블 분리 원칙과 동일).

BEGIN;

CREATE TABLE IF NOT EXISTS trading.fdc_legacy_http_start_events (
    event_id UUID PRIMARY KEY,
    provider_scope TEXT NOT NULL,
    decision_context_id TEXT,
    correlation_id TEXT,
    attempt_no INTEGER NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- provider 전체 60초 sliding window 집계(§4 산출 지표)가 이 인덱스로
-- `(provider_scope, observed_at)` 범위 스캔을 탄다.
CREATE INDEX IF NOT EXISTS idx_fdc_legacy_http_start_events_scope_time
    ON trading.fdc_legacy_http_start_events (provider_scope, observed_at);

COMMIT;
