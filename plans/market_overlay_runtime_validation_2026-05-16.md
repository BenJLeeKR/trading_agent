# market_overlay 실운영 반영 여부 검증 보고서

**작성일**: 2026-05-16  
**우선순위**: P1 (BACKLOG.md)  
**분석 모드**: Read-only (코드 수정 없음)

---

## 1. 검증 요약

| 항목 | 결과 |
|------|------|
| `market_overlay` 로직 자체 | ✅ **완전 구현** (`_add_market_overlay()`: pre-pool → KIS batch quote → F4/F5 필터 → 3축 스코어링 → Top-N) |
| 실운영 반영 여부 | ❌ **반영 안 됨** — 0건 |
| 원인 | `KISRestClient(settings=settings)` **TypeError** (dataclass 인자 불일치) |
| 영향 | `kis_client = None` → `_add_market_overlay()` 가드에서 조기 return |
| 분류 | **D — 코드는 구현되었으나 인스턴스화 지점이 깨져 사실상 미구동** |

---

## 2. 코드 구현 상태 분석

### 2.1 SourceType enum

[`src/agent_trading/services/universe_selection_types.py`](../../src/agent_trading/services/universe_selection_types.py:23)

```python
class SourceType(str, Enum):
    HELD_POSITION = "held_position"   # priority 0 (최우선)
    EVENT_OVERLAY  = "event_overlay"  # priority 1
    MARKET_OVERLAY = "market_overlay"  # priority 2
    MANUAL         = "manual"          # priority 3
    CORE           = "core"            # priority 4
```

- `MARKET_OVERLAY` enum 정상 정의됨
- 우선순위는 `HELD_POSITION(0) > EVENT_OVERLAY(1) > MARKET_OVERLAY(2) > MANUAL(3) > CORE(4)`
- 낮을수록 높은 우선순위

### 2.2 UniverseSelectionService._add_market_overlay()

[`src/agent_trading/services/universe_selection.py`](../../src/agent_trading/services/universe_selection.py:431)

**전체 파이프라인 (431-533행):**

```
_pre_pool (최대 50종목)
  → KIS get_quotes_batch() [Semaphore 10, 3s timeout]
    → F4 필터: iscd_stat_cls_code (관리종목 제외)
    → F5 필터: acc_trade_amount < 1B 제외
      → 3축 composite score 계산
        → Top-N (market_overlay_cap=5)
          → _upsert_with_priority()로 삽입
```

**핵심 로직 가드 (450-451행):**
```python
if self._kis_client is None:
    logger.debug("_add_market_overlay | no KIS client — skipping (P1 stub).")
    return
```

→ `self._kis_client`가 `None`이면 메서드 전체가 No-op

### 2.3 DecisionOrchestrator.assemble() — source_type 전달

[`src/agent_trading/services/decision_orchestrator.py`](../../src/agent_trading/services/decision_orchestrator.py:546)

```python
source_type: str = request.metadata.get("source_type", "core")
```

- `AssembledContext`에 `source_type` 필드 존재 (225행)
- `request.metadata`에서 추출, 기본값 `"core"`
- **DB에 source_type 컬럼 없음** — application 계층에서만 유지됨

---

## 3. 실운영 파이프라인 단계별 분석

### 3.1 Universe 생성 단계 — `run_paper_decision_loop.py:_read_trading_universe()`

[`scripts/run_paper_decision_loop.py`](../../scripts/run_paper_decision_loop.py:331)

```python
try:
    from agent_trading.config.settings import AppSettings
    settings = AppSettings()
    kis_client = KISRestClient(settings=settings)  # ← BUG: TypeError
except Exception:
    logger.debug("KIS client init failed — market overlay disabled.", exc_info=True)
    kis_client = None

selector = UniverseSelectionService(repos, kis_client=kis_client)
```

**버그 상세:**
- `KISRestClient`는 [`@dataclass(slots=True)`](../../src/agent_trading/brokers/koreainvestment/rest_client.py:219)로 선언됨
- 생성자 파라미터: `api_key`, `api_secret`, `account_number`, `account_product_code`, `env`, `base_url`, `budget_manager`
- `settings=` 키워드 인자를 받지 않음 → **TypeError**
- `except Exception:`이 이 에러를 catch → `kis_client = None` → market_overlay 영구 비활성화

### 3.2 스케줄러 — `run_near_real_ops_scheduler.py`

[`scripts/run_near_real_ops_scheduler.py`](../../scripts/run_near_real_ops_scheduler.py:369)

- `_decision_command()`가 `run_paper_decision_loop.py`를 subprocess로 호출
- market_overlay 관련 인자 전달 없음
- 스케줄러 자체에는 문제 없으나, 하위 프로세스에서 위 3.1의 버그가 동일하게 발생

### 3.3 AI 판단 단계

- `source_type`은 `request.metadata`를 통해 AI agent까지 전달됨
- 단, DB에 source_type이 저장되지 않으므로 사후 분석 불가
- `decision_json` JSONB 키: `sizing_hint`, `decision_type`, `execution_preferences`, `entry_style`, `risk_opinion`, `time_horizon`, `risk_flags`, `event_conflict`, `event_bias`, `side` — **source_type 없음**

---

## 4. DB 현황 실측

### 4.1 decision_contexts 테이블
- `source_type` 컬럼 **없음**
- `decision_json` JSONB에 source_type 미포함

### 4.2 trade_decisions 테이블
- `source_type` 컬럼 **없음**

### 4.3 order_requests 테이블
- `source_type` 컬럼 **없음**
- `client_order_id` 포맷: `dc-{short_uuid}-{timestamp_suffix}` (예: `dc-ed1da30c-0531215739`)
- order_id로 source_type 복원 불가

### 4.4 universe 현황 (2026-05-14 ~ 2026-05-15, 48시간)

| 메트릭 | 값 |
|--------|------|
| 총 의사결정 레코드 | 2,921건 |
| Unique symbols | 100개 |
| Core symbols (~95 records each) | 30개 |
| 추가 symbols (~3 records each) | 70개 |
| **market_overlay symbols** | **0개** |
| Decision Type: hold | 2,798건 (95.8%) |
| Decision Type: reduce | 69건 (2.4%) |
| Decision Type: approve | 52건 (1.8%) |
| Decision Type: watch | 2건 (0.07%) |

→ **market_overlay 종목 0건, source_type = "market_overlay"인 레코드 0건**

### 4.5 스케줄러 로그 확인

| 검색어 | 매칭 결과 |
|--------|----------|
| `_add_market_overlay` | **0건** |
| `pre-pool` | **0건** |
| `market_overlay` | **0건** |
| `Trading universe from UniverseSelectionService` | 1건 (30 symbols, cap=30) |

→ market_overlay 관련 로그가 전혀 출력되지 않음. KIS client init 실패 로그는 `DEBUG` 레벨이라 스케줄러 로그에 보이지 않음.

---

## 5. KIS API 계측

### 5.1 get_quotes_batch()

[`src/agent_trading/brokers/koreainvestment/rest_client.py`](../../src/agent_trading/brokers/koreainvestment/rest_client.py:1177)

```python
async def get_quotes_batch(
    self, symbols: Sequence[str], budget_key: str = "universe"
) -> dict[str, dict[str, Any]]:
```

- **완전 구현** — Semaphore(10) 동시성 제어, 3s 타임아웃
- 실패한 symbol은 skip (budget-safe)
- 반환: `{symbol: raw_output_dict}`
- **market_overlay에 의해 호출되지 않음** (kis_client=None으로 인해)

### 5.2 get_quote()

[`src/agent_trading/brokers/koreainvestment/rest_client.py`](../../src/agent_trading/brokers/koreainvestment/rest_client.py:1154)

- 단건 조회용 (`inquire_price` endpoint)
- market_overlay는 batch 사용이므로 관련 없음

---

## 6. 버그 재현

```bash
$ python3 -c "
from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.config.settings import AppSettings
settings = AppSettings()
client = KISRestClient(settings=settings)
"
# TypeError: KISRestClient.__init__() got an unexpected keyword argument 'settings'
```

**정확한 사용법:**
```python
client = KISRestClient(
    api_key=settings.kis_api_key,
    api_secret=settings.kis_api_secret,
    account_number=settings.kis_account_number,
    account_product_code=settings.kis_account_product_code,
    env=settings.kis_env,
    base_url=settings.kis_base_url,
    budget_manager=budget_manager,
)
```

---

## 7. 근본 원인 분류

| 분류 | 설명 |
|------|------|
| **A — 완전 구현 & 정상 작동** | SourceType enum, _add_market_overlay() 로직 전체, get_quotes_batch(), AssembledContext.source_type |
| **B — 구현됐으나 미세조정 필요** | - |
| **C — 설정/환경 문제** | - |
| **D — 아직 사실상 미구현** | **✅ KIS client 인스턴스화 지점 버그로 market_overlay=0** |
| **E — 설계만 됨** | - |
| **F — 설계도 안 됨** | - |

**분류 근거:** `_add_market_overlay()` 메서드 자체는 pre-pool → batch quote → F4/F5 필터 → 3축 스코어링 → Top-N까지 완전히 구현되어 있음. 그러나 [`run_paper_decision_loop.py:338`](../../scripts/run_paper_decision_loop.py:338)에서 `KISRestClient(settings=settings)`가 TypeError를 발생시키고, `except Exception`이 이를 조용히 catch하여 `kis_client = None`으로 설정. 이로 인해 `UniverseSelectionService.__init__`에 `None`이 전달되고, `_add_market_overlay()`의 가드 조건(`if self._kis_client is None`)에서 조기 return되어 메서드 전체가 No-op가 됨.

---

## 8. 권장 수정사항 (최소 2-3 항목)

> **참고**: 이 보고서는 read-only 분석입니다. 아래는 코드 수정 시 우선순위 권장사항입니다.

### P0 — KISRestClient 인스턴스화 수정

[`scripts/run_paper_decision_loop.py:338`](../../scripts/run_paper_decision_loop.py:338)

```python
# BEFORE (bug):
kis_client = KISRestClient(settings=settings)

# AFTER:
kis_client = KISRestClient(
    api_key=settings.kis_api_key,
    api_secret=settings.kis_api_secret,
    account_number=settings.kis_account_number,
    account_product_code=settings.kis_account_product_code,
    env=settings.kis_env,
    base_url=settings.kis_base_url,
    budget_manager=budget_manager,
)
```

### P1 — 소스코드 설정(AppSettings)에 KISRestClient 팩토리 메서드 추가

[`src/agent_trading/config/settings.py`](../../src/agent_trading/config/settings.py:205)

`AppSettings`에 `build_kis_client()` 메서드를 추가하여 재사용성과 안전성 확보:

```python
def build_kis_client(self, budget_manager: BudgetManager) -> KISRestClient:
    return KISRestClient(
        api_key=self.kis_api_key,
        api_secret=self.kis_api_secret,
        account_number=self.kis_account_number,
        account_product_code=self.kis_account_product_code,
        env=self.kis_env,
        base_url=self.kis_base_url,
        budget_manager=budget_manager,
    )
```

### P2 — exception handling 개선

`except Exception:`을 구체적으로 변경:
- `except (ImportError, AttributeError, TypeError) as e:` 로 좁힘
- 실패 시 `logger.warning()` 이상 레벨로 로깅하여 운영자가 인지 가능하도록 개선
- KIS 설정 미완료 상태를 구분할 수 있는 명시적 플래그 도입

### P3 — source_type DB 저장

`decision_contexts` 또는 `trade_decisions` 테이블에 `source_type` 컬럼 추가:
- 향후 source_type 기반 성과 분석 가능
- market_overlay vs core vs event_overlay 기여도 측정 가능
- migration 필요

---

## 9. 결론

| 질문 | 답변 |
|------|------|
| market_overlay 로직이 universe에 반영되는가? | **아니오** — KIS client 초기화 버그로 인해 `_add_market_overlay()`가 항상 No-op |
| market_overlay source_type이 AI 판단까지 전달되는가? | **아니오** — universe에 포함되지 않으므로 전달될 기회 없음 |
| 코드 자체는 구현되어 있는가? | **예** — `_add_market_overlay()`는 pre-pool, batch quote, 필터, 스코어링, Top-N까지 완전 구현 |
| DB에서 source_type을 추적할 수 있는가? | **아니오** — DB 스키마에 source_type 컬럼 없음, application 계층 metadata로만 유지 |
| 수정 난이도 | **낮음** — 1) KISRestClient 인자 수정, 2) 로그 레벨 상향, 2-3시간 작업 예상 |

**핵심**: 이 문제는 설계/구현의 문제가 아니라 **인스턴스화 지점의 단순한 API 불일치** 버그입니다. `KISRestClient`가 `@dataclass(slots=True)`로 `settings=` 인자를 받지 않는데, 호출부에서 `KISRestClient(settings=settings)`로 잘못 호출하고 있습니다. 이는 30분이면 수정 가능한 단순 버그이며, 수정 즉시 market_overlay 파이프라인이 정상 작동할 것으로 예상됩니다.
