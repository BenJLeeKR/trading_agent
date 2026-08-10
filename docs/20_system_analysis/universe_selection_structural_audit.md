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
- **분류(2026-08-07 실측으로 정정): 처음 추정("정리 대상")과 달리, v2/v3/v5는 실제로 소비되는 활성 A/B 실험 변형이었다** — §12에서 코드 기준으로 확인했다. Universe 선정 단계에는 이 리스크 레짐 개념이 전혀 없다 — 전부 뒤단(gating)에만 존재한다는 점은 그대로 유효하지만, "shadow 세대 병존 = 정리 대상"이라는 초기 판단은 **성급했다.**

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

### 1순위 — `core_risk_off` shadow 버전 정리(v1/v2/v3/v5 병존) — **[2026-08-07 실측으로 정정: 정리 후보 아님]**

- **원래 추정(§6 최초 작성 시점)**: 리스크 레짐 판정에 최소 3개 세대의 shadow floor bucket 로직이 동시에 남아 "정리 대상 1순위"로 지목했다.
- **§12에서 코드 기준으로 확인한 결과, 이 추정은 틀렸다.** v2/v3/v5 floor bucket은 죽은 코드가 아니라 `trigger_proxy_attribution.py`가 소비하는 **활성 A/B 실험 변형**이며, `scripts/run_ops_scheduler.py`가 장후(after-hours)에 정기적으로 forward-return 귀속 분석을 수행하는 데 쓰인다(§12 참고).
- **남은 진짜 문제는 "정리"가 아니라 "명명 혼선"이다**: `_CORE_RISK_OFF_RANKING_MODE="hard_block_v1"`(authoritative 버전 라벨), `_CORE_RISK_OFF_SHADOW_MODE="shadow_topk_exception_v2"`(top-k shadow 메커니즘 버전 라벨), 그리고 floor bucket의 `v2`/`v3`/`v5`(참후보 검증용 임계값 변형)가 **서로 다른 세 가지 버전 축**인데 모두 "v숫자" 표기를 공유해 코드만 보고는 헷갈리기 쉽다. 이는 §6-1의 새 항목으로 아래에 재정의한다.

### 1순위(정정) — `core_risk_off`의 세 가지 서로 다른 버전 축이 같은 "v숫자" 표기를 공유해 혼선을 만든다

- **문제**: `hard_block_v1`(authoritative 게이트 버전), `shadow_topk_exception_v2`(top-k shadow/apply 메커니즘 버전), floor bucket `v2`/`v3`/`v5`(forward-return 귀속 분석용 임계값 실험 변형) — 이 셋은 서로 완전히 다른 것을 가리키는데 이름만 보면 같은 계열의 순차 버전처럼 보인다.
- **왜 비효율/부적절한가**: 코드를 처음 보는 사람은 "v2가 v1을 대체했나?", "v5는 왜 v4 없이 바로 나오나?" 같은 잘못된 질문을 하게 된다. 실제로는 세 축 모두 병렬로 살아있고, 대체 관계가 아니다.
- **코드 위치**: `deterministic_trigger_engine.py` 상단 상수(`_CORE_RISK_OFF_RANKING_MODE`, `_CORE_RISK_OFF_SHADOW_MODE`, `_CORE_RISK_OFF_SHADOW_V2_*`/`_V3_*`/`_V5_*`), `_build_core_risk_off_shadow_experiment_metadata()`.
- **운영 비용**: 디버깅/온보딩 시 오해 비용. 실제 동작에는 영향이 없다(순수 명명/문서화 문제).
- **단순화 방향**: 세 버전 축을 구분하는 짧은 주석/문서 한 줄이면 충분하다 — 코드 구조 변경은 불필요해 보인다.
- **지금 당장 손대면 위험한가**: 문서화는 안전. 상수 이름 자체를 바꾸는 것은 `decision_json`에 이미 그 이름으로 대량 기록된 이력 데이터(`trigger_proxy_attribution.py`가 그 필드명으로 과거 데이터를 읽는다)와의 하위 호환을 깨뜨릴 수 있어 **위험** — 이번 감사 범위에서 이름 변경을 제안하지 않는다.

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
- `core_risk_off`의 세 버전 축(authoritative/shadow-topk/floor-실험)이 같은 "v숫자" 표기를 공유하는 명명 혼선(§6-1, 정정판) — 코드 정리가 아니라 문서화로 해소 가능.
- 신호 신선도 이중 정의의 미문서화(§6-2) — 문서화만으로 해소 가능한 낮은 비용 항목.

**[2026-08-07 정정] 처음에는 아니었지만 이제 유지해야 하는 필수 복잡성으로 재분류**
- `core_risk_off` floor bucket v2/v3/v5 — §12 실측으로 `trigger_proxy_attribution.py`/`run_ops_scheduler.py`가 소비하는 활성 A/B 실험 변형임을 확인했다. 제거하면 안 된다.

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

## 12. `core_risk_off` shadow 세대 구조 정리(2026-08-07 KST)

§2 축 C와 §6-1이 "v1/v2/v3/v5 병존 = 정리 대상"으로 지목했던 부분을 코드 기준으로 끝까지 추적했다. **코드 변경 없음 — read-only 조사·문서 보강이다.** 결론을 먼저 밝히면: **이 추정은 부분적으로 틀렸다.** v2/v3/v5는 죽은 흔적이 아니라 실제로 소비되는 활성 실험 변형이다. 진짜 문제는 "정리 대상 코드"가 아니라 "서로 다른 세 버전 축이 같은 표기를 공유하는 명명 혼선"이다.

### authoritative guard — 실제로 BUY pass/block에 영향을 주는 지점

`_is_core_risk_off_regime(source_type, market_regime)`(`deterministic_trigger_engine.py:610-617`)이 게이트 발동 여부를 판정한다(`source_type=='core'` 이고 `market_regime.risk_tone=='risk_off'` 이고 `market_regime.regime_label=='bearish_trend'`일 때만 활성). 활성이면 `_assess_core_risk_off_buy_guard()`(`:620-701`)가 호출되어 4단계를 순서대로 통과해야 한다:

1. `authoritative_entry_gate_score`(entry_score와 allocation 여유도의 가중합)가 `_CORE_RISK_OFF_RANKING_MIN_SCORE` 미만이면 차단(`eligibility_core_risk_off_ranking_blocked`) — **단, `apply_topk_override_selected=True`면 이 단계를 우회하고 통과**(`eligibility_core_risk_off_topk_override_pass`).
2. `overall`/`slow` 신호 점수 최소 기준 미달 시 차단.
3. `volume_surge_ratio`/`turnover_surge_ratio` 최대값이 활동성 최소 기준(`apply_topk_override_selected`면 완화된 `_CORE_RISK_OFF_SHADOW_ACTIVITY_MIN`, 아니면 `1.20`) 미달 시 차단.
4. `strategy_selection.preferred_strategy`가 정해진 3종(`defensive_low_volatility_rotation`/`mean_reversion_bounce`/`event_continuation`) 밖이면 차단.

이 함수의 반환값(`risk_off_exception_eligible`, `core_risk_off_guard_reasons`)이 `_assess_buy_eligibility()`에 그대로 전달되어 **실제 `eligibility_passed`를 좌우한다** — 이것이 유일한 authoritative 경로다.

### shadow metadata — 단순 관측 기록

`_build_core_risk_off_shadow_experiment_metadata()`(`:789-1012`)가 계산하는 대부분의 필드(`shadow_overall_pass`, `shadow_slow_pass`, `shadow_signal_pass`, `shadow_activity_pass`, `shadow_strategy_pass`, `shadow_reason_codes` 등)는 **decision_json에 기록될 뿐, 이 값들 자체가 `eligibility_passed`나 `_assess_core_risk_off_buy_guard()`의 계산에 다시 입력되지 않는다** — authoritative guard는 이 shadow 함수를 호출하지 않고 완전히 별도로 자체 계산한다. 순수 관측용이다.

### apply/projection 경로 — shadow 결과가 실제로 authoritative 판단에 반영되는 유일한 다리

- **`project_core_risk_off_topk_exceptions()`**(`core_risk_off_topk_projection.py`)는 그 자체로는 "This helper is shadow-only. It does not change authoritative eligibility"라고 docstring에 명시한 순수 함수다 — 여러 종목의 shadow 후보를 cross-sectional로 랭킹해 `shadow_topk_selected`를 부여할 뿐, 아무것도 변경하지 않는다.
- 그러나 이 함수의 **호출자**가 그 결과를 실제로 사용한다 — `scripts/run_decision_loop.py`의 `_build_core_risk_off_apply_overrides_for_cycle()`(`:1281-`)이 그날 cycle 시작 시 **core 유니버스 전체에 대해 미리 한 번씩 deterministic trigger를 계산**(prepass)하고, `project_core_risk_off_topk_exceptions()`로 top-k를 뽑아 `overrides[symbol]["core_risk_off_topk_v1"] = {"selected": True, ...}`를 만든다. 이 `overrides`가 그 cycle의 **실제 decision 평가에 `deterministic_trigger_override`로 전달**되어, 앞서 authoritative guard의 1·3단계(ranking/activity 임계값)를 완화한다 — **즉 projection 함수 자체는 순수해도, 그 호출자는 shadow 결과를 authoritative 판단에 실제로 반영한다.** "shadow-only"라는 docstring은 그 함수 자신에 대해서만 맞는 말이고, 전체 파이프라인에 대한 설명으로 그대로 쓰면 오해를 낳는다.
- **[중요, 실측 확인]** 이 apply 경로는 `_APPLY_CORE_RISK_OFF_TOPK`(env `DETERMINISTIC_TRIGGER_APPLY_CORE_RISK_OFF_TOPK`, 코드 기본값 `"0"`=비활성) 플래그로 게이트된다. `docker-compose.yml:343`은 `${DETERMINISTIC_TRIGGER_APPLY_CORE_RISK_OFF_TOPK:-1}`로 **기본 활성화를 선언**하지만, **실제 실행 중인 `agent_trading-app-1` 컨테이너의 프로세스 환경에는 이 변수가 전혀 설정되어 있지 않음을 직접 확인했다**(`docker exec ... env | grep RISK_OFF` 결과 없음). 즉 코드 기본값(`"0"`)이 적용돼 **이 컨테이너에서는 현재 이 apply 경로가 비활성 상태로 동작 중**이다. 이 불일치의 원인(컨테이너 재기동 필요/`.env` 미설정/다른 시작 경로 등)은 이번 조사에서 확정하지 않았다 — read-only 관찰 결과만 보고한다.
- 반대로, decision들이 이미 만들어진 **뒤**(cycle 종료 후) `_apply_core_risk_off_shadow_projection_for_cycle()`(`:1184-`)가 별도로 존재한다 — 이건 그 cycle의 실제 decision 결과(`decision_json`)를 다시 읽어 `project_core_risk_off_topk_exceptions()`를 한 번 더 돌리고, 그 결과(`shadow_topk_candidate`/`shadow_topk_selected`/`shadow_rank`/`shadow_group_size`)를 **이미 확정된 그 decision들의 `decision_json`에 UPDATE로 되써넣는다.** 이건 순수 관측 라벨 갱신이다 — 이미 일어난 decision의 eligibility를 바꾸지 않는다.

### v1 / v2 / v3 / v5의 정체 — 서로 다른 세 축이 섞여 있다

이 조사에서 확인한 가장 중요한 사실: **"core_risk_off의 v1/v2/v3/v5"는 하나의 순차 버전 계열이 아니라, 완전히 다른 세 가지 것을 가리키는 세 개의 독립된 축이 우연히 같은 "v숫자" 표기를 공유하는 것이다.**

1. **`_CORE_RISK_OFF_RANKING_MODE = "hard_block_v1"`** — authoritative guard(`_assess_core_risk_off_buy_guard`) 자체의 버전 라벨. 구현은 하나뿐이다("v1"이라고 부르지만 "v2"가 따로 존재하지 않는다 — 향후 교체를 염두에 둔 라벨일 뿐).
2. **`_CORE_RISK_OFF_SHADOW_MODE = "shadow_topk_exception_v2"`** — top-k 예외 승격(apply) 메커니즘의 버전 라벨. 이 역시 구현은 하나뿐이다.
3. **floor bucket의 `v2`/`v3`/`v5`** — `_classify_core_risk_off_shadow_floor_bucket()`을 서로 다른 임계값 조합(`mild_overall_min`/`mild_slow_min`/`moderate_overall_min`/`moderate_slow_min`)으로 반복 호출해 만든 **병렬 실험 변형**이다. "v1"(암묵, 기본 임계값), v2, v3는 같은 `overall`/`slow` 입력을 쓰고 임계값만 다르며, **v5만 유일하게 다른 입력값**(`signal_feature_snapshot.component_scores_json`의 `shadow_overall_score_v5`/`shadow_slow_score_v5` — 별도로 계산된 점수)을 쓴다. `v4`는 코드 어디에도 없다(건너뛴 이유는 이번 조사로 확인하지 못했다).

이 세 축은 서로 대체 관계가 아니라 **병렬로 항상 함께 계산**된다 — 하나의 decision마다 authoritative 판정 1회, shadow topk 판정 1회, floor bucket 판정 4종(v1/v2/v3/v5)이 전부 계산되어 `decision_json`에 함께 기록된다.

### 현재 활성 경로 정리

| 구성 요소 | 활성 상태 | 실제 영향 |
|---|---|---|
| authoritative guard(`hard_block_v1`) | **항상 활성**(core_risk_off_guard_active일 때) | eligibility_passed 직접 결정 |
| top-k apply override(`shadow_topk_exception_v2`) | **코드상 존재, 이 컨테이너에서는 env 플래그 부재로 비활성 관측됨**(위 실측 참고) | 활성화되면 authoritative guard의 ranking/activity 임계값을 완화 |
| floor bucket v1(암묵)/v2/v3 | **활성 — `trigger_proxy_attribution.py`가 소비** | eligibility에는 영향 없음, 장후 forward-return 귀속 분석(`run_ops_scheduler.py`)에 쓰임 |
| floor bucket v5 | **활성 — 좌동, 단 입력 신호가 다름**(`component_scores_json` 기반) | 좌동 |
| post-cycle shadow projection(라벨 재기록) | **항상 실행**(cycle_results가 있으면) | decision_json 메타데이터만 갱신, eligibility 불변 |

### 정리 후보 vs 보류 후보(보수적 재분류)

- **즉시 제거 후보**: 없음. 이번 조사에서 실제로 아무 곳에서도 읽히지 않는 "완전한 죽은 코드"는 발견하지 못했다.
- **문서화만 필요**(코드 변경 불필요): `hard_block_v1`/`shadow_topk_exception_v2`/floor bucket `v2·v3·v5`가 서로 다른 세 축이라는 사실 — 이번 문서가 그 역할을 한다.
- **[2026-08-07 후속 조사로 해소] `APPLY_CORE_RISK_OFF_TOPK` 활성 상태 불일치**: §13에서 원인을 확인했다 — 배포 불일치가 아니라, 최초 관측이 **잘못된 컨테이너**(`agent_trading-app-1`, idle 유틸리티 컨테이너)를 확인한 것이었다. 실제 decision loop를 실행하는 `agent_trading-ops-scheduler` 컨테이너에서는 이 변수가 존재함을 확인했다.

### 이번 조사 결과만으로 리팩터링 착수 가능한가

**아니다 — 문서화만으로 충분하다.** 코드/설정 변경 필요성 자체가 §13에서 해소됐다 — 남은 것은 "①명명 혼선 문서화"(이미 이 문서로 완료)뿐이다. 리스크 게이트 코드 자체를 건드리는 것은 여전히 `src/AGENTS.md` 경계 원칙상 범위 밖이며, 애초에 이번 조사로는 코드를 건드릴 근거 자체가 나오지 않았다.

### 아직 단정하지 못한 부분

- `v4`가 왜 없는지(건너뛴 이유, 혹은 다른 이름으로 존재하는지)는 git blame/log를 이번 조사 범위에서 깊이 추적하지 않았다.
- floor bucket v1/v2/v3/v5 실험이 `trigger_proxy_attribution.py`의 귀속 분석에서 실제로 어떤 결론(어느 변형이 가장 유망한지)을 내고 있는지는 이번 조사 범위 밖이다 — 이번 조사는 "소비되는지 여부"만 확인했다.

## 13. `APPLY_CORE_RISK_OFF_TOPK` env/기동 경로 조사(2026-08-07 KST)

§12가 "추가 확인 필요" 항목으로 남긴 질문 — `DETERMINISTIC_TRIGGER_APPLY_CORE_RISK_OFF_TOPK`가 `docker-compose.yml` 선언과 실제 컨테이너 관측 사이에 왜 차이가 있었는가 — 를 기동 경로 기준으로 추적했다. **코드/설정 변경 없음, 컨테이너 재기동 없음 — read-only 조사다. env 값은 어디에도 인용하지 않는다(키 존재 여부만 기술).**

**결론을 먼저 밝히면: 이것은 배포 불일치가 아니라, 이전 조사가 확인한 컨테이너 자체가 잘못됐다.**

### 코드 읽기 위치

`scripts/run_decision_loop.py:324-326`: `_APPLY_CORE_RISK_OFF_TOPK = os.environ.get("DETERMINISTIC_TRIGGER_APPLY_CORE_RISK_OFF_TOPK", "0") == "1"` — 이 모듈 레벨 상수가 `run_decision_loop.py` 프로세스 자신의 환경변수를 읽는다.

### compose 선언 위치 — 어떤 서비스에 주입되는가

`docker-compose.yml`에는 `app`/`api`/`frontend`/`migrate`/`ops-scheduler`/`reconciliation-worker`/`realized-pnl-recompute-worker` 등 여러 서비스 블록이 있다. `DETERMINISTIC_TRIGGER_APPLY_CORE_RISK_OFF_TOPK: "${...:-1}"` 선언은 **`ops-scheduler` 서비스 블록(약 343행)에만** 있다 — `app` 서비스 블록에는 이 키가 전혀 없다. `docker compose config`(read-only 렌더링)로 확인한 결과도 이 키는 `ops-scheduler` 서비스 아래에 정확히 1회만 나타난다.

### 컨테이너/기동 경로 실제 관측

- `agent_trading-app-1`: compose 서비스 `app`, 컨테이너 커맨드가 **`tail -f /dev/null`** — decision loop를 실행하지 않는 idle 유틸리티 컨테이너다(`docker exec` 등으로 코드를 들여다볼 때 쓰는 용도로 보인다).
- `agent_trading-ops-scheduler`: compose 서비스 `ops-scheduler`, 컨테이너 커맨드가 **`python3 /app/scripts/run_ops_scheduler.py --max-general-buy-submit-per-day 5`** — 이 컨테이너가 실제로 살아있는 프로세스다.
- `run_ops_scheduler.py`는 decision 사이클마다 `run_decision_loop.py`를 **서브프로세스로 실행**한다(`scripts/run_ops_scheduler.py:1929-1938`, `python3 -m scripts.run_decision_loop --count 1 ...`).
- 그 서브프로세스에 전달되는 환경은 `_build_base_env()`(`scripts/run_ops_scheduler.py:419-423`)가 만든다 — `env = os.environ.copy()`로 **부모 프로세스(`ops-scheduler` 컨테이너 자신)의 환경을 그대로 복사**하고 `PYTHONUNBUFFERED`만 추가한다. 즉 `ops-scheduler` 컨테이너 프로세스가 이 변수를 갖고 있다면, 그 서브프로세스인 `run_decision_loop.py`도 그대로 물려받는다.
- **`agent_trading-ops-scheduler` 컨테이너의 프로세스 환경에서 이 키가 실제로 존재함을 확인했다**(`docker exec agent_trading-ops-scheduler env | grep -c DETERMINISTIC_TRIGGER_APPLY_CORE_RISK_OFF_TOPK` → `1`; 값은 확인·인용하지 않았다).

### wrapper/env 주입 경로(`scripts/harness/docker_compose_env.sh`)

- `docker_compose_env.sh`는 `load_external_env.sh`를 source해 `/etc/agent_trading/`(기본 경로, `AGENT_TRADING_ENV_DIR`로 오버라이드 가능) 아래의 `runtime.env:ai.env:kis.env`(필수)와 `local.override.env`(선택)를 모아 `docker compose --env-file ... "$@"`로 넘겨준다.
- 실제 서버에서 `/etc/agent_trading/runtime.env`, `ai.env`, `kis.env`는 존재하고, `local.override.env`는 존재하지 않는다(파일 존재 여부만 확인, 값은 열람하지 않음).
- 위 세 파일 중 어디에도 `DETERMINISTIC_TRIGGER_APPLY_CORE_RISK_OFF_TOPK` **키 자체가 존재하지 않는다**(`grep -c '^DETERMINISTIC_TRIGGER_APPLY_CORE_RISK_OFF_TOPK='`로 확인, 결과 0건씩) — 즉 외부 env 파일이 이 값을 명시적으로 지정하지 않고, `docker-compose.yml`의 기본값(`:-1`)이 그대로 적용되는 구조로 보인다.

### 코드 기대값 vs 실제 관측값 비교

| 관점 | 관측/기대 |
|---|---|
| compose 선언(소스 기준) | `ops-scheduler` 서비스에만 `${...:-1}`로 기본 활성 선언 |
| `app` 서비스(소스 기준) | 이 키 선언 자체가 없음 |
| `agent_trading-app-1` 실제 프로세스 | 키 없음(선언이 없으므로 당연) |
| `agent_trading-ops-scheduler` 실제 프로세스 | **키 존재 확인**(값은 미인용) |
| 외부 env 파일(`/etc/agent_trading/*.env`) | 이 키에 대한 명시적 오버라이드 없음(파일에 키 자체가 없음) |
| `run_decision_loop.py` 서브프로세스(실제 실행 경로) | `ops-scheduler`의 env를 `os.environ.copy()`로 그대로 물려받음 — 존재할 것으로 판단됨 |

### 가능한 원인 후보(분류)

이전 조사의 "불일치"는 다음 후보들로 설명될 수 있었으나, 실제로는 아래 첫 번째 후보로 확정됐다:

1. **[확정] 애초에 다른 서비스/컨테이너를 관측했다** — `agent_trading-app-1`은 decision loop를 실행하지 않는 idle 컨테이너이고, compose 선언 자체도 그 서비스에는 없다. "불일치"가 아니라 "처음부터 무관한 대상을 비교했다."
2. (배제됨) 컨테이너가 오래 떠 있어 compose 재정의 이전 상태로 남아 있다 — `ops-scheduler`에서 키가 확인되므로 이 가능성은 이번 발견으로 뒷받침되지 않는다(다만 `ops-scheduler`가 언제 마지막으로 재생성됐는지는 확인하지 않았다).
3. (배제됨) wrapper가 기대한 env 파일을 안 읽는다 — 외부 env 파일 자체가 이 키를 아예 선언하지 않으므로, wrapper의 파일 로딩 성공/실패와 무관하게 compose 기본값이 적용되는 구조다.
4. (미확인) 다른 compose project/파일로 컨테이너가 생성됐을 가능성 — `docker inspect`의 `com.docker.compose.project` 라벨이 두 컨테이너 모두 `agent_trading`으로 동일함을 확인해, 이 가능성은 낮아 보인다.

### 가장 가능성 높은 설명

**이전 조사(§12)의 "불일치" 관측은 실제 배포/env 문제가 아니라, decision loop를 실행하지 않는 `agent_trading-app-1`(idle 컨테이너)의 환경을 확인했기 때문에 발생한 것으로 판단된다.** 실제로 `run_decision_loop.py`가 실행되는 경로(`ops-scheduler` → subprocess)의 컨테이너에서는 이 변수가 존재함을 직접 확인했다. `docker-compose.yml`의 기본값 선언과 실제 실행 경로 사이에 구조적 불일치는 발견되지 않았다.

### 다음 액션 판단

- **문서화만으로 충분하다.** 배포 재확인, 컨테이너 재기동, `.env` 점검 등 운영 조치는 필요하지 않은 것으로 판단된다 — 애초에 "문제"라고 여겼던 관측이 잘못된 대상 비교에서 나온 것이었다.
- 다만 이번 조사에서도 **`ops-scheduler` 프로세스의 실제 env 값 자체**(활성 `"1"`인지, 다른 값인지)는 인용하지 않았다 — 키 존재 여부만 확인했으므로, "정확히 어떤 값으로 활성화되어 있는지"는 이 문서만으로는 확정되지 않는다(다만 값이 무엇이든, §12에서 관측한 "비활성처럼 보였던" 현상 자체가 잘못된 컨테이너 관측에서 비롯된 것이라는 결론에는 영향이 없다).

### 아직 단정하지 못한 부분

- `ops-scheduler` 컨테이너가 언제 마지막으로 (재)생성됐는지, 그 시점이 `docker-compose.yml`의 현재 선언과 일치하는 이미지/설정으로 떠 있는지는 이번 조사에서 별도로 확인하지 않았다(단, 키 존재 자체는 실측으로 확인했으므로 이 부분이 결론에 영향을 주지는 않는다).
- `agent_trading-app-1`이 왜 `tail -f /dev/null`로만 떠 있는지(의도된 설계인지, 다른 목적의 유틸리티 컨테이너인지)는 이번 조사 범위 밖이라 확정하지 않았다 — `scripts/harness/README.md`/`docs/80_harness_engineering/`에서 관련 근거를 찾지 못했다(문서 두 곳을 훑었으나 이 컨테이너의 존재 목적을 명시한 문구를 발견하지 못했다 — 문서 부재일 수도, 조사 범위 부족일 수도 있어 단정하지 않는다).

## 14. `APPLY_CORE_RISK_OFF_TOPK`의 BUY 차단 경로/downstream 영향(2026-08-07 KST)

이번 절은 §13이 "존재를 확인했다"에서 멈춘 것을 이어받아, **이 값이 실제로 BUY 차단 경로와 그 뒤(downstream)의 최종 결정에 영향을 주는지**를 코드 인과 체인 + read-only 실측으로 확인한다. **코드/설정/컨테이너 변경 없음. env 값은 어디에도 인용하지 않는다(존재 여부·실측 결과만 기술).**

**용어 확인**: 코드/문서 어디에도 리터럴 `"downstream"`이라는 필드명은 없다. 이 절에서 "downstream"은 사용자 표현을 그대로 따르되, 코드에서 실제로 발견한 개념 — `decision_orchestrator.py`의 `_check_ai_buy_override_gate()`(로그 태그 `[ai_override_gate]`) 등, **FDC(`FinalDecisionComposerAgent`)가 결정을 내린 뒤 그 결정을 다시 검사·강등할 수 있는 후속 단계** — 로 해석했다. 이 해석 자체가 사용자의 의도와 다를 수 있다는 점을 명시한다.

### 코드 읽기 위치와 분기

1. `scripts/run_decision_loop.py:324-326`: `_APPLY_CORE_RISK_OFF_TOPK`가 `_build_core_risk_off_apply_overrides_for_cycle()`(§13)의 실행 여부를 켠다/끈다. 꺼져 있으면 그 cycle의 `deterministic_trigger_override`에 `core_risk_off_topk_v1` 키가 전혀 만들어지지 않는다.
2. `deterministic_trigger_engine.py`의 `assess_deterministic_triggers()` 진입부에서 `core_risk_off_topk_override = _normalize_core_risk_off_topk_override(deterministic_trigger_override)` — override가 없으면 빈 dict.
3. `apply_topk_override_selected = bool(core_risk_off_topk_override.get("selected"))`가 `_assess_core_risk_off_buy_guard(apply_topk_override_selected=...)`에 전달된다(`:241-244`).

### authoritative guard 영향 범위 — 정확히 어느 단계가 바뀌는가

`_assess_core_risk_off_buy_guard()`(`:620-701`) 안에서 `apply_topk_override_selected`가 바꾸는 것은 정확히 두 곳이다:

- **활동성 최소 기준**: `required_activity_min = _CORE_RISK_OFF_SHADOW_ACTIVITY_MIN if apply_topk_override_selected else 1.20` — override가 선택되면 더 낮은(완화된) 기준을 쓴다.
- **ranking score 하한 우회**: `authoritative_entry_gate_score < _CORE_RISK_OFF_RANKING_MIN_SCORE`일 때, override가 없으면 즉시 차단(`eligibility_core_risk_off_ranking_blocked`)하지만, **override가 선택돼 있으면 차단하지 않고 통과시킨다**(`eligibility_core_risk_off_topk_override_pass` + `eligibility_core_risk_off_shadow_rank_promoted`).

신호 품질(overall/slow) 체크와 전략 체크(strategy)는 override와 무관하게 그대로 적용된다 — override는 ranking/activity 두 지점만 완화한다.

### 그 영향이 실제 BUY pass/block에 반영되는가 — 직접 인과 체인(코드 추적으로 확정)

이 함수의 반환값(`risk_off_exception_eligible`, `core_risk_off_guard_reasons`)은 곧바로 `_assess_buy_eligibility()`에 전달되어 **`eligibility_passed`를 직접 결정**한다(`:225-238`). 그리고 `eligibility_passed`는 `buy_candidate` 산정의 **필수 선행 조건**이다:

```python
# deterministic_trigger_engine.py:279-284
if (
    eligibility_passed
    and entry_score >= thresholds["buy_candidate_threshold"]
    and (regime_switch_v1_gate_assessment is None or ...gate_open)
):
    buy_candidate = True
```

즉 `apply_topk_override_selected` → `eligibility_passed` → `buy_candidate` — **직접 인과 체인이다(간접 영향이나 단순 metadata 변화가 아니다).**

### downstream(FDC 이후) 반영 방식

`decision_orchestrator.py`의 `_check_ai_buy_override_gate()`(약 `:559-` 이후, 로그 태그 `[ai_override_gate]`)는 FDC가 `APPROVE`/`BUY`를 결정했더라도 `deterministic_trigger.buy_candidate`가 `False`면 그 결정을 강등(downgrade)한다:

```python
# decision_orchestrator.py 발췌(요지)
if bool(getattr(deterministic_trigger, "buy_candidate", False)):
    return None  # 강등 없음 — FDC 결정 유지
# buy_candidate=False면 이 아래에서 downgrade_decision(WATCH/HOLD)으로 강등
```

**즉 `apply_topk_override_selected`가 `True`가 되어 `buy_candidate`가 `True`로 바뀌면, `_check_ai_buy_override_gate`가 FDC의 BUY/APPROVE 결정을 강등하지 않고 그대로 통과시킨다. 반대로 override가 없어 `buy_candidate=False`면 FDC가 BUY라고 판단했어도 WATCH/HOLD로 강등된다.** 이는 단순 metadata 변화가 아니라 **최종 결정(decision_type) 자체를 바꾸는 직접 영향**이다.

이 전체 메커니즘은 **`core_risk_off_guard_active=True`일 때만** 작동한다 — 즉 `source_type=='core'`이고 `market_regime.risk_tone=='risk_off'`이고 `market_regime.regime_label=='bearish_trend'`일 때만 관여한다. **`risk_tone`이 `risk_off`가 아닌 상태에서는 이 메커니즘 자체가 개입하지 않는다** — 사용자가 질문한 "risk_tone 관련 결과"와 정확히 이 조건에서만 연결된다.

### `0` vs `1` 차이 요약(코드 기준)

| | `=0`(또는 override 미선택) | `=1`이고 해당 심볼이 top-k로 선택됨 |
|---|---|---|
| 활동성 최소 기준 | `1.20`(엄격) | `_CORE_RISK_OFF_SHADOW_ACTIVITY_MIN`(완화) |
| ranking score 하한 미달 시 | 즉시 차단 | 우회 통과(`topk_override_pass`) |
| `eligibility_passed`(해당 조건 경계에서) | `False`가 될 수 있음 | `True`로 바뀔 수 있음 |
| `buy_candidate` | `eligibility_passed=False`면 항상 `False` | `eligibility_passed=True`이고 entry_score 충족 시 `True` 가능 |
| FDC 이후 `_check_ai_buy_override_gate` | `buy_candidate=False`면 FDC의 BUY를 WATCH/HOLD로 강등 | `buy_candidate=True`면 강등 없이 FDC 결정 유지 |

### read-only 실측 — 실제로 이 경로가 발동한 적이 있는가

컨테이너 `agent_trading-app-1`에서 `trading.trade_decisions`를 read-only로 조회했다(`source_type='core'`, `2026-07-24` 이후, `env 값은 조회하지 않음`):

- `core_risk_off_guard_active=True`(risk_off 레짐이 실제로 활성이었던 decision) 건수: **4044건**
- 이 중 `core_risk_off_experiment.shadow_topk_candidate=True`(top-k 후보 자체가 될 자격이 있었던 건): **0건**
- `apply_selected=True`(override가 실제로 선택된 건): **0건**
- `apply_ready=True`: **0건**
- `eligibility_reasons`에 `eligibility_core_risk_off_topk_override_pass`가 기록된 건: **0건**
- 이 4044건의 `eligibility_passed` 분포: **100% `false`**(4044/4044)

**해석(실측 기반)**: 이번 표본 기간 동안, top-k override가 관여할 수 있는 **전제 조건(`shadow_topk_candidate=True`) 자체가 단 한 번도 성립하지 않았다.** `shadow_topk_candidate`는 `ranking_score`, 신호(overall/slow), 활동성, 전략 4가지를 모두 통과해야 하는데, risk_off 레짐이 활성이었던 4044건 전부가 이 중 최소 하나에서 막혔다. **따라서 이 표본 기간에는 `_APPLY_CORE_RISK_OFF_TOPK`가 `0`이든 `1`이든 실제 BUY 판단 결과에 아무런 차이가 없었을 것으로 판단된다** — 값을 조회하지 않고도 이 결론에 도달할 수 있다(선택 후보 자체가 없었으므로 "선택됨"이 발생할 수 없다).

### 운영값 판단(보수적)

- **"영향은 있지만 지금은 꺼야 한다" / "켜는 게 맞다" 같은 단정은 이번 조사 근거로는 내릴 수 없다.** 코드상 인과관계는 명확히 존재하지만(직접 영향), 실측상 최근 10영업일 동안 그 인과관계가 **한 번도 실제로 발동되지 않았다**(전제 조건 자체가 성립하지 않음).
- **"실제로 downstream에는 거의 영향이 없다"는 이번 표본 기준으로는 맞다** — 다만 이는 "이 메커니즘이 원래 영향이 없다"는 뜻이 아니라 "이 표본 기간에 발동 조건이 우연히든 구조적으로든 성립하지 않았다"는 뜻이다. risk_off 레짐이 더 오래 지속되거나 신호/활동성/전략 조건을 만족하는 종목이 나타나면 언제든 발동할 수 있는 살아있는 코드 경로다.
- **값을 `0`으로 바꿔야 한다거나 `1`로 유지해야 한다는 근거는 이번 조사에서 나오지 않았다.** 이는 "이 완화 메커니즘을 risk_off 국면에서 top-k 한정으로 허용할 것인가"라는 **정책 결정**이며, 코드 조사만으로 대신 판단할 수 없다. 이번 조사가 제공하는 것은 "그 정책을 켜두어도 최근 10일간 실제로 작동한 적이 없었다"는 사실뿐이다.

### 이번 조사 결과만으로 무엇이 맞는가

**"현재 값 유지" 또는 "실제 변경 필요성 없음"이 가장 근접한 결론이다** — 단, 그 근거는 "이 값이 안전하다고 검증됐다"가 아니라 "이 표본 기간에 실제 영향이 관측되지 않았다"이다. "운영 확인 후 변경 검토"는 이 메커니즘을 **의도적으로 활용하려는 목적**(risk_off 국면에서 소수 우량 종목에 예외를 허용)이 있다면 유효한 다음 단계지만, 이번 조사만으로 그 의도 자체를 확인하지는 못했다.

### 아직 단정하지 못한 부분

- "downstream"의 정확한 의미(§ 상단 용어 확인 참고) — 사용자가 실제로 가리킨 화면/필드가 무엇인지 확인하지 못했다.
- `shadow_topk_candidate`가 4044건 전부에서 실패한 정확한 사유(신호/활동성/전략 중 어느 것이 주로 막았는지)는 이번 조사에서 세분화하지 않았다.
- `ops-scheduler`의 실제 env 값 자체(§13에서도 인용하지 않음)는 여전히 확인하지 않았다 — 다만 위 실측 결론은 그 값과 무관하게 성립한다(전제 조건이 없었으므로).
- 이 메커니즘이 설계된 원래 정책 의도(왜 top-k 예외를 두려 했는지)는 관련 SPPV 설계 문서를 깊이 추적하지 않아 확정하지 못했다.

## 15. 유니버스 품질 개선 후속 우선순위(2026-08-08 KST)

`signal_feature_snapshot` 정합성 조사(§10·§11)가 마무리된 상태를 전제로, 본론인 **유니버스 품질 개선**(활동성 부족으로 반복 차단되는 종목을 앞단에서 덜 들어오게 하는 것) 트랙으로 돌아온다. **이번 절은 read-only 정리다 — 코드 변경 없음.**

### 현재까지 닫힌 이슈(재논쟁하지 않음)

- **앞단/뒤단 `signal_feature_snapshot_id` 정합성**(§10·§11): 최근 10영업일 실측 100% 일치 — **닫힘.** 유니버스 품질 문제를 이 경로로 설명할 근거는 없다.
- **`core_risk_off` shadow 세대(v1/v2/v3/v5) 병존**(§12): "정리 대상"이 아니라 활성 A/B 실험 변형으로 확인 — **닫힘.**
- **`APPLY_CORE_RISK_OFF_TOPK` env/기동 경로 불일치**(§13): 잘못된 컨테이너 관측이 원인, 배포 문제 아님 — **닫힘.**
- **`APPLY_CORE_RISK_OFF_TOPK`의 downstream 영향**(§14): 코드상 직접 인과관계는 있으나 최근 10영업일 표본에서 발동 전제 조건 자체가 성립하지 않아 실제 영향 0건 — **닫힘.** (이 항목은 `core` soft demotion 트랙과는 별개 축이다 — `core_risk_off`는 레짐 기반 리스크 게이트이고, soft demotion(A3)는 반복 활동성 부족 이력 기반이다. 서로 다른 문제를 다룬다.)

### 아직 남은 유니버스 품질 문제(구체적으로)

1. **정적 core seed 자체는 활동성과 무관하게 결정된다.** `APPROVED_CORE_UNIVERSE_SYMBOLS`(정적 allowlist) + `instrument_index_memberships`(수동 갱신 DB 테이블) 어느 쪽도 활동성 지표를 참조하지 않는다(이전 세션 조사, 이 문서 상단 §참고). 이는 의도된 설계이고 이번 트랙에서 바꾸지 않기로 이미 합의됐다 — 다만 "정적 seed가 저활동 종목을 계속 다시 공급하는 근본 원인"이라는 사실 자체는 여전히 유효한 잔여 배경이다.
2. **soft demotion(A3)은 core 내부 "순서"만 바꾼다 — 완전 배제가 아니다.** `core_cap`(운영 기본값 12)이 그날 core 후보 풀보다 헐거우면(그날 core 후보가 12개 미만이면) A3가 매칭돼도 여전히 유니버스에 포함된다. 즉 A3는 "cap이 실제로 절단하는 날"에만 효과가 있다 — 이 조건이 얼마나 자주 성립하는지는 이번 세션에서 별도로 실측하지 않았다.
3. **A5(비연속 5일 창 차단일수≥3)는 여전히 관측만 하고 있다.** 시뮬레이션(이전 turn)에서 `001450`류 경계선 변동형을 A3보다 더 자주 잡는 경향이 확인돼 보수적으로 미반영 상태를 유지 중이다 — 이 자체가 "잔여 미해결 범위"다.
4. **A3의 실제 운영 발동 빈도/오탐률이 아직 관측되지 않았다.** shadow-only 관측(PR #178)과 실제 반영(PR #197)은 코드로는 들어갔지만, 실제 운영 데이터에서 A3가 얼마나 자주 발동했는지, 발동 후 해당 종목이 실제로 회복했는지(오탐 여부)는 이번 세션에서 실측하지 않았다.
5. **market_overlay/event_overlay와 core 사이의 "품질 책임" 경계가 명시적으로 문서화되어 있지 않다.** market_overlay는 이미 "활동성과 독립적으로 설계된 것으로 보인다"는 결론이 있었다(이전 원인분해) — 즉 core만 activity 기반 demotion을 적용하는 현재 설계가 옳다는 근거는 있지만, 이 경계를 설계 문서(§`universe_selection_service.md`)에 정식으로 반영하지는 않았다.

### `core soft demotion(A3)`가 해결하는 범위 vs 아직 해결하지 못한 범위

| | A3가 다루는 것 | A3가 다루지 않는 것 |
|---|---|---|
| 대상 | `core` 내부, 연속 3거래일 이상 반복 차단된 종목 | 비연속 반복 차단(A5 영역), core가 아닌 source_type |
| 효과 | core 내부 정렬 최하위로 밀어 `core_cap` 절단 시 배제될 수 있게 함 | 정적 seed 자체의 재유입은 막지 못함(다음 날 다시 후보로 잡힘, 조건 벗어나면 즉시 재진입) |
| 검증 상태 | 코드 반영 완료, 단위 테스트 존재 | 실제 운영 발동 빈도/오탐률 미관측 |

### 유니버스 품질 저하 원인 — 5개 축 재정리

1. **정적 core seed 자체의 한계**: 활동성 무관 선정 — 의도된 설계, 바꾸지 않기로 합의됨. 잔여 배경일 뿐 이번 트랙의 작업 대상은 아니다.
2. **core 내부 ranking/cap 구조의 한계**: `core_cap`이 헐거운 날에는 A3도 무력화됨 — 실측 필요(아래 후보 작업 참고).
3. **soft demotion 관측 기간 부족**: A3가 실제 반영된 지 얼마 되지 않아, 발동 빈도/오탐률에 대한 운영 데이터가 아직 없다 — 가장 직접적인 잔여 공백.
4. **market_overlay/event_overlay와의 역할 경계**: 개념적으로는 정리됐으나 문서에 정식 반영되지 않음 — 낮은 우선순위의 문서화 과제.
5. **downstream gate와의 책임 분리**: §9에서 이미 "일부 입력은 겹치지만 책임은 다르다"로 정리됨 — 추가 작업 불필요, 이 축은 사실상 닫혀 있다.

### 다음 후보 작업 우선순위

| 순위 | 후보 | 왜 필요한가 | 코드 변경 필요? | 리스크 | 지금 바로 가능? |
|---|---|---|---|---|---|
| 1 | **A3 운영 관측**(발동 빈도, 발동 후 회복/지속 패턴, `core_cap` 절단과의 실제 교차 빈도) | A3가 실제로 효과를 내고 있는지, 오탐이 있는지 판단할 유일한 근거 — 지금 이게 없으면 A5/추가 개입 논의 자체가 근거 없는 추측이 된다 | 아니오(read-only 실측) | 낮음 | **예** — 이미 있는 `analyze_core_relative_activity_repeat_gap.py`/`simulate_core_demotion_rules.py` 계열 스크립트를 확장하거나 재사용 가능 |
| 2 | **A5 반영 여부 판단용 추가 실측**(A3 운영 관측과 함께, A5가 추가로 잡을 종목이 실제로 얼마나 되는지, 그 중 오탐 비율) | A5를 반영할지 말지는 아직 근거 부족 — 1순위 관측 데이터가 쌓인 뒤에야 의미 있게 판단 가능 | 아니오(read-only) | 낮음 | 조건부(1순위 데이터 축적 후) |
| 3 | **`core_cap` 절단이 실제로 얼마나 자주 발생하는지 실측**(그날 core 후보 수가 12개를 넘는 날의 비율) | A3의 실효성 자체가 이 조건에 달려 있다 — cap이 거의 항상 헐거우면 A3는 관측 지표로서만 의미 있고 실제 배제 효과는 미미할 수 있다 | 아니오(read-only) | 낮음 | **예** — 이전 세션 데이터(core 유니버스 크기 12 고정 관찰)로 일부 추정 가능, 정식 실측은 아직 없음 |
| 4 | **`universe_selection_service.md` 설계 문서에 core/event/market 품질 책임 경계 정식 반영** | 문서화 공백 — 다음에 유사한 품질 개입을 설계할 때 매번 재추론하지 않도록 | 아니오(문서만) | 낮음 | 가능하나 낮은 우선순위 |

### 지금 바로 구현할 것 vs 운영 관측 후 결정할 것

- **지금 바로 구현할 것: 없음.** A3 이후 추가 코드 개입(A5 반영, 새 demotion 규칙, 새 prefilter)을 지금 넣을 근거는 없다 — 1순위 관측이 선행되지 않은 상태에서의 추가 구현은 근거 없는 확장이다.
- **운영 관측 후 결정할 것**: A5 반영 여부/강도, `core_cap` 정책 조정 필요성, 추가 demotion 규칙 도입 여부 — 전부 1~3순위 관측 데이터가 쌓인 뒤에 판단해야 한다.

### 질문 7에 대한 명확한 답

**A3 외 추가 품질 개입을 지금 바로 넣을 근거는 없다. A3 운영 관측이 먼저다.** A3가 실제 반영된 지 얼마 되지 않았고, 발동 빈도조차 실측하지 않은 상태에서 A5나 다른 규칙을 추가하면 "효과가 있는지도 모르는 것 위에 또 다른 것을 쌓는" 구조가 된다.

### 권장 다음 1턴 작업

**A3 운영 관측(1순위) — read-only 실측 1건으로 좁힌다.** 구체적으로: A3 반영(PR #197) 시점 이후 실제 운영 데이터에서 (a) A3 매칭으로 `CORE_SIGNAL_TIER_DEMOTED`가 부여된 사례가 얼마나 있었는지, (b) 그 사례들이 `core_cap` 절단과 실제로 교차해 유니버스에서 빠진 적이 있는지, (c) demotion됐던 종목이 이후 활동성을 회복해 정상 복귀했는지를 확인한다. 이 실측 결과가 나와야 A5/추가 규칙 논의를 근거 있게 다시 열 수 있다.

## 16. A3 실제 운영 발동 상태 계량 측정(2026-08-08 KST)

§15가 권장한 다음 1턴 작업을 수행했다. **코드 변경 없음** — 새 read-only 분석 스크립트 `scripts/analysis/measure_a3_operational_effectiveness.py`를 추가해 A3(streak≥3)가 실제 운영 데이터에서 얼마나 자주 발동했는지, `core_cap` 절단과 교차해 실제 배제로 이어졌는지, 이후 회복 패턴이 어떤지를 계량했다.

### 측정 방법과 그 근거

운영 코드가 실제로 계산한 A3 판정은 DB에 저장되지 않는다(메모리 diagnostics에만 존재). 대신 다음 관찰로 "실제 배제 여부"를 판정했다: A3는 매 compose 시점에 **그 직전까지의** 차단 이력만 보고 core 내부 정렬을 낮춘다. 따라서 **d일 진입 시점(=d-1일 종가 기준) streak≥3인 종목이 d일에 core로 평가된 decision이 단 한 건도 없다면**, 이는 그날 freeze에서 실제로 빠졌다는 직접 증거다 — decision은 그날 freeze에 포함된 종목에만 생성되기 때문이다(`run_decision_loop.py`의 freeze-then-evaluate 계약, §10 참고). streak 계산 로직은 `simulate_core_demotion_rules.py`와 동일하다.

**한계**: d일 결측이 정확히 `core_cap` 절단 때문인지, liquidity 예외(정지/관리종목 등) 때문인지는 구분하지 못한다 — "배제 후보"로만 보고했다.

### 실행

- 컨테이너: `agent_trading-app-1`
- 짧은 범위(2일) 검증: `python3 scripts/analysis/measure_a3_operational_effectiveness.py --date-from 2026-08-05 --date-to 2026-08-06 --account-alias 'Entrypoint Paper' --output-json /tmp/uag_a3/short_result.json` → 이벤트 1건, 정상 동작 확인.
- 본 실측(최근 10영업일): `python3 scripts/analysis/measure_a3_operational_effectiveness.py --date-from 2026-07-24 --date-to 2026-08-06 --account-alias 'Entrypoint Paper' --output-json /tmp/uag_a3/result_10d.json`
- **A3 반영(PR #197, 2026-08-07T01:28 UTC) 이후 보조 창**: 이번 문서 작성 시점(2026-08-08) 기준으로 반영 이후 아직 만 하루도 지나지 않아, 의미 있는 별도 표본을 구성할 수 없었다 — 이 보조 창은 이번 실측에서 생략했다(향후 며칠~1~2주 누적 후 재실측 필요).

### 결과 — 발동 빈도

- **A3 매칭 이벤트: 11건**(5개 종목, 6개 거래일에 분산)
- 발동 종목: `000810`(4건), `001800`(3건), `001450`(2건), `000240`(1건), `081660`(1건)
- 일별 분포: `2026-07-24`(1건), `07-27`(2건), `07-28`(2건), `07-29`(2건), `07-30`(3건), `08-06`(1건) — **특정 며칠에 몰리지 않고 10거래일 중 6일에 걸쳐 분산**돼 있다. 다만 `07-25`/`07-26`(주말), `07-31`~`08-05` 구간에는 발동이 없었다.

### 결과 — `core_cap` 교차/실제 배제 효과

- **실제 배제 후보(그날 core decision 자체가 없음): 2건/11건(18.18%)** — `000810`(1건, `07-30`), `081660`(1건, `08-06`)
- **발동했지만 배제로 이어지지 않음(그날도 core decision이 있었음): 9건/11건(81.82%)**

**해석(보수적)**: A3는 발동하지만, 발동이 곧 배제로 이어지는 경우는 소수(약 18%)다. 나머지 82%는 "순위는 낮아졌으나 `core_cap`과 교차하지 않아 그날도 유니버스에 포함됐다"는 뜻이다 — 이를 "무의미"라고 단정하지 않는다. 순위 하향 자체는 매번 적용됐고, cap이 더 빡빡하게 절단되는 날(§15가 언급한 "core_cap 절단 실측"이 필요한 이유)이었다면 배제 비율이 달라졌을 수 있다.

### 결과 — 이후 회복 패턴(사후 관찰 지표, 정책 판정 아님)

- 회복 관찰 가능(3거래일 내 재등장) 이벤트: 11건 중 11건(전부 관찰 가능)
- 그중 다음 재등장일에 `passed`(정상 통과)로 회복: **3건/11건(27.27%)**
- 나머지 8건(72.73%)은 재등장 시에도 여전히 `blocked` 상태였다.

**표현 원칙 준수**: 이 27.27%는 정책 오류를 뜻하지 않는다 — A3가 계속 정확하게 저활동 종목을 잡아내고 있다는 뜻으로도, 가끔 회복하는 종목을 과도하게 잡는다는 뜻으로도 양쪽 다 해석 가능한 관찰 지표일 뿐이다.

### A3의 발동 성격 분류

**"자주 발동하지만 `core_cap`과 거의 안 만난다"에 가장 가깝다.** 10영업일 중 6일에 걸쳐 11건이 발동했으니 드물다고 보기는 어렵지만, 그중 실제 배제로 이어진 것은 2건(18%)뿐이다. "드물게 발동하지만 만날 때 효과가 크다"거나 "거의 발동하지 않는다"는 이번 표본과 맞지 않는다.

### 이번 실측 결과만으로 다음이 무엇인가

- **A3 유지**: 근거 있음 — 실제로 발동하고 있고(11건/10일), 배제 효과도 일부 확인됐다(2건). 유지에 반대할 근거는 나오지 않았다.
- **A5 추가 검토**: **아직 근거 부족.** 이번 실측은 A3만 다뤘고, A5가 추가로 무엇을 더 잡을지는 별도 실측이 필요하다 — §15의 결론("A3 외 추가 개입을 지금 바로 넣을 근거 없음")이 이번 실측으로도 바뀌지 않았다.
- **`core_cap` 추가 실측**: **가장 가치 있는 다음 후보로 뒷받침됨.** 배제율이 18%로 낮게 나온 이유가 "그날 core 후보 풀이 애초에 cap보다 작았기 때문"인지 "다른 종목들이 더 낮은 순위였기 때문"인지는 이번 실측에서 구분하지 못했다 — `core_cap` 절단이 실제로 얼마나 자주 발생하는지를 알아야 이 18%를 올바르게 해석할 수 있다.

### 대표성 한계

- 표본 10영업일·1개 계정(`Entrypoint Paper`)뿐이다.
- A3가 반영된 지 얼마 되지 않아(§실행 참고), 이번 측정 대상 기간(`2026-07-24`~`08-06`)은 A3가 **실제 코드에 반영되기 이전** 기간이다 — 즉 이번 수치는 "A3 규칙을 그 기간 데이터에 사후 적용했을 때의 결과"이며, "A3가 실제로 그 기간 동안 운영 결정에 영향을 줬다"는 뜻이 아니다. **이는 §10~§16 전체에서 최초로 명시하는 중요한 구분이다** — A3의 판정 로직 자체(streak 계산)는 코드 반영 전후로 달라지지 않으므로 "발동 여부/빈도" 수치는 유효하지만, "그 발동이 실제로 그 시점 유니버스 구성에 영향을 줬다"는 인과적 주장은 반영 이후 데이터에서만 성립한다.
- "실제 배제 후보"는 원인(cap vs liquidity 예외)을 구분하지 못하는 관찰일 뿐이다.
- 회복 관찰은 3거래일 창으로 한정했다 — 더 긴 창에서는 다른 비율이 나올 수 있다.

## 17. A3 post-deploy 초기 운영 관측(2026-08-10 KST)

§16의 실측은 **A3가 실제 코드에 반영(commit `ec76ff26`, 2026-08-07 병합)되기 이전 기간**(`2026-07-24`~`08-06`)의 데이터에 규칙을 사후 재구성한 것이었다. 이번 절은 그 공백을 메운다 — **A3 반영 이후 실제 운영 기간**의 데이터를 같은 스크립트로 재실행한 **post-deploy 실제 운영 관측**이다. **코드 변경 없음, 신규 스크립트 없음** — `scripts/analysis/measure_a3_operational_effectiveness.py`를 그대로 재사용했다.

**용어 구분(반드시 유지)**: §16은 "pre-deploy 사후 재구성", 이 절은 "post-deploy 실제 운영 관측"이다. 두 결과를 같은 성격으로 섞어 쓰지 않는다.

### 분석 기간과 표본 크기

- 명령: `python3 scripts/analysis/measure_a3_operational_effectiveness.py --date-from 2026-08-07 --date-to 2026-08-10 --account-alias 'Entrypoint Paper' --output-json /tmp/uag_a3_postdeploy/result.json`(컨테이너 `agent_trading-app-1`)
- 요청 구간은 `2026-08-07`~`2026-08-10`(4일)이지만, 실제 거래일은 **`2026-08-07`(금)과 `2026-08-10`(월) 2일뿐**이다(`08-08`/`08-09`는 주말).
- **표본이 매우 짧다 — 이 사실 자체가 이번 관측의 중요한 결과다.** A3가 반영된 지 실질적으로 영업일 기준 2일밖에 지나지 않았다.

### post-deploy 발동 결과

- **A3 매칭 이벤트: 2건** — 고유 종목 **1개**(`138040`), 거래일 **2일**(`08-07`, `08-10`)
- **실제 배제 후보(그날 core decision 자체 없음): 0건/2건(0%)**
- 발동했지만 배제로 이어지지 않음(그날도 core decision 있었음): 2건/2건(100%)

### post-deploy 회복 패턴(사후 관찰 지표)

- 회복 관찰 가능 이벤트: 2건/2건
- 다음 재등장일에 `passed`로 회복: **0건/2건(0%)** — 2건 모두 재등장 시에도 `blocked` 상태 유지

### pre-deploy 재구성(§16) vs post-deploy 관측(이 절) 비교

| | pre-deploy 재구성(§16, `07-24`~`08-06`) | post-deploy 관측(이 절, `08-07`~`08-10`) |
|---|---|---|
| 실제 거래일 수 | 10일 | 2일 |
| A3 매칭 이벤트 | 11건 | 2건 |
| 고유 종목 | 5개 | 1개 |
| 실제 배제 후보 비율 | 18.18%(2/11) | 0%(0/2) |
| 회복률(3거래일 내) | 27.27%(3/11) | 0%(0/2) |

**비교 판단(보수적): 아직 비교 자체가 이르다.** post-deploy 표본이 n=2로 극히 작아 — 비율(0% vs 0%, 18.18% vs 0%)의 차이를 "post-deploy에서 배제 효과가 줄었다"거나 "회복이 안 된다"는 경향으로 해석하면 표본 크기 오류다. 두 표본이 "같은 경향"인지 "다른 경향"인지 판단할 수 있는 통계적 근거 자체가 아직 없다.

### 발동 0건이 아니라는 점의 의미

이번 표본에서는 발동이 0건이 아니라 2건이었다 — A3가 반영 이후 실제로 작동하고 있다는 최소한의 증거는 확보됐다. (발동이 0건이었다면 "표본 부족" 또는 "초기 운영 기간 특성" 가능성을 함께 봐야 했을 것이나, 이번에는 그 시나리오에 해당하지 않는다.)

### 지금 판단 가능한 것 / 아직 판단 불가능한 것

**지금 판단 가능한 것**:
- A3가 반영 이후 실제로 발동하고 있다(0건이 아님).
- 이 최소 표본에서는 발동이 그날의 core decision 존속(배제 없음)과 함께 관측됐다 — 즉 이 2건은 순위만 낮아졌을 뿐 유니버스에서 빠지지 않았다.

**아직 판단 불가능한 것**:
- A3가 post-deploy 기간에 `core_cap`과 실제로 교차해 배제 효과를 내는지(0/2라는 수치를 "배제 효과가 없다"는 결론으로 쓸 수 없다 — n=2).
- 회복률이 pre-deploy와 다른 경향인지(n=2로는 통계적 의미 부여 불가).
- A5 검토로 넘어갈 근거가 쌓였는지 — **여전히 아니다.** 이번 관측은 오히려 "A3 관측을 더 쌓아야 한다"는 §15/§16의 기존 결론을 그대로 뒷받침한다.

### 이번 결과가 뒷받침하는 다음 단계

**A3 유지 + 추가 관측 누적 필요.** A5 검토 시작을 뒷받침할 근거는 이번에도 나오지 않았다. post-deploy 표본이 실용적인 통계적 판단이 가능한 수준(예: 최소 몇 영업일, 두 자릿수 이벤트)에 도달할 때까지 이 스크립트를 주기적으로 재실행해 누적하는 것이 다음 단계다 — 새로운 규칙이나 코드 개입은 이번 결과로 정당화되지 않는다.

### 대표성 한계

- 실제 거래일 2일, 이벤트 2건, 종목 1개뿐이다 — 이 절의 모든 수치는 방향성 참고용일 뿐 결론 근거로 쓸 수 없다.
- 계정 1개(`Entrypoint Paper`)로 한정.
- 회복 관찰 창은 3거래일로 한정 — 더 긴 창에서는 다른 비율이 나올 수 있다.

## 다음 단계 제안

**설계/문서 정리를 우선한다.** 코드 리팩터링(1순위인 `core_risk_off` 정리조차)은 `src/AGENTS.md`의 리스크 경계 원칙상 이번 감사만으로 바로 들어가면 안 된다. 권장 순서:

1. (문서) 신호 신선도 이중 정의(§6-2) 명문화 — 가장 낮은 리스크, 가장 빠른 착수 가능.
2. (조사) `core_risk_off` shadow v1~v5의 실제 도입 이력/현재 활성 여부 read-only 조사 — 1순위 정리의 선행 작업.
3. (문서) `universe_selection_service.md`에 4층 구분(selection/ranking/gating/execution) 정식 편입.
4. market_overlay 목적 재정의는 사용자 판단이 필요한 정책 논의 사안 — 이번 문서에서 결론 내지 않는다.

현상 유지가 아니라 **문서/조사 우선 후속 착수**를 권장한다 — 다만 어떤 코드 리팩터링도 이번 감사 결과만으로 바로 시작하지 않는다.
