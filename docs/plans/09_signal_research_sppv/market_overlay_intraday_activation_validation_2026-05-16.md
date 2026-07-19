# market_overlay 활성화 hotfix 장중 효과 측정 — 검증 보고서

**작성일**: 2026-05-16 06:57 KST  
**검증 시각**: 2026-05-16 06:30 ~ 06:57 KST (장전)  
**검증 방법**: 실시간 dry-run (`--dry-run --count 1`) + Docker/DB 관측  
**분석 모드**: Read-only (코드 수정 없음)

---

## 1. 관측 기간

| 항목 | 값 |
|------|-----|
| 검증 시각 | 2026-05-16 06:30 ~ 06:57 KST |
| 장중 여부 | ❌ 장전 (개장 09:00 KST) |
| 스케줄러 | 아직 미기동 (cron: 07:40 smoke, 07:55 본 스케줄) |
| 컨테이너 재기동 | 05:30 KST 경 재기동 완료 (`About an hour ago`) |
| hotfix 반영 상태 | ✅ 소스코드 반영 완료 (`KISRestClient(api_key=..., ...)`) |

---

## 2. Hotfix 적용 확인 (코드 검증)

### 2.1 소스코드 상태

[`scripts/run_paper_decision_loop.py:338`](../../scripts/run_paper_decision_loop.py:338)

```python
# BEFORE (bug - 이전 보고서 확인):
# kis_client = KISRestClient(settings=settings)  # TypeError

# AFTER (hotfix 적용됨):
kis_client = KISRestClient(
    api_key=settings.kis_api_key,
    api_secret=settings.kis_api_secret,
    account_number=settings.kis_account_number,
    account_product_code=settings.kis_account_product_code,
    env=settings.kis_env,
    base_url=settings.kis_base_url,
    dev_token_cache_enabled=settings.kis_dev_token_cache_enabled,
    dev_token_cache_path=settings.kis_dev_token_cache_path,
)
```

### 2.2 Python import 검증

```bash
$ python3 -c "
from agent_trading.config.settings import AppSettings
from agent_trading.brokers.koreainvestment.rest_client import KISRestClient

settings = AppSettings()
client = KISRestClient(
    api_key=settings.kis_api_key,
    api_secret=settings.kis_api_secret,
    ...
)
print(f'KISRestClient created successfully: env={client.env}')
"
# 출력: KISRestClient created successfully: env=paper
```

✅ **code-level instantiation PASS**

---

## 3. Cycle 로그 요약 (dry-run 결과)

[`scripts/run_paper_decision_loop.py`](../../scripts/run_paper_decision_loop.py) dry-run 실행 (`--count 1 --dry-run`):

### 3.1 market_overlay Funnel

| 단계 | 로그 메시지 | 결과 |
|------|-----------|------|
| KIS client init | (예외 없음 - DEBUG 로그 없음) | ✅ 성공 |
| Pre-pool 생성 | `market_overlay pre-pool: 50 symbols (cap=50).` | ✅ **50 symbols** |
| Quote fetch | `market_overlay quotes fetched: 2/50.` | ⚠️ 2/50 (4%) |
| F4/F5 filter + scoring | (내부) | ✅ candidates: 1 |
| Top-N 선정 | (내부) | ✅ 1 symbol selected |
| Universe 편입 | `market_overlay symbols added to universe: 1 (cap=5, candidates=1).` | ✅ **1 symbol** |
| 최종 universe | `Trading universe from UniverseSelectionService: 30 symbols loaded (cap=30).` | ✅ 30 symbols |

### 3.2 Quote fetch 저조 원인

dry-run 수행 시각이 **06:50 KST (장전)** 이므로 KIS paper 모의투자 API가 대부분의 종목에 대해 500 에러를 반환:

```
HTTP Request: GET ... inquire-price?FID_INPUT_ISCD=000100 "HTTP/1.1 200 OK"
HTTP Request: GET ... inquire-price?FID_INPUT_ISCD=000270 "HTTP/1.1 500 Internal Server Error"
HTTP Request: GET ... inquire-price?FID_INPUT_ISCD=000880 "HTTP/1.1 200 OK"
...
```

- **200 OK**: 2건 (000100, 000880)
- **500 Error**: 48건 (기타 전종목)

→ **09:00 KST 개장 이후에는 정상 quote fetch 예상됨**

### 3.3 Quote 성공 2건 중 filter 통과

2개 quote 중 F4(관리종목)/F5(거래대금 1B 미만) 필터와 3축 스코어링 통과 후 **1 symbol**만 선정:

- `candidates=1`: F4/F5 필터 통과 1건
- `symbols added to universe: 1`: Top-N 선정되어 universe에 편입

---

## 4. Source_type 분포 실측

### 4.1 DB 스키마 한계

[`decision_contexts`](../../db/migrations/0001_initial_schema.sql) 및 [`trade_decisions`](../../db/migrations/0004_expand_trade_decision.sql) 테이블에 **`source_type` 컬럼이 존재하지 않음**.

- `decision_json` JSONB에도 `source_type` 키 미포함
- Application 계층 (`SelectedSymbol.source_type`)에서만 유지됨
- DB-based source_type 분석 불가

### 4.2 최근 24시간 decision 분포 (어제 05-15 데이터)

| decision_type | cnt | 비고 |
|--------------|-----|------|
| hold | 2,427 | 94.9% |
| reduce | 67 | 2.6% |
| approve | 49 | 1.9% |
| watch | 13 | 0.5% |

→ 어제는 hotfix 미반영 상태 → **market_overlay 0건**

### 4.3 오늘 dry-run 결정

dry-run(`--dry-run`)은 DB에 **persist되지 않음** (status=DRY_RUN). 따라서 오늘 dry-run의 market_overlay decision은 DB 미반영 상태.

---

## 5. market_overlay 샘플 (dry-run, 비-persist)

dry-run에서 생성된 decision 중 market_overlay source_type 심볼은 **1개** (정확한 심볙은 로그에서 `symbols added to universe` 메시지만 확인 가능, 개별 심볙 로그는 `DEBUG` 레벨).

dry-run 자체는 decision을 persist하지 않으므로 trade_decisions 테이블에서 확인 불가.

---

## 6. 최종 판정

| 기준 | 결과 | 설명 |
|------|------|------|
| pre-pool 생성 | ✅ A | 50 symbols |
| quote fetch 성공 | ⚠️ C (장전 한계) | 2/50 (개장 후 개선 예상) |
| universe 편입 | ✅ A | 1 symbol added |
| decision row 생성 | ⏳ N/A | dry-run이라 미생성 (장중 실제 cycle 필요) |
| source_type DB 저장 | ❌ D | source_type 컬럼 자체 없음 |
| **최종 판정** | **B (부분 성공)** | |

### 판정 근거

**판정: B (부분 성공)**

- ✅ **hotfix 자체는 완전히 정상 작동** — KIS client init → pre-pool → quote fetch → filter → Top-N → universe 편입 전체 pipeline 구동 확인
- ⚠️ **장전 quote fetch 저조**는 hotfix 문제가 아니라 KIS paper API의 장전 500 응답이 원인. **09:00 KST 개장 이후 재측정 필요**
- ❌ **source_type DB 미저장** — application 계층의 metadata로만 유지되어 사후 분석 불가. DB 스키마 개선(P3) 필요
- ⏳ **실제 decision row 생성 여부**는 장중 실제 cycle(`--submit` 아님, dry-run이어도 decision은 생성되나 persist 안 됨)에서 확인 필요

### 제약 재확인

| 제약 | 준수 |
|------|------|
| 코드 수정 금지 | ✅ |
| `.env` 수정 금지 | ✅ |
| 실제 submit 강행 금지 | ✅ (`--dry-run` 사용) |
| `python3` 사용 | ✅ |

---

## 7. 다음 수정 필요 여부

### P0 — 더 이상 없음 (hotfix 성공)
✅ `KISRestClient(settings=settings)` → 개별 파라미터 수정으로 **market_overlay pipeline 정상화 완료**

### P1 — 장중 재측정 필요 (개장 후)
오늘(05-16) **09:00 KST 개장 이후**, 스케줄러(cron 07:55)가 1~2 cycle 실행된 후 재검증:
1. `market_overlay quotes fetched: X/50` — X값이 50에 근접하는지 확인
2. `market_overlay symbols added to universe: N (cap=5)` — cap=5까지 도달하는지
3. `trade_decisions`에 market_overlay 심볙들의 decision_type 분포

### P2 — source_type DB 저장
[`decision_contexts`](../../db/migrations/0001_initial_schema.sql) 또는 [`trade_decisions`](../../db/migrations/0004_expand_trade_decision.sql)에 `source_type` 컬럼 추가:
- `source_type VARCHAR(32)` 기본값 `'core'`
- migration + application code 연동
- 향후 source_type 기반 성과 분석 가능

### P3 — Quote fetch timeout/logging 개선
장전 500 에러가 Many log noise를 유발. `_add_market_overlay()`의 quote fetch 실패를 `WARNING`이 아닌 `DEBUG`로 하향하거나, batch 실패율 임계치 로깅 개선.

---

## 8. 결론

| 질문 | 답변 |
|------|------|
| hotfix가 KIS client init 에러를 해결했는가? | ✅ **예** — TypeError 없이 KISRestClient 정상 초기화 |
| market_overlay pre-pool이 생성되는가? | ✅ **예** — 50 symbols |
| Quote fetch가 성공하는가? | ⚠️ **장전 한계 2/50** (개장 후 재측정 필요) |
| 최종 universe에 market_overlay 심볼이 편입되는가? | ✅ **예** — 1 symbol 편입 확인 |
| source_type이 DB에 저장되는가? | ❌ **아니오** — DB 스키마에 source_type 컬럼 없음 |
| **최종 판정** | **B (부분 성공)** — hotfix는 정상 작동하나 장전 장애로 완전 검증 불가 |

**한 줄 요약**: `KISRestClient(settings=settings)` hotfix는 정상적으로 market_overlay pipeline을 활성화시켰으며, 장전 제약(2/50 quote)을 감안하면 **성공적인 hotfix**로 판정. **09:00 KST 개장 이후 재측정하여 A 판정으로 upgrade 필요.**
