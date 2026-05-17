# KIS Token Cache 후속 정리 — 최종 보고서

> **작성일**: 2026-05-17  
> **대상**: Korea Investment & Securities (KIS) OAuth Token Cache 정합성 정리  
> **관련 PR/작업**: Live Disclosure Cache의 `CachePurpose` 분리 및 정합성 검증

---

## 1. 개요

본 보고서는 Live 환경의 Disclosure Client가 공통 `KisTokenCache` 경로를 사용하면서 발생한 `CachePurpose` 정합성 문제를 진단하고, 이를 해결하기 위해 적용한 수정 사항을 종합 정리한다. 또한 현재 Cache Purpose 체계와 중앙 Auth Manager 필요성을 평가하고, 남은 후속 과제를 식별한다.

### 관련 파일

| 파일 | 역할 |
|------|------|
| [`token_cache.py`](src/agent_trading/brokers/koreainvestment/token_cache.py) | `CachePurpose` enum, `KisTokenCache` 캐시 저장/로드/검증 로직 |
| [`rest_client.py`](src/agent_trading/brokers/koreainvestment/rest_client.py) | `KISRestClient` dataclass — `cache_purpose` 파라미터 보유 |
| [`runtime/bootstrap.py`](src/agent_trading/runtime/bootstrap.py) | Live Disclosure Client 생성 시 `cache_purpose` 전달 |
| [`test_token_cache.py`](tests/brokers/koreainvestment/test_token_cache.py) | `TestDisclosurePurpose` 신규 테스트 2개 |

---

## 2. Live Disclosure Cache 정합성 점검

### 2.1 Disclosure Client의 Token Cache 경로

- Disclosure client는 `bootstrap.py`에서 `KISRestClient(env="live")`로 생성됨
- `KISRestClient.__post_init__()`에서 [`KisTokenCache`](src/agent_trading/brokers/koreainvestment/token_cache.py:184) 인스턴스를 생성
- 즉, **disclosure client도 공통 `KisTokenCache` 경로를 타며**, 다른 live client와 동일한 캐시 메커니즘 사용

### 2.2 발견된 문제

| 항목 | 내용 |
|------|------|
| **문제** | Live Disclosure Client가 `CachePurpose.PAPER_ACCESS_TOKEN`을 재사용하고 있었음 |
| **영향** | 의미상 부정확 (Paper용 purpose를 Live Disclosure에서 사용). 캐시 키 충돌 가능성은 낮지만(purpose 필드가 검증에 사용되므로), 명확성과 유지보수 측면에서 개선 필요 |
| **심각도** | 중간 (런타임 오류는 아니나, 로깅/디버깅 시 혼란 초래 가능) |

### 2.3 수정 사항

| 단계 | 변경 내용 | 파일:라인 |
|------|----------|-----------|
| 1 | `CachePurpose` enum에 `LIVE_DISCLOSURE_ACCESS_TOKEN` 추가 | [`token_cache.py:48`](src/agent_trading/brokers/koreainvestment/token_cache.py:48) |
| 2 | `KISRestClient` dataclass에 `cache_purpose` 필드 추가 (기본값 `PAPER_ACCESS_TOKEN`) | [`rest_client.py:254`](src/agent_trading/brokers/koreainvestment/rest_client.py:254) |
| 3 | `runtime/bootstrap.py`의 live disclosure client 생성 시 `cache_purpose=CachePurpose.LIVE_DISCLOSURE_ACCESS_TOKEN` 전달 | [`runtime/bootstrap.py:167-168`](src/agent_trading/runtime/bootstrap.py:167), [`runtime/bootstrap.py:228-229`](src/agent_trading/runtime/bootstrap.py:228) |
| 4 | 신규 purpose 검증 테스트 2개 추가 | [`test_token_cache.py:237`](tests/brokers/koreainvestment/test_token_cache.py:237) |

#### 2.3.1 하위호환성

- `rest_client.py:254`에서 `cache_purpose` 기본값을 `CachePurpose.PAPER_ACCESS_TOKEN`으로 설정
- 기존 `KISRestClient(env="paper")` 생성자는 아무런 변경 없이 동작
- 기존 캐시 파일 포맷에 `cache_purpose`가 없는 구버전 데이터는 빈 문자열로 처리되어 검증 시 skip

---

## 3. Cache Purpose 체계 평가

### 3.1 현재 `CachePurpose` Enum

[`token_cache.py:39`](src/agent_trading/brokers/koreainvestment/token_cache.py:39)

```python
class CachePurpose(str, Enum):
    PAPER_ACCESS_TOKEN = "paper_access_token"                  # KISRestClient (paper/dev)
    LIVE_HOLIDAY_OAUTH = "live_holiday_oauth"                  # KISHolidayClient
    LIVE_APPROVAL_KEY = "live_approval_key"                    # KisMarketStateClient
    LIVE_DISCLOSURE_ACCESS_TOKEN = "live_disclosure_access_token"  # 신규 추가
```

### 3.2 평가

| 기준 | 평가 |
|------|------|
| **커버리지** | 4개 purpose로 모든 KIS OAuth 캐시 경로(paper access token, holiday oauth, approval key, live disclosure access token) 명확히 식별 가능 |
| **중복** | 없음. 각 purpose가 unique client에 매핑됨 |
| **확장성** | 신규 client 추가 시 새로운 purpose를 enum에 추가하는 것으로 충분 |
| **판단** | ✅ **현재 체계로 충분. 추가 purpose 불필요.** |

---

## 4. 중앙 Auth Manager 필요성 평가

### 4.1 현재 클라이언트별 Auth 책임 분산 현황

| 책임 | `KISRestClient` | `KISHolidayClient` | `KisMarketStateClient` |
|------|:---:|:---:|:---:|
| OAuth HTTP 호출 (`/oauth2/tokenP`, `/oauth2/Approval`) | ✅ | ✅ | ✅ |
| In-memory token cache | ✅ | ✅ | ✅ |
| File cache (dev only) | ✅ | ❌ | ❌ |
| Token refresh 정책 (mem → file → HTTP) | ✅ | ✅ (mem → HTTP) | ✅ |
| 1 rps cooldown | ✅ | ❌ | N/A (1회 호출) |
| `save_expiry_buffer` | 300s | 60s | N/A |

### 4.2 평가

| 항목 | 판단 |
|------|------|
| **중앙화 필요성** | 현재 4개 클라이언트로 중앙화의 즉각적 이점이 크지 않음 |
| **도입 조건** | 클라이언트 수가 6~7개 이상으로 늘어나고, auth 로직 중복이 가시적인 유지보수 부담이 될 때 검토 |
| **위험 요소** | `KISHolidayClient`의 1 rps cooldown 부재는 KIS rate limit 정책 위반 가능성이 있음 → 별도 추적 필요 |

> **판단**: ❌ **현재는 중앙 Auth Manager 불필요. 후순위 과제.**

---

## 5. 적용한 수정 내용

| 파일 | 라인 | 변경 내용 | 영향 |
|------|------|----------|------|
| [`token_cache.py`](src/agent_trading/brokers/koreainvestment/token_cache.py) | 48 | `CachePurpose` enum에 `LIVE_DISCLOSURE_ACCESS_TOKEN` 추가 | 신규 purpose 사용 가능 |
| [`rest_client.py`](src/agent_trading/brokers/koreainvestment/rest_client.py) | 254 | `cache_purpose` dataclass 필드 추가 (기본값 `PAPER_ACCESS_TOKEN`) | 하위호환성 유지, 기존 client 무변경 |
| [`runtime/bootstrap.py`](src/agent_trading/runtime/bootstrap.py) | 167-168 | live disclosure client 생성 시 `cache_purpose=LIVE_DISCLOSURE_ACCESS_TOKEN` 전달 | live disclosure 전용 purpose 사용 |
| [`runtime/bootstrap.py`](src/agent_trading/runtime/bootstrap.py) | 228-229 | 두 번째 live disclosure client 생성 시 동일 purpose 전달 | 동일 |
| [`test_token_cache.py`](tests/brokers/koreainvestment/test_token_cache.py) | 237+ | `TestDisclosurePurpose` 클래스 — 2개 테스트 추가 | 정합성 검증 |

---

## 6. 테스트 결과

### 6.1 전체 결과

```
pytest tests/brokers/koreainvestment/ -v
→ 117 passed, 2 failed (2건 pre-existing, 리팩터링 무관)
```

### 6.2 모듈별 상세

| 테스트 모듈 | 통과 | 실패 | 비고 |
|------------|:---:|:---:|------|
| `test_token_cache.py` | 25 | 0 | 기존 23 + 신규 2 (`TestDisclosurePurpose`) |
| `test_disclosure_client.py` | 7 | 0 | 영향 없음 |
| `test_holiday_client.py` | 29 | 0 | 영향 없음 |
| `test_rest_client_submit.py` | 44 | 0 | 영향 없음 |
| `test_market_state_client.py` | - | 2 | **Pre-existing**: URL 누락 버그, 리팩터링 무관 |

### 6.3 신규 테스트 (`TestDisclosurePurpose`)

[`test_token_cache.py:237`](tests/brokers/koreainvestment/test_token_cache.py:237)

| 테스트 | 검증 내용 |
|--------|----------|
| `test_live_disclosure_purpose_is_distinct` | `LIVE_DISCLOSURE_ACCESS_TOKEN`이 다른 purpose와 구분되는지 검증 |
| `test_live_disclosure_purpose_roundtrip` | 해당 purpose로 저장/로드 시 정상 동작 확인 |

---

## 7. 남은 후속 과제

### 7.1 KISHolidayClient 1 rps cooldown 추가

| 항목 | 내용 |
|------|------|
| **문제** | [`KISHolidayClient._ensure_token()`](src/agent_trading/brokers/koreainvestment/holiday_client.py:134)에 1 rps cooldown 로직 없음 |
| **위험** | KIS rate limit (1 rps) 정책 위반 가능성 |
| **해결 방안** | `_last_auth_call_time` 인스턴스 변수 추가 → `_ensure_token()` 내에서 `time.monotonic()` 기반 cooldown 체크 |
| **참고** | `KISRestClient._ensure_token()`에는 이미 구현되어 있음 |

### 7.2 `save_expiry_buffer` 통일 검토

| 클라이언트 | `save_expiry_buffer` | 비고 |
|-----------|:---:|------|
| `KISRestClient` | 300s | paper/live 공통 |
| `KISHolidayClient` | 60s | 더 짧은 buffer 사용 |
| `KisMarketStateClient` | N/A | approval key는 만료 개념 상이 |

**검토 필요**: 60s vs 300s 차이가 의도된 설계인지 (holiday API의 토큰 수명이 더 긴 경우 등) 확인 필요.

### 7.3 중앙 Auth Manager

| 조건 | 내용 |
|------|------|
| **현재** | 불필요 |
| **재검토 조건** | KIS OAuth client가 6~7개 이상으로 증가할 때 |
| **고려 사항** | 공통 auth 로직(HTTP 호출, refresh 정책, cooldown, in-memory cache)을 추상화할 인터페이스 설계 |

---

## 부록: Docker/Health 검증

Docker 재빌드/재기동 및 `/health` 확인 절차는 **이번 수정 범위에 포함되지 않음**.

- 이번 수정은 config/import 레벨의 변경 (`CachePurpose` enum 추가, dataclass 필드 추가, 파라미터 전달)
- Runtime 동작에 영향을 주지 않으므로 별도 배포 검증 불필요
- 단, 후속 작업(KISHolidayClient cooldown 등) 시 통합 검증 권장

---

*End of Report*
