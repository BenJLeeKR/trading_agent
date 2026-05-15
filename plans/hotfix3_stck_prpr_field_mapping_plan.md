# Critical Hotfix #3: `stck_prpr` → `Quote.last` Field Mapping Fix

## Root Cause

`KoreaInvestmentAdapter.get_quote()` at [`adapter.py:132-141`](../src/agent_trading/brokers/koreainvestment/adapter.py:132) reads KIS API response using **wrong dictionary keys**:

```python
# CURRENT (BROKEN) — lines 132-141
async def get_quote(self, symbol: str, market: str) -> Quote:
    raw = await self._rest.get_quote(symbol)
    return Quote(
        symbol=symbol,
        market=market,
        bid=raw.get("bid"),       # ← KIS key is "stck_bidp"
        ask=raw.get("ask"),       # ← KIS key is "stck_askp"
        last=raw.get("last"),     # ← KIS key is "stck_prpr"
        as_of=datetime.now(tz=timezone.utc),
    )
```

`KISRestClient.get_quote()` at [`rest_client.py:1091-1112`](../src/agent_trading/brokers/koreainvestment/rest_client.py:1091) returns the raw `output` dict from KIS `inquire-price` endpoint. The dict contains KIS-standard keys like `stck_prpr`, `stck_bidp`, `stck_askp` — **not** `last`, `bid`, `ask`.

Additionally, KIS returns **string numbers with thousand separators** (e.g., `"67,200"`), but the current code passes raw strings directly. The `Quote` model expects `Decimal | None` for numeric fields ([`domain/models.py:58-66`](../src/agent_trading/domain/models.py:58)).

## Reference Implementation

[`_parse_quote_to_snapshot()`](../src/agent_trading/services/universe_selection.py:142) in `universe_selection.py` already correctly handles this:

```python
def _decimal(key: str) -> Decimal | None:
    val = raw.get(key)
    if val is None:
        return None
    try:
        return Decimal(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None

current_price=_decimal("stck_prpr"),  # ← CORRECT pattern
```

This fix applies the **same pattern** to `adapter.py:get_quote()`.

## Related Bug: `get_orderbook()`

[`adapter.py:get_orderbook()`](../src/agent_trading/brokers/koreainvestment/adapter.py:143) has the **same pattern error** — it reads `raw.get("bids")` and `raw.get("asks")` which don't exist in the KIS orderbook response. KIS `inquire-asking-price-exp-ccn` endpoint returns keys like `askp1..10`, `bidp1..10`, `askp_rsqn1..10`, `bidp_rsqn1..10`.

This fix also corrects the `get_orderbook()` mapping.

---

## Detailed Fix Plan

### 1. Fix `adapter.py:get_quote()` (lines 132-141)

**Changes:**
1. Add inline `_decimal()` helper function (same pattern as `universe_selection.py:151-158`)
2. Change `last=raw.get("last")` → `last=_decimal("stck_prpr")`
3. Change `bid=raw.get("bid")` → `bid=_decimal("stck_bidp")`
4. Change `ask=raw.get("ask")` → `ask=_decimal("stck_askp")`

**Expected result:**
```python
async def get_quote(self, symbol: str, market: str) -> Quote:
    raw = await self._rest.get_quote(symbol)

    def _decimal(key: str) -> Decimal | None:
        val = raw.get(key)
        if val is None:
            return None
        try:
            return Decimal(str(val).replace(",", "").strip())
        except (ValueError, TypeError):
            return None

    return Quote(
        symbol=symbol,
        market=market,
        bid=_decimal("stck_bidp"),
        ask=_decimal("stck_askp"),
        last=_decimal("stck_prpr"),
        as_of=datetime.now(tz=timezone.utc),
    )
```

### 2. Fix `adapter.py:get_orderbook()` (lines 143-151)

**Changes:**
1. KIS `inquire-asking-price-exp-ccn` returns `askp1..10`, `bidp1..10` (prices) + `askp_rsqn1..10`, `bidp_rsqn1..10` (quantities)
2. Add `_orderbook_levels()` helper to parse 10 levels
3. Map `bidpN` + `bidp_rsqnN` → `OrderBookLevel(price=Decimal, quantity=Decimal)`
4. Same for `askpN` + `askp_rsqnN`

### 3. Update Existing Tests (`test_kis_adapter_validation.py:298-338`)

**`test_get_quote_calls_rest_with_symbol_only`** (line 303):
- Change mock return value from `{"last": "15000", "bid": "14900", "ask": "15100"}` to `{"stck_prpr": "15000", "stck_bidp": "14900", "stck_askp": "15100"}`
- Assert Decimal values: `quote.last == Decimal("15000")` instead of string comparison
- Add assertions for `quote.bid == Decimal("14900")` and `quote.ask == Decimal("15100")`

**`test_get_quote_empty_response`** (line 324):
- No change needed — already tests empty dict → all None

### 4. Add New Tests

| Test Name | Purpose |
|-----------|---------|
| `test_get_quote_stck_prpr_with_comma` | KIS returns `"67,200"` → should parse as `Decimal("67200")` |
| `test_get_quote_missing_stck_prpr` | Missing `stck_prpr` key → `last` is None |
| `test_get_quote_stck_prpr_is_none` | `stck_prpr` is `None` → `last` is None |
| `test_get_quote_stck_prpr_invalid` | `stck_prpr` is non-numeric → `last` is None |

### 5. Verification Steps

| Step | Command | Expected Result |
|------|---------|-----------------|
| 1. pytest | `python3 -m pytest tests/brokers/test_kis_adapter_validation.py -v 2>&1 \| tail -40` | All tests PASSED |
| 2. Full test suite | `python3 -m pytest -x --timeout=30 2>&1 \| tail -20` | No regression |
| 3. Docker build | `docker compose build` | Build succeeds |
| 4. Docker restart | `docker compose up -d` | Container healthy |
| 5. Health check | `curl -s http://localhost:8000/health \| python3 -m json.tool` | `"status": "ok"` |
| 6. 장중 관측 | `docker compose logs api --tail=50 \| grep -i "live_quote\|stck_prpr\|source=live"` | `source=live_quote` in logs |

---

## Mermaid: Data Flow After Fix

```mermaid
flowchart LR
    A[KIS inquire-price API] -->|raw dict: stck_prpr, stck_bidp, stck_askp| B[KISRestClient.get_quote]
    B -->|raw dict returned| C[KoreaInvestmentAdapter.get_quote]
    C -->|_decimal\"stck_prpr\"| D[Quote.last = Decimal\"67200\"]
    C -->|_decimal\"stck_bidp\"| E[Quote.bid = Decimal\"67100\"]
    C -->|_decimal\"stck_askp\"| F[Quote.ask = Decimal\"67300\"]
    D --> G[_resolve_symbol_price]
    G -->|quote.last is not None and > 0| H[source=live_quote]
```

---

## Risk Assessment

- **Low risk**: `get_quote()` is a pure transformation with well-understood KIS key mapping. The `_decimal()` pattern is already proven in `universe_selection.py`.
- **No schema changes**: `Quote` model remains unchanged.
- **No API changes**: `get_quote()` signature unchanged.
- **장중 deploy**: Safe because we're only changing parsing logic, not trading submission paths.
