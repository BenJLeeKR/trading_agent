# KIS Paper Order Readiness — Phase 1-C 실행 보고서

**실행 일시**: 2026-05-10 11:35 UTC (KST 20:35)
**실행 환경**: paper (`KIS_ENV=paper`, 계좌 50186448)
**실행자**: Roo (Phase 1-C, 진단 전용)

---

## 1. Step 0: Env/Config 확인 결과

| 항목 | 값 | 상태 |
|------|-----|------|
| `KIS_ENV` | `paper` | ✅ |
| `KIS_ACCOUNT_NO` | `50186448` (paper 계좌) | ✅ |
| Token cache | `.cache/kis_token.json` 존재 | ✅ |
| `KIS_DEV_TOKEN_CACHE_ENABLED` | `true` | ✅ |
| `KIS_APP_KEY` | 설정됨 | ✅ |
| `KIS_APP_SECRET` | 설정됨 | ✅ |
| `DATABASE_URL` | shell export 필요 (`.env` 미포함) | ⚠️ (export로 해결) |
| `KIS_BASE_URL` | `openapivts.koreainvestment.com:29443` (paper) | ✅ |
| `KIS_PAPER_REST_RPS` | 기본 1 → **2로 override 필요** (positions + cash) | ⚠️ (해결) |

**결론**: Paper env 정상. `--all` flag는 현재 env에 등록된 paper 계좌만 대상.

---

## 2. Snapshot Sync 실행 결과

| 항목 | 값 |
|------|-----|
| 실행 명령 | `sync_kis_snapshots.py --all --format json` |
| 최초 실행 | 실패 (RPS=1, cash balance `Global REST cap exhausted`) |
| 재실행 (`KIS_PAPER_REST_RPS=2`) | **성공** ✅ |
| 최종 `status` | `completed` |
| `succeeded_accounts` | 1 |
| `cash_synced_count` | 1 |
| `failed_accounts` | 0 |

**참고**: Paper env는 RPS 기본값이 1이라 positions + cash balance 동시 조회 시 budget을 초과. `KIS_PAPER_REST_RPS=2` env var 설정으로 해결.

---

## 3. Snapshot Sync Health / Run 기록 반영 결과

```python
# Health Summary
is_stale = False           # ✅ 최신 상태
consecutive_failures = 0   # ✅ 연속 실패 없음
last_successful_run_at = 2026-05-10 11:31:35 UTC  # ✅ 정상
last_run_at = 2026-05-10 11:31:35 UTC             # ✅ 정상
```

---

## 4. Stale Snapshot Blocker 해소 여부

**✅ 해소됨**

처음에는 `is_stale=True` (history 없음) 상태였으나, snapshot sync 성공 후:

- `is_stale = False`
- `consecutive_failures = 0`
- Health summary 정상 반환

Paper Gate의 `_check_snapshot_freshness()` 통과 가능.

---

## 5. Dry-Run 성공/실패 여부

**❌ 실패 (exit code 1)**

Dry-run은 **hang 없이 60초 내 정상 종료**되었으나, 다음 두 가지 오류로 exit code 1 반환:

### 5-A. `UniqueViolationError` (비차단)
```
duplicate key value violates unique constraint "uq_decision_context_correlation"
```
- 원인: 이전 실행에서 생성된 seed data가 이미 존재
- 영향: **비차단 경고** — 해당 오류는 내부적으로 catch되어 로그만 남기고 계속 진행

### 5-B. `EventInterpretationAgent failed` (차단)
```
EventInterpretationAgent failed — returning default output (safe fallback)
JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```
- **근본 원인: `DEEPSEEK_MODEL_ID=deepseek-v4-pro` → 잘못된 모델명**
- DeepSeek API에 HTTP 200으로 요청은 성공하지만, model name이 유효하지 않아 **빈 응답 본문** 반환
- Agent가 빈 응답을 JSON 파싱 시도 → `JSONDecodeError`
- Safe fallback으로 default output 반환, 그러나 상위 파이프라인에서 exit code 1 처리

---

## 6. LLM Provider / API Key 진단 결과

| 진단 항목 | 결과 |
|-----------|------|
| `LLM_PROVIDER` | `deepseek` ✅ |
| `DEEPSEEK_API_KEY` | 존재 (`sk-9890...6186`) ✅ |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` ✅ |
| `DEEPSEEK_MODEL_ID` | **`deepseek-v4-pro`** ❌ **(원인)** |
| DeepSeek API `/models` | HTTP 200 ✅ |
| DeepSeek API chat (`deepseek-v4-pro`) | HTTP 200 but **empty response** ❌ |
| DeepSeek API chat (`deepseek-chat`) | HTTP 200, 정상 응답 ✅ |
| API key 유효성 | **유효함** ✅ (key 자체는 문제 없음) |
| Provider agent 생성 여부 | 생성됨 (`_build_provider_agent()` → real agent) |

**판정**: API key/base_url은 정상. **`DEEPSEEK_MODEL_ID=deepseek-v4-pro`가 잘못된 모델명**입니다. `deepseek-chat`으로 변경 시 정상 작동 예상.

---

## 7. 현재 Readiness 판정

> ## 🚦 **실행 금지** ❌
> 
> Dry-run 실패. 잠재적인 LLM 응답 실패로 인해 실제 submit 시도 시
> agent 결정이 fallback으로만 처리되어 의도치 않은 결과 발생 가능.
> 
> **현재 등급**: `실행 금지` → 모델명 수정 후 dry-run 재시도 필요

---

## 8. 남은 Blocker 1~2개

| # | Blocker | 심각도 | 해결 방안 |
|---|---------|--------|-----------|
| 1 | **`DEEPSEEK_MODEL_ID=deepseek-v4-pro` → 빈 응답** | 🔴 HIGH | `.env`에서 `DEEPSEEK_MODEL_ID=deepseek-chat`로 변경 (env var 변경, 코드 변경 아님) |
| 2 | **Dry-run 미실시** | 🟡 MED | 모델명 수정 후 `run_orchestrator_once.py --dry-run --output json` 재실행하여 full pipeline 통과 확인 |

---

## 9. 다음 직접 액션 1개

```
1. .env 파일에서 DEEPSEEK_MODEL_ID를 "deepseek-v4-pro" → "deepseek-chat"으로 변경
   (코드 변경 없음, 환경 변수만 수정)

2. export DATABASE_URL="postgresql+asyncpg://..."  # DB 연결
   export KIS_PAPER_REST_RPS=2                      # Paper RPS override
   python scripts/run_orchestrator_once.py --dry-run --output json
   # Dry-run 재실행 → 성공 예상

3. Dry-run 성공 시:
   python scripts/run_orchestrator_once.py --submit --output json  # (opt-in)
   # 실제 paper submit smoke 실행 가능
```

---

## 요약

| 구분 | 상태 |
|------|------|
| KIS paper auth | ✅ 정상 (token cache 활용) |
| Snapshot sync (stale) | ✅ 해소됨 |
| Snapshot sync (RPS) | ⚠️ `KIS_PAPER_REST_RPS=2` 필요 (env var) |
| DB connection | ✅ 정상 |
| LLM API key | ✅ 존재, 유효 |
| LLM model ID | ❌ `deepseek-v4-pro` → 빈 응답 → `deepseek-chat` 필요 |
| Dry-run (overall) | ❌ 실패 (LLM empty response) |
| **최종 판정** | **🚦 실행 금지 — 모델명 수정 후 dry-run 재시도 필요** |
