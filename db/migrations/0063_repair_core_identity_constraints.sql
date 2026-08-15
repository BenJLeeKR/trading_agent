-- 0063: 운영 DB core identity 4개 테이블의 PK/UNIQUE drift 복구.
-- 설계 근거: docs/00_foundational_design/detailed_design/16_broker_fill_
-- snapshot_historical_backfill_design.md §8.14 (`config_versions` PK drift
-- 조사 및 복구 설계).
--
-- 배경 — 왜 이 migration이 필요한가:
-- `007070` historical BUY fee overlay 파일럿에서 `0062_add_historical_buy_
-- fee_overlays.sql`을 운영 DB에 적용하던 중
--   InvalidForeignKeyError: there is no unique constraint matching given
--   keys for referenced table "config_versions"
-- 오류가 발생했다. read-only catalog 조사(pg_constraint/pg_index/
-- information_schema) 결과, 운영 DB의 `trading.clients`, `trading.
-- strategies`, `trading.broker_accounts`, `trading.config_versions` 4개
-- 테이블 전부가 `db/migrations/0001_initial_schema.sql`이 선언한
-- PRIMARY KEY/UNIQUE 제약을 실제로는 갖고 있지 않다는 것이 확인됐다.
--
-- 원인: `trading.schema_migrations` 원장에서 `0001`~`0050`(51개 파일)이
-- 전부 동일한 마이크로초 타임스탬프로 기록돼 있다 — 이는 순차 실행이
-- 아니라 `src/agent_trading/db/migrations/run.py`의
-- `_bootstrap_ledger_if_needed()`가 "trading.clients가 이미 있으니 0001
-- ~0050은 이미 적용된 것"이라고 검증 없이 일괄 backfill한 시그니처다.
-- 즉 이 4개 테이블은 마이그레이션 이력 시스템 도입 이전에 이미 다른
-- 경로로 존재하던 테이블이었고, 그 실제 정의가 현재 0001의 정의와
-- 어긋난 상태로 원장에만 "적용됨"으로 남아 있었다.
--
-- 이 drift의 부작용으로, PK/UNIQUE가 없는 상태에서 idempotent 시드
-- 스크립트가 재실행되며 4개 테이블 모두에서 완전히 동일한 값의 행이
-- 정확히 2번씩 삽입돼 있었다(중복 쌍마다 business key와 PK 후보 값이
-- 모두 동일하고, 실질적으로 다른 값은 created_at/activated_at 같은
-- 시각 계열뿐이다). 이 migration은 이 중복을 "서로 다른 두 레코드의
-- 충돌"이 아니라 "같은 seed row의 재삽입"으로 취급해 정리한다.
--
-- 왜 FK 복구를 이 migration에 넣지 않는가:
-- 이 4개 테이블을 참조해야 할 FK(예: accounts.client_id,
-- decision_contexts.config_version_id 등)도 운영 DB에 함께 누락돼
-- 있으나, 그중 `order_blocking_locks.strategy_id`는 이미 NULL인 채로
-- (스키마상 NOT NULL로 선언돼 있음에도) 남아 있는 만료된 과거 행 4건이
-- 있어 FK 추가 전 별도의 데이터 정리 판단이 필요하다. PK/UNIQUE 복구와
-- FK 복구는 리스크 성격이 다르므로 감사/승인 단위를 분리한다 — FK 복구는
-- `0064_repair_core_identity_foreign_keys.sql`(별도 턴)로 넘긴다.
--
-- 왜 이 migration이 0062보다 먼저 와야 하는가:
-- `0062`는 `historical_buy_fee_overlays.basis_config_version_id`가
-- `trading.config_versions (config_version_id)`를 참조하는 FK를
-- 선언한다. PostgreSQL은 FK가 참조하는 컬럼에 PK 또는 UNIQUE 제약이
-- 있어야만 FK 생성을 허용하므로, `config_versions.config_version_id`에
-- PK를 복구하는 이 migration이 먼저 적용되지 않으면 `0062`는 항상
-- 실패한다.
--
-- 이 migration의 범위: PRIMARY KEY / UNIQUE 복구 및 그 전제조건인 중복
-- 제거뿐이다. FK는 다루지 않는다. 정상 스키마(이미 PK/UNIQUE가 있는
-- 환경 — 예: 테스트에서 0001부터 순서대로 실행되는 경우)에서는 각
-- 블록이 멱등적으로 아무 일도 하지 않도록 catalog 존재 여부를 먼저
-- 확인한다.

BEGIN;

-- ============================================================================
-- 1. trading.clients
--    기대: PK client_id, UNIQUE client_code (0001_initial_schema.sql:6-16)
-- ============================================================================

-- 1-1. 중복 제거 — 완전 동일한 client_id가 2번 삽입된 행 중, 더 늦게
--      삽입된 사본을 제거한다. keep 기준은 created_at 오름차순(가장 이른
--      행을 보존), 동률이면 ctid(이 migration 내부의 결정론적 tie-break
--      구현 세부사항일 뿐 — 애플리케이션 식별자로 취급하지 않는다)로
--      최종 결정한다.
WITH ranked AS (
    SELECT
        ctid,
        row_number() OVER (
            PARTITION BY client_id
            ORDER BY created_at ASC, ctid ASC
        ) AS rn
    FROM trading.clients
)
DELETE FROM trading.clients
WHERE ctid IN (SELECT ctid FROM ranked WHERE rn > 1);

-- 1-2. PK 복구 (이미 있으면 건너뜀 — 정상 스키마에서는 no-op)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'trading.clients'::regclass AND contype = 'p'
    ) THEN
        ALTER TABLE trading.clients
            ADD CONSTRAINT clients_pkey PRIMARY KEY (client_id);
    END IF;
END $$;

-- 1-3. UNIQUE 복구 (이미 있으면 건너뜀).
--      정상 스키마(0001을 그대로 실행한 환경)에서는 client_code에 대한
--      UNIQUE 제약이 inline `UNIQUE` 키워드로 선언되어 Postgres가
--      `clients_client_code_key`라는 기본 이름을 붙인다 — 여기서도 같은
--      이름을 사용해 정상 스키마와의 정합성을 유지한다.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'trading.clients'::regclass
          AND contype = 'u'
    ) THEN
        ALTER TABLE trading.clients
            ADD CONSTRAINT clients_client_code_key UNIQUE (client_code);
    END IF;
END $$;

-- ============================================================================
-- 2. trading.strategies
--    기대: PK strategy_id, UNIQUE (client_id, strategy_code)
--    (0001_initial_schema.sql:53-66)
-- ============================================================================

WITH ranked AS (
    SELECT
        ctid,
        row_number() OVER (
            PARTITION BY strategy_id
            ORDER BY created_at ASC, ctid ASC
        ) AS rn
    FROM trading.strategies
)
DELETE FROM trading.strategies
WHERE ctid IN (SELECT ctid FROM ranked WHERE rn > 1);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'trading.strategies'::regclass AND contype = 'p'
    ) THEN
        ALTER TABLE trading.strategies
            ADD CONSTRAINT strategies_pkey PRIMARY KEY (strategy_id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'trading.strategies'::regclass AND conname = 'uq_strategies_code'
    ) THEN
        ALTER TABLE trading.strategies
            ADD CONSTRAINT uq_strategies_code UNIQUE (client_id, strategy_code);
    END IF;
END $$;

-- ============================================================================
-- 3. trading.broker_accounts
--    기대: PK broker_account_id, UNIQUE (broker_name, account_ref, environment)
--    (0001_initial_schema.sql:18-33)
-- ============================================================================

WITH ranked AS (
    SELECT
        ctid,
        row_number() OVER (
            PARTITION BY broker_account_id
            ORDER BY created_at ASC, ctid ASC
        ) AS rn
    FROM trading.broker_accounts
)
DELETE FROM trading.broker_accounts
WHERE ctid IN (SELECT ctid FROM ranked WHERE rn > 1);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'trading.broker_accounts'::regclass AND contype = 'p'
    ) THEN
        ALTER TABLE trading.broker_accounts
            ADD CONSTRAINT broker_accounts_pkey PRIMARY KEY (broker_account_id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'trading.broker_accounts'::regclass
          AND conname = 'uq_broker_accounts_ref'
    ) THEN
        ALTER TABLE trading.broker_accounts
            ADD CONSTRAINT uq_broker_accounts_ref
                UNIQUE (broker_name, account_ref, environment);
    END IF;
END $$;

-- ============================================================================
-- 4. trading.config_versions
--    기대: PK config_version_id, UNIQUE (client_id, environment, version_tag)
--    (0001_initial_schema.sql:81-94)
--
--    이 테이블만 activated_at이 있어 tie-break에 추가로 사용한다 — keep
--    기준은 created_at 오름차순, 동률이면 activated_at 오름차순
--    (NULLS LAST), 최종 동률이면 ctid.
-- ============================================================================

WITH ranked AS (
    SELECT
        ctid,
        row_number() OVER (
            PARTITION BY config_version_id
            ORDER BY created_at ASC, activated_at ASC NULLS LAST, ctid ASC
        ) AS rn
    FROM trading.config_versions
)
DELETE FROM trading.config_versions
WHERE ctid IN (SELECT ctid FROM ranked WHERE rn > 1);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'trading.config_versions'::regclass AND contype = 'p'
    ) THEN
        ALTER TABLE trading.config_versions
            ADD CONSTRAINT config_versions_pkey PRIMARY KEY (config_version_id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'trading.config_versions'::regclass
          AND conname = 'uq_config_versions'
    ) THEN
        ALTER TABLE trading.config_versions
            ADD CONSTRAINT uq_config_versions
                UNIQUE (client_id, environment, version_tag);
    END IF;
END $$;

COMMIT;
