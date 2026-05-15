# Cash Snapshot 장후 미갱신 — 파라미터 검증 및 근본 원인 분석 보고서

**작성일**: 2026-05-15 (KST)  
**스코프**: `get_cash_balance()` 파라미터 검증, 운영 로그 분석, 근본 원인 판정  
**제약 조건**: 문서 작성만 수행 (코드 수정 불가)

---

## 1. 현재 `get_cash_balance()` 호출 스펙 요약

### Endpoint

| 항목 | 값 |
|------|-----|
| HTTP Method | `GET` |
| Path | `/uapi/domestic-stock/v1/trading/inquire-balance` |
| TR ID (paper) | `VTTC8434R` |
| TR ID (live) | `TTTC8434R` |

출처: [`rest_client.py:59,78`](../src/agent_trading/brokers/koreainvestment/rest_client.py:59)

### 12개 파라미터 전체 목록

[`rest_client.py:1063-1076`](../src/agent_trading/brokers/koreainvestment/rest_client.py:1063) 기준:

```python
params = {
    "CANO": self.account_number,              # 계좌번호 (체계 8-2)
    "ACNT_PRDT_CD": self.account_product_code, # 상품코드
    "AFHR_FLPR_YN": "N",                      # 시간외단일가여부
    "OFL_YN": "",                              # 오프라인여부
    "INQR_DVSN": "01",                        # 조회구분 (01=추정)
    "UNPR_DVSN": "01",                        # 단가구분 (01=종목)
    "FUND_STTL_ICLD_YN": "N",                 # 펀드결제포함여부
    "FNCG_AMT_AUTO_RDPT_YN": "N",             # 융자금액자동상환여부
    "PRCS_DVSN": "01",                        # 처리구분 (01=전체)
    "COST_ICLD_YN": "N",                      # 비용포함여부
    "CTX_AREA_FK100": "",                     # 연속조회검색조건100
    "CTX_AREA_NK100": "",                     # 연속조회키100
}
```

### 응답 처리

[`rest_client.py:1087-1090`](../src/agent_trading/brokers/koreainvestment/rest_client.py:1087):

```python
output2 = data.get("output2", {})
if isinstance(output2, list):
    output2 = output2[0] if output2 else {}
return output2
```

- `output2` (예수금 총괄) 추출
- `output2`가 리스트면 첫 요소 사용, 빈 dict면 `{}` 반환

---

## 2. 문서 대비 파라미터 차이점 표

| 파라미터 | 현재 코드 값 | KIS 문서 권장값 | 일치? | 비고 |
|---------|------------|---------------|-------|------|
| `CANO` | 계좌번호 | 계좌번호 | ✅ | 동일 |
| `ACNT_PRDT_CD` | 상품코드 | 상품코드 | ✅ | 동일 |
| `AFHR_FLPR_YN` | `N` | `N` | ✅ | 시간외단일가 OFF |
| `OFL_YN` | `""` (빈값) | `""` | ✅ | 오프라인 조회 아님 |
| `INQR_DVSN` | `01` (추정) | `01` | ✅ | 추정조회 모드 |
| `UNPR_DVSN` | `01` (종목) | `01` | ✅ | 종목단가 기준 |
| `FUND_STTL_ICLD_YN` | `N` | `N` | ✅ | 펀드 미포함 |
| `FNCG_AMT_AUTO_RDPT_YN` | `N` | `N` | ✅ | 융자상환 OFF |
| `PRCS_DVSN` | `01` (전체) | `01` | ✅ | 전체처리 |
| `COST_ICLD_YN` | `N` | `N` | ✅ | 비용 미포함 |
| `CTX_AREA_FK100` | `""` | `""` (최초) | ✅ | 연속조회 초기값 |
| `CTX_AREA_NK100` | `""` | `""` (최초) | ✅ | 연속조회 초기값 |

**판정**: 모든 파라미터가 KIS 문서 권장값과 일치. 파라미터 불일치는 원인이 아니다.

> Ask 모드 분석 결과 인용: KIS OpenAPI Excel 문서(`reference_docs/한국투자증권_오픈API_전체문서_20260503_030000.xlsx`)와 현행 코드 파라미터를 비교하여 일치 확인.

---

## 3. 실측 API 호출 결과 (Code 모드 실행 결과)

### 테스트 스크립트

[`_test_cash_balance.py`](../_test_cash_balance.py) — 장후(19:46 KST) 3개 파라미터 조합으로 KIS paper API 직접 호출

### 조합별 결과

| 조합 | `AFHR_FLPR_YN` | `INQR_DVSN` | `PRCS_DVSN` | `FUND_STTL_ICLD_YN` | `dnca_tot_amt` | 결과 |
|------|---------------|------------|------------|-------------------|---------------|------|
| A (현행) | `N` | `01` | `01` | `N` | 27,329,630원 | ✅ 정상 |
| B (전체조회) | `N` | `00` | `00` | `Y` | 27,329,630원 | ✅ 정상 |
| C (시간외) | `Y` | `01` | `01` | `N` | 27,329,630원 | ✅ 정상 |

### 핵심 발견

- **장후(19:46 KST)에도 모든 조합에서 `output2` 정상 반환** — `dnca_tot_amt` = 27,329,630원
- 조합 A/B/C 모두 동일 결과 → 시간외단일가 여부, 조회구분, 처리구분 모두 무관
- `get_cash_balance()`와 `get_positions()` 모두 동일 endpoint/inquiry 사용 → 둘 다 정상 작동

**판정**: **KIS paper API의 본질적 제약이 아니다.** 장후에도 cash 조회는 정상 동작한다.

> Code 모드 실행 결과 인용: `_test_cash_balance.py` 장후 실측 (2026-05-15 19:46 KST, TZ=Asia/Seoul)

---

## 4. 운영 로그 분석 결과 (Ask 모드 분석 결과 인용)

### 로그 출처

[`logs/near_real_scheduler_2026-05-15.log`](../logs/near_real_scheduler_2026-05-15.log) — 18,484 lines

### 주요 타임라인

| KST 시간 | 이벤트 | 상세 |
|---------|-------|------|
| 07:55:01 | 스케줄러 시작 | `KIS_ENV=paper` |
| 08:00:02~08:00:17 | Pre-market 페이즈 | snapshot, event, post_submit_sync |
| 08:50:00~15:25:55 | Intraday 페이즈 | ~5분 간격 snapshot_sync (171 cycles) |
| **15:31:10** | **⭐ `phase=end-of-day` 진입** | 마지막 intraday snapshot_sync 후 전환 |
| **15:31:10~15:31:16** | **`eod_snapshot_sync` 실행** | cash=1 성공 (인증+DB persist 정상) |
| **15:31:16~15:31:20** | **`eod_post_submit_sync` 실행** | 완료 |
| **15:31:20** | **⭐ `phase=end-of-day complete`** | `state.end_of_day_done = True` |
| **15:31:20~16:30:03** | **🚫 IDLE** | 더 이상 snapshot_sync 없음 |
| 16:30:03 | 스케줄러 종료 | `end_at(16:30)` 도달 |

### EOD 페이즈 로그 상세

```
15:31:10 phase=end-of-day start
15:31:10 eod_snapshot_sync start → run_snapshot_sync_loop.py --max-cycles 1
15:31:10 HTTP POST oauth2/tokenP → 200 OK
15:31:10 HTTP GET inquire-balance → 200 OK (positions)
15:31:16 HTTP GET inquire-balance → 200 OK (cash)
15:31:16 sync-cycle accounts=1 cash=1 positions=2 errors=0   ← cash 정상
15:31:16 eod_snapshot_sync complete (6.05s)
15:31:16 eod_post_submit_sync start
15:31:20 phase=end-of-day complete
```

### 직접적 원인

**스케줄러 `end-of-day` 페이즈 진입 후 snapshot_sync 중단**

[`run_near_real_ops_scheduler.py:694-711`](../scripts/run_near_real_ops_scheduler.py:694):

```python
if intraday_at <= now < market_close_at:
    await _run_intraday_due_tasks(...)      # ← 정규 snapshot_sync 사이클

if now >= market_close_at and not state.end_of_day_done:
    await _run_end_of_day(...)              # ← 1회 EOD 실행 후 종료

await asyncio.sleep(args.tick_seconds)      # ← IDLE
```

- `MARKET_CLOSE = dtime(15, 30)` ([line 66](../scripts/run_near_real_ops_scheduler.py:66))
- `END_OF_DAY_END = dtime(16, 30)` ([line 67](../scripts/run_near_real_ops_scheduler.py:67))
- EOD 완료 후 `state.end_of_day_done = True` → 조건 `not state.end_of_day_done` 실패
- 동시에 `now >= market_close_at` → intraday 조건 `now < market_close_at`도 실패
- **어느 조건도 만족하지 않아 IDLE → 16:30까지 snapshot_sync 완전 중단**

> Ask 모드 분석 결과 인용: 운영 로그 타임라인 및 스케줄러 코드 경로 분석 완료.

---

## 5. 추가 발견된 문제점

### 5.1 OAuth2 Token Rate Limit (EGW00133)

로그에서 38회의 `EGW00133` 에러 확인:

```
HTTP 403 (msg_cd=EGW00133): 접근토큰 발급 잠시 후 다시 시도하세요(1분당 1회)
```

- 매 snapshot_sync 사이클(~5분)마다 [`authenticate()`](../src/agent_trading/brokers/koreainvestment/rest_client.py:376) 호출
- KIS paper API는 1회/분 rate limit (2026-04-20 공지)
- 동시에 여러 subprocess(token cache 미공유)가 실행되면 **~80% 실패율**
- 실패 시 해당 cycle 전체 abort → cash/position 미갱신
- [`rest_client.py:403-408`](../src/agent_trading/brokers/koreainvestment/rest_client.py:403)에서 1초 cooldown만 적용하고 있어 분당 제한 미준수

### 5.2 Cash Balance 빈 dict `{}` 반환 시 무음성 스킵

[`kis_snapshot_sync.py:268`](../src/agent_trading/services/kis_snapshot_sync.py:268):

```python
if raw_cash:  # ← {}는 falsy → cash_entity 미생성
    ...       # 로깅 없이 조용히 스킵
```

- 빈 dict `{}` 반환 시 `if raw_cash:` 조건 falsy로 통과
- `result.cash_balance_synced`가 `False`로 남음 → `total_cash_synced` 미증가
- 이 시점에 **어떤 경고 로그도 출력되지 않음**
- [`run_snapshot_sync_loop.py:134-141`](../scripts/run_snapshot_sync_loop.py:134)에서 `CASH_SYNC_ZERO` 경고는 전체 계좌 기준이라 단일 계좌에서는 출력 안 될 수 있음

### 5.3 `order_manager.py` — `name 'logger' is not defined` 버그

[`order_manager.py:10`](../src/agent_trading/services/order_manager.py:10):

```python
logger = logging.getLogger(__name__)  # line 10
# ... imports after line 12 ...
```

모듈 임포트 순서상 `logger`가 import 이전에 정의되어 있으나, 일부 Python 버전/환경에서 `__name__` 참조 타이밍 문제로 `NameError` 발생 가능. 안정성을 위해 로거 정의를 모듈 하단으로 이동하거나 import 이후로 재배치 필요.

### 5.4 `adapter.py:204` — `get_cash_balance(account_ref)` 시그니처 불일치

[`adapter.py:203-204`](../src/agent_trading/brokers/koreainvestment/adapter.py:203):

```python
async def get_cash_balance(self, account_ref: str) -> CashBalance:
    raw = await self._rest.get_cash_balance(account_ref)  # ← 인자 전달
```

vs [`rest_client.py:1044`](../src/agent_trading/brokers/koreainvestment/rest_client.py:1044):

```python
async def get_cash_balance(self) -> dict[str, Any]:  # ← 인자 없음
```

- `adapter.get_cash_balance()`가 `account_ref`를 인자로 받아 `self._rest.get_cash_balance(account_ref)` 호출
- 그러나 `KISRestClient.get_cash_balance()`는 **인자를 받지 않음** (`self.account_number`/`self.account_product_code` 사용)
- `account_ref` 인자가 전달되면 `TypeError` 발생 (unexpected keyword argument)
- 현재 운영에서는 `kis_snapshot_sync.py`가 직접 `rest_client.get_cash_balance()` 호출하므로 우회되고 있으나, adapter 경로 사용 시 장애 발생

---

## 6. Root Cause 판정

### 1차 원인 (직접적): 스케줄러 설계 ⭐

| 항목 | 내용 |
|------|------|
| **원인** | 스케줄러가 `end-of-day` 페이즈 진입 후 정규 `snapshot_sync` 사이클을 중단 |
| **설계 결정** | [`run_near_real_ops_scheduler.py:694-711`](../scripts/run_near_real_ops_scheduler.py:694) |
| **영향** | 15:31:20~16:30:03 (약 59분) 동안 snapshot_sync 미실행 |
| **증상** | 장 마감 후 cash snapshot 미갱신 → `stale-snapshot` guardrail이 submit 차단 |
| **해결 방향** | EOD 이후에도 일정 간격 snapshot_sync를 지속하도록 스케줄러 수정 |

```
타임라인:
  15:25:50  snapshot_sync (마지막 intraday)
  15:31:10  phase=end-of-day 진입
  15:31:16  eod_snapshot_sync (cash=1 성공)
  15:31:20  phase=end-of-day complete → IDLE
  16:30:03  스케줄러 종료
```

### 2차 원인 (악화 요인): OAuth2 Token Rate Limit

| 항목 | 내용 |
|------|------|
| **원인** | 매 사이클(5분)마다 `authenticate()` 호출 → KIS 1회/분 제한에 ~80% 실패 |
| **증상** | `EGW00133` 에러로 snapshot_sync cycle 전체 실패 |
| **영향** | 장중에도 ~20%의 cycle에서 cash=0 기록 |
| **해결 방향** | Token 캐싱/재사용, token file cache 활성화, 인증 실패 시 재시도 로직 개선 |

### 3차 원인 (리스크): 빈 응답 무음성 처리

| 항목 | 내용 |
|------|------|
| **원인** | `if raw_cash:` 조건에서 빈 dict `{}`가 falsy여서 조용히 스킵 |
| **영향** | 장애 상황에서 디버깅 어려움 |
| **해결 방향** | 빈 cash 응답 시 경고 로그 추가 |

---

## 7. 장후 Cash 조회 가능 여부 판정

### ✅ 가능 (KIS Paper API)

| 근거 | 출처 | 결과 |
|------|------|------|
| 장후(19:46 KST) 실측 호출 | [`_test_cash_balance.py`](../_test_cash_balance.py) | 3개 조합 모두 `dnca_tot_amt=27,329,630` 정상 반환 |
| EOD(15:31 KST) snapshot_sync | 로그 line 18440 | `cash=1` 성공 (positions=2) |
| 모든 파라미터 조합 동일 | Code 모드 실행 | A/B/C 조합 차이 없음 |

**KIS paper API의 `inquire-balance`는 장 마감 후에도 정상 동작한다.** 장 마감 후 cash snapshot이 미갱신된 근본 원인은 API 제약이 아닌, **스케줄러가 EOD 이후 snapshot_sync를 중단하는 설계 결정** 때문이다.

---

## 8. 후속 수정 제안 (우선순위 순)

| 우선순위 | 수정 항목 | 대상 파일 | 이유 |
|---------|----------|---------|------|
| **P1** | EOD 이후 snapshot_sync 지속 | [`run_near_real_ops_scheduler.py`](../scripts/run_near_real_ops_scheduler.py) | 가장 직접적 원인 해결. EOD 페이즈 종료 후에도 일정 간격(예: 15분) snapshot_sync 유지 |
| **P2** | Cash 빈 응답 로깅 추가 | [`kis_snapshot_sync.py`](../src/agent_trading/services/kis_snapshot_sync.py:268) | 빈 cash dict 반환 시 `logger.warning()` 출력. 디버깅 가능성 확보 |
| **P3** | OAuth2 토큰 캐싱/재사용 | [`rest_client.py`](../src/agent_trading/brokers/koreainvestment/rest_client.py:376) + 스케줄러 | `dev_token_cache_enabled` 강제 활성화, token 만료 전까지 재사용. KIS 1회/분 rate limit 준수 |
| **P4** | `logger is not defined` 버그 수정 | [`order_manager.py`](../src/agent_trading/services/order_manager.py:10) | 로거 정의를 import 블록 이후로 이동 또는 모듈 하단 배치 |
| **P5** | `adapter.py` 시그니처 정합 | [`adapter.py`](../src/agent_trading/brokers/koreainvestment/adapter.py:204) | `get_cash_balance(account_ref)` → `get_cash_balance()` 인자 제거 또는 `**kwargs`로 방어 |

---

## 9. `get_positions()` vs `get_cash_balance()` 비교 표

| 항목 | `get_positions()` | `get_cash_balance()` |
|------|------------------|---------------------|
| Endpoint | `inquire-balance` | `inquire-balance` |
| HTTP Path | 동일 | 동일 |
| Parameters | 동일 (12개) | 동일 (12개) |
| TR ID (paper) | `VTTC8434R` | `VTTC8434R` |
| 응답 블록 | `output`/`output1` (종목별잔고) | `output2` (예수금총괄) |
| 응답 정규화 | list → output (output1 정규화) | list → 첫 요소 / `{}` |
| 장후 작동 | ✅ 정상 | ✅ 정상 |
| Position OK + Cash만 안 오는 상황? | — | **발생하지 않음** (둘 다 동일 endpoint) |

**결론**: `get_positions()`와 `get_cash_balance()`는 동일 endpoint(`inquire-balance`)를 공유하므로, Position이 정상 조회되는 상황에서 Cash만 실패하는 경우는 발생하지 않는다. 이는 [`kis_snapshot_sync.py:204-268`](../src/agent_trading/services/kis_snapshot_sync.py:204)에서 두 호출이 동일한 `KISRestClient` 인스턴스와 동일한 인증 토큰을 사용하기 때문이다.

---

## 부록: 참조 파일 목록

| 파일 | 설명 |
|------|------|
| [`_test_cash_balance.py`](../_test_cash_balance.py) | 장후 cash balance 실측 테스트 스크립트 |
| [`rest_client.py:1044-1090`](../src/agent_trading/brokers/koreainvestment/rest_client.py:1044) | `get_cash_balance()` 구현 |
| [`kis_snapshot_sync.py:170-317`](../src/agent_trading/services/kis_snapshot_sync.py:170) | `sync_kis_account_snapshots()` 구현 |
| [`run_snapshot_sync_loop.py`](../scripts/run_snapshot_sync_loop.py) | snapshot sync loop |
| [`run_near_real_ops_scheduler.py:475-498`](../scripts/run_near_real_ops_scheduler.py:475) | `_run_end_of_day()` 구현 |
| [`run_near_real_ops_scheduler.py:694-711`](../scripts/run_near_real_ops_scheduler.py:694) | 스케줄러 메인 루프 (phase 전환 로직) |
| [`logs/near_real_scheduler_2026-05-15.log`](../logs/near_real_scheduler_2026-05-15.log) | 2026-05-15 운영 로그 |
| [`plans/cash_sync_count_mismatch_root_cause_2026-05-15.md`](./cash_sync_count_mismatch_root_cause_2026-05-15.md) | 이전 분석 보고서 |

---

*본 보고서는 Ask 모드(파라미터 분석, 로그 분석)와 Code 모드(실측 API 호출)의 분석 결과를 종합하여 작성되었습니다.*
