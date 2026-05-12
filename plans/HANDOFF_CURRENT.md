# Current Work Handover — Phases A-D

> **작성일**: 2026-05-12
> **목적**: KIS paper mock post-submit sync 검증 및 문서화 완료. 다음 작업(뉴스 source adapter 설계)로 전환 전 현재 상태 요약.

---

## 작업 이력 요약

### Phase A: Post-Submit Sync / Reconciliation E2E 실검증
- **상태**: ✅ 완료
- **핵심 결과**: 장중 post-submit sync E2E 검증 완료. 6개 프로토콜 정합성 버그 발견 및 수정.
- **보고서**: [`plans/post_submit_sync_e2e_report.md`](plans/post_submit_sync_e2e_report.md)
- **수정 파일**:
  - `src/agent_trading/brokers/koreainvestment/rest_client.py` — Bug 3-8 수정 (시그니처, 필드명, enum 값)
  - `src/agent_trading/brokers/koreainvestment/adapter.py` — `get_order_status()` 단순 위임 복원

### Phase B: Post-Submit Sync 상태수렴 미완료 원인 분리
- **상태**: ✅ 완료 (Read-Only 분석)
- **핵심 결과**: `get_order_status()`의 ODNO 매칭(line 896)이 `broker_order_id`와 `item.get("ODNO")` 비교에 실패 → `RECONCILE_REQUIRED` 수렴. 원인은 paper mock `inquire-daily-ccld`가 빈 배열 반환으로 추정.
- **보고서**: [`plans/post_submit_sync_status_convergence_analysis.md`](plans/post_submit_sync_status_convergence_analysis.md)

### Phase C: KIS Paper `inquire-daily-ccld` 응답 계측
- **상태**: ✅ 완료
- **핵심 결과**: Probe 스크립트(`/tmp/probe_inquire_daily_ccld.py`)로 실제 payload 캡처 → `output: []` (빈 배열) 확정. ODNO 매칭 실패의 **근본 원인 확정**.
- **코드 변경**: `rest_client.py:get_order_status()`에 DEBUG/INFO instrumentation logging 2개 지점 추가 (Live 검증 시까지 유지)
- **보고서**: [`plans/inquire_daily_ccld_payload_capture_report.md`](plans/inquire_daily_ccld_payload_capture_report.md)

### Phase D: Paper Mock 한계 문서화 + 검증 범위 재정의 + Live 체크리스트
- **상태**: ✅ 완료
- **핵심 결과**: Paper mock 한계를 "버그"가 아닌 "검증 범위 제약"으로 분리. Paper 환경 성공 기준 재정의. Live 검증 전 체크리스트 문서화.
- **수정 문서** (4개):
  - `plans/paper_submit_smoke_ops_checklist.md` — 9-D Paper Mock 한계표, 9-E Sync 확인 SQL
  - `plans/post_submit_sync_e2e_report.md` — 최종 판정 분리
  - `plans/paper_submit_smoke_market_hours_execution.md` — RECONCILE_REQUIRED 행 추가
  - `plans/inquire_daily_ccld_payload_capture_report.md` — Section 7 logging 제거 조건 보강
- **신규 문서** (2개):
  - `plans/paper_mock_boundary_validation_scope.md` — 6항목 보고서 + logging 제거 조건 + Live 체크리스트 요약
  - `plans/live_verification_prerequisites.md` — Live 검증 전 체크리스트 (장중, 계정/토큰, snapshot, sync loop)
- **코드 변경**: 없음 (Phase C instrumentation 유지)

---

## 현재 확정된 상태

### Paper Mock 한계 (코드 버그 아님)
| 항목 | 상태 |
|------|------|
| Paper `inquire-daily-ccld` | `output: []` 반환 (체결 데이터 없음) |
| ODNO 매칭 | Paper에서 매칭 불가 (loop 미실행) |
| Post-submit sync 결과 | `reconcile_required` 고정 (정상) |
| 영향 | Paper 환경에서 terminal status 수렴 검증 불가 |
| 대응 | "검증 범위 제약"으로 문서화. Live에서만 terminal status 검증 |

### Logging 제거 조건 (3가지 모두 충족 필요)
1. Live `inquire-daily-ccld` payload `output_count > 0`
2. ODNO 매칭 성공 (INFO logging에 match failure 미출력)
3. Terminal status 수렴 (FILLED/CANCELLED/REJECTED)

### Live 검증 전 체크리스트
| 항목 | 확인 사항 |
|------|----------|
| 장중 여부 | 월~금 08:30~15:30 KST |
| 계정/토큰 | `KIS_ENV=real`, Live key/secret, token cache 삭제 |
| Snapshot freshness | 최근 sync 5분 이내 |
| Sync loop 경로 | `run_post_submit_sync_loop.py` 존재 |

---

## 관련 문서 목록

| 문서 | 내용 | 위치 |
|------|------|------|
| E2E 검증 보고서 | Phase A 결과, 6개 버그 | `plans/post_submit_sync_e2e_report.md` |
| 상태수렴 분석 보고서 | Phase B ODNO 매칭 실패 경로 | `plans/post_submit_sync_status_convergence_analysis.md` |
| Payload 계측 보고서 | Phase C `output: []` 확정 | `plans/inquire_daily_ccld_payload_capture_report.md` |
| 종합 보고서 | Phase D paper mock 한계 문서화 | `plans/paper_mock_boundary_validation_scope.md` |
| 운영 체크리스트 | Smoke 실행 절차 + 검증 기준 | `plans/paper_submit_smoke_ops_checklist.md` |
| 장중 실행 절차 | Market hours smoke 실행 | `plans/paper_submit_smoke_market_hours_execution.md` |
| Live 체크리스트 | Live 검증 전 준비 사항 | `plans/live_verification_prerequisites.md` |
| Paper/Live 경계 | Mode 전환 절차 | `plans/mode_boundary_paper_live.md` |

---

## 다음 작업으로 넘어가는 시점의 코드 상태

- **변경 없음 영역**: admin UI, DB schema, broker submit semantics, rate limit — 모두 변경 없음
- **유지 중인 계측**: `rest_client.py:896-928` — DEBUG/INFO instrumentation logging (Live 검증 시까지)
- **Probe 스크립트**: `/tmp/probe_inquire_daily_ccld.py` — 임시 진단용, repo 관리 대상 아님

---

## 알려진 리스크

1. **Reconciliation loop Live 경로 미검증**: `RECONCILE_REQUIRED` → FILLED/CANCELLED/REJECTED 수렴 분기를 Paper에서 검증 불가. Live 첫 submit 시 디버깅 필요.
2. **Live `inquire-daily-ccld` 응답 구조 불확실**: Paper mock(`output: []`)과 Live 응답 구조가 다를 가능성. Instrumentation logging으로 첫 호출 시 탐지 가능.
3. **Token cache 전환 누락 위험**: Paper→Live 전환 시 `.cache/kis_token.json` 삭제 필요. 삭제하지 않으면 `HTTP 403` 발생.
