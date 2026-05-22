# `decision_submit_gate` 완료 블록 들여쓰기 버그 수정 보고서

- **날짜:** 2026-05-22
- **관련 태스크:** Cadence trace 시간 기준 보정 후속 수정 (Task 5)

---

## 1. 버그 요약

[`_run_intraday_due_tasks()`](scripts/run_near_real_ops_scheduler.py) 함수 내 `decision_submit_gate` 완료 처리 블록(9개 라인)이 [`if tasks["decision"].due:`](scripts/run_near_real_ops_scheduler.py:905) 조건문 **바깥**(4칸 indent)에 위치하여, decision이 due가 아니어도 `mark_ran()`이 항상 실행되는 제어 흐름 버그.

### 영향

- `mark_ran()`이 decision 미실행 시에도 `last_run_at`을 갱신 → `due`가 영원히 `True`가 될 수 없음
- `CADENCE_TRACE action=complete`가 decision 미실행 시에도 출력 → 모니터링 혼란
- 같은 함수 내 snapshot/event/post_submit 완료 블록은 올바르게 `if` 블록 내부(8칸 indent)에 위치

---

## 2. 근본 원인

### 수정 전 코드 (버그)

```python
    if tasks["decision"].due:                          # 905: 4칸
        result = await _run_and_record(...)             # 944: 8칸
        ...budget logic...                              # 951-972: 8칸
                                                        # ← if 블록 종료 (972번)
    completed_at = datetime.now(KST)                    # 973: 4칸 ← if 바깥! (버그)
    tasks["decision"].mark_ran(completed_at)             # 974: 4칸 ← if 바깥! (버그)
    logger.info("CADENCE_TRACE decision ...")           # 977: 4칸 ← if 바깥! (버그)
```

### 수정 후 코드

```python
    if tasks["decision"].due:                           # 905: 4칸
        result = await _run_and_record(...)             # 944: 8칸
        ...budget logic...                              # 951-972: 8칸
        completed_at = datetime.now(KST)                # 973: 8칸 ← if 내부
        tasks["decision"].mark_ran(completed_at)         # 974: 8칸 ← if 내부
        logger.info("CADENCE_TRACE decision ...")       # 977: 8칸 ← if 내부
```

---

## 3. 수정한 파일

| 파일 | 변경 내용 |
|------|----------|
| [`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py) | Lines 973-983 indent를 4칸 → 8칸으로 변경 (9개 라인) |

---

## 4. 추가한 테스트

| 테스트 함수 | 파일 | 검증 내용 |
|------------|------|----------|
| [`test_decision_complete_block_not_executed_when_not_due`](tests/scripts/test_run_near_real_ops_scheduler.py) | [`tests/scripts/test_run_near_real_ops_scheduler.py`](tests/scripts/test_run_near_real_ops_scheduler.py) | `decision.due == False` 시 `mark_ran()` 호출되지 않음, `CADENCE_TRACE action=start/complete` 로그 미출력 |

---

## 5. 테스트 결과

```
109 passed in 1.15s
```

- 기존 108개 테스트 → **회귀 없음**
- 신규 테스트 1개 → **통과**
- snapshot/event/post_submit 완료 블록 indent 구조 영향 없음 확인

---

## 6. 배포 검증

| 단계 | 결과 |
|------|------|
| `docker compose build ops-scheduler` | ✅ 성공 |
| `docker compose up -d ops-scheduler` | ✅ 성공 (컨테이너 재생성) |
| Health check (`curl /health`) | `{"status": "ok", "database": "connected", "scheduler.healthy": true}` |
| 컨테이너 로그 | 에러 없음, advisory lock 정상 획득, heartbeat 정상 동작 |

---

## 7. 관련 문서

- [Cadence trace 시간 기준 보정 보고서 (Task 4)](plans/refine_cadence_trace_and_last_run_at_semantics_for_snapshot_and_decision_tasks_2026-05-22.md)
- [KIS Snapshot Sync Cadence 리팩토링 보고서 (Task 3)](plans/refactor_kis_snapshot_sync_cadence_to_reduce_scheduler_coupling_2026-05-22.md)
