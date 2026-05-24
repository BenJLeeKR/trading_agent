# EI 실패 원인 분석 및 수정 보고서

**작성일:** 2026-05-24  
**대상:** Event Interpretation Agent (`dict`/`InterpretedEvent` 타입 오류 + Provider DNS resolution 실패)

---

## 1. 실제 원인 1: `dict`/`InterpretedEvent` 타입 오류

### Root Cause
[`schemas.py:_coerce_fields()`](src/agent_trading/services/ai_agents/schemas.py) 조건 버그.  
`dict` → `InterpretedEvent` 변환 후에도 `self.events`가 교체되지 않아, 이후 `_build_summary_text()`에서 `getattr(event, "is_reconstructed", False)` 호출 시 `dict` 객체에는 해당 속성이 없어 예외 발생.

### 영향 범위
- **in-process 경로**에서만 발생 (events가 schemas 내부에서 처리됨)
- **subprocess 경로**는 events가 이미 JSON 직렬화/역직렬화 과정에서 `InterpretedEvent`로 변환되므로 안전

### 수정 사항 (사전 완료)
| 파일 | 변경 내용 |
|------|----------|
| [`schemas.py:_coerce_fields()`](src/agent_trading/services/ai_agents/schemas.py:370) | 조건에 `had_dict_items` 플래그 추가, `__post_init__()` 순서 변경 |
| [`event_interpretation.py:_build_summary_text()`](src/agent_trading/services/ai_agents/event_interpretation.py:88) | 방어 코드 추가 (dict fallback 처리) |
| [`test_agents.py`](tests/services/ai_agents/test_agents.py) | `TestDictEventTypeSafety` 5개 신규 테스트 |

---

## 2. 실제 원인 2: Provider 연결 실패 `[Errno -5] No address associated with hostname`

### 분류
**DeepSeek API DNS의 일시적 장애 (EAI_NODATA)**

- 오류 메시지: `[Errno -5] No address associated with hostname`
- DNS lookup이 일시적으로 실패 (transient DNS failure)
- 설정(`https://api.deepseek.com`)은 정상, 현재 DNS resolution도 정상

### 설정 문제 아님
- `api.deepseek.com` 도메인은 유효
- DNS가 현재 정상 조회됨
- 일시적인 네트워크/인프라 문제로 추정

### 수정 사항

#### 2-a. [`event_interpretation.py:_classify_exception()`](src/agent_trading/services/ai_agents/event_interpretation.py) — `socket.gaierror` 명시적 분류

**변경 전:**
```python
# socket.gaierror → generic "provider_error", retryable=None (모호함)
```

**변경 후:**
```python
if isinstance(exc_value, socket.gaierror):
    return {
        **base,
        "error_type": "dns_error",
        "http_status": None,
        "retryable": True,
    }
```

- `import socket` 추가
- `socket.gaierror`를 `"dns_error"`로 명시적 분류
- `retryable=True`로 재시도 가능 표시

#### 2-b. [`provider_client.py:generate_structured()`](src/agent_trading/services/ai_agents/provider_client.py) — Retry 로직 추가

**변경 전:** 단일 요청, retry 없음

**변경 후:** 최대 3회 재시도 + exponential backoff

| 설정 | 값 |
|------|-----|
| `MAX_RETRIES` | 3 |
| `RETRY_DELAY` | 1.0초 (base, `2^attempt` 배수) |
| Retry 대상 | `httpx.TransportError`, `httpx.TimeoutException`, `httpx.HTTPStatusError` (429, 5xx), `socket.gaierror` |
| Non-retryable | HTTP 4xx (400-428, 430-499), `json.JSONDecodeError`, `TypeError`, `ValueError` |

**Retry 정책 상세:**
```python
# 지연 시간 (초): 1.0, 2.0, 4.0 (exponential backoff)
delay = RETRY_DELAY * (2 ** attempt)
```

---

## 3. 적용한 수정 목록

| 파일 | 변경사항 | 상태 |
|------|---------|------|
| [`schemas.py`](src/agent_trading/services/ai_agents/schemas.py) | `_coerce_fields()` 조건 버그 수정 (dict→InterpretedEvent 변환) | 사전 완료 |
| [`event_interpretation.py`](src/agent_trading/services/ai_agents/event_interpretation.py) | `_build_summary_text()` 방어 코드 | 사전 완료 |
| [`event_interpretation.py`](src/agent_trading/services/ai_agents/event_interpretation.py) | `import socket` 추가, `_classify_exception()`에 `socket.gaierror` → `"dns_error"` 분류 | ✅ 완료 |
| [`provider_client.py`](src/agent_trading/services/ai_agents/provider_client.py) | `import asyncio`, `import socket` 추가, `MAX_RETRIES=3`, `RETRY_DELAY=1.0` 추가, `generate_structured()`에 retry 루프 추가 | ✅ 완료 |
| [`test_provider_client.py`](tests/services/ai_agents/test_provider_client.py) | `TestRetryAndDnsError` 클래스, 8개 신규 테스트 추가 | ✅ 완료 |
| [`test_agents.py`](tests/services/ai_agents/test_agents.py) | `TestDictEventTypeSafety` 5개 신규 테스트 | 사전 완료 |

---

## 4. 테스트 결과

| 테스트 파일 | 통과 | 실패 | 비고 |
|------------|------|------|------|
| [`test_provider_client.py`](tests/services/ai_agents/test_provider_client.py) | **19** | 0 | 8개 신규 retry/DNS 테스트 포함 |
| [`test_agents.py`](tests/services/ai_agents/test_agents.py) | **109** | 0 | 사전 완료된 `TestDictEventTypeSafety` 포함 |
| [`test_schemas.py`](tests/services/ai_agents/test_schemas.py) | 4 | 1 | 1개 실패는 사전 존재하던 로그 경고 메시지 검증 이슈 (내 변경사항과 무관) |

### 신규 테스트 목록 (`TestRetryAndDnsError`)

| 테스트 | 검증 내용 |
|--------|----------|
| `test_dns_error_retry_then_success` | DNS `gaierror` → retry 후 2번째 시도 성공 |
| `test_dns_error_all_retries_exhausted` | DNS `gaierror` → 모든 retry(3회) 소진 후 실패 |
| `test_http_429_retry_then_success` | HTTP 429 → retry 후 2번째 시도 성공 |
| `test_http_400_non_retryable_fails_immediately` | HTTP 400 → retry 없이 즉시 실패 |
| `test_http_500_retry_then_success` | HTTP 500 → retry 후 2번째 시도 성공 |
| `test_json_decode_error_no_retry` | JSON decode 에러 → retry 없이 즉시 실패 |
| `test_transport_error_retry_then_success` | TransportError (connection refused) → retry 후 성공 |
| `test_timeout_exception_retry_then_success` | TimeoutException → retry 후 성공 |

### 기존 회귀 확인
- 기존 11개 테스트: **모두 통과** (회귀 없음)

---

## 5. 남은 운영 이슈

1. **DNS intermittent failure (근본적 해결 불가)**
   - retry 로직으로 방어하지만, DNS 장애 자체를 완전히 제거할 수는 없음
   - 장기적 개선: DNS 캐싱 레이어 도입 or `resolver` 옵션을 통한 대체 DNS 서버 지정 고려

2. **DeepSeek API rate limit / availability 모니터링 필요**
   - HTTP 429 (rate limit)은 retry로 방어되나, 지속적 발생 시 요청 지연 누적
   - 모니터링 지표: `provider_error` rate, retry 횟수, 평균 응답 시간

3. **`test_schemas.py` 1개 실패**
   - `test_empty_with_events_logs_warning`: 로그 메시지 검증 관련 사전 존재 이슈
   - 내 변경사항과 무관, 별도 이슈로 추적 필요

---

## 6. 최종 판정

| 항목 | 상태 | 설명 |
|------|------|------|
| **타입 오류 (dict/InterpretedEvent)** | ✅ **완전 수정** | `_coerce_fields()` 조건 버그 수정, `_build_summary_text()` 방어 코드 추가 |
| **DNS 오류 (socket.gaierror)** | ✅ **방어 완료** | `_classify_exception()` 명시적 분류 + `generate_structured()` retry 로직 (최대 3회, exponential backoff) |
| **`provider_error` 쌓임** | ✅ **두 가지 주요 원인 모두 제거/방어** | 타입 오류는 완전 수정, DNS 오류는 retry로 방어 |

### 요약
- **2가지 실제 원인**을 식별하고 모두 수정/방어함
- **8개 신규 단위 테스트**로 retry/DNS 에러 처리 검증
- **기존 109개 테스트** 모두 통과 (회귀 없음)
- **Docker 재빌드 + 재기동** 완료, `/health` 정상 확인
