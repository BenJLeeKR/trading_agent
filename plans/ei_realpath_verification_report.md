# EI 실경로 검증 보고서 — Postgres + OpenDART 데이터 기준 P1-A/P1-B Prompt 확인

## 1. 생성한 스크립트 파일

[`scripts/ei_realpath_verification.py`](scripts/ei_realpath_verification.py)

- Read-only 검증 전용 (DB write 없음, provider 호출 없음)
- `postgres_runtime()` → `list_by_symbol()` → `_build_user_prompt()` 직접 호출
- 10개 검증 항목 자동 체크 + exit code 반환

## 2. 실제 실행 명령

```bash
cd /workspace/agent_trading && . /workspace/agent_trading/.env && python3 -m scripts.ei_realpath_verification
```

## 3. 조회된 symbol / event count

| 항목 | 값 |
|------|-----|
| Symbol | `030200` |
| 조회 조건 | `list_by_symbol(symbol="030200", since=2026-05-09 00:00:55Z)` (72h window) |
| 조회 결과 | **5건** |
| 각 event 상세 | `published_at=2026-05-11 00:00Z`, `ingested_at=2026-05-11 09:46Z` |

## 4. 72h retention 확인 결과

- 현재 시각: `2026-05-12 00:00:55Z`
- `since = now - 72h = 2026-05-09 00:00:55Z`
- 모든 5개 event의 `published_at = 2026-05-11` → `since` 이후 → **모두 72h window 내 포함** ✅
- `PostgresExternalEventRepository.list_by_symbol()`의 SQL `WHERE published_at >= $2` 조건 정상 작동 확인

## 5. Provenance tag 확인 결과

| 태그 | 결과 |
|------|------|
| `[src:opendart]` | ✅ 존재 |
| `[tier:T1]` | ✅ 존재 |
| `[Y\|임원ㆍ주요주주특정증권등소유상황보고서]` | ✅ 존재 |
| `[2026-05-11]` | ✅ 존재 |
| `[issuer:00190321]` | ✅ 존재 |

**실제 생성된 prompt event line:**
```
  [src:opendart] [tier:T1] [Y|임원ㆍ주요주주특정증권등소유상황보고서] [2026-05-11] [issuer:00190321] 임원ㆍ주요주주특정증권등소유상황보고서
```

## 6. 생략 태그 확인 결과

| 태그 | 결과 | 이유 |
|------|------|------|
| `⚠️STALE` | ✅ 미표시 | `ingested_at=09:46` (24h 이내, fresh) |
| `[severity:medium]` | ✅ 미표시 | `severity=medium`은 default → 생략 |
| `[severity:...]` | ✅ 미표시 | 모든 severity 태그 생략 |
| `[positive]` / `[negative]` | ✅ 미표시 | `direction=neutral`은 default → 생략 |

## 7. Exit code

**`exit 0`** — 10개 항목 ALL PASS ✅

## 8. 남은 리스크 1개

**`issuer_code → symbol` 해석 경로 부재 (P0-3 미구현)**

현재 `list_by_symbol()`은 `symbol` 단독 조회만 수행한다. `issuer_code` 기반 fallback query가 없어서, `symbol=null`인 20개 event는 orchestrator가 전혀 읽지 못한다. P0-3 설계 문서(`plans/ei_agent_enhancement_phase1_design.md`)에는 `InstrumentRepository`를 통한 `issuer_code → symbol` resolve 로직이 제안되었으나 아직 구현되지 않았다.

- 영향: 20%의 OpenDART event가 EI prompt에 포함되지 않음
- 심각도: 중간 (현재 universe가 좁아 실제 tradeable symbol 누락 가능성은 낮지만, universe 확장 시 문제)

## 9. 다음 직접 액션 1개

**P1-A/P1-B 통합 테스트를 기존 `test_decision_submit_pipeline.py`에 유지하고, 필요시 `ei_realpath_verification.py`를 CI 검증 파이프라인에 등록**

현재 InMemory 통합 테스트(`TestP1AandP1BIntegration`, 5 tests)와 실경로 검증 스크립트(`ei_realpath_verification.py`)가 모두 통과했다. 다음 단계로:

1. `ei_realpath_verification.py`를 Makefile에 `make verify-ei-realpath` 타겟으로 등록
2. P0-3 (`issuer_code` fallback query) 설계 검토 및 우선순위 결정
3. universe 확장 시 실경로 검증 스크립트를 여러 symbol 대상으로 확장
