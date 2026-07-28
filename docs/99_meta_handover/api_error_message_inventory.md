# Inspection API 오류 메시지 Inventory

## 문서 목적

이 문서는 `src/agent_trading/api/`의 `HTTPException` 사용 현황을 정적 분석해, AI 친화적 오류 메시지 보강의 다음 구현 범위를 정하기 위한 inventory다.

현재 범위는 문서화다. API 응답 형식, Admin UI 동작, 테스트 코드는 변경하지 않는다.

## 측정 기준

- 측정 대상: `src/agent_trading/api/**/*.py`
- 측정 방식: Python AST 기반 `HTTPException(...)` 호출 탐색
- 측정 시점: 2026-07-28
- 제외 범위: `src/agent_trading/services/`, `scripts/`, `tests/`

## 전체 지표

| 항목 | 카운트 |
|------|--------|
| API Python 파일 수 | 30 |
| `HTTPException` 호출 수 | 98 |
| `HTTPException`이 있는 파일 수 | 21 |
| 문자열 또는 f-string `detail` 수 | 93 |
| 구조화된 dict `detail` 수 | 0 |

현재 API 오류 응답은 대부분 사람이 읽는 문자열 중심이다. 따라서 `error_code`, `field`, `expected`, `actual`, `next_action` 같은 구조화 필드를 바로 파싱할 수 없다.

## 상태 코드 분포

| 상태 코드 | 카운트 |
|-----------|--------|
| 400 | 59 |
| 404 | 22 |
| 409 | 1 |
| 422 | 5 |
| 500 | 2 |
| 503 | 3 |
| `HTTP_401_UNAUTHORIZED` | 4 |
| `HTTP_403_FORBIDDEN` | 2 |

가장 큰 묶음은 400 입력 검증 오류다. 1차 구현은 입력 검증 오류의 `error_code` 표준화부터 시작하는 것이 효율적이다.

## `detail` 형태 분포

| 형태 | 카운트 |
|------|--------|
| `Constant` | 63 |
| `JoinedStr` | 30 |
| `Call` | 5 |
| `Dict` | 0 |

`Call` 형태는 주로 `str(exc)` 계열 예외 전달로 추정된다. 이 경로는 내부 예외 메시지가 외부 API 응답으로 그대로 나갈 수 있으므로, 구조화 전환 시 우선 검토 대상이다.

## 의미 분류

| 분류 | 카운트 |
|------|--------|
| 입력 검증 | 42 |
| 동적 문자열 | 30 |
| not found | 8 |
| dependency/config | 5 |
| 예외 passthrough | 5 |
| 기타 | 8 |

동적 문자열은 실제 값이 포함될 수 있으므로 비밀값 노출 위험이 있는지 함께 검토해야 한다. 특히 `received` 필드를 도입할 때는 원문 값 대신 안전한 식별자 또는 redacted 표현을 사용한다.

## 파일별 상위 분포

| 파일 | `HTTPException` 수 | 우선순위 |
|------|--------------------|----------|
| `src/agent_trading/api/routes/performance.py` | 31 | P1 |
| `src/agent_trading/api/routes/orders.py` | 15 | P1 |
| `src/agent_trading/api/routes/clients.py` | 6 | P2 |
| `src/agent_trading/api/security.py` | 6 | P2 |
| `src/agent_trading/api/routes/realtime_quotes.py` | 5 | P2 |
| `src/agent_trading/api/routes/reconciliation.py` | 4 | P3 |
| `src/agent_trading/api/routes/accounts.py` | 3 | P3 |
| `src/agent_trading/api/routes/decisions.py` | 3 | P3 |
| `src/agent_trading/api/routes/execution_attempts.py` | 3 | P3 |
| `src/agent_trading/api/routes/fill_history.py` | 3 | P3 |

`performance.py`와 `orders.py`가 전체 98건 중 46건을 차지한다. 따라서 첫 코드 변경은 이 두 파일이 아니라 공통 스키마와 테스트 기준을 먼저 만든 뒤, 이 파일들에 점진 적용하는 것이 안전하다.

## 반복 메시지 상위 목록

| 메시지 | 카운트 | 후보 `error_code` |
|--------|--------|-------------------|
| `Invalid account_id UUID` | 13 | `invalid_account_id` |
| `Invalid strategy_id UUID` | 6 | `invalid_strategy_id` |
| `start_date must be on or before end_date` | 5 | `invalid_date_range` |
| `Invalid start_date (use YYYY-MM-DD)` | 5 | `invalid_start_date` |
| `Invalid end_date (use YYYY-MM-DD)` | 5 | `invalid_end_date` |
| `Instrument not found` | 3 | `instrument_not_found` |
| `Invalid client_id UUID` | 2 | `invalid_client_id` |

반복 메시지는 공통 helper 또는 공통 오류 factory로 묶을 수 있다. 다만 Admin UI와 기존 API 테스트가 문자열 `detail`을 직접 기대할 수 있으므로, 변경 전 테스트 영향 범위를 먼저 확인한다.

## 1차 구현 후보

### P1: 공통 오류 응답 스키마 후보 작성

코드 변경 전 테스트 기준을 먼저 정한다.

권장 필드:

- `error_code`
- `message`
- `field`
- `expected`
- `received`
- `request_path`
- `next_action`

호환성 기본안:

- 기존 endpoint는 당장 문자열 `detail`을 유지한다.
- 신규 helper 테스트에서 구조화 객체 형태를 먼저 검증한다.
- endpoint 전환은 파일 단위가 아니라 오류 유형 단위로 적용한다.

### P2: 입력 검증 오류부터 전환

반복 수가 많은 UUID와 날짜 검증 오류를 우선한다.

대상 후보:

- `invalid_account_id`
- `invalid_strategy_id`
- `invalid_client_id`
- `invalid_start_date`
- `invalid_end_date`
- `invalid_date_range`

이 경로는 외부 시스템이나 DB 연결 없이 단위 테스트로 검증할 수 있어 부하가 낮다.

### P3: `str(exc)` passthrough 차단

`detail=str(exc)` 또는 `detail`에 예외 문자열을 그대로 전달하는 경로는 별도 분류가 필요하다.

권장 정책:

- 내부 예외 원문은 로그에만 남긴다.
- API 응답에는 안정 `error_code`와 사용자 조치만 반환한다.
- 비밀값 가능성이 있는 값은 `received`에 넣지 않는다.

### P4: 운영 로그 보강

API 응답 구조화 이후 `order_manager`, `order_sync_service`, `reconciliation_worker`의 운영 로그에 `event`, `error_code`, 주요 ID를 점진 추가한다.

이 단계는 런타임 의미론에 더 가까우므로 API 입력 검증보다 뒤에 둔다.

## 1차 helper 구현 기준

2026-07-28에 endpoint 응답을 바꾸지 않고 다음 파일을 추가했다.

- `src/agent_trading/api/errors.py`
- `tests/api/test_errors.py`

고정한 계약:

- `error_code`는 소문자 `snake_case`만 허용한다.
- `message`는 기존 문자열 detail과 대응되는 사람이 읽는 설명이다.
- `field`, `expected`, `received`, `request_path`, `next_action`은 선택 필드다.
- `authorization`, `token`, `secret`, `password`, `api_key`, KIS 계좌 원문 가능 필드는 `received=present-redacted`로 마스킹한다.
- UUID와 날짜 입력 검증용 helper를 먼저 제공한다.
- `build_http_exception()`의 기본값은 기존 호환성을 위해 문자열 `detail`을 유지한다.
- 구조화된 dict `detail`은 `structured_detail=True`를 명시한 신규 또는 전환 endpoint에서만 opt-in으로 사용한다.

기존 endpoint 전환은 helper 기본 모드로만 수행한다. 따라서 전환한 endpoint에서도 API 응답의 `detail` 타입은 문자열로 유지한다.

## 1차 endpoint 전환

2026-07-28에 `src/agent_trading/api/routes/performance.py`의 `/performance-benchmark` 입력 검증 오류 6건, `/performance-benchmark-history` 입력 검증 오류 6건, `/performance-metrics` 입력 검증 오류 5건, `/performance-history` 입력 검증 오류 5건, `/performance-trigger-attribution` 입력 검증 오류 1건, `/performance-holding-profile-attribution` 입력 검증 오류 1건, `/performance-summary` 입력 검증 오류 2건, `/paper-go-no-go` 입력 검증 오류 5건을 `build_http_exception()` 기본 모드로 전환했다.

`/performance-benchmark` 입력 검증 오류 6건은 전환 과정에서 `request_path` 메타데이터가 `/performance-benchmark-history`로 기록되어 있었다. 이를 `/performance-benchmark`로 정정하고 helper 호출 메타데이터 테스트를 추가했다.

전환한 오류:

- `invalid_account_id`
- `invalid_start_date`
- `invalid_end_date`
- `invalid_date_range`
- `invalid_benchmark_code`
- `invalid_strategy_id`

`structured_detail=True`를 사용하지 않았으므로 기존 API 응답의 `detail` 타입은 문자열로 유지된다. 이 구간의 validation 테스트는 문자열 `detail` assertion을 유지한다.

## 2차 endpoint 전환

2026-07-28에 `src/agent_trading/api/routes/orders.py`의 `GET /orders/{order_request_id}` 입력 검증 오류 1건, `GET /orders/{order_request_id}/events` 입력 검증 오류 1건, `GET /orders/{order_request_id}/broker-orders` 입력 검증 오류 1건, `PUT /orders/{order_request_id}/status` 입력 검증 오류 1건, `GET /orders/{order_request_id}/broker-truth` 입력 검증 오류 1건을 `build_http_exception()` 기본 모드로 전환했다.

전환한 오류:

- `invalid_order_request_id`

`structured_detail=True`를 사용하지 않았으므로 기존 API 응답의 `detail` 타입은 문자열로 유지된다. `Order not found` 같은 404 의미론은 이번 범위에서 변경하지 않았다.

## 3차 endpoint 전환

2026-07-28에 `src/agent_trading/api/routes/clients.py`의 `GET /clients/{client_id}` 입력 검증 오류 1건을 `build_http_exception()` 기본 모드로 전환했다.

전환한 오류:

- `invalid_client_id`

`structured_detail=True`를 사용하지 않았으므로 기존 API 응답의 `detail` 타입은 문자열로 유지된다. `/clients/default`의 설정·해결 실패 404 의미론은 이번 범위에서 변경하지 않았다.

## 4차 endpoint 전환

2026-07-28에 `src/agent_trading/api/routes/realtime_quotes.py`의 `GET /realtime-quotes/snapshot` 단순 query validation 오류 1건을 `build_http_exception()` 기본 모드로 전환했다.

전환한 오류:

- `empty_symbols_query`

`structured_detail=True`를 사용하지 않았으므로 기존 API 응답의 `detail` 타입은 문자열로 유지된다. `InvalidSymbolError`, `SubscriptionLimitExceededError`, stream 예외처럼 서비스 예외 원문을 전달하는 경로는 이번 범위에서 변경하지 않았다.

## 다음 추천 작업

`performance.py`의 반복 입력 검증 오류는 1차 범위에서 모두 helper 기본 모드로 전환했다. `orders.py`의 반복 path UUID 입력 검증 오류도 2차 범위에서 모두 helper 기본 모드로 전환했다. `clients.py`의 UUID 입력 검증 오류도 3차 범위에서 helper 기본 모드로 전환했다. `realtime_quotes.py`의 단순 query validation도 4차 범위에서 helper 기본 모드로 전환했다. 다음 작업은 `str(exc)` passthrough 차단 정책을 별도 범위로 잡을지 판단하는 것이다.

권장 이유:

1. 남은 `realtime_quotes.py` 오류는 서비스 예외 원문을 API 응답으로 넘기는 경로라 단순 입력 검증보다 정책 영향이 크다.
2. `security.py` 오류는 인증/인가 계약과 직접 연결되므로 일반 validation helper와 같은 기준으로 일괄 전환하면 안 된다.
3. 기본 모드는 문자열 `detail`을 반환하므로 기존 테스트 기대값을 유지하면서 helper 사용을 시작할 수 있다.

## 비목표

- 이번 inventory 문서에서 API 응답 형식을 변경하지 않는다.
- 전체 route를 한 번에 바꾸지 않는다.
- Admin UI 동작을 변경하지 않는다.
- 전체 테스트를 요구하지 않는다.
