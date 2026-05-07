# Broker Capacity Inspection — REST Budget / WS Subscription Read-Only API

## 목적

현재 broker rate-limit budget과 WebSocket subscription 사용량을 운영자가 read-only로 조회할 수 있게 만든다. Enforcement가 아니라 **visibility**가 목적이다.

## 분석 결과

### 이미 존재하는 snapshot 기능

| 대상 | 상태 | 상세 |
|------|------|------|
| [`RateLimitBudgetManager.snapshot()`](src/agent_trading/brokers/rate_limit.py:313) | ✅ 이미 존재 | 모든 5개 bucket (auth/order/inquiry/reconciliation/market_data)의 remaining/capacity/utilization + session_id + can_accept_new_entries 반환 |
| [`SubscriptionBudget`](src/agent_trading/brokers/base.py:26) | ❌ snapshot 메서드 없음 | dataclass 필드로 max_subscriptions/critical_limit/optional_limit/current_critical/current_optional/total_used 접근 가능. snapshot() 추가 필요 |

### Runtime 접근 경로

```
build_default_runtime()
  └─ "primary_broker_adapter" → KoreaInvestmentAdapter
       ├─ ._mode                → "paper" | "live"
       ├─ ._rest.budget_manager → RateLimitBudgetManager (→ snapshot())
       ├─ ._subscription_budget → SubscriptionBudget
       ├─ ._market_data_subscriptions → dict[channel, set[symbol]]
       ├─ ._order_event_accounts      → set[account_ref]
       └─ .broker_name               → BrokerName.KOREA_INVESTMENT
```

### API wiring

현재 [`create_app()`](src/agent_trading/api/app.py:34)은 `repos`, `runtime_mode`, `auth_*` 파라미터만 받고 broker adapter를 받지 않는다. `broker_adapter` 파라미터를 추가하고 `app.state.broker_adapter`에 저장해야 한다.

### Test 패턴

[`tests/api/conftest.py`](tests/api/conftest.py:333)에서 `create_app(repos=seeded_repos, auth_enabled=False)`로 TestClient 생성. 동일 패턴으로 broker_adapter를 주입할 수 있게 한다.

---

## 구현 계획

### Step 1: `SubscriptionBudget.snapshot()` 추가

**파일**: [`src/agent_trading/brokers/base.py`](src/agent_trading/brokers/base.py)

SubscriptionBudget에 snapshot() 메서드 추가:

```python
def snapshot(self) -> dict[str, Any]:
    return {
        "max_subscriptions": self.max_subscriptions,
        "critical_limit": self.critical_limit,
        "optional_limit": self.optional_limit,
        "current_critical": self.current_critical,
        "current_optional": self.current_optional,
        "total_used": self.total_used,
        "remaining": self.max_subscriptions - self.total_used,
    }
```

### Step 2: `BrokerCapacityResponse` 스키마 추가

**파일**: [`src/agent_trading/api/schemas.py`](src/agent_trading/api/schemas.py)

```python
class BucketSnapshot(BaseModel):
    """Single token-bucket state."""
    remaining: int
    capacity: int
    utilization: float
    refill_rate: float


class WsSubscriptionSnapshot(BaseModel):
    """WebSocket subscription budget state."""
    max_subscriptions: int
    critical_limit: int
    optional_limit: int
    current_critical: int
    current_optional: int
    total_used: int
    remaining: int


class BrokerCapacityResponse(BaseModel):
    """``GET /broker-capacity`` response."""
    broker_name: str
    environment: str  # "paper" | "live"
    rest_budget: dict[str, BucketSnapshot] | None = None  # keyed by bucket type
    can_accept_new_entries: bool | None = None
    websocket: WsSubscriptionSnapshot | None = None
    market_data_subscriptions: dict[str, list[str]] | None = None
    order_event_accounts: list[str] | None = None
```

### Step 3: `GET /broker-capacity` 라우트 추가

**파일**: [`src/agent_trading/api/routes/broker_capacity.py`](src/agent_trading/api/routes/broker_capacity.py) (신규)

```python
router = APIRouter(tags=["broker-capacity"])


@router.get("/broker-capacity", response_model=BrokerCapacityResponse)
async def get_broker_capacity(request: Request) -> BrokerCapacityResponse:
    adapter: KoreaInvestmentAdapter | None = getattr(
        request.app.state, "broker_adapter", None
    )
    if adapter is None:
        # No broker adapter available — return empty response gracefully
        return BrokerCapacityResponse(
            broker_name="unknown", environment="unknown"
        )
    
    # REST budget snapshot
    budget = adapter._rest.budget_manager
    rest_snapshot = budget.snapshot() if budget else None
    
    # WS subscription snapshot
    ws_snapshot = adapter._subscription_budget.snapshot()
    
    # Subscriptions detail
    mkt_data = {
        ch: sorted(syms) 
        for ch, syms in adapter._market_data_subscriptions.items()
    }
    order_accts = sorted(adapter._order_event_accounts)
    
    return BrokerCapacityResponse(
        broker_name=adapter.broker_name.value,
        environment=adapter._mode,
        rest_budget=rest_snapshot,
        can_accept_new_entries=budget.can_accept_new_entries if budget else None,
        websocket=ws_snapshot,
        market_data_subscriptions=mkt_data,
        order_event_accounts=order_accts,
    )
```

### Step 4: `create_app()`에 `broker_adapter` 파라미터 추가

**파일**: [`src/agent_trading/api/app.py`](src/agent_trading/api/app.py)

1. `create_app()` 시그니처에 `broker_adapter: Any | None = None` 추가
2. lifespan에서 `broker_adapter is not None`일 때 `app.state.broker_adapter = broker_adapter` 설정
3. 라우트 등록: `broker_capacity_router` import + protected_routers에 추가

### Step 5: 테스트 추가

**파일**: [`tests/api/test_broker_capacity.py`](tests/api/test_broker_capacity.py) (신규)

```python
class TestBrokerCapacityEndpoint:
    """``GET /broker-capacity`` endpoint tests."""

    async def test_no_adapter_returns_graceful_fallback(
        self, empty_client: TestClient
    ) -> None:
        """No broker adapter → broker_name='unknown', environment='unknown'."""
        resp = empty_client.get("/broker-capacity")
        assert resp.status_code == 200
        data = resp.json()
        assert data["broker_name"] == "unknown"
        assert data["environment"] == "unknown"
        assert data["rest_budget"] is None

    async def test_with_adapter_returns_full_snapshot(
        self, client_with_adapter: TestClient
    ) -> None:
        """With adapter → all fields populated."""
        resp = client_with_adapter.get("/broker-capacity")
        assert resp.status_code == 200
        data = resp.json()
        assert data["broker_name"] == "KOREA_INVESTMENT"
        assert data["environment"] == "paper"
        assert data["rest_budget"] is not None
        for bucket in ("auth", "order", "inquiry", "reconciliation", "market_data"):
            assert bucket in data["rest_budget"]
            assert "remaining" in data["rest_budget"][bucket]
            assert "capacity" in data["rest_budget"][bucket]
        assert data["websocket"] is not None
        assert "total_used" in data["websocket"]
        assert "remaining" in data["websocket"]

    async def test_auth_protected(self, auth_client: TestClient) -> None:
        """Endpoint requires auth when auth is enabled."""
        resp = auth_client.get("/broker-capacity")
        assert resp.status_code == 403  # Unauthorized
```

### Step 6: 테스트 Fixture 업데이트

**파일**: [`tests/api/conftest.py`](tests/api/conftest.py)

새 fixture `client_with_adapter` 추가:

```python
@pytest.fixture
async def client_with_adapter() -> TestClient:
    """FastAPI TestClient with a real KIS adapter (mocked HTTP) attached."""
    budget = build_kis_budget_manager(
        kis_env="paper",
    )
    rest_client = KISRestClient(
        api_key="dummy", api_secret="dummy",
        account_number="12345678", account_product_code="01",
        env="paper", budget_manager=budget,
    )
    adapter = KoreaInvestmentAdapter(rest_client=rest_client)
    # Mock _get_client to avoid real network
    async def _noop_client() -> AsyncMock:
        return AsyncMock(spec=httpx.AsyncClient)
    # ... class-level monkeypatch or real create_app with adapter ...
    app = create_app(auth_enabled=False, broker_adapter=adapter)
    with TestClient(app) as tc:
        yield tc
```

**중요**: `_get_client`가 `slots=True`로 인해 문제가 될 수 있으므로, `rest_client` 없이 adapter를 만들거나,
아니면 unit test에서는 adapter의 budget/WS 상태를 직접 설정해서 검증하는 방식으로 간소화.

**대안**: `client_with_adapter` fixture는 실제로 adapter를 만들지 않고, `MagicMock`을 adapter로 전달:

```python
@pytest.fixture
async def client_with_adapter() -> TestClient:
    adapter = MagicMock(spec=KoreaInvestmentAdapter)
    adapter.broker_name = BrokerName.KOREA_INVESTMENT
    adapter._mode = "paper"
    
    budget = RateLimitBudgetManager()
    adapter._rest.budget_manager = budget
    adapter._rest = MagicMock()
    adapter._rest.budget_manager = budget
    
    adapter._subscription_budget = SubscriptionBudget()
    adapter._market_data_subscriptions = {}
    adapter._order_event_accounts = set()
    
    app = create_app(auth_enabled=False, broker_adapter=adapter)
    with TestClient(app) as tc:
        yield tc
```

Wait — `adapter._rest.budget_manager` with mock... Slots=True on KISRestClient makes this tricky.

**권장**: Test에서 `MagicMock`을 adapter로 사용. 단, `_mode`, `_subscription_budget`, `_rest.budget_manager` 등 속성 접근을 mock이 처리할 수 있게 configure.

---

## 변경 파일 목록

| 파일 | 작업 | 설명 |
|------|------|------|
| [`src/agent_trading/brokers/base.py`](src/agent_trading/brokers/base.py) | 수정 | `SubscriptionBudget.snapshot()` 메서드 추가 |
| [`src/agent_trading/api/schemas.py`](src/agent_trading/api/schemas.py) | 수정 | `BucketSnapshot`, `WsSubscriptionSnapshot`, `BrokerCapacityResponse` 추가 |
| [`src/agent_trading/api/routes/broker_capacity.py`](src/agent_trading/api/routes/broker_capacity.py) | **생성** | `GET /broker-capacity` 엔드포인트 |
| [`src/agent_trading/api/app.py`](src/agent_trading/api/app.py) | 수정 | `create_app()`에 `broker_adapter` 파라미터 + 라우트 등록 |
| [`tests/api/conftest.py`](tests/api/conftest.py) | 수정 | `client_with_adapter` fixture 추가 |
| [`tests/api/test_broker_capacity.py`](tests/api/test_broker_capacity.py) | **생성** | 3개 테스트 케이스 |

## 변경 금지 확인

- [x] strict enforcement 로직 변경 — ❌ 변경 없음 (snapshot만 노출)
- [x] WebSocket budget eviction policy 변경 — ❌ 변경 없음
- [x] broker submit semantics 변경 — ❌ 변경 없음
- [x] hard guardrail / reconciliation 경계 변경 — ❌ 변경 없음
- [x] admin UI write 기능 추가 — ❌ 이번 턴 범위 외

## 후속 연결

이 inspection API는 다음 strict enforcement 작업의 전제 조건이다:
1. **WS 41 exact enforcement**: `SubscriptionBudget`의 현재 사용량을 API로 확인하면서 enforcement 로직 검증 가능
2. **Strict Global REST Cap**: `RateLimitBudgetManager.snapshot()`으로 bucket 상태 모니터링 후 enforcement 임계값 조정 가능
3. **Admin UI 노출**: `GET /broker-capacity`의 response schema가 정해졌으므로, 이후 Admin UI에서 `fetch('/broker-capacity')`로 데이터를 읽어서 표시 가능
