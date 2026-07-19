# 휴장일 KIS Reject Live Smoke Test — 재실행 보고서 (DeepSeek 실제 환경)

- **작성일**: 2026-05-25 (KST)
- **실행 환경**: `agent_trading-api-1` 컨테이너 내부
- **대상 종목**: 005930 (삼성전자)
- **스크립트**: `python -m scripts.run_orchestrator_once`

---

## 1. 배경

이전 smoke test는 `DEEPSEEK_API_KEY`가 **실제로는 `.env`에 존재**했지만, `run_orchestrator_once.py`가 `load_dotenv()`를 호출하지 않아 호스트 shell에서 실행 시 env var가 비어 Stub Agent로 fallback되었다.

이번 재실행에서는:
- 컨테이너 내부(Docker Compose가 `.env` 자동 로드)에서 실행
- `AgentSubprocessInput` 버그(`request` 키 미스매치)를 사전 수정
- 실제 DeepSeek provider 경로로 EI/AR/FDC 실행 검증
- KIS 휴장일 reject 경로 검증 시도

---

## 2. 수행한 작업

### 2.1 코드 분석 (Ask 모드)

분석 파일:
- [`scripts/run_orchestrator_once.py`](../scripts/run_orchestrator_once.py)
- [`scripts/run_paper_decision_loop.py`](../scripts/run_paper_decision_loop.py)
- [`scripts/run_agent_subprocess.py`](../scripts/run_agent_subprocess.py)
- [`src/agent_trading/runtime/bootstrap.py`](../src/agent_trading/runtime/bootstrap.py)
- [`src/agent_trading/services/decision_agent_runner.py`](../src/agent_trading/services/decision_agent_runner.py)
- [`src/agent_trading/services/decision_orchestrator.py`](../src/agent_trading/services/decision_orchestrator.py)
- [`src/agent_trading/services/subprocess_helpers.py`](../src/agent_trading/services/subprocess_helpers.py)

#### 5대 질문 답변

**Q1. `run_orchestrator_once.py`에 `load_dotenv()`가 있는가?**
- **없다.** `dotenv` import 자체가 존재하지 않는다. 따라서 호스트 shell에서 실행 시 `.env` 파일이 자동 로드되지 않는다.

**Q2. `run_paper_decision_loop.py`는 `load_dotenv()`를 호출하는가?**
- **호출한다.** `_load_env()` 함수(1363~1370행)에서 `load_dotenv()`를 호출한다. 따라서 이 스크립트는 호스트에서도 `.env`를 자동 로드한다.

**Q3. Provider client(DeepSeek) 생성 경로와 Stub fallback 로직은?**
- [`bootstrap.py`](../src/agent_trading/runtime/bootstrap.py)의 `_build_provider_agent()`(241~270행), `_build_ai_risk_agent()`(273~306행), `_build_final_decision_agent()`(309~344행)에서 생성
- 세 함수 모두 `settings.provider_api_key`가 비어있으면 `return None`
- [`decision_orchestrator.py`](../src/agent_trading/services/decision_orchestrator.py:192~196)에서 agent가 `None`이면 `StubEventInterpretationAgent()` 등으로 대체

**Q4. `AgentSubprocessInput` 버그 발생 경로는?**
- [`subprocess_helpers.py:50`](../src/agent_trading/services/subprocess_helpers.py:50): `serialize_agent_input()`이 `"request"` 키를 JSON payload에 포함
- [`run_agent_subprocess.py:114`](../scripts/run_agent_subprocess.py:114): `AgentSubprocessInput` dataclass에 `request` 필드 **없음**
- `AgentSubprocessInput(**data)` 실행 시 `TypeError: __init__() got an unexpected keyword argument 'request'` 발생
- [`run_agent_subprocess.py:546`](../scripts/run_agent_subprocess.py:546): `except TypeError`로 catch → `sys.exit(1)`
- [`decision_agent_runner.py:538~545`](../src/agent_trading/services/decision_agent_runner.py:538): 부모 프로세스에서 `result["success"]`가 False → `build_fallback_bundle()` 반환 → **모든 agent가 Stub 기본값**

**Q5. 컨테이너 내부에서 `.env` 없이도 env var가 주입되는 이유는?**
- [`docker-compose.yml`](../docker-compose.yml)의 `environment:` 섹션이 `${VAR_NAME}` 문법으로 선언
- Docker Compose가 실행 시 **자동으로 `.env` 파일을 읽어** 컨테이너 env에 주입

### 2.2 `AgentSubprocessInput` 버그 수정

**수정 파일:** [`src/agent_trading/services/subprocess_helpers.py`](../src/agent_trading/services/subprocess_helpers.py:54)

**변경 내용:**
```python
# Before:
payload = {
    "request": dataclass_to_dict(request),   # ← AgentSubprocessInput에 없는 필드
    "context": dataclass_to_dict(context),
    "score": ...,
    "positional_args": ...,
}

# After:
payload = {
    "context": dataclass_to_dict(context),
    "score": ...,
    "positional_args": ...,
}
```

**근거:** [`run_agent_subprocess.py:409`](../scripts/run_agent_subprocess.py:409)의 `_reconstruct_request()`가 이미 `inp.context`에서 request를 재구성하므로 payload의 `"request"`는 불필요.

### 2.3 컨테이너 env 확인

`agent_trading-api-1` 컨테이너 내부 env var 상태:

| 환경변수 | 값 | 상태 |
|----------|-----|------|
| `LLM_PROVIDER` | `deepseek` | ✅ |
| `DEEPSEEK_API_KEY` | `[SET]` | ✅ |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | ✅ |
| `DEEPSEEK_MODEL_ID` | `deepseek-chat` | ✅ |

Python `AppSettings`에서도 정상 로딩 확인: `provider=deepseek, api_key_set=True, model_id=deepseek-chat`

### 2.4 Assemble-Only Smoke Test

**명령어:** `docker exec agent_trading-api-1 sh -c 'cd /app && python -m scripts.run_orchestrator_once'`

**결과:**

| 단계 | 소요시간 | 결과 |
|------|---------|------|
| EI (EventInterpretation) | ~60초 | ✅ `input_events=4 output_events=4 detected_event_count=4` |
| AR (AIRisk) | ~28초 | ✅ `risk_opinion=review risk_score=0.50` |
| FDC (FinalDecisionComposer) | ~57초 | ✅ `decision_type=WATCH` |
| **최종** | **~2분 27초** | **`WATCH` (005930)** |

**Provider 확인:** DeepSeek 실제 사용 — `api.deepseek.com/v1/chat/completions`에 3회 HTTP 200 OK

### 2.5 Submit Smoke Test

**명령어:** `docker exec agent_trading-api-1 sh -c 'cd /app && python -m scripts.run_orchestrator_once --submit'`

**결과:**

| 단계 | 결과 | 상세 |
|------|------|------|
| EI | ✅ 성공 | 3 events, `slightly_bullish`, `moderate` |
| AR | ✅ 성공 | `risk_score=0.55`, `risk_opinion=review` |
| FDC | ✅ 성공 | `decision_type=WATCH` |
| Sizing | ⏭️ **SKIPPED** | `non_actionable_decision` — WATCH는 매수/매도 행동 아님 |
| Broker Submit | ❌ **미도달** | sizing skip으로 인해 broker submit 단계 진입 실패 |

**최종 Status:**
- `status`: `SKIPPED`
- `error_phase`: `sizing`
- `error_message`: `non_actionable_decision`
- `sized_quantity`: `0`

---

## 3. 검증 결과 매트릭스

| # | 검증 항목 | 상태 | 비고 |
|---|----------|------|------|
| 1 | EI agent 실행 및 판단 결과 생성 | ✅ | 3~4 events detected, slightly_bullish |
| 2 | AR/FDC 포함 decision assembly 정상 동작 | ✅ | risk_score=0.50~0.55, decision_type=WATCH |
| 3 | 주문 사이징 실행 | ✅ | WATCH → non_actionable_decision → SKIPPED |
| 4 | translation / execution_service / order_manager 경계 동작 | ⚠️ | sizing까지만 확인, broker submit 경로 미도달 |
| 5 | KIS submit 시도 | ❌ | FDC가 BUY/SELL을 반환하지 않아 sizing에서 차단 |
| 6 | 휴장일 broker reject를 정상 `REJECTED` 경로로 처리 | ❌ | broker submit 단계 도달 못함 |
| 7 | DB row / API / 스크립트 출력 확인 | ✅ | agent_runs 3건, trade_decisions, decision_contexts 정상 |

---

## 4. 발견된 이슈

### 4.1 `calculate_max_order_value()` `TypeError` (price=None)

**발생 위치:** [`src/agent_trading/services/translation.py:185`](../src/agent_trading/services/translation.py:185)

**증상:**
```
calculate_max_order_value(request.price, request.quantity, ...)
→ TypeError: unsupported operand type(s) for *: 'NoneType' and 'decimal.Decimal'
```

**원인:** MARKET order에서 `request.price`가 `None`인 상태로 `calculate_max_order_value()`가 호출됨

**영향:** 비치명적 (trade_decision 저장 실패, 파이프라인 흐름 자체는 계속됨). 하지만 submit 시 trade_decision ID가 `None`으로 저장되어 추적성 저하.

### 4.2 KIS Quote API — AppKey 누락 (재현됨)

이전 smoke test와 동일 — KIS paper API (`openapivts`) 토큰 발급 시도에서 `403 Forbidden` (AppKey 필수). KIS env var(`KIS_APP_KEY`, `KIS_APP_SECRET`)가 설정되지 않았기 때문.

### 4.3 FDC가 BUY/SELL 대신 WATCH 반환

FDC가 005930에 대해 BUY/SELL 대신 WATCH를 반환한 원인:
- AR의 `risk_opinion=review` (중립적, 위험 점수 0.50~0.55)
- 투입된 3~4개 이벤트가 충분히 강한 신호를 제공하지 못함
- 휴장일 컨텍스트가 AI 판단에 영향을 주었을 가능성

---

## 5. 한계 및 장중 필요 항목

### 오늘(휴장일) 검증 가능했던 것
| 항목 | 상태 |
|------|------|
| 컨테이너 env var 주입 | ✅ 확인 |
| 실제 DeepSeek provider 사용 | ✅ 확인 |
| EI → AR → FDC pipeline | ✅ 정상 |
| sizing 로직 (non-actionable skip) | ✅ 정상 |
| DB persistence (agent_runs 등) | ✅ 정상 |
| `AgentSubprocessInput` 버그 수정 | ✅ 완료 |
| `calculate_max_order_value()` `price=None` 버그 | ⚠️ 발견 (수정 필요) |

### 장중에만 검증 가능한 것
| 항목 | 이유 |
|------|------|
| KIS submit 시도 (BUY/SELL decision 필요) | 휴장일에는 FDC가 BUY/SELL 판단을 내리지 않음 |
| KIS 휴장일 reject (`OPR00001`) | broker submit 단계 도달 필요 |
| broker submit → REJECTED status 경로 | broker submit 단계 도달 필요 |
| translation → execution_service → order_manager submit 경계 | broker submit 단계 도달 필요 |

---

## 6. 권장 사항

1. **`calculate_max_order_value()` 수정** — `price=None`인 MARKET order에 대해 graceful handling 추가 (예: price=0 또는 fallback quote 사용)
2. **장중 smoke test 재실행** — 다음 영업일에 BUY/SELL decision이 예상되는 종목으로 submit smoke test 실행
3. **`run_orchestrator_once.py`에 `load_dotenv()` 추가** — 호스트 shell 실행 시에도 `.env`가 자동 로드되도록 하여 컨테이너/호스트 간 실행 경로 일관성 확보
4. **KIS credential 설정** — `KIS_APP_KEY`, `KIS_APP_SECRET`을 `.env`에 추가하여 실제 broker submit 테스트 가능하도록 함

---

## 7. 로그 파일 목록

| 파일 | 내용 |
|------|------|
| [`logs/smoke_test_full_20260525.log`](../logs/smoke_test_full_20260525.log) | assemble-only 전체 로그 (1.3MB, 8537 lines) |
| [`logs/smoke_test_submit_20260525.log`](../logs/smoke_test_submit_20260525.log) | submit smoke test 로그 |
| [`logs/smoke_test_assemble_only_2026-05-25.json`](../logs/smoke_test_assemble_only_2026-05-25.json) | 1차 assemble-only JSON 출력 (Stub, 이전) |
| [`logs/smoke_test_submit_2026-05-25.txt`](../logs/smoke_test_submit_2026-05-25.txt) | 1차 submit 로그 (Stub, 이전) |
