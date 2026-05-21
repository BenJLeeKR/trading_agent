# Broker Truth Sync + Sell Guard 배포 체크리스트

> **배포 일시**: KST 2026-05-20 (장중 검증)
> **관련 Plan**: [`plans/kis_daily_order_truth_sync_and_duplicate_sell_guard_2026-05-19.md`](plans/kis_daily_order_truth_sync_and_duplicate_sell_guard_2026-05-19.md)
> **배포 스크립트**: [`scripts/deploy_broker_truth_sync.sh`](../scripts/deploy_broker_truth_sync.sh)

---

## 변경 파일 (21 files in git diff, +3 untracked new = ~24 files)

### Git-tracked 변경 (21 files, +2743/-230 lines)
| # | 파일 | 변경 유형 | 설명 |
|---|------|-----------|------|
| 1 | `scripts/run_near_real_ops_scheduler.py` | 수정 | `DEFAULT_TASK_TIMEOUT_SECONDS` 240→120 |
| 2 | `scripts/run_paper_decision_loop.py` | 수정 | `PER_AGENT_HARD_TIMEOUT` 90→120 |
| 3 | `src/agent_trading/api/deps.py` | 수정 | Inspection API 의존성 |
| 4 | `src/agent_trading/api/routes/orders.py` | 수정 | Inspection API 엔드포인트 |
| 5 | `src/agent_trading/api/schemas.py` | 수정 | Response models |
| 6 | `src/agent_trading/brokers/koreainvestment/rest_client.py` | 수정 | ODNO matching/pagination |
| 7 | `src/agent_trading/services/ai_agents/provider_client.py` | 수정 | Provider client 변경 |
| 8 | `src/agent_trading/services/decision_orchestrator.py` | 수정 | Subprocess isolation + sell guard |
| 9 | `src/agent_trading/services/order_sync_service.py` | 수정 | reconcile_required 해소 |
| 10 | `tests/conftest.py` | 수정 | `AGENT_SUBPROCESS_ISOLATION=0` |
| 11 | `tests/scripts/test_run_paper_decision_loop.py` | 수정 | 테스트 |
| 12 | `tests/services/ai_agents/test_orchestrator_agents.py` | 수정 | 테스트 |
| 13 | `tests/services/test_decision_orchestrator.py` | 수정 | 테스트 |
| 14 | `tests/services/test_decision_replay.py` | 수정 | 테스트 |
| 15 | `.gitignore` | 수정 | 캐시 파일 ignore |
| 16 | `plans/BACKLOG.md` | 수정 | 백로그 업데이트 |
| 17 | `plans/decouple_naver_t3_from_decision_submit_gate_2026-05-18.md` | 수정 | Plan 문서 |
| 18 | `plans/reduce_exit_sell_submit_runtime_validation_2026-05-18.md` | 수정 | Plan 문서 |
| 19-21 | `.cache/*.json` (3 files) | 수정 | 토큰 캐시 (git-tracked) |

### 신규 파일 (untracked, 3 files)
| # | 파일 | 설명 |
|---|------|------|
| 22 | `scripts/run_agent_subprocess.py` | **신규** — LLM subprocess isolation runner |
| 23 | `src/agent_trading/services/sell_guard.py` | **신규** — Duplicate sell guard |
| 24 | `plans/test_failures_track_record.md` | **신규** — Pre-existing test failures 문서화 |

---

## 사전 점검

- [x] Pre-existing test failures 2건 확인 및 문서화 → [`plans/test_failures_track_record.md`](../plans/test_failures_track_record.md)
- [ ] `.env` 변경 불필요 확인
  - 신규 env var 없음 (모든 설정은 기존 env var로 동작)
  - `AGENT_SUBPROCESS_ISOLATION`은 `conftest.py`에서 테스트 전용으로 `0` 설정
- [ ] 신규 외부 의존성 없음 확인
  - `sell_guard.py`: 표준 라이브러리 + 내부 모듈만 사용
  - `run_agent_subprocess.py`: 표준 라이브러리 + 내부 모듈만 사용
- [ ] DB migration 불필요 확인
  - `sell_guard.py`는 in-memory LRU cache 사용 (DB 테이블 불필요)
  - `order_sync_service.py`는 기존 `broker_orders` 테이블만 사용
  - `rest_client.py`는 API 호출 방식 변경 (DDL 불필요)

---

## 배포 전 검증 (로컬)

> **Note**: 아래 명령어는 docker-compose `app` 컨테이너 내에서 실행

- [ ] `pip install -e .` 성공 (또는 `docker compose build app` 통과)
- [ ] pytest ai_agents 통과 (332개)
  ```bash
  docker compose exec app python3 -m pytest tests/services/ai_agents/ -v --tb=short 2>&1 | tail -30
  ```
- [ ] pytest services 통과 (1001개)
  ```bash
  docker compose exec app python3 -m pytest tests/services/ -v --tb=short 2>&1 | tail -30
  ```

---

## 배포 절차 (KST 15:30+)

> 장 마감 후 실행 권장 (KST 15:30 이후)

- [ ] `bash scripts/deploy_broker_truth_sync.sh` 실행
  - [ ] Step 1: Git working tree 확인
  - [ ] Step 2: `docker compose build --no-cache app ops-scheduler` 성공
  - [ ] Step 3: `docker compose up -d --force-recreate app ops-scheduler` 성공
  - [ ] Step 4: Health check (HTTP 200) 통과
  - [ ] Step 5: Container status 확인 (`docker compose ps`)
  - [ ] Step 6: Inspection API smoke test 통과 (`GET /orders?limit=1`)
  - [ ] Step 7: Ops-scheduler health check 통과

---

## 장중 검증 (KST 2026-05-20)

| 검증 항목 | 방법 | 기대 결과 |
|-----------|------|-----------|
| RECONCILE_REQUIRED 해소 | Admin UI Reconciliation View 확인 | `RECONCILE_REQUIRED` 상태 주문 0건 |
| Duplicate sell guard 차단 | 동일 종목 연속 sell submit 시도 | 두 번째 요청 차단 (HTTP 429 or 409) |
| Broker truth inspection API | `GET /orders?status=RECONCILE_REQUIRED` | 정상 JSON 응답 |
| Sell availability API | `GET /orders/sell-availability?symbol=...` | 정상 JSON 응답 |
| Ops-scheduler 정상 기동 | `docker compose logs ops-scheduler --tail=50` | 에러 없이 heartbeat 로그 |
| LLM subprocess isolation | Agent decision loop 로그 확인 | `run_agent_subprocess.py` 호출 로그 |

---

## Rollback Plan

문제 발생 시 아래 절차로 롤백:

```bash
# 1. 이전 이미지로 되돌리기
git checkout HEAD~1 -- src/ scripts/ tests/

# 2. 재빌드
docker compose build --no-cache app ops-scheduler

# 3. 재시작
docker compose up -d --force-recreate app ops-scheduler
```
