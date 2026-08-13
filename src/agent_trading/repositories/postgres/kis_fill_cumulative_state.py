from __future__ import annotations

from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import KisFillCumulativeStateEntity


class PostgresKisFillCumulativeStateRepository:
    """``trading.kis_fill_cumulative_state`` postgres 구현.

    ``get()``은 항상 ``SELECT ... FOR UPDATE``를 사용한다 — 이 저장소의
    유일한 실사용 패턴이 "조회 → delta 계산 → upsert"(read-modify-write)
    이므로, 조회 시점에 행 잠금을 걸어 같은 주문번호를 동시에 폴링하는
    다른 트랜잭션(예: post_submit_sync와 fill_sync가 겹치는 경우)이
    커밋 전까지 기다리게 한다 — 설계 문서 14번 3.2절 "1차 방어선".
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def get(
        self,
        *,
        account_id: UUID,
        broker_name: str,
        broker_native_order_id: str,
    ) -> KisFillCumulativeStateEntity | None:
        row = await self._tx.connection.fetchrow(
            """SELECT * FROM trading.kis_fill_cumulative_state
               WHERE account_id = $1 AND broker_name = $2
                 AND broker_native_order_id = $3
               FOR UPDATE""",
            account_id,
            broker_name,
            broker_native_order_id,
        )
        if row is None:
            return None
        return row_to_entity(row, KisFillCumulativeStateEntity)

    async def upsert(
        self, state: KisFillCumulativeStateEntity
    ) -> KisFillCumulativeStateEntity:
        row = await self._tx.connection.fetchrow(
            """INSERT INTO trading.kis_fill_cumulative_state
               (kis_fill_cumulative_state_id, account_id, broker_name,
                broker_native_order_id, last_cumulative_filled_quantity,
                last_average_fill_price, last_observed_at,
                last_raw_field_fingerprint)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
               ON CONFLICT (account_id, broker_name, broker_native_order_id)
               DO UPDATE SET
                   last_cumulative_filled_quantity = EXCLUDED.last_cumulative_filled_quantity,
                   last_average_fill_price = EXCLUDED.last_average_fill_price,
                   last_observed_at = EXCLUDED.last_observed_at,
                   last_raw_field_fingerprint = EXCLUDED.last_raw_field_fingerprint,
                   updated_at = NOW()
               RETURNING *""",
            state.kis_fill_cumulative_state_id,
            state.account_id,
            state.broker_name,
            state.broker_native_order_id,
            state.last_cumulative_filled_quantity,
            state.last_average_fill_price,
            state.last_observed_at,
            state.last_raw_field_fingerprint,
        )
        return row_to_entity(row, KisFillCumulativeStateEntity)
