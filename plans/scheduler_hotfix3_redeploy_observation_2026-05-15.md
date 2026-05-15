# Scheduler Hotfix #3 재배포 관측 보고서

**작성일:** 2026-05-15 13:50 KST  
**작성자:** Roo (운영 자동화)  
**상태:** ✅ Hotfix #3 적용 완료 — `source=live_quote` 정상 출력 확인

---

## 1. 배경

### 1.1 Hotfix #3 개요

Hotfix #3은 [`KISRestClient.get_quote()`](src/agent_trading/brokers/koreainvestment/rest_client.py:1091)의 시그니처 불일치를 수정하는 패치입니다.

- **수정 전:** `get_quote(self, symbol, market)` — 2개의 positional argument (`symbol`, `market`)를 받음
- **수정 후:** `get_quote(self, symbol: str)` — 1개의 argument (`symbol`)만 받음

이 수정은 [`KoreaInvestmentAdapter.get_quote()`](src/agent_trading/brokers/koreainvestment/adapter.py:133)가 `self._rest.get_quote(symbol)`만 호출하도록 변경한 것과 일치합니다.

### 1.2 Hotfix #3이 Scheduler에 미적용된 원인

| 항목 | 내용 |
|------|------|
| **Hotfix 배포 대상** | Docker 컨테이너 (`docker compose build` / `docker compose up -d`) |
| **실제 운영 경로** | 호스트에서 직접 실행되는 `run_near_real_ops_scheduler.py` (PID 130036) |
| **문제** | Scheduler는 호스트 프로세스로, Docker 재빌드와 무관하게 기존 Python 프로세스가 계속 실행됨 |
| **영향** | Scheduler가 spawn하는 subprocess (`run_paper_decision_loop`)도 호스트 Python 사용 → 구버전 코드(bytecode cache)로 실행 |

**이전 관측 보고서:** [`plans/post_hotfix3_submit_transition_observation_2026-05-15.md`](plans/post_hotfix3_submit_transition_observation_2026-05-15.md)

---

## 2. 재시동 절차

### 2.1 타임라인

| 시간 (KST) | 작업 | 상세 |
|-----------|------|------|
| 13:27:30 | 사전 확인 완료 | PID 130036 (scheduler), PID 232605 (subprocess) 확인, 중복 없음 |
| 13:27:31 | 기존 scheduler 종료 (SIGTERM) | `kill 130036` — graceful shutdown 실패 (프로세스 생존) |
| 13:27:36 | 강제 종료 (SIGKILL) | `kill -9 130036` — 즉시 종료 |
| 13:27:38 | 종료 확인 | `ps` 결과 없음 ✅ |
| 13:27:51 | Scheduler 재시작 (1차) | `nohup python3 scripts/run_near_real_ops_scheduler.py &` → PID 233815 |
| 13:28:46 | 1차 dry-run 시작 | timeout 기본값 240초 |
| 13:32:56 | 1차 dry-run 실패 | `returncode=-9 timeout=True duration=250.01s` |
| 13:33:42 | 2차 dry-run 시작 | 자동 재시도 |
| 13:37:52 | 2차 dry-run 실패 | 동일하게 timeout (250.01s) |
| 13:38:47 | 3차 dry-run 시작 | 자동 재시도 |
| 13:42:57 | 3차 dry-run 실패 | 동일하게 timeout (250.01s) |
| 13:43:27 | Scheduler 재시작 (2차) | `kill -9 233815` → `--task-timeout 600` 옵션으로 재시작 → PID 244315 |
| 13:44:36 | 4차 dry-run 시작 | timeout 600초로 증가 |
| 13:48:37 | **`source=live_quote` 최초 확인** | symbol=004000 price=55400 |
| 13:49:29 | 마지막 live_quote 확인 | symbol=005380 price=703000 |
| 13:50:17 | 5차 dry-run 시작 | 정상 순환 |

### 2.2 PID 이력

| 프로세스 | PID | 명령어 | 상태 |
|---------|-----|--------|------|
| 기존 scheduler | 130036 | `python3 scripts/run_near_real_ops_scheduler.py` | ❌ 종료 (SIGKILL) |
| 기존 subprocess | 232605 | `python3 -m scripts.run_paper_decision_loop --dry-run` | ❌ 함께 종료 |
| 1차 재시작 scheduler | 233815 | `python3 scripts/run_near_real_ops_scheduler.py` | ❌ 종료 (SIGKILL, timeout 문제) |
| **최종 scheduler** | **244315** | `python3 scripts/run_near_real_ops_scheduler.py --task-timeout 600` | **✅ 운영 중** |

---

## 3. Hotfix #3 적용 확인

### 3.1 코드 검증

| 파일 | 시그니처 | 상태 |
|------|---------|------|
| [`KISRestClient.get_quote()`](src/agent_trading/brokers/koreainvestment/rest_client.py:1091) | `(self, symbol: str)` | ✅ 1개 인자 |
| [`KoreaInvestmentAdapter.get_quote()`](src/agent_trading/brokers/koreainvestment/adapter.py:133) | `self._rest.get_quote(symbol)` | ✅ symbol만 전달 |

### 3.2 로그 기반 검증 — `source=live_quote` 출력 확인

| 시간 | Symbol | 가격 | 소스 |
|------|--------|------|------|
| 13:48:37 | 004000 | 55,400 | `live_quote` ✅ |
| 13:48:43 | 004020 | 46,750 | `live_quote` ✅ |
| 13:48:51 | 004170 | 536,000 | `live_quote` ✅ |
| 13:48:58 | 004370 | 392,500 | `live_quote` ✅ |
| 13:49:09 | 004800 | 227,500 | `live_quote` ✅ |
| 13:49:19 | 004990 | 28,650 | `live_quote` ✅ |
| 13:49:29 | 005380 | 703,000 | `live_quote` ✅ |

### 3.3 부재 확인 (이전 오류)

| 이전 오류 | Hotfix #3 적용 후 |
|-----------|------------------|
| `get_quote() takes 2 positional arguments but 3 were given` | **발생하지 않음** ✅ |
| `KIS_SMOKE_PRICE(fallback)` 사용 (280500) | **발생하지 않음** ✅ (모든 가격이 실제 시세) |
| `40270000` (모의투자 상/하한가 오류) | **발생하지 않음** ✅ |

---

## 4. 주문 상태 전이 현황

### 4.1 현재 DB 상태 (13:50 KST)

| 상태 | 건수 | 설명 |
|------|------|------|
| `pending_submit` | 96 | 제출 대기 (이전 103 → 96으로 감소) |
| `reconcile_required` | 1 | 정합성 확인 필요 |
| `submitted` | 0 | 아직 제출되지 않음 |

### 4.2 분석

- `pending_submit`이 103에서 96으로 감소한 것은 post-submit sync가 일부 주문을 정리한 것으로 추정
- 현재 scheduler는 **dry-run 모드**로만 실행 중 (실제 submit 없음)
- Scheduler의 submit 게이트 로직이 dry-run 완료 후 submit으로 전환될 것으로 예상되나, dry-run이 지속적으로 timeout 나면서 submit 단계까지 도달하지 못함
- `--task-timeout 600` 적용 후 dry-run이 성공했으므로, 다음 cycle부터 submit 게이트 진입 가능

---

## 5. 발견된 추가 문제점

### 5.1 Scheduler Task Timeout (P1)

| 항목 | 내용 |
|------|------|
| **증상** | `run_paper_decision_loop --dry-run`이 240초 이내 완료되지 못함 |
| **원인** | `DEFAULT_TASK_TIMEOUT_SECONDS = 240`이 너무 짧음. 실제 dry-run 소요 시간은 약 250~300초 |
| **임시 조치** | `--task-timeout 600` 옵션으로 scheduler 재시작 (PID 244315) |
| **권장 조치** | `DEFAULT_TASK_TIMEOUT_SECONDS`를 600으로 증가하거나, 환경변수로 설정 가능하게 개선 |

### 5.2 KIS OAuth2 Token Rate Limit (P2)

| 항목 | 내용 |
|------|------|
| **증상** | `HTTP 403 (msg_cd=EGW00133): 접근토큰 발급 잠시 후 다시 시도하세요(1분당 1회)` |
| **영향** | Snapshot sync 실패 (oauth2 token refresh 실패) |
| **빈도** | scheduler 재시작 시 항상 발생 (초기 1회) |
| **심각도** | 낮음 — 재시도 시 정상 동작 |

### 5.3 Pre-market Snapshot Sync 파싱 경고 (P3)

| 항목 | 내용 |
|------|------|
| **증상** | `could not parse sync summary from stdout` |
| **원인** | `_parse_snapshot_sync_summary()`가 stderr에서 JSON을 찾지 못함 |
| **영향** | 없음 (경고만 출력) |

---

## 6. 결론

### 6.1 Hotfix #3 적용 결과

| 지표 | 결과 |
|------|------|
| `source=live_quote` 출력 | ✅ **7개 symbol 모두 정상 출력** |
| `get_quote()` 에러 | ✅ **0건** (이전에는 매 cycle마다 발생) |
| `KIS_SMOKE_PRICE(fallback)` | ✅ **0건** (이전에는 모든 가격이 fallback) |
| `40270000` 오류 | ✅ **0건** (이전에는 3건 발생) |
| 실시간 시세 반영 | ✅ **실제 KIS API 시세로 가격 결정** |

### 6.2 잔여 병목

1. **Scheduler timeout 기본값 240초** — `--task-timeout 600`으로 임시 조치 완료, 코드 기본값 변경 필요
2. **`pending_submit` 96건 미처리** — dry-run만 실행 중, submit 게이트 통과 후 처리 필요
3. **`submitted` 0건** — 아직 실제 제출 단계까지 도달하지 못함

### 6.3 권장 후속 조치

1. `DEFAULT_TASK_TIMEOUT_SECONDS`를 600으로 증가 (코드 변경)
2. Scheduler가 submit 게이트를 통과하면 `pending_submit` → `submitted` 전이 모니터링
3. 장 마감 후 EOD(End-of-Day) 프로세스 정상 동작 확인
