# Universe 선정 구조 감사 (2026-08-07 KST)

## 목적

최근 `Universe 선정` 관련 후속 작업(`market_overlay` 원인 분해, `core` 반복 활동성 부족 차단 원인 분해, `core` 동적 강등(demotion) 설계·구현)을 개별 이슈 단위로 진행해왔다. 이 문서는 그 개별 작업들을 다시 모아, **`Universe 선정` 전반의 구조를 감사**해 중복/비효율/책임 혼선 지점을 찾는다.

**이 문서는 read-mostly 구조 분석이다 — 코드 변경, DB 조회, 정책 반영은 없다.** 목적은 "무조건 단순화"가 아니라, 기대수익률을 해치지 않으면서 불필요한 중복·비효율·설명 불가능성을 줄일 수 있는 지점을 찾는 것이다. 시스템 목표는 "차단 최소화"가 아니라 감내 가능한 손실 제약 아래 기대수익률을 높이는 구조라는 전제를 유지한다.

## 분석 범위

- `src/agent_trading/services/universe_selection.py` / `universe_selection_types.py`
- `src/agent_trading/services/deterministic_trigger_engine.py`
- `src/agent_trading/services/decision_factory.py`
- `scripts/run_decision_loop.py`
- `docs/40_action_plans/universe_activity_prefilter_measurement_plan.md`(직전까지의 실측/설계/구현 이력)
- membership 최신화 문제는 이번 감사의 본질이 아니므로 다시 다루지 않는다(기존 결론 유지: 수동 업로드 정적 소스로 유지).

## 1. Universe 선정 파이프라인 전체 지도

`UniverseSelectionService.compose_with_diagnostics()`(`universe_selection.py:1044-`)가 단일 진입점이다. 8+1단계로 구성된다(Step 6.5는 이번 세션에서 새로 추가됨).

| 단계 | 함수 | 입력 | 출력 | 목적 | 실제 운영 영향 | 다른 단계와의 관계 |
|---|---|---|---|---|---|---|
| 1. Core Universe | `_add_core_universe` | 정적 allowlist(`APPROVED_CORE_UNIVERSE_SYMBOLS`) + DB 인덱스 편입(`instrument_index_memberships`, 수동 갱신) + `instrument.metadata` override | `seen`에 `source_type=CORE` 심볼 추가 | 대형주/고유동성 종목의 authoritative source 확보 | 매 compose마다 재계산, 활동성 지표 미참조 | 이후 모든 override 단계의 기반. Step 6.5/8이 이 결과에 개입 |
| 2. Held Positions | `_add_held_positions` | 현재 보유 포지션 스냅샷 | `seen` override(강제 포함) | 보유 종목은 무조건 평가 대상 | source_type을 `HELD_POSITION`으로 덮어씀 | core였던 심볼도 여기서 override되면 Step 6.5/8 대상에서 제외됨(의도된 예외) |
| 3. Reconciliation Overlay | `_add_reconciliation_overlay` | 미체결/정합성 필요 주문 | `seen` override(강제 포함) | 주문 안전성 보장 | 2와 동일한 override 성격 | 2와 마찬가지로 soft demotion 대상에서 자동 제외 |
| 4. Event Overlay | `_add_event_overlay` | 최근 고중요도 이벤트(`ExternalEventEntity`) | `seen`에 `EVENT_OVERLAY` 추가 | 이벤트 기반 승격 | 정적 core와 별개의 동적 후보 생성 경로 | core와 겹치는 심볼이면 유지 |
| 5. Manual Overlay | `_add_manual_overlay` | 운영자 수동 watchlist | `seen`에 `MANUAL` 추가 | 사람 판단 반영 | 낮은 빈도, 명시적 override | 자동 규칙(soft demotion 포함)이 침범하면 안 되는 영역 |
| 6. Market Overlay | `_add_market_overlay` | KIS 시세 배치(pre-pool→quote→3축 스코어→top-N) + momentum shadow | `seen`에 `MARKET_OVERLAY` 추가 | 시장 활동성 기반 발굴 | 여러 하위 단계(F4/F5 필터, quote 성공률, scored capture rate)로 구성된 가장 무거운 단계 | 원인분해(이전 세션)로 "선정 기준이 activity와 독립적"임을 실측 확인 |
| **6.5. Core Activity Demotion (UNIV-5)** | `_evaluate_core_activity_demotion_shadow` | `trade_decisions`의 최근 `eligibility_low_relative_activity` 이력(A3/A5) | `MarketOverlayDiagnostics`에 shadow 신호 + `demotion_applied` | core 내부에서 반복 실패 종목을 뒤로 미룸 | **A3만 실제로 Step 8 정렬에 반영**, A5는 관측만 | Step 1의 정적 core 판정과 Step 8의 정렬을 잇는 유일한 "동적 품질" 개입 지점 |
| 7. Exclusion | `_apply_exclusions` | `LiquidityFilterService.check()`(정지/관리종목/비활성/틱사이즈/우선주 패턴) | 통과 심볼만 `candidates`로 | 거래 자체가 불가능한 종목 제거 | 모든 source_type 공통 적용 | 활동성/거래대금 관련 조건은 없음(오직 뒤단 eligibility에만 존재) |
| 8. Sort (+ Core Ranking) | `candidates.sort(...)` + `_core_signal_sort_rank` | freshness tier(FRESH/STALE/MISSING) + score + (신규) DEMOTED tier | 최종 정렬 순서 | source_type 간 우선순위 + core 내부 품질 정렬 | `priority` 불변, core만 보조 키 적용 | Step 6.5 신호를 유일하게 소비 |
| 9. Cap | `_apply_cap` | 정렬된 `candidates`, `max_cap`(기본 30), `core_cap`(기본 12) | 최종 universe 리스트 | 하루 평가 대상 수 제한 | **`core_cap=12`가 실제 운영값** — Step 8의 정렬 결과가 실질적으로 포함/배제를 가른다 | Step 8이 없으면 이 단계가 사실상 무력화(항상 순서 그대로 잘림) |
| (병렬) Universe Freeze | `run_decision_loop.py::_load_intraday_frozen_universe_with_anchor` | 위 compose 결과를 하루 1회 materialize | `universe_freeze_runs`/`_items`에 스냅샷 저장, 하루 종일 재사용 | 결정 사이클마다 재계산 방지 | 하루 안에서 같은 compose 결과가 반복 사용됨 — 위 8단계 자체는 **하루 1회만** 실질적으로 실행됨 |  |
| (뒤단, 별도 서비스) BUY Eligibility Gating | `deterministic_trigger_engine._assess_buy_eligibility` + `_assess_core_risk_off_buy_guard` | freeze된 universe의 개별 심볼 + 그 시점 signal feature | `eligibility_passed`, `eligibility_reasons`(다수) | 활동성/신호품질/레짐/리스크 최종 게이트 | **Universe 선정과 완전히 분리된 별도 판단 축** — 여기서 반복 차단이 발생 |  |

## 2. 의미적으로 중복되는 단계 분류

같은 "거래 가능성/활동성/품질" 개념이 여러 층에서 반복되는지 확인했다. 4가지 축으로 분류한다.

### 축 A — 신호 데이터 신선도/커버리지

- Step 8의 freshness tier(`_core_signal_tier`, FRESH/STALE/MISSING)와 뒤단 게이트의 `eligibility_feature_coverage_ok` / `eligibility_low_feature_coverage`(`deterministic_trigger_engine.py`)가 **같은 개념("이 종목의 signal feature가 있는가/최신인가")을 서로 다른 레이어에서 각자 판단**한다.
- **분류: 설명 가능한 단계 분리(정당)** — 앞단(Step 8)은 "순위를 낮출 뿐"이고 뒤단은 "그 사이클에서 아예 막을지"를 결정한다. 둘의 결과가 항상 일치할 필요는 없다(freshness가 STALE이어도 여전히 feature 자체는 존재해 커버리지는 OK일 수 있음). 다만 **두 값이 서로 다른 신선도 정의(날짜 기준 vs 존재 여부 기준)를 쓰는지 문서화된 곳이 없다** — 이 부분은 "구조적 책임 혼선" 소지가 있다(§3 참고).

### 축 B — 활동성(relative_activity/volume/turnover)

- Step 6.5(soft demotion, A3: 반복 차단 이력 기반)와 뒤단 `eligibility_low_relative_activity`/`eligibility_low_average_volume`/`eligibility_low_turnover`가 **정확히 같은 원천 데이터(뒤단 게이트의 과거 판정 결과)를 다시 사용**한다.
- **분류: 정당한 방어 중복이 아니라 "의도적으로 설계된 피드백 루프"** — 이것은 우연한 중복이 아니라 이번 세션에서 의도적으로 만든 구조다(뒤단 판정 이력을 앞단 순위에 반영). 다만 **이 루프가 유일하게 존재하는 축**이라는 점이 중요하다 — 아래 축 C/D에는 이런 피드백 루프가 없다(비대칭).

### 축 C — 리스크 레짐(core_risk_off)

- `deterministic_trigger_engine.py`에서 확인한 `core_risk_off_*` reason code가 최소 **13종**(`eligibility_core_risk_off_guard_blocked/pass`, `_ranking_blocked/pass`, `_signal_blocked/pass`, `_activity_blocked/pass`, `_strategy_blocked/pass`, `_topk_override_pass`, `_exception_pass` 등)이고, `decision_json.metadata.core_risk_off_experiment`에는 `mode`(`hard_block_v1`), `shadow_mode`(`shadow_topk_exception_v2`), `apply_ready`/`apply_enabled`/`apply_selected`, `shadow_rank`, `shadow_floor_bucket`(v2/v3/v5 세 버전 병존 확인됨) 등이 있다.
- **분류: 비효율적 중복 + 구조적 책임 혼선.** 활동성(축 B)과 달리, 리스크 레짐 쪽은 **shadow 버전이 v1(암묵)/v2/v3/v5로 세대를 거치며 병존**하고 있고, "authoritative guard"(`_assess_core_risk_off_buy_guard`, 실제로 막음)와 "shadow 실험"(로그만 남김)이 뒤섞여 하나의 함수(`_build_core_risk_off_shadow_experiment_metadata`) 안에 공존한다. Universe 선정 단계에는 이 리스크 레짐 개념이 전혀 없다 — **전부 뒤단(gating)에만 존재**한다. 이는 "앞단이 몰라도 되는 것"이라는 관점에서는 정상 분리지만, **shadow 세대가 3개나 겹쳐 있는 것 자체는 정리 대상**이다(§6 우선순위 참고).

### 축 D — 유동성/거래 가능성(정지/관리종목/틱사이즈)

- `LiquidityFilterService.check()`(Step 7, 선정 단계)만 담당하고, 뒤단 게이트에는 대응하는 개념이 없다(뒤단은 활동성/레짐/신호 품질만 본다).
- **분류: 정당한 단계 분리** — 이 축은 중복이 전혀 없다. 정지/관리종목 여부는 선정 시점에 한 번만 확인하면 충분하고, 뒤단에서 다시 볼 이유가 없다. **이 축이 오히려 "올바른 분리"의 참고 사례**다.

## 3. 책임 경계가 불명확한 지점

1. **`UniverseSelectionService` vs `deterministic_trigger_engine`의 "활동성" 소유권이 이번 세션 전까지 사실상 없었다.** Step 6.5가 생기기 전까지, "활동성이 낮다"는 판단은 오직 뒤단에만 있었고 앞단은 전혀 몰랐다(이전 원인분해에서 확인). 지금은 Step 6.5로 최소한의 피드백이 생겼지만, **"selection이 활동성을 얼마나 알아야 하는가"에 대한 명시적 정책 문서가 없다** — 이번에 임기응변으로 좁게(A3만) 들여온 것이지, 설계 문서에 "이 정도까지만 안다"는 경계가 아직 명문화되지 않았다.
2. **정적 seed 관리(Step 1) vs 동적 품질 관리(Step 6.5/8)가 같은 함수(`_core_signal_sort_rank`) 안에서 섞이기 시작했다.** freshness tier와 DEMOTED tier가 같은 정수 축에 있다 — 설계 검토 문서(§`core` soft demotion 설계안)에서 이미 "이 축에 개념을 섞는 것에 대한 우려"를 언급했고 완화책(별도 tier 상수)을 뒀지만, **장기적으로 이 함수가 계속 "새 tier"를 받는 그릇이 될 위험**이 있다(A5 반영 시 또 tier가 늘어날 수 있음).
3. **selection vs ranking vs gating vs execution feasibility의 4층 구분이 코드 어디에도 명시적으로 문서화되어 있지 않다.** 이번 감사에서 필자가 재구성한 것이지, `universe_selection_service.md` 설계 문서 자체에 이 4층 구분이 있는 것은 아니다(확인 필요 — 아래 "아직 확인 못한 부분" 참고).
4. **관측용 shadow와 실제 정책 반영의 경계는 리스크 레짐(축 C)에서 가장 흐릿하다.** `core_risk_off_experiment`의 `apply_ready`/`apply_enabled`/`apply_selected` 같은 필드가 있다는 것 자체가, "지금 이게 shadow인지 실반영인지"를 코드를 직접 읽지 않고는 알기 어렵다는 뜻이다. 반면 이번에 만든 UNIV-5 shadow(`demotion_applied`)는 boolean 하나로 명확하다 — **리스크 레짐 쪽이 이번에 만든 패턴을 참고해 정리될 여지가 있다.**

## 4. 효과 대비 복잡도가 큰 부분

1. **`core_risk_off` 다세대 shadow 버전(v1/v2/v3/v5) 병존** — 코드에 버전이 3개 이상 남아있다는 것 자체가 "이전 버전이 정리되지 않고 누적됐다"는 신호다. 각 버전이 실제로 다른 정책을 대표하는지, 아니면 단순 반복 실험의 흔적인지 이번 감사에서는 확인하지 못했다(코드 히스토리 조사 필요, §7 보류 항목).
2. **market_overlay의 다단계 파이프라인(seed pool → pre-pool 후보 → quote 배치 → 3축 스코어 → top-N → momentum shadow)** — 이전 원인분해에서 이미 "market_overlay 선정 기준이 relative_activity와 독립적"이라는 실측 결과가 나왔다. 즉 이 무거운 파이프라인이 만들어내는 정교한 스코어링이, 뒤단에서 반복적으로 활동성 부족으로 걸러지는 것을 막지 못한다 — **정교함과 뒤단 통과율이 비례하지 않는다는 실측 근거가 이미 있다.**
3. **절대 임계값 기반 유니버스 사전 필터(가설 A/B/C/D)** — 이미 34거래일 실측(efficiency_score 0.3155, 권장 기준의 1/10)으로 "효과 낮음"이 확정됐다. 이 문서에서 다시 만들 필요는 없지만, **"효과 낮은 절대 필터를 다시 시도하고 싶은 유혹"에 대한 경고로 남겨둔다.**

## 5. "앞단에서 처리할 것"과 "뒤단에 남길 것"의 재정리

| 축 | 앞단(selection) 소관인가 | 뒤단(gating) 소관인가 | 현재 상태 |
|---|---|---|---|
| 정적 자격(core seed) | **예** | 아니오 | 정상 — Step 1만 담당 |
| 유동성/거래 가능성(정지/관리종목/틱사이즈) | **예** | 아니오 | 정상 — Step 7만 담당, 중복 없음 |
| 동적 품질(신호 신선도) | 예(순위만) | 예(feature_coverage 게이트) | 두 층 모두 존재 — 정의가 다르면 정당, 같은 정의를 두 번 구현한 것이면 낭비(미확인) |
| 활동성/거래 반복 실패 이력 | **이번에 신규로 최소 진입**(A3만) | **예**(최종 권위) | 의도된 피드백 루프. 앞단은 절대 하드 게이트를 복제하지 않음(soft demotion만) — 올바른 경계 |
| 리스크 레짐 | 아니오 | **예** | 정상 분리이나 내부가 다세대로 지저분함(§4-1) |
| 포지션/정합성 예외(held/reconciliation) | **예**(강제 override) | 일부 중복 확인 필요 | Step 2/3이 명확히 소관. 뒤단에서 held_position에 대해 `core_risk_off_guard_active`를 강제로 `False` 처리하는 코드(`deterministic_trigger_engine.py:374-376`)가 있어 — **이 예외가 앞단과 뒤단 양쪽에 각각 다른 방식으로 존재** — 방어 중복으로 보이나 "왜 두 곳에 있어야 하는지" 명문화 필요 |
| 실행 가능성(체결 feasibility) | 아니오 | **예**(`eligibility_execution_feasibility_pass`) | 정상 — 선정 단계가 알 필요 없는 실행 시점 정보 |

## 6. 우선순위별 개선 후보 (1~5)

### 1순위 — `core_risk_off` shadow 버전 정리(v1/v2/v3/v5 병존)

- **문제**: 리스크 레짐 판정에 최소 3개 세대의 shadow floor bucket 로직이 동시에 남아 있다.
- **왜 비효율/부적절한가**: 어느 버전이 "현재 유효한 실험"이고 어느 게 "죽은 코드에 가까운 과거 흔적"인지 코드만으로 구분이 안 된다. 디버깅/신규 온보딩 비용이 크다.
- **코드 위치**: `deterministic_trigger_engine.py`의 `_build_core_risk_off_shadow_experiment_metadata`, `_classify_core_risk_off_shadow_floor_bucket` 호출부(v2/v3/v5).
- **운영 비용**: 로그/decision_json 크기 증가, 신규 개발자가 "지금 뭐가 실제로 작동 중인지" 파악하는 데 드는 시간.
- **단순화 방향**: 각 버전의 도입 시점/목적을 git blame + 관련 SPPV 문서로 먼저 재구성하고, 죽은 버전은 제거하거나 "역사 기록"으로만 문서화.
- **지금 당장 손대면 위험한가**: **위험하다.** 리스크 게이트는 `src/AGENTS.md`가 명시한 "명시적 근거와 테스트 없이 변경하지 않는다" 경계 정중앙에 있다. 이번 턴에서 손대지 않았고, 다음 턴도 먼저 각 버전의 실제 활성 여부를 read-only로 확인하는 것부터 시작해야 한다.

### 2순위 — 신호 신선도 판정의 이중 정의(freshness tier vs feature_coverage_ok) 명문화

- **문제**: 같은 개념("신호가 있는가/최신인가")이 Step 8과 뒤단 게이트에 각각 다른 이름·다른 기준으로 존재하는데, 이 둘의 관계가 어디에도 문서화되어 있지 않다.
- **왜 비효율/부적절한가**: 두 값이 실제로 다른 기준(날짜 vs 존재)을 쓴다면 정당하지만, 확인되지 않은 채로 남으면 "왜 STALE인데 feature_coverage_ok인 경우가 있지?" 같은 디버깅 혼선을 만든다.
- **코드 위치**: `universe_selection.py`의 `_core_signal_tier`/`DEFAULT_CORE_SIGNAL_FRESHNESS_MAX_AGE_DAYS`, `deterministic_trigger_engine.py`의 `eligibility_feature_coverage_ok`/`eligibility_low_feature_coverage`.
- **운영 비용**: 낮음(현재는 잠재적 혼선일 뿐, 실제 장애 사례는 확인되지 않음).
- **단순화 방향**: 코드 변경 없이 **문서화만으로 해결 가능** — 두 판정의 정의 차이를 명시적으로 적어두면 된다.
- **지금 당장 손대면 위험한가**: 문서화는 안전, 코드 통합은 아직 이르다(두 판정이 정말 같은지 확인 전).

### 3순위 — held_position 예외가 앞단(Step 2 override)과 뒤단(`core_risk_off_guard_active` 강제 False) 양쪽에 각각 구현된 것

- **문제**: 같은 안전장치가 두 곳에 있다.
- **왜 비효율/부적절한가**: 방어적 중복(정당할 수 있음)이지만, "왜 두 곳 다 필요한지"에 대한 근거가 코드 주석 외에는 없다. 한쪽만 있어도 되는지 검증되지 않았다.
- **코드 위치**: `universe_selection.py::_add_held_positions`(Step 2), `deterministic_trigger_engine.py:374-376`.
- **운영 비용**: 낮음 — 오히려 안전 측 중복이라 리스크는 작다.
- **단순화 방향**: **지금은 건드리지 않는 것을 권장**(§7 참고) — 이 중복은 "정당한 방어 중복"에 가깝다.
- **지금 당장 손대면 위험한가**: 위험하다 — `held_position` 관련 안전장치는 `src/AGENTS.md`가 직접 명시한 보호 대상.

### 4순위 — market_overlay 파이프라인의 정교함 대비 낮은 실효성

- **문제**: pre-pool→quote→3축 스코어→top-N→momentum shadow의 무거운 파이프라인이, 실측상 "선정 기준이 활동성과 독립적"이라는 결과를 낳는다.
- **왜 비효율/부적절한가**: 정교한 스코어링에 들이는 복잡도(API 호출 budget, 여러 필터 단계)가 뒤단 통과율 개선으로 이어지지 않는다는 실측 근거가 이미 있다(이전 원인분해).
- **코드 위치**: `universe_selection.py::_add_market_overlay`.
- **운영 비용**: KIS API 호출 budget 소모, 코드 복잡도.
- **단순화 방향**: **아직 단정하지 말 것** — market_overlay의 목적이 "활동성이 아니라 이벤트/뉴스 신호 포착"이라면, 뒤단 활동성 게이트와 충돌하는 게 오히려 설계 의도일 수 있다(이전 원인분해 결론). 단순화보다는 "이 파이프라인의 진짜 성공 지표가 무엇인지"를 먼저 재정의하는 문서화가 먼저다.
- **지금 당장 손대면 위험한가**: 코드 변경은 위험, 목적 재정의(문서) 논의는 안전.

### 5순위 — Universe 선정 단계 4층(selection/ranking/gating/execution) 구분의 미문서화

- **문제**: 이번 감사에서 재구성한 4층 구분이 기존 설계 문서에 명시적으로 존재하는지 확인하지 못했다.
- **왜 비효율/부적절한가**: 층 구분이 암묵적이면, 새 기능을 추가할 때(이번 UNIV-5처럼) "이건 어느 층에 넣어야 하는가"를 매번 새로 판단해야 한다.
- **코드 위치**: 해당 없음(문서 부재 자체가 문제).
- **운영 비용**: 낮음(현재는 설계 논의 비용만 있음).
- **단순화 방향**: 이 문서(구조 감사)가 그 출발점 역할을 할 수 있다. 후속으로 `universe_selection_service.md`(원 설계 문서)에 4층 구분을 정식으로 편입하는 것을 권장.
- **지금 당장 손대면 위험한가**: 문서화는 완전히 안전.

## 7. 유지해야 하는 복잡성 vs 줄여도 되는 복잡성

**유지해야 하는 필수 복잡성**
- held/reconciliation override의 이중 안전장치(§6-3) — 방어적 중복은 리스크 계열에서 정당하다.
- Step 7(유동성 필터)과 뒤단 게이트의 완전한 분리(축 D) — 이미 올바르게 분리되어 있다.
- Step 6.5의 "A3만 반영, A5는 관측만" 보수적 설계 — 최근 도입된 안전장치이므로 충분한 운영 관측 없이 확장하면 안 된다.
- 정적 core seed의 단순성(activity 미참조) — 이번 감사로도 "정적 유지"라는 기존 전제를 뒤집을 근거를 찾지 못했다.

**줄일 수 있는 accidental complexity**
- `core_risk_off` shadow 버전 3세대 병존(§6-1) — 가장 유력한 정리 대상.
- 신호 신선도 이중 정의의 미문서화(§6-2) — 문서화만으로 해소 가능한 낮은 비용 항목.

**아직 판단 보류가 필요한 영역**
- market_overlay 파이프라인의 목적 재정의(§6-4) — 코드 문제가 아니라 정책 목적 정의 문제일 수 있어, 이번 감사만으로 결론 낼 수 없다.
- 4층 구분의 정식 문서화 범위(§6-5) — 다음 턴에서 기존 설계 문서(`universe_selection_service.md`) 내용을 먼저 재확인해야 한다.

## 8. 아직 확인하지 못한 부분(다음 턴 조사 필요)

- `docs/10_signal_research_sppv/[DESIGN] universe_selection_service.md`와 `[PRIORITY_MAP] remaining_work_priority_map.md`는 이번 감사에서 제목만 확인 대상으로 지정됐을 뿐, 본문 전체를 정독하지는 못했다 — `core_risk_off` shadow 버전(v1~v5)의 도입 배경과 "죽은 코드 여부"를 판단하려면 이 문서들과 관련 SPPV 이력을 먼저 봐야 한다.
- freshness tier와 `feature_coverage_ok`가 실제로 같은 기준을 쓰는지(같으면 순수 중복, 다르면 정당 분리)는 코드 구조만으로 확정하지 못했다 — 두 판정에 쓰이는 signal_feature_snapshot 필드가 동일한지 직접 대조가 필요하다.

## 다음 단계 제안

**설계/문서 정리를 우선한다.** 코드 리팩터링(1순위인 `core_risk_off` 정리조차)은 `src/AGENTS.md`의 리스크 경계 원칙상 이번 감사만으로 바로 들어가면 안 된다. 권장 순서:

1. (문서) 신호 신선도 이중 정의(§6-2) 명문화 — 가장 낮은 리스크, 가장 빠른 착수 가능.
2. (조사) `core_risk_off` shadow v1~v5의 실제 도입 이력/현재 활성 여부 read-only 조사 — 1순위 정리의 선행 작업.
3. (문서) `universe_selection_service.md`에 4층 구분(selection/ranking/gating/execution) 정식 편입.
4. market_overlay 목적 재정의는 사용자 판단이 필요한 정책 논의 사안 — 이번 문서에서 결론 내지 않는다.

현상 유지가 아니라 **문서/조사 우선 후속 착수**를 권장한다 — 다만 어떤 코드 리팩터링도 이번 감사 결과만으로 바로 시작하지 않는다.
