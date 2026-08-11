# 손실률 기반 Loss-cut 정책 명세 초안(A) + 설정 경로 설계 초안

> **문서 성격**: 정책/설정 **설계 문서**다. 이 문서 자체는 어떤 코드도 변경하지
> 않는다. 기존 held_position 청산 경로에 실제로 연결하는 구현(아래에서
> "B단계"로 지칭)은 이 문서의 범위 밖이며, 별도 착수 턴에서 이 문서를
> 근거로 진행한다.
> **선행 조사**: [`loss_cut_policy_investigation.md`](../../20_system_analysis/loss_cut_policy_investigation.md)(`docs/20_system_analysis/`) —
> 현재 운영 코드에 손실률 기반 Loss-cut이 없다는 사실 확인, 정책안 3종(A/B/C)
> 1차 비교, 설정 경로가 `env`가 아니라 `config_versions` 계열이어야 하는
> 이유의 1차 근거(설계 조사/현황 분석 문서). 이 설계 문서는 그 결론을
> **구현 직전 수준까지 구체화**한다.
> **선례**: [`06_config_schema.md`](./06_config_schema.md) §9,
> [`config_version_admin.py`](../../../src/agent_trading/services/config_version_admin.py) —
> `risk.max_single_position_pct`를 `config_versions` + Admin API/CLI로
> 관리하는 이미 운영 중인 경로. 이 문서의 설정 경로 설계는 이 선례를
> 최대한 그대로 재사용한다.

## 0. 사실 / 해석 / 추천 구분 안내

이 문서 전체에서:
- **[사실]** = 실제 코드를 읽고 확인한 것(파일:라인 인용 포함).
- **[해석]** = 확인된 사실로부터 합리적으로 추론했으나 코드에 명시적으로
  적혀 있지는 않은 것.
- **[추천]** = 이 문서 작성자(에이전트)의 설계 판단 — 사용자 결정이 필요한
  지점이며, 되돌릴 수 없는 방식으로 코드에 반영되지 않았다.

## 1. 문제 정의

현재 운영 코드는 보유 포지션의 청산을 **신호 기반**(AI risk_opinion/
risk_score, thesis invalidation, edge collapse, downside shock,
holding_profile 만료)으로만 결정한다([사실], `loss_cut_policy_
investigation.md`(`docs/20_system_analysis/`) §1.3). 매수가(평균단가) 대비 손실률이 얼마든 이 값만
가지고 청산을 강제하는 경로는 없다. 사용자가 요청한 것은 "-10% 넘으면
더 손실 나기 전에 처분"이라는 **정량 손절 규칙**이며, 이 문서는 그
규칙의 명세(threshold 구조, 적용 범위, 기존 로직과의 합성 규칙, 기준
가격, 재진입 제한)와, 그 규칙을 운영자가 안전하게 바꿀 수 있는 설정
경로를 확정 가능한 수준까지 구체화한다.

## 2. 현재 코드 기준 현황 (요약, 상세는 선행 조사 문서 참고)

### 2.1 청산 판정이 실제로 일어나는 위치와 순서 [사실]

`decision_orchestrator.py`의 `assemble()`은 아래 순서로 여러 "guard"
함수를 **순차 적용**하며, 각 guard는 이전 guard의 결과를 그대로
덮어쓴다(공통 severity 비교 로직 없음 — 마지막에 실행된 guard가 이긴다):

1. `_check_held_position_sell_override`(L355-413, 호출 L2140-2170) —
   `source_type=="held_position"`이고 AI Risk가 강한 부정 신호일 때
   HOLD/APPROVE/BUY → REDUCE/EXIT.
2. `_check_source_policy_upgrade_guard`(L2172-2239)
3. `_check_watch_candidate_upgrade_guard`(L2241-2290)
4. `_check_held_position_exit_hysteresis_gate`(L746-801, 호출
   L2292-2348) — 1번이 이미 REDUCE/EXIT로 바꿔놓은 것을 다시
   `evaluate_symbol_state_sell_hysteresis()`(`reverse_trade_
   hysteresis.py`)로 재검증해, "이른 축소 구간"(`earliest_reduce_at`
   이전)이면서 아래 §2.2의 escape-hatch 키워드가 하나도 없으면
   `"WATCH"`로 **되돌린다**.
5. `_check_buy_eligibility_upgrade_guard`(L2350-2399)
6. `_check_ai_buy_override_gate`(L2401-2457)

### 2.2 hysteresis escape-hatch 키워드 [사실, 직접 재확인]

`reverse_trade_hysteresis.py:441-453`:

```python
holding_profile_breach = _contains_keyword(
    risk_flags + reason_codes,
    ("breach", "stop_loss", "drawdown", "mae", "adverse", "concent", "expos", "over"),
)
if edge_collapse or downside_shock or thesis_invalidation or holding_profile_breach:
    return ExitHysteresisDecision(blocked=False, details=merged_details)
```

`"stop_loss"`/`"drawdown"`이 **이미** 이 키워드 목록에 존재한다 — 단,
지금은 AI가 생성한 텍스트에 이 단어가 우연히 있는지만 보는 정성적
게이트이고, 실제 숫자 손실률 계산과는 무관하다.

### 2.3 재사용 가능한 저장 구조 [사실]

`SymbolTradeStateEntity`(`entities.py` ~L150-181)는 이미
`minimum_hold_until`, `reentry_cooldown_until`, `sell_cooldown_until`
필드를 갖고 있고, `decision_orchestrator.py::_persist_symbol_trade_
state_from_decision()`(L860-1078)이 실제로 채우며, `reverse_trade_
hysteresis.py`가 실제로 읽는다 — 선언만 되고 안 쓰이는 필드가 아니다.
자유 형식 `metadata_json["holding_profile_policy"]` dict도 이미 존재해
`earliest_reduce_at`/`earliest_reentry_at` 같은 추가 필드를 코드
스키마 변경 없이 얹는 관례가 있다.

### 2.4 가격 데이터 가용성 [사실]

`position_snapshot`(`average_price`, `market_price`, `unrealized_pnl`
포함)은 `assemble()` 내부 L1901-1999에서 held_position 여부와 무관하게
**모든** 심볼에 대해 이미 조회되어 `AssembledContext`에 실려 있다 —
`_check_held_position_sell_override`(L355-360 시그니처)는 현재 이
값을 인자로 받지 않을 뿐, 새로 조회할 필요 없이 넘겨받기만 하면 된다.

### 2.5 `source_type`별 차등 처리 선례 [사실]

`held_position`은 이미 `sizing_engine.py`(축소 비율 전용 분기),
`submit_lane_gate.py`(예산 게이트 우회), `holding_profile_policy.py`
(전용 보유 프로필)에서 다른 `source_type`(`core`/`event_overlay`/
`market_overlay`/`reconciliation_overlay`)과 다르게 취급된다 — "Loss-cut을
source_type별로 다르게 둘지"는 이 저장소에서 처음 시도하는 패턴이
아니다.

### 2.6 `config_versions`의 실제 세분화 단위 [사실, 직접 재확인]

`ConfigVersionEntity`(`entities.py:76-86`)와 `db/migrations/0001_
initial_schema.sql:81-94`의 실제 컬럼은 `config_version_id, client_id,
environment, version_tag, config_json, checksum, created_at,
activated_at, activated_by`뿐이다. **`account_id`/`strategy_id`/
`source_type` 컬럼은 없다.** `get_active(client_id, environment)`가
유일한 조회 키다. `06_config_schema.md`의 예시 `config_json`에
`strategy_id: swing_equity_v1`이 나타나지만, 이건 **JSON 값으로
중첩된 것**이지 별도 컬럼/조회 차원이 아니다.

### 2.7 shadow 실험용 env 플래그 선례 [사실]

`.env.example`에 이미 `REGIME_SWITCH_V1_GATE_OVERRIDE_ENABLED=false`,
`ENTRY_SCORE_R3B_ALPHA_ENABLED=false`, `EV_GATE_NEAR_MISS_OVERRIDE_
ENABLED=false` 패턴이 있고, `decision_orchestrator.py.__init__()`
(L273-329)이 이를 생성자 인자로 받아 "기본값(false)이면 기존 동작과
100% 동일"을 코드 주석으로 명시한다. 이 명명 규칙(`<FEATURE>_
ENABLED=false`, 기본 꺼짐, 순수 게이팅 함수)이 이번 설계가 따를
기존 관례다.

## 3. 정책 명세 초안(A)

### 3.1 적용 범위(전량 vs 부분) — [추천] 2단계(staged) 구조

| 옵션 | 판단 |
|---|---|
| 전량 청산만 | 단순하지만, `-10%`를 살짝 넘는 순간 전량 처분은 "손실 회피"이지 "기대값 개선"이 아닐 수 있다(`loss_cut_policy_investigation.md`(docs/20_system_analysis/) §2 안 A 비판 그대로 적용) |
| 부분 축소만 | 손실이 계속 깊어지는 tail 위험을 막지 못한다 |
| **2단계(soft→hard)** | soft 임계치(예: -7%)에서 **부분 축소(REDUCE)**, hard 임계치(예: -12%)에서 **전량 청산(EXIT)** — tail 위험은 막되, 일시적 조정에 즉시 전량 반응하지 않는다 |

**[추천] 2단계 구조를 채택한다.** 구체적 임계치 숫자(-7%/-12%,
축소 비율 등)는 이 문서에서 확정하지 않는다 — §5(구현 전 확인 필요
사항)에서 사후 성과 실측(shadow) 후 결정하도록 명시한다. 임계치는
config로 완전히 외부화하므로, 이 결정 자체가 코드 변경을 요구하지
않는다.

### 3.2 `source_type`별 적용 차이 — [추천] 기본은 균일 적용 + 확장 가능한 override 구조

- **[추천]** v1은 모든 `source_type`에 **동일한** loss-cut 규칙을
  기본 적용한다 — "이 포지션이 왜 매수됐는가"와 무관하게 "지금 이만큼
  손실 중"이라는 사실 자체는 `source_type`을 가리지 않기 때문이다.
- 단, §2.6의 확인대로 config_json은 이미 JSON이므로, `source_type_
  overrides`라는 선택적 nested map을 스키마에 포함해 둔다(§4.2) —
  지금 값을 채우지 않으면 균일 적용과 100% 동일하게 동작하며, 향후
  "held_position만 더 타이트하게" 같은 조정이 필요해지면 코드/스키마
  변경 없이 config 값만 추가하면 된다.
- **held_position에 대한 특기 사항**: `holding_profile_policy.py`가
  이미 held_position을 `"risk_reduction_only"` 프로필로 두어 그
  자체로 축소 편향이 있다(§2.5). Loss-cut이 여기 추가로 적용되면
  "이미 축소 지향인 포지션에 또 다른 축소 규칙이 겹치는" 구조가
  되므로, held_position에 한해 soft 임계치를 더 낮게(더 보수적으로)
  주는 것이 합리적일 수 있다 — 이것도 §5의 확인 필요 사항으로 남긴다.

### 3.3 기존 `reduce`/`exit`와의 합성 규칙 — [추천] 새 guard를 1번과 4번 사이에 삽입

§2.1의 순서를 그대로 이용해, **`_check_loss_cut_override`라는 새
guard를 1번(`_check_held_position_sell_override`) 바로 다음, 4번
(`_check_held_position_exit_hysteresis_gate`) 이전에 삽입한다.**

이유:
- 1번 다음에 두면, AI가 HOLD/BUY로 판단한 포지션이라도 손실률
  임계치를 넘으면 loss-cut이 **덮어써서** REDUCE/EXIT로 격상할 수
  있다("last-mutator-wins" 규칙, §2.1) — "합성 규칙"의 핵심은 여기서
  loss-cut이 AI의 낙관적 판단을 **강제로 이긴다**는 것이다.
- 4번(hysteresis gate) 이전에 두면, loss-cut이 만든 REDUCE/EXIT도
  기존 "이른 축소 구간" 안전장치를 완전히 우회하지 않는다 — 대신
  **loss-cut이 자신의 `reason_codes`/`risk_flags`에 `"stop_loss"`
  또는 `"drawdown"`을 명시적으로 포함시켜**(§2.2에서 확인한 기존
  escape-hatch 키워드) hysteresis gate가 이를 정당한 이탈 사유로
  인식하고 통과시키도록 한다. **새 코드를 `reverse_trade_hysteresis.
  py`에 추가할 필요가 없다** — 기존 게이트를 그대로 재사용한다.
- 이 설계의 함의: loss-cut은 "AI의 낙관을 이길 수 있지만, hysteresis
  gate의 관점에서는 기존에 이미 존재하던 정당한 이탈 사유(경제적
  손절)의 하나로 취급된다." 완전한 우회 권한을 주지 않는 이유는,
  손실률 계산이 스냅샷 지연이나 일시적 급락에 취약할 수 있는데(§3.4)
  이를 무조건적 최우선 규칙으로 두면 whipsaw(손절→반등→재진입)
  위험이 더 커지기 때문이다. **[사용자 확인 필요]**: 이 판단(부분적
  우선순위, 완전 우회 아님)에 동의하는지.

### 3.4 기준 가격 — [추천] snapshot 기준(`position_snapshot.market_price`), 실시간 폴백 없음(v1)

- §2.4에서 확인했듯 `market_price`/`average_price`는 결정 시점에
  이미 로드돼 있다 — **v1은 이 스냅샷 값을 그대로 쓴다**(신규 조회
  없음, 기존 결정 사이클과 동일한 데이터 신선도 계약을 따름).
- 실시간 quote 폴백은 v1 범위에서 제외한다 — 이유: (1) 신규 API
  호출/latency 예산 증가, (2) 이 시스템은 이미
  `data_quality.max_quote_delay_seconds`류 신선도 게이트가 있어
  스냅샷 자체의 신선도는 그 프레임이 별도로 보장한다, (3) loss-cut처럼
  "즉시 최신가"가 결정적으로 중요한 규칙은 스냅샷 지연 시 **오히려
  더 위험**할 수 있어(지연된 스냅샷이 실제보다 낙관적이면 손절이
  늦어짐) 이 리스크는 §5의 확인 필요 사항으로 명시적으로 남긴다.
- 손실률 계산식: `loss_pct = (market_price - average_price) /
  average_price * 100`(계산 기준가로 `average_price`를 쓰고,
  이동평균 원가 `position_cost_basis_state.average_cost`는 쓰지
  않는다 — 두 값을 섞으면 "기준에 따라 손실률이 달라지는" 혼란이
  생기므로 단일 소스로 고정한다, `loss_cut_policy_investigation.md`(docs/20_system_analysis/)
  §4에서 이미 지적한 원칙 그대로).

### 3.5 재진입/재발동 제한(cooldown) — [추천] 기존 `metadata_json["holding_profile_policy"]` 재사용

- 신규 DB 컬럼/마이그레이션 없이, `SymbolTradeStateEntity.metadata_
  json["holding_profile_policy"]`에 `loss_cut_triggered_at`/`loss_
  cut_cooldown_until` 필드를 추가하는 방식을 추천한다(§2.3의 기존
  관례와 동일).
- **[추천]** loss-cut으로 인한 EXIT 이후의 재진입 cooldown은 일반
  신호 기반 EXIT보다 **더 길게** 둔다 — 손실 직후 즉시 재진입하면
  "손절→반등→재진입" whipsaw로 같은 종목에서 반복 손실이 날 위험이
  있다. 구체적 시간(예: N거래일)은 §5로 남긴다.
- REDUCE(soft 단계)는 cooldown을 걸지 않는다 — 포지션이 아직 남아
  있으므로 "재진입"의 개념 자체가 적용되지 않는다.

### 3.6 shadow 단계 vs 정식 운영 단계 — [추천] 명확히 분리된 두 단계

| 항목 | Shadow 단계 | 정식 운영 단계 |
|---|---|---|
| 실제 주문/decision_type 변경 | **없음** — `_check_loss_cut_override`는 계산만 하고 로그/필드에만 기록, `object.__setattr__`로 실제 값을 바꾸지 않음 | 있음 — §3.3의 guard가 실제로 개입 |
| 활성화 스위치 | `env`(`LOSS_CUT_SHADOW_ENABLED`, §4.3) | `config_versions`의 `risk.loss_cut.enabled`(§4.2) |
| 목적 | "지금 발동했다면 어떤 성과였을까"를 누적 관측(기존 `scripts/validate_r3b_stop_loss_ablation.py` 패턴의 상시화) | 실제 리스크 통제 |
| 전환 조건 | — | shadow 누적 표본으로 "loss-cut 발동 표본의 사후 성과가 미발동 대비 개선"이 확인된 뒤에만(이 저장소의 반복 원칙 — 빈도가 아니라 기대값 개선으로 판단) |

### 3.7 구현 현황(2026-08-11 갱신) — [사실]

§3.6의 shadow 단계를 실제로 구현했다. 이 문서가 초안 시점에
`_check_loss_cut_override`라는 이름의 guard 함수를 가정했던 것과
달리, 실제 구현은 **guard 목록에 전혀 속하지 않는 별도 private
메서드**(`_record_loss_cut_shadow_observation()`, `decision_
orchestrator.py`)로 만들었다 — 어떤 `object.__setattr__` 호출도
하지 않는다는 것을 이름과 구조 모두로 드러내기 위해서다.

- 실제 구현: `src/agent_trading/services/loss_cut_shadow.py`
  (순수 계산) + `decision_orchestrator.py::assemble()`에서
  `trade_decision_id` 확정 **직후**(모든 결정 mutating guard가
  끝난 뒤) 호출.
- 관측 대상: §3.2가 열어둔 질문(source_type별 차등)에 대해, shadow
  단계에서는 차등을 두지 않고 `position_snapshot.quantity > 0`인
  모든 사이클에 공통 적용했다 — `source_type`은 payload에 기록만
  하고 필터링에는 쓰지 않는다(표본이 쌓이면 사후에 `source_type`별
  분리 집계 가능).
- 저장: §2.3이 언급한 재사용 가능 저장 구조 중 `decision_json`
  additive JSONB patch(`sync_execution_sizing()`과 동일 패턴)를
  택했다 — 신규 테이블 없음.
- 상세 근거/검증 결과: `docs/40_action_plans/loss_cut_policy_and_
  config_path_action_plan.md` 2단계.
- **read path 보강(2026-08-11 후속)**: `GET /trade-decisions`만으로는
  운영자가 raw JSON을 뒤져야 했던 문제를 `GET /trade-decisions/
  loss-cut-shadow/summary`(계좌×기간 집계)와 `GET /trade-decisions/
  loss-cut-shadow/samples`(개별 관측 표본, cursor pagination)로
  보강했다 — 신규 계산 엔진이나 신규 write 경로는 추가하지 않았고,
  `decision_json.loss_cut_shadow`를 그대로 읽어 집계만 한다(상세:
  action plan "2단계 후속").
- **일자별 breakdown 추가(2026-08-11 추가 후속)**: `summary`가
  기간 전체를 하나의 숫자로만 합산하는 한계를 `GET /trade-decisions/
  loss-cut-shadow/daily`로 보강했다 — 신규 repository/SQL 없이
  기존 `list_loss_cut_shadow_observations()`의 원시 행을 route에서
  KST 날짜로 그룹핑만 한다(상세: action plan "2단계 후속 2").
- **realized PnL 교차 inspection 추가(2026-08-11 추가 후속)**:
  `GET /trade-decisions/loss-cut-shadow/by-instrument`로 종목별
  shadow 발동 이력(`shadow_triggered_count`/`latest_shadow_at`)과
  기존 realized PnL 누계(`realized_pnl_daily_aggregates`)·
  `position_cost_basis_state.recompute_required`를 나란히 보여준다
  — 신규 repository 메서드 없이 기존 3개 read 메서드를 조합만
  했고, 두 값을 인과관계로 해석하지 않는다(상세: action plan
  "2단계 후속 3").

## 4. 설정 경로 설계 초안

### 4.1 왜 `env`가 아니라 `config_versions`인가 — [추천, §13 결론 재확인]

| 기준 | `env` | `config_versions` + Admin API/CLI |
|---|---|---|
| 감사(audit) | 배포 로그/git에만 남고 "누가 왜"가 구조화 안 됨 | `audit_logs`에 before/after+`reason`+`activated_by` 구조화 저장(§4.4의 선례 그대로) |
| 환경별(`paper`/`live`) 분리 | 배포 파일 단위로 갈라야 함 | `(client_id, environment)` 키로 이미 분리됨(§2.6) |
| 변경 이력/replay | 배포 스냅샷만 남음 | `get_active_at()`으로 임의 시점 활성 정책 재현 가능 |
| self-service 즉시성 | 재배포 필요 | CLI `--apply` 또는 Admin API로 재배포 없이 즉시 발행(`max_single_position_pct` 10→5 실사례로 이미 검증됨) |
| 값 검증 | 로딩 코드에 흩어지기 쉬움 | `validate_*()` 단일 지점(§4.4) |
| 세분화 확장성 | 사실상 불가 | `config_json`이 JSONB라 `source_type_overrides` 같은 중첩 구조로 스키마 변경 없이 확장 가능(§2.6) |

**결론(§13과 동일, 재확인)**: 정식 운영 정책값은 `config_versions` +
Admin API/CLI로 간다. `env`는 §4.3의 shadow 전용 스위치로만 예외를
둔다.

### 4.2 config_json 스키마 초안 — [추천]

```json
{
  "risk": {
    "max_single_position_pct": "5",
    "loss_cut": {
      "enabled": false,
      "mode": "staged",
      "soft_threshold_pct": "7",
      "soft_action": "reduce",
      "soft_reduce_fraction": "0.5",
      "hard_threshold_pct": "12",
      "hard_action": "exit",
      "cooldown_hours_after_hard_exit": "72",
      "price_basis": "position_snapshot.market_price",
      "source_type_overrides": {}
    }
  }
}
```

- 기존 `risk.max_single_position_pct`와 **같은 `risk` 네임스페이스**에
  둔다 — 둘 다 같은 계열의 리스크 정책값이라는 §13의 판단을 스키마에도
  반영한다.
- `enabled: false`가 기본값 — 이번 정책 초안 자체가 "지금 켜자"는
  뜻이 아니다.
- `mode: "staged"`는 향후 다른 모드(예: `"hard_only"`)를 추가할 수
  있는 여지를 남긴다(YAGNI를 어기지 않는 선에서 — 지금 다른 모드를
  구현하지는 않는다).
- `source_type_overrides: {}` — §3.2의 균일 적용 기본값과 정확히
  일치. 빈 dict면 전체 균일 적용, 채우면 예외 적용(예:
  `{"held_position": {"soft_threshold_pct": "5"}}`).
- 모든 숫자를 **문자열**로 저장한다 — 기존 `max_single_position_pct`
  가 `"10"`(문자열)로 저장되는 관례(`scripts/publish_max_single_
  position_pct.py`, `services/config_version_admin.py`)와 JSON에
  `Decimal`을 직접 넣을 수 없다는 제약을 그대로 따른다.

### 4.3 shadow 전용 `env` 허용 범위 — [추천]

- 이름: `LOSS_CUT_SHADOW_ENABLED`(기존 `<FEATURE>_ENABLED=false`
  명명 규칙, §2.7 그대로 적용).
- **엄격한 경계**: 이 env 플래그는 **"관측 로그를 남길지 말지"만
  제어한다.** 실제 거래 결정을 바꾸는 어떤 코드 경로도 이 플래그가
  직접 게이팅해서는 안 된다 — 그 권한은 오직 `config_versions`의
  `risk.loss_cut.enabled`에만 있다. 이 경계가 무너지면(즉, env
  하나로 실거래 정책이 바뀌면) §4.1에서 정리한 audit/replay 이점이
  전부 무의미해진다.
- 수명: 이 플래그는 **shadow 계산기가 상시화된 뒤에도 남아 있을 수
  있다** — "이 관측을 계속 켜둘지"는 운영 편의 문제이지 거래 정책이
  아니기 때문이다. 다만 shadow 단계 자체가 목적을 다하면(정식 전환
  완료 또는 폐기 결정) 이 플래그도 함께 정리 대상이 된다.
- **구현 현황(2026-08-11)**: 실제 구현에서는 이 절이 예시로 든
  `LOSS_CUT_SHADOW_ENABLED` 외에, "shadow 관측용 threshold"도
  사용자가 명시적으로 허용한 범위(작업 지시의 "shadow on/off,
  shadow 관측용 threshold, 최소 로그 제어" 허용 목록)에 포함돼
  `LOSS_CUT_SHADOW_SOFT_THRESHOLD_PCT`/`LOSS_CUT_SHADOW_HARD_
  THRESHOLD_PCT`도 env로 추가했다. 두 threshold 값은 §4.2의
  `risk.loss_cut.soft_threshold_pct`/`hard_threshold_pct`와 이름이
  의도적으로 유사하지만, **이 env 값은 shadow 계산에만 쓰이고
  `config_versions`의 정식 값을 대체하거나 자동으로 채우지
  않는다** — 두 경로가 이름만으로 혼동되지 않도록 `.env.example`
  주석에 "이름에 항상 SHADOW가 들어가는 것 자체가 관측 전용이라는
  표시"임을 명시했다.

### 4.4 Admin API / CLI 입력 계약 — [추천, 기존 패턴 1:1 재사용]

기존 `publish_max_single_position_pct()`(`config_version_admin.py`
L129-249)의 8단계 검증 순서를 그대로 따르는 **대응 함수**
`publish_loss_cut_policy()`를 신설하는 것을 추천한다(범용 "아무
키나 patch하는" 함수 대신, 필드별 전용 함수를 유지하는 기존 설계
원칙 — 필드마다 다른 검증 규칙을 명시적으로 강제하기 위함).

**요청 계약(초안)**:

| 필드 | 타입 | 필수 | 검증 |
|---|---|---|---|
| `client_id` | UUID string | Y | 기존과 동일 |
| `environment` | `"paper"` \| `"live"` | Y | 기존과 동일(`"real"` 명시 거부, PR #216 수정 그대로 재사용) |
| `enabled` | bool | Y | — |
| `mode` | `"staged"` | Y(v1은 단일 값) | 열거값 검증 |
| `soft_threshold_pct` | Decimal | `mode=="staged"`일 때 Y | `0 < soft < hard <= 100` |
| `soft_reduce_fraction` | Decimal | 위와 동일 | `0 < x <= 1` |
| `hard_threshold_pct` | Decimal | Y | `soft < hard <= 100` |
| `cooldown_hours_after_hard_exit` | int | Y | `>= 0` |
| `source_type_overrides` | dict | N(기본 `{}`) | 각 override 값도 동일 규칙 재검증 |
| `reason` | string | **Y(필수로 격상)** | 아래 참고 |

**[추천, 기존 계약과의 명시적 차이]**: 기존 `max_single_position_pct`
endpoint는 `reason`이 선택(`str | None = None`)이지만, loss-cut의
`enabled` 토글은 **거래 동작 자체를 켜고 끄는** 더 큰 blast radius를
가지므로 `reason`을 **필수**로 격상할 것을 추천한다. 이 판단 근거는
"기대값/운영 통제/감사 가능성"이지 정성적 신중함이 아니다 — 손실률
%
 하나를 조정하는 것과, 자동 손절 자체를 켜는 것은 같은 감사 요구
수준이 아니다.

**응답 계약(초안)**: 기존 `UpdateMaxSinglePositionPctResponse`와
동일한 shape(before/after 전체 `loss_cut` 객체, `config_version_id`,
`previous_config_version_id`, `activated_at`, `activated_by`).

**Endpoint**: `POST /config-versions/risk/loss-cut-policy`
(`require_admin` 게이팅, 기존과 동일 — `orders.py`의 `PUT /orders/
{id}/status` 패턴 계승).

**CLI**: `scripts/publish_loss_cut_policy.py` — 기존 `--dry-run`
(기본)/`--apply` 분리 그대로.

**저장/audit 구조**: 기존과 동일 — `repos.config_versions.add()`로
새 row만 추가(기존 row UPDATE 금지), `audit_logs`에 전체 `loss_cut`
객체의 before/after를 JSON으로 남긴다.

## 5. 향후 구현 단계 제안 (B단계 — 이번 문서 범위 아님)

1. **B0. Shadow 계산기 구현**: `scripts/validate_r3b_stop_loss_
   ablation.py` 패턴을 상시 관측 스크립트/서비스로 승격. 실제
   `decision_orchestrator.py` 변경 없음. `LOSS_CUT_SHADOW_ENABLED`
   env로 게이팅.
2. **B1. Shadow 누적 실측**: 최소 N거래일(구체 값 미정 — 기존 SPPV
   계열 실측에서 쓰인 표본 크기 기준을 참고해 별도 턴에서 정한다)
   누적 후 "loss-cut 발동 표본 vs 미발동 표본"의 사후 성과 비교.
3. **B2. 정책 확정**: B1 결과로 §3.1의 구체적 임계치(soft/hard %,
   축소 비율, cooldown 시간)를 확정.
4. **B3. Admin API/CLI 구현**: §4.4 계약대로
   `config_version_admin.py`에 `publish_loss_cut_policy()` 추가,
   대응 route/CLI/테스트(기존 `max_single_position_pct` PR들과
   동일한 검증 절차 — `py-compile`/`accept style`/`accept no-bypass`/
   `accept architecture`/컨테이너 대체 pytest).
5. **B4. `decision_orchestrator.py` 연결**: §3.3의 guard 함수 삽입,
   `_check_held_position_sell_override` 시그니처에 `position_
   snapshot` 전달 추가, `SymbolTradeStateEntity.metadata_json`에
   cooldown 필드 추가(마이그레이션 불필요).
6. **B5. 운영 전환**: `risk.loss_cut.enabled=true`를 Admin API/CLI로
   발행(장중 배포 금지 원칙 준수, 장 종료 후).

## 6. 미확인 가정 / 구현 전 추가 확인 필요 사항

- **soft/hard 임계치 구체 숫자**: 이 문서는 구조(2단계)만 정했고
  숫자(-7%/-12% 등은 예시)는 확정하지 않았다 — B1(shadow 실측) 이후
  결정.
- **§3.3의 우선순위 판단**(loss-cut이 hysteresis gate를 완전
  우회하지 않고 기존 키워드 escape-hatch를 통해서만 통과) — 이건
  안전 측 선택이지만, 사용자가 "loss-cut은 무조건 최우선"을
  원한다면 다른 삽입 지점/로직이 필요하다. **명시적 확인 필요.**
- **held_position에 대한 더 타이트한 override 여부**(§3.2) — 데이터
  없이는 판단 불가, shadow 단계에서 held_position/core를 나눠
  관측해야 답이 나온다.
- **스냅샷 지연이 실제로 loss-cut 오탐/지연을 얼마나 유발하는지**
  (§3.4) — 이번 문서는 코드 구조상 실시간 조회가 없다는 사실만
  확인했고, 실제 지연 분포는 조사하지 않았다.
- **cooldown 구체 시간**(§3.5) — 임계치와 마찬가지로 shadow 실측
  후 결정 대상.
- **`mode` 확장 필요성**(예: 계단식 3단 이상) — 현재는 2단계로 충분
  하다고 가정했으나 검증되지 않았다.
- 이 문서에서 제안한 스키마/API 계약은 **초안**이며, B3 착수 시점의
  실제 코드 상태(예: `config_version_admin.py`가 그 사이 바뀌었을
  가능성)를 다시 확인해야 한다.
