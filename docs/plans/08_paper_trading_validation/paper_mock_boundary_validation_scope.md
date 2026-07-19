# Paper Mock 한계 문서화 + Post-Submit Sync 검증 범위 재정의 — 보고서

> **Phase D 완료 보고서**
> Phase C (inquire-daily-ccld payload 계측) → Phase D (Paper mock 한계 문서화 + 검증 범위 재정의)

---

## 1. 수정한 문서 목록

| # | 문서 | 수정 내용 |
|---|------|----------|
| 1 | [`paper_submit_smoke_ops_checklist.md`](plans/paper_submit_smoke_ops_checklist.md) | **9-C**: `last_synced_at` + `order_state_events`를 성공 기준에 추가. **9-D (신규)**: Paper Mock 한계 비교표 (Paper 허용 vs Live 기대). **9-E (신규)**: Post-Submit Sync 확인 SQL. **9-F**: 기존 9-D를 9-F로 이동, `order_state_events ❌ 미구현` 제거 |
| 2 | [`post_submit_sync_e2e_report.md`](plans/post_submit_sync_e2e_report.md) | 종합 판정 제목: "부분 성공" → "부분 성공 — Paper Mock 한계 분리". 제약을 "Paper Mock 한계 (코드 버그 아님)"와 "제약 (코드/운영)"으로 분리 |
| 3 | [`paper_submit_smoke_market_hours_execution.md`](plans/paper_submit_smoke_market_hours_execution.md) | 예상 결과표에 `⚠️ ODNO 발급 + RECONCILE_REQUIRED` 행 추가. Paper Mock 한계 note 추가 |
| 4 | [`inquire_daily_ccld_payload_capture_report.md`](plans/inquire_daily_ccld_payload_capture_report.md) | Section 7: "계측용 logging 제거" → "계측 logging 유지"로 방침 변경. 유지 근거 + 제거 조건 + probe 스크립트 상태 문서화 |

---

## 2. 재정의한 Paper 성공 기준

Paper 환경에서 post-submit sync의 성공 기준은 다음과 같이 재정의합니다.

> **2026-05-13 실증 반영**: 아래 기준 중 `Submit 성공`, `Sync loop 실행`, `order_state_events 기록`은 2026-05-13 APPROVE 실증에서 **모두 ✅ 확인**되었습니다.

| 항목 | 기준 | 비고 | 검증 상태 |
|------|------|------|----------|
| Submit 성공 | ✅ `broker_native_order_id` (ODNO) 발급 | 최소 성공 조건 | ✅ **2026-05-13 실증 완료** |
| Sync loop 실행 | ✅ `last_synced_at` 갱신 | 1회 이상 sync cycle이 정상 실행되어야 함 | ✅ **2026-05-13 실증 완료** |
| `order_state_events` 기록 | ✅ 상태 전이 이력 DB 저장 | `submitted → reconcile_required` 경로도 정상 | ✅ **2026-05-13 실증 완료** |
| `broker_status = reconcile_required` | ✅ **허용 (정상)** | Paper mock의 `inquire-daily-ccld`가 `output: []` 반환하므로 예상된 결과 | ✅ Paper mock 정상 범위 |
| FILLED / CANCELLED / REJECTED 수렴 | ❌ **Paper mock에서 기대 불가** | Live 환경 전용 검증 항목 | ❌ Live 전용 |
| `side` / `requested_quantity` 정확성 | ✅ Submit payload에 정상 반영 | DB `order_requests`에서 확인 | ✅ **2026-05-13 실증 완료** |

**핵심 원칙**: Paper 환경에서는 "sync pipeline이 정상 동작하는가"와 "submit API가 정상 호출되는가"를 검증하고, "terminal status가 무엇으로 수렴하는가"는 검증하지 않습니다. 후자는 Live 환경에서만 검증 가능합니다.

---

## 3. Live와의 차이

| 항목 | Paper | Live |
|------|-------|------|
| `inquire-daily-ccld` 응답 | `output: []` (빈 배열) | 실제 체결 데이터 반환 예상 |
| Post-submit sync 후 broker_status | `reconcile_required` (고정) | FILLED / CANCELLED / REJECTED (실제 체결 상태) |
| ODNO 매칭 성공 | ❌ 매칭 불가 (loop 미실행) | ✅ 매칭 성공 예상 |
| 실제 fills 조회 | ❌ 기대 불가 | ✅ 가능 |
| 검증 가능한 범위 | Sync pipeline 동작 여부, `last_synced_at` 갱신, `order_state_events` 기록 | 전체 order lifecycle + terminal status convergence |
| 검증 불가능한 범위 | Terminal status 수렴, fills 판독, cancel/reject 처리 | 해당 없음 (Live에서는 모든 경로 검증 가능) |

**중요**: Paper mock 한계는 **Live readiness에 영향을 주지 않습니다**. Live 환경의 `inquire-daily-ccld`는 실제 체결 데이터를 반환하므로, ODNO 매칭 로직이 정상 동작할 것으로 예상됩니다. 코드 자체(`rest_client.py:get_order_status()` line 896)의 로직은 정확합니다.

---

## 4. 코드 변경 여부

**Phase D (이번 턴): 코드 변경 없음** — 문서/검증 기준만 수정.

**Phase C (이전 턴) instrumentation logging**: `rest_client.py:get_order_status()`에 DEBUG/INFO logging 2개 지점 추가 완료. 이 logging은 **Live 검증 완료 시까지 유지**하기로 결정.

| 파일 | 변경 내용 | 상태 |
|------|----------|------|
| `rest_client.py:896-928` | DEBUG logging: inquire-daily-ccld 응답 필드 캡처 | **유지 (Live 검증 완료 후 제거)** |
| `rest_client.py:928` | INFO logging: ODNO 매치 실패 시 로그 | **유지 (오류 진단용)** |
| `/tmp/probe_inquire_daily_ccld.py` | Probe 스크립트 (standalone, 임시) | **Repo 관리 대상 아님** |

---

## 5. 남은 리스크 2개

### 5.1 Reconciliation loop의 Live 경로 사전 검증 불가

Paper mock에서 모든 post-submit sync 결과가 `RECONCILE_REQUIRED`로 수렴하므로, reconciliation loop의 다음 분기들을 paper 환경에서 검증할 수 없습니다:

1. **정상 수렴 분기**: `reconcile_required` → broker 조회 성공 → FILLED/CANCELLED/REJECTED 반영
2. **fills 동기화 분기**: `_sync_fills()`가 실제 체결 건에서 FillEvent를 생성하는 경로
3. **cancel/reject 반영 분기**: broker가 주문을 취소/거절했을 때의 상태 전이

이 경로들은 **Live 첫 번째 submit 시점에 처음으로 검증**됩니다. 문제가 발생할 경우 그때 디버깅이 필요합니다.

### 5.2 Stale `pending_submit` 누적 리스크 (2026-05-13 추가)

**문제**: near-real submit 실패 또는 미완료 시 `pending_submit` 상태의 주문이 DB에 누적됨. broker에 제출되지 않았으므로 `broker_orders` 연결이 없으며, 이후 submit 시도와 혼동될 수 있음.

**완화 조치 (2026-05-13 적용)**:
- 정리 기준: `status='pending_submit' AND created_at < 24h AND no broker_orders`
- 처리: `PENDING_SUBMIT → REJECTED` (reason_code=`stale_cleanup`)
- 도구: [`_cleanup_pending_submit.py`](_cleanup_pending_submit.py)
- 실행 결과: 15건 정리 완료. `reconcile_required` 6건 영향 없음.

**잔여 리스크**: 정기적인 stale cleanup이 누락되면 다시 누적될 수 있음. 향후 운영 절차에 포함 필요.

---

## 6. Logging 제거 조건 (3가지)

계측 logging (`rest_client.py:896-928`)은 **3가지 조건이 모두 충족**되어야 제거 가능합니다.

| # | 조건 | 설명 | 확인 방법 |
|---|------|------|----------|
| 1 | Live `inquire-daily-ccld` payload 확인 | `output: [...]` (비어있지 않음), `ODNO` 필드 존재 | DEBUG logging에서 `output_count > 0`, `first_item_fields` 출력 확인 |
| 2 | ODNO 매칭 성공 | `item.get("ODNO") == broker_order_id` 매칭 성공 → `_parse_order_status_item()` 호출 | INFO logging에 ODNO match failure 미출력 |
| 3 | Terminal status 수렴 | Post-submit sync 후 `broker_status`가 FILLED/CANCELLED/REJECTED로 수렴 | DB `broker_orders.broker_status` 확인 |

**자세한 조건 및 판단 흐름**: [`inquire_daily_ccld_payload_capture_report.md#72-제거-조건-3개-모두-충족-시`](plans/inquire_daily_ccld_payload_capture_report.md)

---

## 7. Live 검증 전 체크리스트 (요약)

Live 검증 실행 전 확인해야 할 6가지 사전 조건:

| # | 항목 | 확인 내용 | 상세 문서 |
|---|------|----------|----------|
| 1 | **장중 여부** | 월~금, 08:30~15:30 KST | [`live_verification_prerequisites.md#1-장중-여부-확인`](plans/live_verification_prerequisites.md) |
| 2 | **계정/토큰** | `KIS_ENV=real`, Live API key/secret, Token cache 삭제 | [`live_verification_prerequisites.md#2-계정토큰-확인`](plans/live_verification_prerequisites.md) |
| 3 | **KIS_SMOKE_PRICE 설정** | near-real submit 전 필수 설정, 기본값 50000 의존 금지 | [`live_verification_prerequisites.md#2.4`](plans/live_verification_prerequisites.md) |
| 4 | **Stale PENDING_SUBMIT 정리** | 24h+ broker 미제출 주문 cleanup 완료 | [`live_verification_prerequisites.md#2.5`](plans/live_verification_prerequisites.md) |
| 5 | **Snapshot freshness** | 최근 snapshot sync 5분 이내 완료 | [`live_verification_prerequisites.md#3-snapshot-freshness-확인`](plans/live_verification_prerequisites.md) |
| 6 | **Sync loop 경로** | `run_post_submit_sync_loop.py` 존재, syncable orders 확인 | [`live_verification_prerequisites.md#4-sync-loop-실행-경로-확인`](plans/live_verification_prerequisites.md) |

전체 체크리스트: [`live_verification_prerequisites.md`](plans/live_verification_prerequisites.md)

---

## 8. 다음 직접 액션 1개

> **2026-05-13 업데이트**: Paper APPROVE smoke ✅ 완료. 남은 작업은 Live 환경 전환 + 3가지 logging 제거 조건 검증.

### 완료된 항목
- ✅ Paper 환경 Dry-run → APPROVE 확인
- ✅ Paper 환경 Submit 성공 (ODNO 발급)
- ✅ Paper 환경 Post-Submit Sync 실행 (last_synced_at 갱신, order_state_events 증가)
- ✅ 성공 기준 문서 고정 ([`paper_submit_smoke_ops_checklist.md`](plans/paper_submit_smoke_ops_checklist.md#9-c-성공-기준-paper-검증-완료--2026-05-13-실증-기준))
- ✅ Live 전용 항목 분리 ([`live_verification_prerequisites.md`](plans/live_verification_prerequisites.md#6-paper-실증-완료-vs-live-전용-분리))

### 남은 액션

1. **장중 Live 환경 전환 대기** — [`live_verification_prerequisites.md`](plans/live_verification_prerequisites.md)의 4가지 사전 조건 충족 확인
2. **Live submit 실행** (별도 절차 — 본 문서 범위 외)
3. **Post-submit sync 실행** → 3가지 logging 제거 조건 확인
   - 조건1: `inquire-daily-ccld` `output_count > 0` (Live 실제 payload)
   - 조건2: ODNO 매칭 성공
   - 조건3: Terminal status 수렴 (FILLED/CANCELLED/REJECTED)
4. **조건 모두 충족 시** instrumentation logging 제거 (`git checkout -- src/agent_trading/brokers/koreainvestment/rest_client.py`)

---

## 9. 최종 보고서 (6항목)

### 9.1 수정/생성한 문서 목록

| # | 문서 | 작업 | 변경 내용 |
|---|------|------|----------|
| 1 | [`inquire_daily_ccld_payload_capture_report.md`](plans/inquire_daily_ccld_payload_capture_report.md) | 수정 | Section 7: logging 유지 목적 3항목 + 제거 조건 3가지 세분화 + 판단 흐름도 |
| 2 | [`live_verification_prerequisites.md`](plans/live_verification_prerequisites.md) | **신규** | Live 검증 전 체크리스트 7개 섹션 |
| 3 | [`paper_mock_boundary_validation_scope.md`](plans/paper_mock_boundary_validation_scope.md) | 수정 | 본 문서 — logging 제거 조건, Live 체크리스트 요약, 다음 액션 추가 |

### 9.2 Logging 제거 조건

**3가지 조건 모두 충족 필수**:

| # | 조건 | 확인 방법 |
|---|------|----------|
| 1 | Live `inquire-daily-ccld` payload: `output_count > 0` | DEBUG logging 출력 확인 |
| 2 | ODNO 매칭 성공 (`broker_order_id` 일치) | INFO logging에 ODNO match failure 미출력 |
| 3 | Terminal status 수렴 (FILLED/CANCELLED/REJECTED) | DB `broker_orders.broker_status` 확인 |

판단 흐름: Live submit -> 조건1 확인 -> 조건2 확인 -> 조건3 확인 -> `git checkout -- rest_client.py`

### 9.3 Live 검증 체크리스트 요약

| # | 항목 | 확인 내용 |
|---|------|----------|
| 1 | 장중 여부 | 월~금 08:30~15:30 KST |
| 2 | 계정/토큰 | `KIS_ENV=real`, Live API key/secret, token cache 삭제 |
| 3 | Snapshot freshness | 최근 sync 5분 이내 |
| 4 | Sync loop 경로 | `run_post_submit_sync_loop.py` 존재, syncable orders 확인 |

상세: [`live_verification_prerequisites.md`](plans/live_verification_prerequisites.md)

### 9.4 코드 변경 여부

**이번 턴: 코드 변경 없음** -- 문서/체크리스트만 수정/생성.
Phase C instrumentation logging (`rest_client.py:896-928`)은 Live 검증 조건 충족 시까지 유지.

### 9.5 남은 리스크 1개

**Live `inquire-daily-ccld` 응답 구조가 paper mock과 다를 가능성**

Paper mock은 `output: []` (빈 배열)이지만, Live 응답 구조가 코드가 예상하는 형식과 다를 수 있음. 예: `output` 필드명 상이, `ODNO` 포맷 상이, `_parse_order_status_item()` 미처리 필드 존재. Instrumentation logging이 DEBUG 레벨로 남아있으면 첫 Live 호출 시 즉시 탐지 가능.

### 9.6 다음 직접 액션 1개

> **2026-05-13 업데이트**: Paper APPROVE smoke ✅ 완료. 이제 Live 환경 전환만 남음.

**Live 환경 전환 + 3가지 logging 제거 조건 검증**

Paper submit 성공 경로는 확정되었습니다. 남은 유일한 직접 액션은 Live 환경에서 submit 후 다음 3가지 조건을 확인하는 것입니다:

| # | 조건 | 확인 방법 |
|---|------|----------|
| 1 | `inquire-daily-ccld` `output_count > 0` | DEBUG logging 출력 확인 |
| 2 | ODNO 매칭 성공 | INFO logging에 ODNO match failure 미출력 |
| 3 | Terminal status 수렴 (FILLED/CANCELLED/REJECTED) | DB `broker_orders.broker_status` 확인 |
| — | 모두 충족 시 logging 제거 | `git checkout -- src/agent_trading/brokers/koreainvestment/rest_client.py` |

상세: [`paper_mock_boundary_validation_scope.md#8-다음-직접-액션-1개`](plans/paper_mock_boundary_validation_scope.md#8-다음-직접-액션-1개)

---

## 부록: 문서 간 크로스 레퍼런스

| 문서 | 주요 내용 |
|------|----------|
| [`post_submit_sync_e2e_report.md`](plans/post_submit_sync_e2e_report.md) | Phase A E2E 검증 결과, 6개 버그 수정 내역 |
| [`post_submit_sync_status_convergence_analysis.md`](plans/post_submit_sync_status_convergence_analysis.md) | Phase B 상태수렴 미완료 원인 분석 (ODNO 매칭 실패 경로) |
| [`inquire_daily_ccld_payload_capture_report.md`](plans/inquire_daily_ccld_payload_capture_report.md) | Phase C payload 계측 결과 (`output: []` 확정) |
| [`paper_submit_smoke_ops_checklist.md`](plans/paper_submit_smoke_ops_checklist.md) | 운영 체크리스트, Phase 4 검증 기준 |
| [`paper_submit_smoke_market_hours_execution.md`](plans/paper_submit_smoke_market_hours_execution.md) | 장중 smoke 실행 절차 |
| [`mode_boundary_paper_live.md`](plans/mode_boundary_paper_live.md) | Paper/Live 모드 경계 및 전환 절차 |
