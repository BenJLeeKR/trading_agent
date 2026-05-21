# Post-Submit Sync `get_fills` Datetime Type Error Fix — 2026-05-19

## 1. 문제 요약
`post-submit-sync` 실행 중 `get_fills failed: 'datetime.datetime' object is not subscriptable` TypeError 발생.

**에러 위치**: [`rest_client.py:1129`](src/agent_trading/brokers/koreainvestment/rest_client.py:1129) — `from_ts[:10]`

## 2. Root Cause
호출 체인 전체에서 `from_ts` 파라미터가 `str`로 타입 힌트되어 있었지만, caller가 `datetime` 객체를 전달:

```
order_sync_service.py:_sync_fills() [L404]
  → from_ts=since or broker_order.created_at  ← datetime 객체!
  → adapter.py:get_fills(from_ts=datetime)    ← str로 선언
  → rest_client.py:get_fills(from_ts=datetime) ← str로 선언
  → L1129: from_ts[:10]  ← TypeError! datetime object is not subscriptable
```

## 3. 수정 내용 (4개 파일)

### 3.1 [`order_sync_service.py`](src/agent_trading/services/order_sync_service.py:404) — Caller
`since or broker_order.created_at` (`datetime` 객체)를 `strftime("%Y%m%d")`로 변환 후 전달:
```python
from_ts: str | None = None
if since is not None:
    from_ts = since.strftime("%Y%m%d")
elif broker_order.created_at is not None:
    from_ts = broker_order.created_at.strftime("%Y%m%d")
```

### 3.2 [`rest_client.py`](src/agent_trading/brokers/koreainvestment/rest_client.py:1127) — Receiver
`from_ts[:10]` subscript 전 `isinstance(from_ts, datetime)` 방어 검사 추가:
```python
if from_ts is not None:
    if isinstance(from_ts, datetime):
        _strt_dt = from_ts.strftime("%Y%m%d")
    else:
        _strt_dt = from_ts[:10].replace("-", "")
```

### 3.3 [`adapter.py`](src/agent_trading/brokers/koreainvestment/adapter.py:395) — Adapter 계층
Type hint를 `str | datetime | None`으로 확장 + body에서 isinstance 변환 로직 추가

### 3.4 [`base.py`](src/agent_trading/brokers/base.py:189) — Protocol
`get_fills()`의 `from_ts` type hint를 `str | datetime | None`으로 명확화

## 4. 테스트 결과
| 테스트 스위트 | 결과 |
|--------------|------|
| KIS broker 테스트 | **120/120 ✅** |
| Service 테스트 (sizing_engine + decision_orchestrator) | **91/91 ✅** |

## 5. 배포 결과
| 단계 | 상태 |
|------|------|
| `docker compose build --no-cache app api ops-scheduler` | ✅ Build 성공 |
| `docker compose up -d --force-recreate app api ops-scheduler` | ✅ 3개 컨테이너 재생성 |
| Health check (`GET /health`) | ✅ HTTP 200 — `status: "ok"`, `database: "connected"`, `scheduler.healthy: true` |
| Container 상태 | ✅ `api`, `app`, `ops-scheduler` 모두 `Up` + `healthy` |

## 6. 파일 변경 요약
| 파일 | 변경 유형 | 설명 |
|------|----------|------|
| `src/agent_trading/services/order_sync_service.py` | 수정 | caller `datetime→str` 변환 |
| `src/agent_trading/brokers/koreainvestment/rest_client.py` | 수정 | receiver `isinstance` 방어 처리 |
| `src/agent_trading/brokers/koreainvestment/adapter.py` | 수정 | adapter type hint + 변환 로직 |
| `src/agent_trading/brokers/base.py` | 수정 | protocol type hint 명확화 |
