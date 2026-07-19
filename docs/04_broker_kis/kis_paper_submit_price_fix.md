# KIS Paper Submit Price 파라미터 조정 — 설계 문서

> **⚠️ 경고: 이 문서는 smoke 검증용 1회성 조정을 다룹니다.**
> 아래 A안(B안 포함)은 **production 코드 변경이 아닌, KIS paper broker accept 경로 검증을 위한 임시 smoke 값 조정**입니다.
> 장기 해법(동적 가격 조회, production-grade price discovery)과 혼동하지 마세요.

---

## 1. 현재 상태

### 문제
`run_orchestrator_once.py`에서 하드코딩된 `price=Decimal("50000")`이 KIS paper 모의투자 환경의 상/하한가 범위를 벗어남.

```
BrokerError: KIS order_cash: business error (rt_cd=1, msg_cd=40270000): 모의투자 상/하한가 오류
```

### 원인 분석
- KOSPI 종목은 전일종가 기준 ±30% 상/하한가 적용
- 삼성전자(005930)의 최근 거래가는 약 70,000~90,000원 범위
- `50000`원은 하한가 이하 → KIS paper에서 reject

### 현재 상태 요약
| 항목 | 상태 |
|------|------|
| AI contract 정렬 | ✅ `risk_opinion=allow`, `decision_type=APPROVE` |
| Broker submit 경로 | ✅ Phase 5까지 진입 성공 |
| KIS endpoint/auth | ✅ 인증 성공 |
| **Price validation** | ❌ `msg_cd=40270000` 상/하한가 오류 |

---

## 2. 선택지 비교

| 방안 | 접근 | 변경량 | 장점 | 단점 |
|------|------|--------|------|------|
| **A안** LIMIT price 조정 | `price=50000` → 현재가 근처 값 | 1줄 | 최소 수정, 현재 구조 유지 | 고정값이므로 시세 변동 시 재조정 필요 |
| **B안** MARKET order | `OrderType.LIMIT` → `OrderType.MARKET` | 1줄 | 가격 문제 완전 회피 | KIS paper에서 MARKET semantics 확인 필요 |
| **C안** 동적 가격 조회 | submit 직전 `get_quote()` 호출 | 여러 줄 | 항상 유효한 가격 | 과도한 변경, smoke 목적에 비해 복잡 |

### 권장: **A안 우선 (smoke 검증용 1회성)**

이유:
1. **최소 변경** — `run_orchestrator_once.py`의 1줄만 수정
2. **smoke 목적 적합** — 고정된 smoke price로 충분 (장기 해법과 혼동 금지)
3. **B안은 fallback 불가** — KIS paper에서 MARKET order가 LIMIT보다 덜 검증됨. B안은 **자동 fallback 대상이 아니며**, 별도 승인 포인트로만 진행 가능
4. **C안은 범위 초과** — 이번 턴은 smoke 검증이 목적이지 일반화 아님

---

## 3. 필요 정보: 현재 KIS paper 005930 기준가

KIS paper API(`get_quote('005930')`)로 다음 필드를 조회해야 함:
- `stck_prpr`: 현재가
- `prdy_clpr`: 전일종가 (상/하한가 기준)
- `stck_hgpr`: 고가
- `stck_lwpr`: 저가

### 상/하한가 계산
- 상한가 = `prdy_clpr * 1.3`
- 하한가 = `prdy_clpr * 0.7`

### 가격 선정 기준
- **최종 채택가 = `prdy_clpr` (전일종가)**
- `prdy_clpr`을 채택하는 이유:
  1. 전일종가는 장 시작 시간 외에도 항상 유효한 값
  2. ±30% 범위의 중앙에 위치 → 상/하한가 이탈 위험 최소화
  3. KIS paper 모의투자 환경에서도 전일종가는 안정적으로 조회 가능
  4. `stck_prpr`(현재가)는 장중에만 의미있는 값

### 조회 결과 기록 항목 (보고서에 포함)
| 필드 | 설명 | 출처 |
|------|------|------|
| `stck_prpr` | KIS paper 현재가 (장중) | `get_quote()` |
| `prdy_clpr` | **전일종가 ← 최종 채택가** | `get_quote()` |
| `prdy_clpr * 0.7` | 하한가 | 계산 |
| `prdy_clpr * 1.3` | 상한가 | 계산 |
| 최종 채택가 | `prdy_clpr` (Decimal) | 결정값 |

---

## 4. 변경 파일 및 범위

### 유일한 변경: `scripts/run_orchestrator_once.py`

```diff
- price=Decimal("50000"),
+ price=Decimal("<prdy_clpr>"),  # KIS paper 005930 전일종가 (smoke 검증용 1회성)
```

> **smoke용 최소 변경임을 명시**: 이 변경은 production 코드가 아닌 smoke test script의 1줄이며,
> KIS paper broker accept 경로 검증 후 복원 또는 정식 해법으로 대체되어야 함.

### 변경 제외 (명시적)
- `src/agent_trading/` — production 코드 변경 금지
- `.env` — env 변경 불필요 (이전 task에서 이미 완료)
- broker adapter / submit semantics — 변경 금지
- AI agent / schemas — 변경 금지
- guardrail / reconciliation — 변경 금지

---

## 5. 실행 계획

### Step 1: KIS paper 현재가 조회 (Code mode)
- `KISRestClient.get_quote('005930')` 호출
- `stck_prpr`, `prdy_clpr` 확인
- 상/하한가 계산 및 최종 채택가 기록

### Step 2: `run_orchestrator_once.py` price 조정 (Code mode)
- `price=Decimal("<prdy_clpr>")`로 1줄 변경

### Step 3: Dry-run 재확인 (Code mode)
- `--dry-run --output json` 실행
- `risk_opinion=allow`, `decision_type=APPROVE`, `sizing=10` 확인
- 가격 조정 후에도 AI 결정 경로가 변경 없이 유지되는지 확인

### Step 4: Submit smoke 재실행 (Code mode)
- `--submit --output json` 실행
- KIS paper `msg_cd=40270000` 해소 여부 확인

### Step 5: Post-submit 검증 (Code mode)
- broker accept 여부
- order status progression
- trade_decision 상태
- reconcile_required 플래그

---

## 6. Post-Submit 성공 기준

### 3단계 성공 기준 (계층적)

| 단계 | 기준 | 측정 방법 | 성공 조건 |
|------|------|----------|-----------|
| **1차** | price validation 통과 | `BrokerError` 미발생 | `msg_cd=40270000` 없음 |
| **2차** | broker accept | `submit_order_to_broker()` 정상 반환 | `SubmitResult.status != REJECTED` |
| **3차** | order status 확인 | DB 조회 | `order_request.status`가 `PENDING_SUBMIT` 또는 `SUBMITTED`로 진행 |
| **부가** | reconcile_required | `reconciliation_lock` 확인 | `reconcile_required=False` (또는 존재 시 RECONCILE_REQUIRED 허용) |

> **참고**: `SUBMITTED`는 broker가 주문을 접수했음을 의미. 실제 체결 여부(fill)는 이번 검증 범위 밖.

---

## 7. 실패 시 Fallback — 원인 분류 체계

> **B안(MARKET order)은 자동 fallback이 아닙니다.**
> 아래는 A안 실패 시 원인을 **분류하여 보고**하기 위한 체계이며, B안 전환은 별도 승인 이후에만 가능합니다.

### 실패 원인 3가지 분류

| 분류 | 증상 | 확인 방법 | 조치 |
|------|------|----------|------|
| **① Price validation** | 동일 `msg_cd=40270000` | `BrokerError.msg_cd == "40270000"` | 조회한 현재가를 재확인하고, `prdy_clpr`가 아닌 `stck_prpr`로 재시도 가능 |
| **② Broker reject** | 다른 `msg_cd`, `BrokerError` | `BrokerError.msg_cd` 확인 | 장시간 / 계좌 상태 / 기타 KIS paper 제약 가능성 → 별도 진단 필요 |
| **③ Sync 문제** | `BrokerError` 없으나 비정상 상태 | order status / trade_decision 불일치 | snapshot staleness, DB sync 등 인프라 문제 진단 |

### 결정 흐름

```
A안 실패
  ├─ ① Price validation → 현재가 재조회 및 가격 재선정 → 재시도 (Step 2 → 4)
  ├─ ② Broker reject → 보고 후 중단 (B안 전환은 별도 승인 필요)
  └─ ③ Sync 문제 → snapshot sync 재실행 → 재시도 (Step 1 → 3)
```

---

## 8. 보고서 형식 (완료 시)

### 항목 구성

1. **Step 1: 현재가 조회 결과**
   - `stck_prpr`, `prdy_clpr`, 상한가, 하한가, 최종 채택가

2. **Step 2: 변경 파일 및 범위**
   - `run_orchestrator_once.py` 1줄 변경
   - 변경 전/후 diff
   - smoke용 최소 변경임을 명시

3. **Step 3: Dry-run 재확인 결과**
   - risk_opinion, decision_type, sizing_quantity, skip_reason

4. **Step 4: Submit smoke 실행 결과**
   - 성공/실패 여부
   - BrokerError 발생 시 msg_cd 및 원인 분류

5. **Step 5: Post-submit 검증 결과**
   - order status progression
   - trade_decision 상태
   - reconcile_required 플래그

6. **성공/실패 판정 (3단계 기준)**
   - 1차: price validation 통과?
   - 2차: broker accept?
   - 3차: order status 정상?

7. **실패 시 원인 분류** (해당 시)
   - Price validation / Broker reject / Sync 문제

8. **생성된 식별자** (trade_decision_id, decision_context_id, order_id)

9. **다음 액션** (실패 시에만)
   - B안 전환 필요 시 별도 승인 요청
   - 기타 진단 필요 항목
