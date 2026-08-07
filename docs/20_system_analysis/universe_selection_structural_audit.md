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

- Step 8의 freshness tier(`_core_signal_tier`, FRESH/STALE/MISSING/DEMOTED)와 뒤단 게이트의 `eligibility_feature_coverage_ok` / `eligibility_low_feature_coverage`(`deterministic_trigger_engine.py`)가 **비슷해 보이지만 실제로는 서로 다른 판단 기준·다른 입력·다른 결과 영향을 가진 별개의 메커니즘**이다. 상세 비교는 §9 참고.
- **분류(보수적으로): 일부 입력(overall_score의 존재 여부)은 겹치지만, 판단 기준(날짜 경과 vs 항목 존재 개수)과 책임(정렬 순위 vs 차단 여부)이 다르다.** "같다/중복이다"라고 단정할 근거는 소스에서 찾지 못했다 — §9에서 코드 기준으로 상세히 비교한다.

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
- **[2026-08-07 갱신]** freshness tier와 `feature_coverage_ok`의 기준 차이는 §9에서 코드 기준으로 상세 비교해 해소했다 — 둘은 서로 다른 판단 기준(날짜 경과 vs 항목 존재 개수)을 쓰며, 참조하는 snapshot 필드도 부분적으로만 겹친다(`overall_score`만 공통, `fast_score`/`slow_score`는 coverage만 참조). 다만 `deterministic_trigger_engine.py`에 전달되는 `signal_feature_snapshot`을 실제로 어느 호출부가 어떤 조회 방식(같은 `list_latest_by_instrument_ids` 경로인지, 별도 as-of 조회인지)으로 조달하는지는 호출 체인을 끝까지 추적하지 못해 미확인으로 남는다(§9 참고).

## 9. 신호 신선도 vs feature coverage — 상세 비교(2026-08-07 KST 문서 보강)

이 절은 §2 축 A를 코드 기준으로 상세히 뒷받침한다. **코드 변경 없음 — read-only 문서 보강이다.**

### 정의

- **core signal freshness tier**: `core` source_type 후보를 core 내부에서 **재정렬**할 때만 쓰는 계층(FRESH/STALE/MISSING, 그리고 이번 세션에서 추가된 DEMOTED)이다. 특정 종목의 BUY 평가 여부 자체를 바꾸지 않는다.
- **feature coverage gate**(`eligibility_feature_coverage_ok`/`eligibility_low_feature_coverage`): 개별 decision 1건을 **차단할지 말지**를 가르는 BUY eligibility 게이트의 항목 중 하나다.

### 계산 위치(코드 근거)

- **freshness tier**: `UniverseSelectionService._core_signal_tier()`(`universe_selection.py:846-864`)가 계산하고, `_core_signal_sort_rank()`(`universe_selection.py:867-`)의 2차 정렬 키로만 쓰인다. 입력값은 `_prime_core_signal_score_cache()`(`universe_selection.py:811-843`)가 `signal_feature_snapshots.list_latest_by_instrument_ids(instrument_ids, timeframe="1d")`(Postgres 구현: `DISTINCT ON (instrument_id) ... ORDER BY instrument_id, snapshot_at DESC, signal_feature_snapshot_id DESC` — instrument당 최신 1건, timeframe 고정)로 배치 조회해 만든 캐시(`self._core_signal_score_cache`, `{symbol: (overall_score, snapshot_at)}`)뿐이다. **오직 `overall_score`와 `snapshot_at` 두 값만 본다.**
  - 계층 판정 로직: `max_age_days`(운영값은 `scripts/run_decision_loop.py:322`의 `DEFAULT_CORE_SIGNAL_FRESHNESS_MAX_AGE_DAYS = 5`, KST 달력일 기준)가 `None`이거나 캐시에 해당 심볼이 아예 없으면 즉시 FRESH로 반환하는 게 아니라 — 정확히는: `snapshot_at is None`(캐시에 값이 없음)이거나 `max_age_days is None`이면 FRESH, 그 외에는 `(오늘 - snapshot 날짜) <= max_age_days`면 FRESH, 초과하면 STALE. **캐시에 해당 심볼의 `overall_score` 자체가 없으면(스냅샷이 아예 없거나 `overall_score` 필드가 None이면) `_core_signal_sort_rank()`의 `_key()`가 `entry is None` 분기로 빠져 MISSING이 된다** — 즉 MISSING은 "스냅샷 없음"과 "스냅샷은 있지만 `overall_score`가 None"을 구분하지 않고 하나로 합친다.
  - DEMOTED tier(UNIV-5)는 이 freshness 판정과 무관한 별도 입력(`trade_decisions`의 `eligibility_low_relative_activity` 반복 이력, A3 매칭)으로 결정되며, freshness 계산 결과를 덮어쓴다.
- **feature coverage**: `deterministic_trigger_engine.py`의 `_build_feature_coverage_score()`(`deterministic_trigger_engine.py:431-448`)가 계산한다. **7개 항목의 단순 존재(Not-None) 여부 평균**이다 — 날짜/나이는 전혀 보지 않는다:
  1. `signal_feature_snapshot is not None`
  2. `signal_feature_snapshot.overall_score is not None`
  3. `signal_feature_snapshot.fast_score is not None`
  4. `signal_feature_snapshot.slow_score is not None`
  5. `market_regime is not None`
  6. `strategy_selection is not None`
  7. `portfolio_allocation is not None`

  `coverage_score = (참인 항목 수) / 7`이다. BUY 경로에서는 `coverage_score < 0.50`이면 `eligibility_low_feature_coverage`로 차단(`deterministic_trigger_engine.py:471-474`), 그 외 한 경로(포지션 보유 종목의 exit 관련 평가로 보임, `deterministic_trigger_engine.py:1131-1134`)에서는 임계값이 `0.35`다 — **두 개의 서로 다른 coverage 임계값이 코드에 존재**하며, 이번 문서화에서는 두 경로가 정확히 어떤 조건에서 갈리는지까지는 전부 추적하지 못했다(추가 확인 필요, 아래 "아직 단정하지 않은 부분" 참고).

### 입력값 비교

| | freshness tier | feature coverage |
|---|---|---|
| 참조 필드 | `overall_score`, `snapshot_at` | `overall_score`, `fast_score`, `slow_score`, `market_regime`, `strategy_selection`, `portfolio_allocation`(snapshot 자체 존재 여부 포함) |
| 날짜/나이 고려 | **예**(`max_age_days` 대비 경과일) | **아니오**(존재 여부만, 아무리 오래된 값이어도 존재하면 조건 충족) |
| 조회 시점/경로 | universe 선정(compose) 시점, `list_latest_by_instrument_ids`로 배치 조회한 캐시 | decision 평가 시점, 호출자가 넘겨준 `signal_feature_snapshot` 객체(어느 함수가 어떻게 조달하는지는 이번 문서화에서 끝까지 추적하지 못함 — 미확인) |
| 공통 입력 | `overall_score`의 **존재 여부**만 개념적으로 겹친다 | 좌동 |

### 결과 영향 비교

| | freshness tier | feature coverage |
|---|---|---|
| 무엇을 바꾸는가 | `core` 내부 정렬 **순서만** (2차 정렬 키) | 그 decision의 **BUY eligibility 통과/차단 자체** |
| 직접 차단하는가 | 아니오 | **예**(`eligibility_low_feature_coverage`) |
| 간접적으로 배제로 이어질 수 있는가 | `core_ranking_mode==CORE_RANKING_MODE_SIGNAL_SCORE`이고 `core_cap`이 실제로 절단되는 상황(운영 기본값 12)이면, 순위가 낮아진 결과로 그날 cap 밖으로 밀려날 수 있다 — 그러나 이는 "차단"이 아니라 "그날 유니버스에 안 들어옴"이라는 다른 결과다 | 해당 없음(이미 차단이 최종 결과) |
| 적용 범위 | `source_type == CORE`만 | source_type 무관, BUY 경로로 평가되는 모든 decision |

### 동시에 어긋날 수 있는 시나리오

- **STALE인데 feature_coverage_ok인 경우**: **코드 구조상 가능하다.** freshness tier는 날짜 경과만 보고, feature coverage는 날짜를 전혀 보지 않는다 — 스냅샷이 `max_age_days`를 넘겨 STALE로 강등돼도, 그 스냅샷의 `overall_score`/`fast_score`/`slow_score`가 여전히 채워져 있고 `market_regime`/`strategy_selection`/`portfolio_allocation`도 정상 산출되면 `coverage_score`는 그대로 1.0일 수 있다.
- **freshness 문제는 없는데(FRESH) feature coverage는 낮은 경우**: **코드 구조상 가능하다.** 스냅샷 자체는 최신(`max_age_days` 이내)이라도, `fast_score`/`slow_score`가 그 스냅샷에 없거나(freshness tier는 `overall_score`만 보므로 이 결측을 못 잡는다), 또는 `market_regime`/`strategy_selection`/`portfolio_allocation` 같은 **snapshot과 무관한 별도 평가 객체**가 그 결정 순간에 산출되지 않았다면(예: 레짐 판정 서비스 일시 실패) `coverage_score`가 0.50 밑으로 떨어질 수 있다 — freshness tier는 이런 실패를 전혀 감지하지 못한다.
- **참고(코드 주석 기준, 미검증 인용)**: `deterministic_trigger_engine.py`의 주석(SPPV-2.137 인용)은 "0.50 하드 게이트를 통과한 population(n=13,016 전수 확인 시점 기준)에서는 `coverage_score`가 예외 없이 1.0이었다"고 적어놓았다 — 즉 **과거 특정 시점의 실측에서는** 0.50~1.0 사이 중간값이 실제로 관측되지 않았다는 뜻이다. 이 문서는 그 주석을 그대로 인용할 뿐, 현재 시점에도 여전히 그런지는 재검증하지 않았다(과거 실측 결과의 인용이지 이번 문서화의 새 확인 사실이 아니다).

### 운영/디버깅에서 왜 헷갈릴 수 있는가

- 두 메커니즘 모두 "신호/데이터 품질"이라는 같은 단어로 설명되기 쉽지만, 하나는 **순서**를, 하나는 **통과/차단**을 결정한다 — 로그나 diagnostics만 보고 "신선도가 낮다"는 사실 하나로 "그래서 차단됐겠다"고 추론하면 틀릴 수 있다(STALE ≠ 차단).
- 두 메커니즘의 참조 필드가 부분적으로만 겹쳐서, "STALE인데 왜 통과했지?" 또는 "MISSING도 아닌데 왜 feature_coverage로 막혔지?" 같은 질문이 코드를 직접 읽지 않고는 답하기 어렵다.
- MISSING tier가 "스냅샷 없음"과 "스냅샷은 있지만 `overall_score`만 없음"을 구분하지 않는다는 점도, 원인 분석 시 추가 확인 없이는 헷갈릴 수 있는 지점이다.

### 그래서 필요한 문서 문구(권장)

- `_core_signal_tier()`/`_core_signal_sort_rank()` docstring 또는 인접 주석에 "이 tier는 순서만 바꾸며 BUY 차단과 무관하다"는 한 줄을 명시.
- `eligibility_low_feature_coverage` 발생 지점 주석에 "이 판정은 snapshot 나이를 보지 않으며, universe 선정의 freshness tier와 독립적이다"는 한 줄을 명시.
- 위 두 문구는 이번 턴 범위(문서화만) 안에서 코드 주석으로 추가할 수도 있으나, 사용자가 "코드 변경 금지"를 명시했으므로 이번 턴에서는 이 문서(구조 감사)에만 남기고 코드 주석 추가는 다음 턴으로 미룬다.

### 판단 — 의도된 분리인가, 순수 중복인가

**보수적 결론: 일부 입력(`overall_score`의 존재 여부)은 겹치지만, 판단 기준과 책임이 명확히 다르다 — "순수 중복"이라고 부르기는 어렵고, "의도적으로 설계된 분리"라고 단정할 근거도 없다(설계 의도를 직접 언급한 문서를 찾지 못했다).** 결과적으로 두 메커니즘이 서로 다른 층(ranking vs gating)에서 각자의 목적에 맞게 존재하는 것은 구조적으로 타당해 보이지만, 그 차이가 어디에도 명문화되어 있지 않았다는 사실 자체가 이번 문서화의 핵심 근거였다.

### 아직 단정하지 않은 부분

- **[2026-08-07 갱신]** `deterministic_trigger_engine.py`에 전달되는 `signal_feature_snapshot`의 실제 호출 체인은 §10에서 끝까지 추적해 해소했다 — `decision_orchestrator.py`가 유일한 호출부이며, `signal_feature_snapshots.get_latest_by_instrument()`(단건 조회)로 조달한다. universe selection의 배치 조회와 **같은 테이블·같은 timeframe·같은 "최신 1건" 선택 로직**을 쓰지만, 동시각 tie-break 방식이 다르고 두 조회가 실행되는 시각도 서로 다르다 — "물리적으로 항상 같은 row"라고 단정하지는 않는다(§10 참고).
- `coverage_score < 0.35` 분기(exit 경로로 보이는 `deterministic_trigger_engine.py:1131`)가 정확히 어떤 조건에서 `< 0.50` 분기 대신 평가되는지는 이번 문서화 범위에서 완전히 추적하지 않았다.
- "0.50 하드 게이트 통과 population에서 coverage_score가 예외 없이 1.0"이라는 SPPV-2.137 인용은 코드 주석을 그대로 옮긴 것이며, 이 문서 작성 시점에 재실측하지 않았다.

## 10. `signal_feature_snapshot` 조달 경로 추적(2026-08-07 KST 문서 보강)

§9가 "아직 단정하지 않은 부분"으로 남긴 질문 — freshness tier와 feature coverage가 **물리적으로 같은 DB row를 보는지** — 를 실제 호출 체인을 끝까지 따라가 확인했다. **코드 변경 없음 — read-only 조사·문서 보강이다.**

### universe selection 경로 (freshness tier)

1. `scripts/run_decision_loop.py`가 `UniverseSelectionService.compose(ctx)`를 호출 — `core_ranking_mode=CORE_RANKING_MODE_SIGNAL_SCORE`, `core_signal_freshness_max_age_days=5`.
2. `compose_with_diagnostics()`의 Step 1(`_add_core_universe`) 실행 도중 `_prime_core_signal_score_cache(instruments)`(`universe_selection.py:811-843`)가 core 후보 **전체**의 `instrument_id`를 모아 **한 번의 배치 조회**로 호출한다.
3. 실제 repository 호출: `self._repos.signal_feature_snapshots.list_latest_by_instrument_ids(instrument_ids, timeframe="1d")`(기본값). Postgres 구현(`repositories/postgres/signal_feature_snapshots.py:130-`)은:
   ```sql
   SELECT DISTINCT ON (instrument_id) *
   FROM trading.signal_feature_snapshots
   WHERE instrument_id = ANY($1::uuid[]) AND timeframe = $2
   ORDER BY instrument_id, snapshot_at DESC, signal_feature_snapshot_id DESC
   ```
   instrument_id별 **최신 1건**을 뽑되, `snapshot_at`이 완전히 동일한 행이 여러 개 있으면 `signal_feature_snapshot_id DESC`로 tie-break한다.
4. 이 조회는 **compose 1회 호출당 1번**(하루 중 freeze materialize 시점 등, compose가 실제로 실행될 때마다) 일어나고, 그 결과(`overall_score`, `snapshot_at`만 추출)가 `self._core_signal_score_cache`에 캐시된 뒤 `_core_signal_sort_rank()`가 재사용한다.

### decision / eligibility 경로 (feature coverage)

1. `assess_deterministic_triggers()`(`deterministic_trigger_engine.py:72`)의 **유일한 실제 호출부**는 `decision_orchestrator.py:1164`다(grep으로 다른 호출부 없음을 확인).
2. 그 직전 `decision_orchestrator.py`의 `_derive_deterministic_context_components()`(`decision_orchestrator.py:1114-`)가 `signal_feature_snapshot`을 준비한다:
   - `instrument`가 이미 있으면 그대로 쓰고, 없으면 `self._repos.instruments.get_by_symbol(symbol, market_code)`로 조회.
   - 실제 repository 호출: `self._repos.signal_feature_snapshots.get_latest_by_instrument(instrument_for_signal.instrument_id)`(`decision_orchestrator.py:1140-1143`, `timeframe` 인자 생략 → 기본값 `"1d"`).
   - Postgres 구현(`repositories/postgres/signal_feature_snapshots.py:98-111`):
     ```sql
     SELECT * FROM trading.signal_feature_snapshots
     WHERE instrument_id = $1 AND timeframe = $2
     ORDER BY snapshot_at DESC
     LIMIT 1
     ```
     역시 **최신 1건**을 뽑지만, **`signal_feature_snapshot_id`로 tie-break하는 2차 정렬 키가 없다** — `snapshot_at`이 완전히 같은 행이 여러 개면 어느 행이 반환될지 이 쿼리만으로는 보장되지 않는다(Postgres가 임의의 한 행을 반환).
3. 이 조회는 **decision(=symbol 평가) 1건마다** 개별적으로 실행된다 — universe selection처럼 배치로 한 번에 여러 종목을 모아 조회하지 않는다.
4. `decision_factory.py`(`decision_factory.py:92-97`)는 이 결과를 다시 조회하지 않고, `decision_orchestrator`가 만든 `assembled_context.signal_feature_snapshot`(또는 `decision_context.signal_feature_snapshot_id`)을 그대로 재사용해 `signal_feature_snapshot_id`만 추출해 기록한다 — **decision_factory는 별도 조달 경로가 아니다.**

### repository 호출 비교

| | universe selection(freshness) | decision/eligibility(feature coverage) |
|---|---|---|
| repository 메서드 | `list_latest_by_instrument_ids`(배치, 복수 instrument) | `get_latest_by_instrument`(단건, instrument 1개) |
| 구현 클래스 | `repositories/postgres/signal_feature_snapshots.py`(**같은 파일, 같은 클래스**) | 좌동 |
| 대상 테이블 | `trading.signal_feature_snapshots` | 좌동(**동일 테이블**) |
| `timeframe` | `"1d"`(기본값, 명시 전달) | `"1d"`(기본값, 생략) — **동일 값** |
| 선택 기준 | instrument별 `snapshot_at DESC` 최신 1건 | 동일(instrument당 `snapshot_at DESC` 최신 1건) |
| 동시각 tie-break | `signal_feature_snapshot_id DESC`로 결정론적 처리 | **tie-break 없음** — 동률이면 결과가 보장되지 않음 |
| 호출 빈도/시점 | compose 1회당 배치 1번(하루 중 특정 시점, 예: freeze materialize) | decision 1건마다 개별 호출(하루 중 여러 번, 각 결정 시점) |
| 조회 방식 | "최신 1건" — 결정 시점 as-of 아님(과거 시점 필터 없음) | 동일 — "최신 1건", as-of 필터 없음 |

### 같은 row를 볼 가능성 / 다른 row를 볼 가능성

- **구조적으로 같은 row를 볼 가능성이 높다.** 같은 테이블, 같은 repository 클래스, 같은 `timeframe="1d"`, 같은 "instrument당 최신 1건" 선택 로직을 쓴다. 하루 단위(`timeframe="1d"`) 배치가 통상 하루 한 번만 적재된다면(이전 세션의 실측에서도 같은 날 반복 평가 시 `volume_surge_ratio`/`turnover_surge_ratio` 값이 완전히 동일하게 관측됨 — §core 반복 차단 분석 참고), 두 조회는 대부분의 경우 동일한 `signal_feature_snapshot_id`를 반환할 것으로 보인다.
- **그러나 "항상 같은 row"라고 단정하지는 않는다.** 두 가지 이유가 있다: (1) 두 조회는 **서로 다른 시각에 독립적으로 실행되는 별개의 쿼리**다 — universe selection은 compose 시점(예: 아침 freeze materialize)에 한 번, decision 평가는 그날 여러 decision 사이클마다 각각 실행된다. 그 사이에 새 배치 적재(재처리, 정정 등)가 발생하면 서로 다른 `snapshot_at`/`signal_feature_snapshot_id`를 볼 수 있다. (2) 동일 `snapshot_at`을 가진 행이 실제로 여러 개 존재하는 경우(재시도로 인한 중복 적재 등), 배치 경로는 `signal_feature_snapshot_id DESC`로 결정론적으로 정해지지만 **단건 경로는 tie-break 키가 없어 다른 행이 선택될 수 있다** — 이 시나리오가 실제로 발생하는지는 이번 조사에서 실측하지 않았다(코드 구조상 가능성만 확인).

### freshness tier와 feature coverage가 참조하는 값의 출처

- freshness tier의 `overall_score`/`snapshot_at`과 feature coverage의 `overall_score`/`fast_score`/`slow_score`는 — **위에서 확인한 두 개의 서로 다른 조회 경로 각각의 결과 객체**에서 나온다. 즉 **같은 snapshot object(같은 Python 인스턴스)를 공유하는 것이 아니라, 각자 별도로 조회한 `SignalFeatureSnapshotEntity` 인스턴스**에서 값을 읽는다 — 위 근거대로 그 두 인스턴스가 (대체로) 같은 DB row를 표현할 가능성이 높다는 것이지, 코드가 하나의 객체를 재사용하는 구조는 아니다.

### 질문 7·8에 대한 판정

- **freshness는 배치 조회 캐시 기반, eligibility는 decision별 개별 조달 — 확인된 사실이다.** (`list_latest_by_instrument_ids` 1회 배치 vs `get_latest_by_instrument` 개별 호출, 위 표 참고)
- **"같은 데이터를 다르게 해석한다" vs "조달 경로 자체가 다르다" 중 어느 쪽에 가까운가**: **보수적으로 결론 내리면 "조달 경로(코드 경로·호출 시점·호출 빈도)는 명확히 다르지만, 결과적으로 대체로 같은 물리적 데이터를 가리킬 가능성이 높은 구조"다.** 두 경로 모두 같은 테이블·같은 timeframe·같은 "최신 1건" 개념을 쓴다는 점에서 "완전히 독립된 두 데이터 소스"라고 보기는 어렵지만, 그렇다고 "하나의 조회 결과를 공유해서 쓴다"고 보기도 어렵다 — **경로는 두 개, 결과는 대부분 같은 데이터를 가리킬 것으로 추정되는 구조**로 정리한다.

### 현재까지 확인된 사실 vs 아직 미확인인 부분

**확인된 사실(호출 체인 직접 추적)**
- `assess_deterministic_triggers()`의 유일한 실제 호출부는 `decision_orchestrator.py`다.
- `decision_orchestrator.py`가 `signal_feature_snapshots.get_latest_by_instrument()`로 단건 조회해 `signal_feature_snapshot`을 준비한다.
- `decision_factory.py`는 별도 조달 없이 `decision_orchestrator`의 결과를 재사용한다.
- universe selection과 decision/eligibility 두 경로 모두 같은 테이블·같은 timeframe·같은 최신-1건 로직을 쓰지만, 동시각 tie-break 처리가 다르다(배치 경로만 있음).

**아직 미확인인 부분(§11에서 일부 실측으로 보완)**
- 실제 운영 데이터에서 같은 instrument·같은 `timeframe`에 `snapshot_at`이 완전히 동일한 중복 행이 실제로 존재하는지 — §11에서 최근 10영업일 실측으로 확인(결과: 관측된 사례 없음).
- 하루 중 두 조회 사이(freeze materialize 시점과 이후 decision 사이클들 사이)에 실제로 새 배치가 끼어드는 사례가 있었는지 — §11 실측 범위 안에서는 관측되지 않았다(대표성 한계는 §11 참고).

## 11. 앞단/뒤단 `signal_feature_snapshot_id` 정합도 실측(2026-08-07 KST)

§10이 "구조적으로는 같은 row일 가능성이 높지만 단정할 수 없다"고 정리한 것을, 최근 10영업일 실제 운영 데이터로 **계량 실측**했다. **코드 변경 없음** — 새 read-only 분석 스크립트 `scripts/analysis/measure_signal_feature_snapshot_alignment.py`를 추가했다.

### 실측 방법

- 앞단(universe selection) snapshot은 **재구성값**이다 — compose 시점에 실제로 무엇을 봤는지는 DB에 저장되지 않으므로(`_core_signal_score_cache`는 메모리에만 존재), 그 거래일의 `universe_freeze_runs.frozen_at`(freeze materialize 시각, `freeze_purpose='decision_loop_intraday'`)을 as-of 커트오프로 써서 `signal_feature_snapshots`를 `snapshot_at <= frozen_at, ORDER BY snapshot_at DESC, signal_feature_snapshot_id DESC LIMIT 1`로 재조회했다 — universe selection의 원본 쿼리와 동일한 정렬·tie-break 기준을 그대로 쓰되 시점만 과거로 고정한 것이다.
- 뒤단(decision/eligibility) snapshot은 **실제 영속화된 값**이다 — `trading.decision_contexts.signal_feature_snapshot_id` 컬럼에서 직접 읽었다(재구성 아님).
- 매칭 키: 같은 거래일(business_date) × 같은 종목(symbol, `source_type='core'`). 그 거래일 그 종목의 모든 decision이 가리키는 `signal_feature_snapshot_id`를 집합으로 모아, 앞단 재구성값이 그 집합 안에 있으면 "일치"로 판정했다.

### 실행

- 컨테이너: `agent_trading-app-1`
- 짧은 범위(2일) 검증 명령: `python3 scripts/analysis/measure_signal_feature_snapshot_alignment.py --date-from 2026-08-05 --date-to 2026-08-06 --account-alias 'Entrypoint Paper' --output-json /tmp/uag_alignment/short_result.json` → 24건 비교, 100% 일치. 스크립트 자체의 동작을 먼저 작은 범위로 확인한 뒤 본 실측으로 확장했다.
- 본 실측(최근 10영업일) 명령: `python3 scripts/analysis/measure_signal_feature_snapshot_alignment.py --date-from 2026-07-24 --date-to 2026-08-06 --account-alias 'Entrypoint Paper' --output-json /tmp/uag_alignment/result_10d.json`

### 결과

- 거래일별 freeze anchor 10건, 종목×거래일 비교 **164건**(일별 12~30건, core 유니버스 일일 규모와 일치).
- **일치 164건 / 불일치 0건 — 일치율 100.0%(164/164).**
- "snapshot_at은 같고 id만 다른" tie-break 실증 사례: **0건**.
- "앞단만 있음"/"뒤단만 있음"/"둘 다 없음" 같은 결측 불일치도 **0건**.
- 반복 불일치 종목: 불일치 자체가 없어 해당 없음.

### 불일치 유형별 분포

이번 10영업일 표본에서는 불일치가 전혀 관측되지 않았다 — 따라서 "타이밍 차이 vs tie-break 차이" 같은 유형 분류를 적용할 대상 자체가 없었다. 이는 유형 분포가 "0"이라는 실측 결과이지, 분류 로직 자체가 작동하지 않았다는 뜻이 아니다(짧은 범위 검증에서도 로직은 정상 동작했다).

### 판단(보수적)

**이번 10영업일·1개 계정 표본에서는 앞단/뒤단 불일치가 아주 드문 예외조차 아니라 "전혀 없었다."** 이는 §10이 우려한 시나리오(배치 재적재로 인한 타이밍 차이, 동시각 중복행으로 인한 tie-break 차이)가 이 표본 안에서는 실제로 발생하지 않았다는 뜻이다. 가능한 설명(추정, 미검증): `timeframe='1d'` 배치가 통상 장 마감 후 하루 1회만 적재되고(이전 세션 메모리 기준 약 20:10 KST 전후로 추정), freeze materialize(오전)와 그날의 모든 decision이 그 사이 시간대에 몰려 있다면, 다음 배치가 오기 전까지는 앞단이 보는 "그 시각 기준 최신"과 뒤단이 보는 "실행 시점 최신"이 물리적으로 같은 단 하나의 행일 수밖에 없다 — 그러나 이 설명 자체를 이번 실측에서 재검증하지는 않았다(배치 스케줄 자체를 이번 턴에서 조회하지 않았다).

### 이번 실측이 근거로 삼기에 충분한가

**`freshness tier` 로직을 수정해야 한다는 근거는 이번 실측에서 나오지 않았다.** 오히려 반대 방향의 근거(불일치가 관측되지 않음)가 나왔다. 다만 **이 결과를 "완전히 안전하다"는 결론으로 과장해서도 안 된다** — 아래 대표성 한계가 있다.

### 실측 결과의 대표성 한계

- **표본 기간이 짧다**: 10영업일, 1개 계정(`Entrypoint Paper`)뿐이다. 배치 재적재나 정정이 드물게만 발생하는 이벤트라면, 10일 표본에 우연히 포함되지 않았을 수 있다.
- **freeze anchor 재구성 자체의 한계**: `frozen_at`을 as-of 커트오프로 쓰는 것은 "그 시각에 앞단이 봤을 값"의 **근사**다 — 실제 `_prime_core_signal_score_cache()` 호출이 `frozen_at`과 정확히 같은 순간에 실행됐는지, 아니면 그 전후로 약간의 시차가 있었는지는 확인하지 않았다. 이 시차 안에서 배치가 끼어들었다면 이 스크립트는 그 차이를 놓칠 수 있다.
- **core source_type만 봤다**: 이번 실측은 `source_type='core'`만 비교했다. `event_overlay`/`market_overlay` 등 다른 source_type에 대한 정합도는 이번 범위 밖이다.
- **"뒤단 값"도 decision_context 단위 집계다**: 같은 거래일·같은 종목에 여러 decision이 있으면 그 decision들이 가리키는 `signal_feature_snapshot_id`를 집합으로 모아 비교했다 — 만약 하루 안에서 뒤단 자체가 서로 다른 snapshot_id를 쓰는 경우(그 자체로 흥미로운 현상)가 있었다면 이번 표본에서는 관측되지 않았다는 뜻이지, 그런 경우가 원천적으로 불가능하다는 뜻은 아니다.

## 다음 단계 제안

**설계/문서 정리를 우선한다.** 코드 리팩터링(1순위인 `core_risk_off` 정리조차)은 `src/AGENTS.md`의 리스크 경계 원칙상 이번 감사만으로 바로 들어가면 안 된다. 권장 순서:

1. (문서) 신호 신선도 이중 정의(§6-2) 명문화 — 가장 낮은 리스크, 가장 빠른 착수 가능.
2. (조사) `core_risk_off` shadow v1~v5의 실제 도입 이력/현재 활성 여부 read-only 조사 — 1순위 정리의 선행 작업.
3. (문서) `universe_selection_service.md`에 4층 구분(selection/ranking/gating/execution) 정식 편입.
4. market_overlay 목적 재정의는 사용자 판단이 필요한 정책 논의 사안 — 이번 문서에서 결론 내지 않는다.

현상 유지가 아니라 **문서/조사 우선 후속 착수**를 권장한다 — 다만 어떤 코드 리팩터링도 이번 감사 결과만으로 바로 시작하지 않는다.
