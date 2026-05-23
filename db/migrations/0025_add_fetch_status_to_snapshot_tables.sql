-- Migration 0025: Add missing fetch_status columns to snapshot tables
-- 코드 INSERT와 DB 스키마 정합성 복구
--
-- 문제 상황:
--   INSERT 구문에는 fetch_status 컬럼이 포함되어 있지만,
--   DB에는 해당 컬럼이 존재하지 않아 INSERT 실패 발생.
-- 해결:
--   cash_balance_snapshots, position_snapshots 테이블에
--   fetch_status 컬럼을 추가하여 정합성 복구.

ALTER TABLE trading.cash_balance_snapshots
    ADD COLUMN fetch_status VARCHAR(16) NOT NULL DEFAULT 'success';

ALTER TABLE trading.position_snapshots
    ADD COLUMN fetch_status VARCHAR(16) NOT NULL DEFAULT 'success';
