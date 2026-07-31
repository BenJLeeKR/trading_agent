-- Migration 0052: Recreate trading.trade_decisions to reset attnum (retry)
--
-- 배경
-- ----
-- 0051_recreate_trade_decisions_reset_attnum.sql이 같은 배포(SPPV-2.153)에서
-- db/migrations/run.py의 이력(ledger) 도입과 함께 추가됐는데, 이력 백필
-- 로직(_bootstrap_ledger_if_needed)이 당시 디렉터리에 존재하던 파일 전체를
-- "이미 적용됨"으로 표시하면서 0051 자신까지 포함시켜버렸다. 그 결과 0051의
-- 실제 DDL(테이블 재생성으로 attnum 리셋)이 **한 번도 실행되지 않은 채**
-- 이력에 "적용됨"으로 기록됐다(운영 배포에서 실제 확인 — attnum은 여전히
-- 1600, trade_decisions 행 수·구조 전혀 변화 없음).
--
-- run.py는 이후 커밋에서 백필 컷오프(`_LEDGER_BOOTSTRAP_CUTOFF_FILENAME =
-- "0050_..."`)로 이 클래스의 문제를 재발하지 않게 고쳤지만, 0051 자신은
-- 이미 이력에 잘못 기록된 채로 남는다(그 한 줄이 잘못된 것 자체는 무해하다
-- — 0051 파일이 다시 시도되지 않을 뿐, 아무 것도 망가뜨리지 않는다).
-- 그래서 0051과 동일한 DDL을 새 번호(0052)로 다시 등록해 실제로 한 번
-- 실행되게 한다.
--
-- 내용은 0051과 동일 — 임시 이름으로 rename → LIKE ... INCLUDING DEFAULTS
-- INCLUDING CONSTRAINTS INCLUDING INDEXES로 재생성(attnum 1부터 재시작) →
-- FK 3개 재추가 → 데이터 복사 → 자식 테이블(execution_attempts/
-- guardrail_evaluations/order_requests) FK 재연결 → 임시 테이블 제거.
-- 단일 트랜잭션.

BEGIN;

ALTER TABLE trading.trade_decisions
    RENAME TO trade_decisions_pre_0052_attnum_reset;

CREATE TABLE trading.trade_decisions (
    LIKE trading.trade_decisions_pre_0052_attnum_reset
        INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES
);

ALTER TABLE trading.trade_decisions
    ADD CONSTRAINT trade_decisions_agent_run_id_fkey
        FOREIGN KEY (agent_run_id) REFERENCES trading.agent_runs(agent_run_id),
    ADD CONSTRAINT trade_decisions_decision_context_id_fkey
        FOREIGN KEY (decision_context_id)
            REFERENCES trading.decision_contexts(decision_context_id),
    ADD CONSTRAINT trade_decisions_instrument_id_fkey
        FOREIGN KEY (instrument_id) REFERENCES trading.instruments(instrument_id);

INSERT INTO trading.trade_decisions
    SELECT * FROM trading.trade_decisions_pre_0052_attnum_reset;

ALTER TABLE trading.execution_attempts
    DROP CONSTRAINT execution_attempts_trade_decision_id_fkey,
    ADD CONSTRAINT execution_attempts_trade_decision_id_fkey
        FOREIGN KEY (trade_decision_id)
            REFERENCES trading.trade_decisions(trade_decision_id);

ALTER TABLE trading.guardrail_evaluations
    DROP CONSTRAINT guardrail_evaluations_trade_decision_id_fkey,
    ADD CONSTRAINT guardrail_evaluations_trade_decision_id_fkey
        FOREIGN KEY (trade_decision_id)
            REFERENCES trading.trade_decisions(trade_decision_id);

ALTER TABLE trading.order_requests
    DROP CONSTRAINT order_requests_trade_decision_id_fkey,
    ADD CONSTRAINT order_requests_trade_decision_id_fkey
        FOREIGN KEY (trade_decision_id)
            REFERENCES trading.trade_decisions(trade_decision_id);

DROP TABLE trading.trade_decisions_pre_0052_attnum_reset;

COMMIT;
