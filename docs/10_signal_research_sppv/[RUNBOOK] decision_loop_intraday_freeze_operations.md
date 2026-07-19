# `decision_loop_intraday` Freeze 운영 Runbook

## 목적

- 장중 `decision loop`가 읽는 authoritative universe anchor인
  `decision_loop_intraday` freeze의 상태 확인, 재사용, 수동 생성,
  stale 판정 기준을 운영 절차로 고정한다.
- 본 문서는 현재 구현 기준만 다룬다.
  - freeze 저장소: `trading.universe_freeze_runs`,
    `trading.universe_freeze_run_items`
  - 장중 생성 트리거: `ops-scheduler`
  - 장중 읽기 경로: `run_decision_loop.py`

## 현재 구현 기준

### 1. 자동 생성 / 재사용

- `ops-scheduler`는 장중 첫 `decision` due 직전에
  `_ensure_decision_loop_intraday_freeze()`를 호출한다.
- 같은 거래일(`business_date`) / 같은 목적값(`freeze_purpose=decision_loop_intraday`)
  에 대해
  - 기존 freeze run이 있고
  - item이 1건 이상이면
  기존 freeze를 재사용한다.
- 기존 freeze가 없거나 item이 비어 있으면
  현재 `UniverseSelectionService.compose()` 결과를 materialize 한다.

### 2. 장중 판단 경로

- `run_decision_loop.py`의 universe 읽기 우선순위는 아래와 같다.
  1. `TRADING_UNIVERSE_SYMBOLS` env override
  2. latest `decision_loop_intraday` freeze
  3. `UniverseSelectionService.compose()`
  4. hardcoded fallback
- 따라서 정상 장중에는 `decision loop`가 live compose가 아니라
  당일 intraday freeze를 우선 사용한다.

### 3. 운영 화면 / API 확인 경로

- `GET /market-sessions/operations-day/latest`
  - `summary_json.intraday_universe_freeze_done`
  - `scheduler_status`
  - `market_phase`
- `GET /instruments/trading-universe/preview?account_id=<ACCOUNT_ID>`
  - `items`: 현재 live compose 결과
  - `active_intraday_freeze`: 현재 active freeze
  - `active_intraday_freeze_comparison`: compose 대비 freeze 비교

## 정상 상태 기준

### 장중 정상

- `operations-day/latest`
  - `scheduler_status`가 `intraday`
  - `summary_json.intraday_universe_freeze_done == true`
- `trading-universe/preview`
  - `active_intraday_freeze`가 `null`이 아님
  - `active_intraday_freeze.freeze_purpose == "decision_loop_intraday"`
  - `active_intraday_freeze.business_date == 오늘 KST`
  - `active_intraday_freeze.target_count > 0`

### 장중 비교 불일치의 해석

- `active_intraday_freeze_comparison.exact_match == false`는
  곧바로 장애를 의미하지 않는다.
- freeze는 장중 첫 anchor이고,
  live compose는 “지금 다시 계산하면 나오는 후보”이므로
  이벤트, held position, manual watchlist, 계측 시점 차이 때문에
  일부 차이가 날 수 있다.
- 따라서 비교 불일치는 기본적으로 `drift 신호`이지
  `hard stale`로 바로 판정하지 않는다.

## 재시작 시 운영 절차

### 1. `ops-scheduler` 재기동 후 기대 동작

- 같은 거래일에 이미 정상 freeze가 있으면
  장중 첫 `decision` tick에서 기존 freeze를 재사용한다.
- 새 freeze sequence를 만들지 않고,
  기존 `universe_freeze_run_id`를 그대로 사용한다.

### 2. 재기동 후 확인 절차

1. `GET /market-sessions/operations-day/latest` 확인
   - `summary_json.intraday_universe_freeze_done == true`
2. `GET /instruments/trading-universe/preview?account_id=<ACCOUNT_ID>` 확인
   - `active_intraday_freeze` 존재
   - `business_date`가 오늘 KST
3. 필요 시 scheduler 로그 확인
   - `decision loop intraday freeze reused`
   - 또는 `decision loop intraday freeze reused after compose`

## 수동 조치 절차

### 1. 수동 `ensure`

- 목적:
  - 오늘 freeze가 없는 경우 생성
  - 오늘 freeze가 정상 존재하면 재사용 상태만 확정
- 특징:
  - 기존 정상 freeze가 있으면 새 sequence를 만들지 않는다.

```bash
docker compose exec -T app python3 - <<'PY'
import asyncio
from datetime import datetime, timedelta, timezone

from scripts.run_ops_scheduler import SchedulerState, _ensure_decision_loop_intraday_freeze

KST = timezone(timedelta(hours=9))
run_date = datetime.now(timezone.utc).astimezone(KST).date()
state = SchedulerState(run_date=run_date)

async def main() -> None:
    await _ensure_decision_loop_intraday_freeze(state)
    print({
        "run_date": state.run_date.isoformat(),
        "intraday_universe_freeze_done": state.intraday_universe_freeze_done,
    })

asyncio.run(main())
PY
```

### 2. 수동 `force-new`

- 목적:
  - 오늘 이미 freeze가 있더라도
    **새 sequence**로 다시 freeze를 생성하고 싶을 때 사용한다.
- 사용 조건:
  - instrument master / membership / event 적재 이상이 복구된 뒤
    새로운 anchor로 장중 판단 기준을 다시 고정해야 할 때
  - operator가 “같은 거래일 내 anchor 교체”를 의도적으로 승인했을 때
- 주의:
  - 현재 코드에는 전용 CLI가 없으므로 아래 ad-hoc 절차를 사용한다.
  - 이 절차는 새 freeze를 만들며, 이후 `decision loop`는
    가장 높은 `freeze_sequence`를 읽는다.

```bash
docker compose exec -T app python3 - <<'PY'
import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from agent_trading.config.settings import AppSettings
from agent_trading.domain.entities import UniverseFreezeRunEntity, UniverseFreezeRunItemEntity
from agent_trading.repositories.filters import AccountLookup
from agent_trading.runtime.bootstrap import _build_kis_live_quote_client, postgres_runtime
from agent_trading.services.universe_selection import UniverseSelectionService
from agent_trading.services.universe_selection_types import CompositionContext, FALLBACK_ACCOUNT_ID

KST = timezone(timedelta(hours=9))
FREEZE_PURPOSE = "decision_loop_intraday"
ACCOUNT_ALIAS = "Entrypoint Paper"

async def main() -> None:
    now_utc = datetime.now(timezone.utc)
    run_date = now_utc.astimezone(KST).date()
    settings = AppSettings()

    async with postgres_runtime(run_migrations=False) as runtime:
        repos = runtime["repositories"]
        kis_client = _build_kis_live_quote_client(settings)
        selector = UniverseSelectionService(repos=repos, kis_client=kis_client)

        account_id = FALLBACK_ACCOUNT_ID
        account = await repos.accounts.find_one(AccountLookup(account_alias=ACCOUNT_ALIAS))
        if account is not None:
            account_id = account.account_id

        selected = await selector.compose(
            CompositionContext(
                account_id=account_id,
                since=now_utc - timedelta(hours=24),
                max_cap=30,
                core_cap=int(os.getenv("TRADING_UNIVERSE_CORE_CAP", "12")),
                exclude_held_from_cap=True,
                market_overlay_cap=5,
                pre_pool_size=50,
                manual_symbols=(),
            )
        )
        if not selected:
            raise SystemExit("selected=0")

        existing = await repos.universe_freeze_runs.get_latest(run_date, FREEZE_PURPOSE)
        freeze_sequence = 1 if existing is None else existing.freeze_sequence + 1
        freeze_run_id = uuid4()
        items = []

        for rank, item in enumerate(selected, start=1):
            instrument = await repos.instruments.get_by_symbol(item.symbol, item.market)
            if instrument is None:
                instrument = await repos.instruments.get_by_symbol_any_market(item.symbol)
            if instrument is None:
                continue
            items.append(
                UniverseFreezeRunItemEntity(
                    universe_freeze_run_item_id=uuid4(),
                    universe_freeze_run_id=freeze_run_id,
                    instrument_id=instrument.instrument_id,
                    symbol=item.symbol,
                    market_code=item.market,
                    source_type=item.source_type.value,
                    inclusion_reason=item.inclusion_reason,
                    rank=rank,
                    cap_bucket=item.source_type.value,
                    metadata_json={},
                )
            )

        if not items:
            raise SystemExit("freeze_items=0")

        await repos.universe_freeze_runs.add(
            UniverseFreezeRunEntity(
                universe_freeze_run_id=freeze_run_id,
                business_date=run_date,
                freeze_purpose=FREEZE_PURPOSE,
                freeze_sequence=freeze_sequence,
                frozen_at=now_utc,
                selection_version="decision_loop_intraday.freeze.v1.manual",
                selection_params_json={
                    "source": "manual_force_new",
                    "target_count": len(items),
                },
                target_count=len(items),
                status="materialized",
            )
        )
        await repos.universe_freeze_run_items.add_many(items)

        print({
            "business_date": run_date.isoformat(),
            "freeze_run_id": str(freeze_run_id),
            "freeze_sequence": freeze_sequence,
            "target_count": len(items),
        })

asyncio.run(main())
PY
```

## stale 판정 기준

### Hard stale

아래 중 하나면 `hard stale`로 본다.

1. 장중인데 `operations-day/latest.summary_json.intraday_universe_freeze_done != true`
2. `preview.active_intraday_freeze == null`
3. `preview.active_intraday_freeze.business_date != 오늘 KST`
4. `preview.active_intraday_freeze.freeze_purpose != "decision_loop_intraday"`
5. `preview.active_intraday_freeze.target_count <= 0`
6. `preview.active_intraday_freeze.items`가 비어 있음

### Soft drift

아래는 `soft drift`로 본다.

1. `active_intraday_freeze_comparison.exact_match == false`
2. `live_only_symbols` 또는 `freeze_only_symbols`가 존재

해석:

- soft drift는 “지금 다시 compose하면 결과가 조금 달라진다”는 뜻이다.
- 즉시 재생성이 필요한 장애라고 단정하지 않는다.
- 다만 다음 상황이면 operator가 `force-new`를 검토한다.
  - instrument master / membership 적재 오류가 방금 복구됨
  - event 적재 누락이 복구됨
  - 수동 watchlist 변경을 오늘 anchor에 반영해야 함

## 운영 판단표

### A. scheduler 재기동 직후

- `active_intraday_freeze` 존재
- `business_date == 오늘`
- `intraday_universe_freeze_done == true`

조치:

- 추가 조치 없음
- 기존 freeze 재사용 정상

### B. freeze 누락

- `active_intraday_freeze == null`
  또는 `intraday_universe_freeze_done != true`

조치:

1. 수동 `ensure` 실행
2. 재확인
3. 여전히 누락이면 scheduler 로그와 DB 정합성 점검

### C. freeze는 있으나 오늘 데이터가 아님

- `business_date != 오늘 KST`

조치:

1. 수동 `force-new` 실행
2. preview 재확인
3. `freeze_sequence` 증가 여부 확인

### D. freeze와 live compose가 다름

- `exact_match == false`

조치:

- 기본값: 관찰만 하고 유지
- 다만 운영자가 “오늘 anchor를 새 기준으로 교체”해야 한다고 판단하면
  수동 `force-new` 실행

## 주의 사항

- 같은 거래일 중간에 `force-new`를 수행하면
  audit 관점에서 “하루 중 universe anchor가 교체되었다”는 의미가 생긴다.
- 따라서 `force-new`는
  - 누락 복구
  - 잘못된 적재 복구 후 재동결
  - operator 승인된 정책 변경 반영
  같은 명시적 사유가 있을 때만 사용한다.
- 단순 drift만으로는 기본적으로 재생성하지 않는다.
