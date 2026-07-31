-- Migration 0051: Recreate trading.trade_decisions to reset attnum
--
-- 문제
-- ----
-- trading.trade_decisions는 살아있는 컬럼이 42개뿐이지만 attnum(컬럼 슬롯)
-- 최댓값이 하드 리밋인 1600에 도달했다(dropped=1558). 원인은 이력 테이블
-- 없이 매 컨테이너 부팅마다 db/migrations/*.sql 전체를 재실행하던 예전
-- 마이그레이션 러너 구조에서, 0021/0022(ADD COLUMN 4개)와 0026(같은 4개
-- DROP COLUMN)이 매 부팅마다 짝으로 재생되며 attnum을 영구 소모했기 때문
-- 이다(0050_*.sql까지의 이력, run.py 참고). 재발 방지는 db/migrations/run.py
-- 에 도입한 schema_migrations 이력(ledger) 테이블이 담당하고, 이 마이그
-- 레이션은 이미 소모된 attnum 자체를 리셋한다 — 그래야 앞으로 이 테이블에
-- 새 컬럼을 추가할 수 있다.
--
-- 방법
-- ----
-- 1. 기존 테이블을 임시 이름으로 rename(메타데이터 변경만, 즉시 완료).
-- 2. LIKE ... INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES로
--    같은 이름의 새 테이블을 만든다 — attnum이 1부터 다시 시작한다.
--    (LIKE는 외래키를 복사하지 않으므로 이 테이블이 참조하는 FK 3개는
--    별도로 추가한다.)
-- 3. 데이터를 그대로 복사한다(72,809 rows, 2026-07-31 KST 기준).
-- 4. 이 테이블을 참조하는 자식 테이블(execution_attempts,
--    guardrail_evaluations, order_requests)의 FK를 새 테이블로 재연결한다.
-- 5. 임시 테이블을 제거한다.
--
-- 트리거/뷰 의존성 없음(사전 확인 완료). 전체가 단일 트랜잭션이라 중간에
-- 실패하면 전부 롤백되어 원래 상태로 남는다.

BEGIN;

ALTER TABLE trading.trade_decisions
    RENAME TO trade_decisions_pre_0051_attnum_reset;

CREATE TABLE trading.trade_decisions (
    LIKE trading.trade_decisions_pre_0051_attnum_reset
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
    SELECT * FROM trading.trade_decisions_pre_0051_attnum_reset;

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

DROP TABLE trading.trade_decisions_pre_0051_attnum_reset;

COMMIT;
