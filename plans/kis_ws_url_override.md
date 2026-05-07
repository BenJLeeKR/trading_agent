# KIS WebSocket URL env override (`KIS_WS_URL`)

## 목적

KIS WebSocket endpoint를 `KIS_WS_URL` env var로 명시적으로 override 가능하게 만든다.
현재 REST는 `KIS_BASE_URL` override가 가능하지만, WebSocket은 `KIS_WS_URLS` 하드코딩 매핑만 사용 중이다.

## 변경 사항

### 1. `src/agent_trading/config/settings.py` — `kis_ws_url` 필드 추가

```python
# AppSettings에 추가 (kis_base_url 바로 아래)
kis_ws_url: str = field(default_factory=lambda: os.getenv("KIS_WS_URL", ""))
```

- 기본값 `""` (미설정 시 기존 매핑 유지)
- `KIS_ENV` 정규화(`real`→`live`)와 충돌 없음

### 2. `src/agent_trading/brokers/koreainvestment/websocket_client.py` — override 지원

**`__init__`** 에 `ws_url: str = ""` 파라미터 추가 → `self._ws_url` 저장

**`connect()`** (line 128) 변경:
```python
# before
url = KIS_WS_URLS[self._env]

# after
url = self._ws_url or KIS_WS_URLS[self._env]
```

- override 우선, 미설정 시 기존 env 기반 매핑

### 3. `src/agent_trading/brokers/koreainvestment/adapter.py` — ws_url 전달

**`__init__`** 에 `ws_url: str = ""` 파라미터 추가 → `self._ws_url` 저장

**`_ensure_ws_connected()`** (line 431) 변경:
```python
self._ws = KISWebSocketClient(
    rest_client=self._rest,
    approval_key=self._ws_approval_key,
    env=self._mode,
    subscription_budget=self._subscription_budget,
    ws_url=self._ws_url,  # 추가
)
```

### 4. `src/agent_trading/runtime/bootstrap.py` — settings 연결

**`_build_kis_adapter()`** 변경:
```python
return KoreaInvestmentAdapter(
    rest_client=rest_client,
    ws_url=settings.kis_ws_url,  # 추가
)
```

### 5. `.env.example` — 문서화

`KIS_BASE_URL` 바로 아래에 추가:
```
KIS_WS_URL=             # optional; empty = use hardcoded default per env
                        # 실전: ws://ops.koreainvestment.com:21000
                        # 모의: ws://ops.koreainvestment.com:31000
```

### 6. `docker-compose.yml` — pass-through

`app` 서비스와 `api` 서비스 모두에 추가:
```
KIS_WS_URL: "${KIS_WS_URL:-}"
```

### 7. `tests/services/ai_agents/test_settings.py` — 테스트 추가

`TestAppSettingsKisFields` 클래스에 2개 테스트 추가:
- `test_kis_ws_url_default` — 미설정 시 `""`
- `test_kis_ws_url_custom` — 설정 시 값 반영

### 8. `tests/brokers/test_kis_websocket.py` — URL override 테스트

`KISWebSocketClient` 테스트에 1개 추가:
- `test_connect_uses_override_url` — `ws_url` 설정 시 해당 URL 사용

## Override 우선순위

1. `KIS_WS_URL` env var (명시적 설정)
2. `KIS_WS_URLS[self._env]` (기존 하드코딩 매핑, `live`/`paper`)

## 변경 금지 확인

- ❌ WebSocket subscription budget / eviction policy 변경
- ❌ WS 41 strict enforcement 구현
- ❌ broker submit semantics 변경
- ❌ admin UI 변경
