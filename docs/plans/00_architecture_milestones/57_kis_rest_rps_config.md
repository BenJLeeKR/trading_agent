# KIS 실전/모의 REST RPS 환경변수 반영

## 목적

KIS 환경(`paper` / `live`)별 실제 REST RPS 수치를 env/config에 반영하여
`RateLimitBudgetManager` 기본값을 환경에 맞게 설정한다.

- **실전(`live`)**: 총 REST RPS ≈ 15
- **모의(`paper`)**: 총 REST RPS ≈ 1

## 핵심 설계 원칙

1. **전체 REST RPS와 bucket 분리 구조의 차이를 명시적으로 문서화**
   - KIS API 문서의 "전체 REST RPS"는 모든 operation의 aggregate limit
   - 현재 시스템은 5개 bucket(ORDER/INQUIRY/RECONCILIATION/MARKET_DATA/AUTH)이 독립적으로 token 소비
   - 각 API call은 정확히 1개 bucket에서만 consume하므로, sum(bucket_refill_rate) ≈ total RPS 가 되도록 분배
2. **안전 기준점(safety baseline)**으로 설정 — throughput 최적화가 아님
3. **env override 가능** — `KIS_REAL_REST_RPS=15`, `KIS_PAPER_REST_RPS=1`

## 파일별 변경 사항

### 1. `src/agent_trading/config/settings.py`

**추가할 resolver 함수**:
```python
def _resolve_kis_real_rest_rps() -> int:
    """Read KIS_REAL_REST_RPS, default 15."""
    raw = os.getenv("KIS_REAL_REST_RPS", "15")
    return max(1, int(raw))

def _resolve_kis_paper_rest_rps() -> int:
    """Read KIS_PAPER_REST_RPS, default 1."""
    raw = os.getenv("KIS_PAPER_REST_RPS", "1")
    return max(1, int(raw))
```

**추가할 AppSettings field**:
```python
kis_real_rest_rps: int = field(default_factory=_resolve_kis_real_rest_rps)
kis_paper_rest_rps: int = field(default_factory=_resolve_kis_paper_rest_rps)
```

### 2. `src/agent_trading/brokers/rate_limit.py`

**추가할 팩토리 함수** (`build_kis_budget_manager`):

```python
def build_kis_budget_manager(
    kis_env: str,
    *,
    real_rest_rps: int = 15,
    paper_rest_rps: int = 1,
) -> RateLimitBudgetManager:
    """KIS 환경별 RateLimitBudgetManager를 생성한다.

    KIS API 문서의 "전체 REST RPS"와 현재 시스템의 bucket 분리 구조는
    1:1 대응이 아니다.  아래 변환 규칙을 적용한다:

    변환 규칙 (Total REST RPS → Bucket 분배)
    -----------------------------------------
    각 API call은 정확히 1개의 bucket에서만 token을 소비하므로,
    sum(bucket_refill_rate) ≈ total_rps 가 되도록 bucket별 rate를 할당한다.

    Paper (total=1 rps):
      auth:     capacity=1,  refill_rate=0.017  (1/60 ≈ 1/min, KIS Paper auth rate limit)
      order:    capacity=1,  refill_rate=0.1    (1 per 10s, paper order는 드뭄)
      inquiry:  capacity=1,  refill_rate=0.5    (1 per 2s)
      market_data: capacity=1, refill_rate=0.5  (1 per 2s)
      reconciliation: capacity=1, refill_rate=0.1 (reserve)
      → sum ≈ 1.2 rps (≈ 1 rps total)

    Live (total=15 rps):
      auth:     capacity=5,   refill_rate=0.1   (1 per 10s, auth는 드뭄)
      order:    capacity=5,   refill_rate=2.0   (2 per second)
      inquiry:  capacity=10,  refill_rate=5.0   (5 per second, inquiry-heavy)
      market_data: capacity=20, refill_rate=5.0 (5 per second)
      reconciliation: capacity=5,  refill_rate=1.0 (reserve)
      → sum ≈ 13.1 rps (≈ 15 rps total, 보수적 분배)
    """
    ...
```

### 3. `src/agent_trading/runtime/bootstrap.py`

`_build_kis_adapter()` 수정:

```python
def _build_kis_adapter(settings: AppSettings) -> KoreaInvestmentAdapter:
    budget_manager = build_kis_budget_manager(
        kis_env=settings.kis_env,
        real_rest_rps=settings.kis_real_rest_rps,
        paper_rest_rps=settings.kis_paper_rest_rps,
    )
    rest_client = KISRestClient(
        api_key=settings.kis_api_key,
        api_secret=settings.kis_api_secret,
        account_number=settings.kis_account_number,
        account_product_code=settings.kis_account_product_code,
        env=settings.kis_env,
        base_url=settings.kis_base_url,
        budget_manager=budget_manager,
    )
    return KoreaInvestmentAdapter(rest_client=rest_client)
```

### 4. `.env.example`

KIS 섹션 하단에 추가:
```ini
# KIS REST rate limit capacity (safety baseline, not throughput optimisation)
KIS_REAL_REST_RPS=15    # live/real environment: ~15 requests/sec total
KIS_PAPER_REST_RPS=1    # paper sandbox: ~1 request/sec total
```

### 5. `docker-compose.yml`

`app`과 `api` 서비스의 `environment`에 추가:
```yaml
KIS_REAL_REST_RPS: "${KIS_REAL_REST_RPS:-15}"
KIS_PAPER_REST_RPS: "${KIS_PAPER_REST_RPS:-1}"
```

### 6. `plan_docs/detailed_design/10_broker_rate_limit_and_capacity_policy.md`

"Implementation Status" 섹션에 env var 반영 사실과 변환 규칙 요약 추가.

### 7. `tests/services/ai_agents/test_settings.py`

`TestAppSettingsKisFields`에 테스트 추가:
```python
def test_kis_real_rest_rps_default(self, monkeypatch):
    monkeypatch.delenv("KIS_REAL_REST_RPS", raising=False)
    settings = AppSettings()
    assert settings.kis_real_rest_rps == 15

def test_kis_paper_rest_rps_default(self, monkeypatch):
    monkeypatch.delenv("KIS_PAPER_REST_RPS", raising=False)
    settings = AppSettings()
    assert settings.kis_paper_rest_rps == 1

def test_kis_real_rest_rps_custom(self, monkeypatch):
    monkeypatch.setenv("KIS_REAL_REST_RPS", "20")
    settings = AppSettings()
    assert settings.kis_real_rest_rps == 20

def test_kis_paper_rest_rps_custom(self, monkeypatch):
    monkeypatch.setenv("KIS_PAPER_REST_RPS", "3")
    settings = AppSettings()
    assert settings.kis_paper_rest_rps == 3

def test_kis_rest_rps_min_one(self, monkeypatch):
    monkeypatch.setenv("KIS_REAL_REST_RPS", "0")
    settings = AppSettings()
    assert settings.kis_real_rest_rps == 1  # clamped
```

### 8. `tests/brokers/test_rate_limit.py` (신규 또는 기존 확장)

`RateLimitBudgetManager` 기본값이 아닌 KIS 환경별 값 검증:
```python
def test_build_kis_budget_manager_paper(self):
    mgr = build_kis_budget_manager("paper")
    assert mgr.auth.refill_rate == pytest.approx(0.017, abs=0.001)
    assert mgr.order.capacity == 1

def test_build_kis_budget_manager_live(self):
    mgr = build_kis_budget_manager("live")
    assert mgr.inquiry.capacity == 10
    assert mgr.inquiry.refill_rate == 5.0

def test_build_kis_budget_manager_custom_rps(self):
    mgr = build_kis_budget_manager("paper", paper_rest_rps=2)
    assert mgr.inquiry.refill_rate == 1.0  # 2 rps → double
```

## RPS → Bucket 분배 상세

### Paper (total 1 rps)

| Bucket | Cap | Refill/s | 근거 |
|--------|-----|----------|------|
| AUTH | 1 | 0.017 (1/60) | KIS Paper 1-token-per-minute rate limit |
| ORDER | 1 | 0.1 | paper에서 order는 드묾 |
| INQUIRY | 1 | 0.5 | 조회 위주, 2초에 1회 |
| MARKET_DATA | 1 | 0.5 | 조회 위주, 2초에 1회 |
| RECONCILIATION | 1 | 0.1 | reserve, 10초에 1회 |
| **합계** | | **≈ 1.2** | **≈ 1 rps** |

### Live (total 15 rps)

| Bucket | Cap | Refill/s | 근거 |
|--------|-----|----------|------|
| AUTH | 5 | 0.1 | 10초에 1회, 인증은 드묾 |
| ORDER | 5 | 2.0 | 초당 2건 주문 |
| INQUIRY | 10 | 5.0 | 조회가 가장 빈번 |
| MARKET_DATA | 20 | 5.0 | market data도 inquiry와 유사 |
| RECONCILIATION | 5 | 1.0 | reserve, 초당 1회 |
| **합계** | | **≈ 13.1** | **≈ 15 rps** |

### 변환 규칙 공식

```
paper:
  각 bucket refill = total_rps * weight
  weights: auth=0.014, order=0.08, inquiry=0.42, market_data=0.42, reconciliation=0.08

live:
  각 bucket refill = total_rps * weight
  weights: auth=0.007, order=0.15, inquiry=0.38, market_data=0.38, reconciliation=0.08
```

## 변경 금지 확인

- admin UI 변경 ❌
- broker submit semantics 변경 ❌
- hard guardrail / reconciliation 경계 변경 ❌
- paper/live safety guard 완화 ❌
- rate limit 엔진 재설계 ❌

## 관련 파일 전체 목록

| 파일 | 변경 유형 |
|------|----------|
| `src/agent_trading/config/settings.py` | 수정 — resolver + field 추가 |
| `src/agent_trading/brokers/rate_limit.py` | 수정 — `build_kis_budget_manager()` 추가 |
| `src/agent_trading/runtime/bootstrap.py` | 수정 — `_build_kis_adapter()`에 budget 연결 |
| `.env.example` | 수정 — RPS env var 추가 |
| `docker-compose.yml` | 수정 — RPS env var 전달 |
| `plan_docs/detailed_design/10_broker_rate_limit_and_capacity_policy.md` | 수정 — 구현 현황 갱신 |
| `tests/services/ai_agents/test_settings.py` | 수정 — resolver 테스트 추가 |
| `tests/brokers/test_rate_limit.py` | 수정 — `build_kis_budget_manager` 테스트 추가 |

---

## 후속 작업: Strict Global REST Cap (v1 범위 외)

현재 v1 구현은 **per-bucket safety scaling**이다. 각 bucket이 독립적으로 동작하므로
5개 bucket이 동시에 max rate로 소비되면 aggregate RPS가 환경 baseline을 초과할 수 있다.

### 필요 조건

Strict global REST cap이 필요해지는 상황:
1. KIS API가 **계정 단위**로 strict RPS 제한을 적용함이 확인된 경우
2. rate limit 위반 시 계정이 **일시 정지**되는 패널티가 있는 경우
3. 감사(audit) 요건으로 "절대 초과하지 않음"을 증명해야 하는 경우

### 권장 아키텍처: 2-Tier Token Bucket

```
Global Token Bucket (capacity=total_rps, refill=total_rps/sec)
    │  모든 API call이 먼저 global token을 consume
    │
    ├── AUTH bucket (sub-limit, capacity=5, refill=0.1/sec)
    ├── ORDER bucket (sub-limit, capacity=5, refill=2.0/sec)
    ├── INQUIRY bucket (sub-limit, capacity=10, refill=5.0/sec)
    ├── MARKET_DATA bucket (sub-limit, capacity=20, refill=5.0/sec)
    └── RECONCILIATION bucket (sub-limit, capacity=5, refill=1.0/sec)
```

**동작 방식**:
1. 모든 API call은 `global_bucket.try_consume(1)`을 먼저 호출
2. 성공하면 `per_bucket.try_consume(1)` 호출
3. global bucket이 고갈되면 **모든 operation이 차단** (fairness)
4. per-bucket sub-limit은 operation type별 max rate 유지

**변경 사항**:
- `RateLimitBudgetManager`에 global bucket 필드 추가
- `try_consume()`이 global → per-bucket 2단 consume 수행
- `build_kis_budget_manager()`가 global bucket도 생성
- `snapshot()`에 global bucket 정보 추가

**예상 난이도**: 중간 (RateLimitBudgetManager 구조 변경 필요)
**현재 상태**: v1 범위 외, 필요시 별도 plan으로 추진
