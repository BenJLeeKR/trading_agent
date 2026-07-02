WITH duplicate_rows AS (
    SELECT universe_freeze_run_item_id
      FROM (
        SELECT universe_freeze_run_item_id,
               ROW_NUMBER() OVER (
                   PARTITION BY universe_freeze_run_id, symbol, market_code
                   ORDER BY rank ASC NULLS LAST, created_at ASC, universe_freeze_run_item_id ASC
               ) AS rn
          FROM trading.universe_freeze_run_items
      ) ranked
     WHERE ranked.rn > 1
)
DELETE FROM trading.universe_freeze_run_items items
USING duplicate_rows dups
WHERE items.universe_freeze_run_item_id = dups.universe_freeze_run_item_id;

CREATE UNIQUE INDEX IF NOT EXISTS uq_universe_freeze_run_items_run_symbol_market
    ON trading.universe_freeze_run_items (universe_freeze_run_id, symbol, market_code);
