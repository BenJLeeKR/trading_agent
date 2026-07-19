# KisMarketStateClient `_is_paper` 판정 로직 수정 보고서

**Date**: 2026-05-17 (KST)
**Scope**: [`KisMarketStateClient`](../src/agent_trading/brokers/koreainvestment/market_state_client.py:201) — `_is_paper` 플래그 결정 로직의 버그 수정
**변경 파일**: 1개 (`market_state_client.py`), 4줄 로직 변경

---

## 1. 개요

### 1.1 문제점

[`KisMarketStateClient`](../src/agent_trading/brokers/koreainvestment/market_state_client.py:201)는 163 국내주식 장운영정보 WebSocket adapter로, paper/mock/sandbox 환경에서는 WebSocket 연결을 건너뛰고 `is_connected()`가 항상 `False`를 반환해야 한다.

그러나 `_is_paper` 판정 로직이 `app_key`/`api_secret` 존재 여부만으로 결정되어, 테스트 환경에서 dummy credential이 제공되면 `_is_paper = False`로 잘못 설정되었다. 이로 인해 `connect()`가 실제 WebSocket/HTTP 연결을 시도했고, 2개 테스트가 `httpx.UnsupportedProtocol` 예외로 실패했다.

### 1.2 원인

`_is_paper` 결정 시 [`settings.kis_env`](../src/agent_trading/config/settings.py:322) 값을 전혀 고려하지 않음.

### 1.3 수정 범위

`settings.kis_env` 값 (`"paper"`, `"mock"`, `"sandbox"`, `"live"`)을 `_is_paper` 판정에 통합하여, 환경 문자열 기반으로도 paper 여부를 결정하도록 수정.

---

## 2. Root Cause 상세 분석

### 2.1 `_is_paper`가 `settings.kis_env`를 무시하는 구조

**수정 전 로직** ([`market_state_client.py:271-275`](../src/agent_trading/brokers/koreainvestment/market_state_client.py:271)):

```python
# If credentials are provided, we attempt connection regardless of env.
if not app_key or not api_secret:
    self._is_paper = True
else:
    self._is_paper = False
```

이 로직의 문제점:

| 조건 | app_key | api_secret | `_is_paper` | 의도 |
|------|---------|------------|-------------|------|
| paper env + dummy cred | `"paper-key"` (truthy) | `"paper-secret"` (truthy) | **False** ❌ | True여야 함 |
| live env + real cred | `"live-key"` (truthy) | `"live-secret"` (truthy) | False ✅ | False가 맞음 |
| cred 없음 | `""` (falsy) | `""` (falsy) | True ✅ | True가 맞음 |

**핵심**: 테스트 fixture [`mock_settings_paper`](../tests/brokers/koreainvestment/test_market_state_client.py:26)는 `kis_env = "paper"`로 설정되어 있지만, 동시에 `app_key = "paper-key"`, `api_secret = "paper-secret"`도 제공한다. 구 로직은 credential 존재 여부만 봤기 때문에 `_is_paper = False`가 되었다.

### 2.2 `connect()` 호출 체인이 `UnsupportedProtocol`에 도달하는 경로

`_is_paper = False`일 때 [`connect()`](../src/agent_trading/brokers/koreainvestment/market_state_client.py:287)의 실행 경로:

```
connect()
  └─ _is_paper=False → early return bypass
  └─ _ensure_approval_key()
       └─ _get_http_client()
            └─ httpx.AsyncClient(base_url="")  ← _base_ws_url이 비어있음
       └─ client.post("/oauth2/Approval", ...)  ← base_url=""이므로 URL scheme 없음
            └─ httpx.UnsupportedProtocol ⚡
```

[`_get_http_client()`](../src/agent_trading/brokers/koreainvestment/market_state_client.py:419)는 `base_url=self._base_ws_url.replace("ws://", "http://")`를 사용한다. paper 환경에서는 `_base_ws_url`이 기본값 `""`이므로 `base_url=""`이 된다. httpx가 빈 base_url에서 `/oauth2/Approval` 같은 상대 경로를 해석할 수 없어 `UnsupportedProtocol`이 발생한다.

### 2.3 테스트 fixture와 실제 코드 간 기대치 불일치

테스트 fixture [`paper_client`](../tests/brokers/koreainvestment/test_market_state_client.py:54)는 paper 환경을 의도했지만, 구 `_is_paper` 로직은 이를 인식하지 못했다:

| 항목 | fixture 값 | 구 로직 해석 | 기대 |
|------|-----------|-------------|------|
| `settings.kis_env` | `"paper"` | 무시됨 | `_is_paper=True` |
| `app_key` | `"paper-key"` | truthy → `_is_paper=False` | 상관없어야 함 |
| `api_secret` | `"paper-secret"` | truthy → `_is_paper=False` | 상관없어야 함 |

테스트 [`test_paper_env_skips_connect`](../tests/brokers/koreainvestment/test_market_state_client.py:117)는 `await paper_client.connect()` 후 `is_connected is False`를 assert하지만, 실제로는 `connect()`가 실행되어 예외가 발생했다.

---

## 3. 수정 상세

### 3.1 변경된 로직

**수정 후** ([`market_state_client.py:271-274`](../src/agent_trading/brokers/koreainvestment/market_state_client.py:271)):

```python
self._is_paper = (
    not app_key or not api_secret
    or getattr(settings, "kis_env", "paper") in ("paper", "mock", "sandbox")
)
```

변경 사항:
1. 기존 `not app_key or not api_secret` 조건 유지 (credential 미존재 시 paper)
2. **추가**: `getattr(settings, "kis_env", "paper") in ("paper", "mock", "sandbox")` — 환경 문자열 기반 판정

### 3.2 환경별 동작 비교표

| 환경 | app_key | api_secret | `settings.kis_env` | 수정 전 `_is_paper` | 수정 후 `_is_paper` | 동작 |
|------|---------|------------|-------------------|---------------------|---------------------|------|
| **paper** (테스트) | `"paper-key"` | `"paper-secret"` | `"paper"` | **False** ❌ | **True** ✅ | `connect()` skip |
| **mock** | `"dummy-key"` | `"dummy-secret"` | `"mock"` | **False** ❌ | **True** ✅ | `connect()` skip |
| **sandbox** | `"dummy-key"` | `"dummy-secret"` | `"sandbox"` | **False** ❌ | **True** ✅ | `connect()` skip |
| **live** (테스트) | `"live-key"` | `"live-secret"` | `"live"` | False ✅ | False ✅ | `connect()` 정상 진행 |
| **cred 없음** | `""` | `""` | `"paper"` (default) | True ✅ | True ✅ | `connect()` skip |
| **live + cred 없음** | `""` | `""` | `"live"` | True ✅ | True ✅ | `connect()` skip (cred 부재) |

> `"live"` 환경은 tuple에 포함되지 않으므로 `_is_paper` 판정에 영향을 주지 않음. `"live"`에서도 credential이 없으면 여전히 `_is_paper = True`.

### 3.3 `getattr(settings, "kis_env", "paper")`의 의미

[`AppSettings.kis_env`](../src/agent_trading/config/settings.py:322)는 [`_resolve_kis_env()`](../src/agent_trading/config/settings.py:120)에 의해 기본값 `"paper"`를 가진다. `getattr` fallback은 테스트에서 `MagicMock`이 `kis_env` attribute를 갖지 않을 경우를 대비한 안전장치.

---

## 4. 검증 결과

### 4.1 `test_market_state_client.py` (35개)

| 상태 | 개수 |
|------|------|
| ✅ PASS (수정 전) | 33개 |
| ✅ PASS (수정 후, 기존 실패 2건 포함) | **35/35** |

### 4.2 기존 실패 2건

| 테스트 | 실패 원인 | 수정 후 |
|--------|----------|---------|
| [`test_paper_env_skips_connect`](../tests/brokers/koreainvestment/test_market_state_client.py:117) | `_is_paper=False`로 `connect()`가 early return하지 않고 `httpx.UnsupportedProtocol` 발생 | `_is_paper=True` → `connect()` 정상 skip ✅ |
| [`test_paper_env_mock_env_also_skips`](../tests/brokers/koreainvestment/test_market_state_client.py:125) | mock/sandbox env에서 동일한 원인으로 실패 | 3 env 모두 `_is_paper=True` → 정상 skip ✅ |

### 4.3 전체 KIS 브로커 테스트 (119개)

| 범위 | 결과 |
|------|------|
| `tests/brokers/koreainvestment/` 전체 | **119/119 PASS** ✅ (회귀 없음) |

---

## 5. 영향도 분석

### 5.1 Production code에서 `KisMarketStateClient` 생성 현황

`KisMarketStateClient`는 **production code에서 직접 생성되지 않음** (테스트 전용).

검증: [`src/`](./src/) 디렉토리 전체에서 `KisMarketStateClient(` 생성 호출 패턴 검색 결과 **0건**.

### 5.2 참조 패턴

| 파일 | 참조 방식 |
|------|----------|
| [`KisMarketStateClient`](../src/agent_trading/brokers/koreainvestment/market_state_client.py:201) | 클래스 정의 (`MarketStateProvider` 상속) |
| [`tests/brokers/koreainvestment/test_market_state_client.py`](../tests/brokers/koreainvestment/test_market_state_client.py) | 테스트에서 직접 생성 |
| [`tests/services/test_market_session.py`](../tests/services/test_market_session.py) | `MarketPhaseCode` enum만 import (간접 참조) |
| [`tests/scripts/test_run_near_real_ops_scheduler.py`](../tests/scripts/test_run_near_real_ops_scheduler.py) | `MarketPhaseCode` enum만 import (간접 참조) |

### 5.3 안전성 결론

수정은 **단일 클래스의 4줄 로직만 변경**하며, production code에서 이 클래스가 사용되지 않으므로 **배포 영향도 zero**에 해당한다. 모든 119개 테스트가 통과하여 회귀가 없음을 확인했다.

---

## 6. 변경 파일 목록

| 파일 | 변경 유형 | 설명 |
|------|----------|------|
| [`src/agent_trading/brokers/koreainvestment/market_state_client.py:271-274`](../src/agent_trading/brokers/koreainvestment/market_state_client.py:271) | 수정 | `_is_paper` 판정 로직 4줄 변경 |
| (기타 파일) | 변경 없음 | — |

---

## 7. 결론

### 7.1 요약

- **버그**: `_is_paper`가 `settings.kis_env`를 무시하고 `app_key`/`api_secret` 존재 여부만으로 판정
- **영향**: paper/mock/sandbox 환경에서도 WebSocket 연결 시도 → `httpx.UnsupportedProtocol`
- **수정**: `getattr(settings, "kis_env", "paper") in ("paper", "mock", "sandbox")` 조건 추가
- **검증**: 119/119 테스트 통과, 회귀 없음
- **안전성**: production code에서 `KisMarketStateClient` 미사용으로 배포 영향 zero

### 7.2 교훈

환경 의존적 판정 로직은 단일 조건(credential 존재 여부)에 의존하지 말고, 명시적인 환경 설정(`kis_env`)을 함께 고려해야 한다. 특히 테스트 fixture에서 제공하는 credential 값이 paper 환경임을 나타내는 유일한 신호는 `settings.kis_env`이며, 이 값을 로직에 반영하지 않은 것이 근본 원인이었다.
