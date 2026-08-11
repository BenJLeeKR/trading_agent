# 손실률 기반 Loss-cut 정책 도입 조사 (2026-08-11 KST)

## 0. 이 문서의 성격

이 문서는 **설계 조사 문서**다 — 손실률 기반 손절(Loss-cut) 정책을
운영 코드에 도입할지, 도입한다면 어떤 형태와 설정 경로가 맞는지를
비교·정리한 것이며, **구현을 확정하거나 착수하는 문서가 아니다.**
이번 조사는 read-only(코드/DB 조회만)로 수행했고 코드/DB 변경은
없다.

여기서 말하는 Loss-cut은 시장 분위기 악화·thesis invalidation·edge
collapse 같은 **신호 기반 청산**이 아니라, **매수가(평균단가) 대비
손실률이 고정 임계치(예: -10%)를 넘으면 정량적으로 청산하는 규칙**을
가리킨다. 관련: `08_ai_decision_policy.md` §4.1 Order Construction
Agent의 "exit rules", `06_config_schema.md`(config 스키마 및
`risk.max_single_position_pct` 관리 경로 선례).

## 1. 현재 운영 코드 기준 사실 확인 (소스 근거)

### 1.1 cost basis / average price — 관측용이지 청산 트리거 입력이 아니다

`src/agent_trading/domain/entities.py`:
- `PositionSnapshotEntity.average_price`(189행), `.unrealized_pnl`(191행) —
  브로커 스냅샷 필드.
- `PositionCostBasisStateEntity.average_cost`(472행) — 체결 기반
  이동평균 원가(실현손익 원장 전용, `12_realized_pnl_moving_average_ledger.md`).

실제 사용처를 전부 추적한 결과:

| 파일:라인 | 용도 | 청산 결정에 쓰이는가 |
|---|---|---|
| `services/ai_agents/ai_risk.py:462` | AI Risk 프롬프트에 텍스트로 출력 | 아니오 — 표시용 |
| `services/ai_agents/ai_risk.py:508-517` | `position_value = qty*avg_price` → 집중도 %(NAV 대비) 계산, `>15%`면 risk_opinion에 참고 신호 | **집중도(익스포저) 판단**이지 손실률 판단이 아님 — PnL 연산 자체가 없음 |
| `services/execution_service.py:1849-1850, 1884` | MARKET BUY 참조가 폴백, `SizingInputs.current_position_avg_price` | BUY 사이징/포지션 집중 한도(`_apply_concentration_constraint`) 입력이지 SELL 트리거 아님 |
| `services/portfolio_allocation.py:333-335` | 배분 비중 계산 | 배분/집중도용, 손실률 아님 |
| `services/performance_summary.py:106-118` | `market_price - average_price` 합산 | **성과 리포팅 전용**(Admin UI/API), 실행 경로 아님 |
| `realized_pnl_engine.py`/`ledger_service.py`/`recompute_service.py` | 매도 체결 **이후** 사후 회계 | 매도가 이미 일어난 뒤의 기록, 청산 의사결정 아님 |

`unrealized_pnl`도 동일 — `ai_risk.py:465-466`에 프롬프트 텍스트로만
쓰이고, `decision_orchestrator.py`/`decision_factory.py`/
`sizing_engine.py`/`deterministic_trigger_engine.py` 어디에도 이 값을
읽어 청산 여부를 계산하는 코드가 없다.

### 1.2 고정 손실률 트리거 — 운영 코드에 존재하지 않는다

`stop_loss`/`loss_cut`/`loss_pct`/`per_position_loss_limit_pct` 전수
검색 결과, 운영 코드에 걸리는 것은 단 하나뿐이다:

- `services/reverse_trade_hysteresis.py:445` — `"stop_loss"`가
  **문자열 키워드**로 AI가 생성한 `risk_flags`/`reason_codes` 텍스트에
  포함되는지만 매칭(`_contains_keyword`, 440-455행). **숫자 손실률
  연산이 전혀 없다** — AI가 스스로 "stop_loss" 계열 단어를 언급했는지
  보는 정성적 게이트다.

나머지 관련 후보는 모두 운영 코드가 아니다:
- **`scripts/validate_r3b_stop_loss_ablation.py`**: 임포트하는 코드가
  전무(전체 검색 0건)함을 재확인. 스크립트 자체 docstring이 "손절
  로직 자체는 이 스크립트 안에서만 시뮬레이션되는 shadow 계산이며,
  운영 코드(`deterministic_trigger_engine.py`)에는 어떤 손절 임계값도
  추가하지 않는다"고 명시한다. DB 쓰기/브로커 제출 없음.
- **`risk.per_position_loss_limit_pct`**: `06_config_schema.md` 38행
  (예시값)·259행(Pydantic 필드 선언)에만 존재. `src/agent_trading/`
  전체에서 이 키를 실제로 읽는 코드는 **0건** — 문서에만 있고 소비자가
  없는 죽은 config 키다.

### 1.3 held_position REDUCE/EXIT의 실제 기준 — 전부 신호 기반

- `decision_orchestrator.py:355-411` `_check_held_position_sell_override`:
  AI Risk의 `risk_opinion`(`reject`/`reduce`) 또는 `risk_score>=0.8`
  기준. REDUCE→EXIT 격상도 `risk_flags`의 `concent`/`expos`/`over`
  키워드 매칭(409-411행)이지 손실률이 아니다.
- `decision_orchestrator.py:746-796`
  `_check_held_position_exit_hysteresis_gate` → `reverse_trade_
  hysteresis.py`의 `evaluate_symbol_state_sell_hysteresis` — `edge_
  after_cost_bps`, thesis-invalidation 키워드, downside-shock,
  holding_profile breach(위 1.2의 키워드 매칭) 기준. 손실률 연산 없음.
- `services/held_position_policy.py:6-27` — 라우팅 판별만(가격 연산
  없음).
- `services/holding_profile_policy.py:49-56` — 보유기간/쿨다운 정책만.

**결론: 손실률 기반 Loss-cut은 현재 운영 코드에 존재하지 않는
별도의 정책 축이다.** `average_price`/`unrealized_pnl`은 표시·집중도·
사이징·사후 회계에만 쓰이고, 어떤 청산 트리거도 `(시장가-평균단가)/
평균단가` 형태의 연산을 거치지 않는다.

### 1.4 새 규칙을 넣는다면 만나는 지점

기존 신호 기반 청산과 가장 자연스럽게 만나는 지점은
**`decision_orchestrator.py:355` `_check_held_position_sell_override`**
다 — 이미 `held_position` 심볼의 `position_snapshot`(따라서
`average_price`)에 접근 가능하고, 이 함수의 판정 결과가 최종
decision_type을 정해 `execution_service.py:_build_sizing_inputs`
(약 1884행)로 이어지는 지점이기 때문이다. 손실률 게이트를 여기에
추가하면 기존 `risk_override` 불리언 로직(384-393행) 옆에 최소
plumbing으로 얹을 수 있다. 대안은
`_check_held_position_exit_hysteresis_gate`(746행) — 손실률을
"unblock 조건"으로 둘지 "강제 override 조건"으로 둘지에 따라 갈린다.

## 2. 정책 설계안 비교 (최소 3안)

| 기준 | 안 A. 단순 하드 손절 | 안 B. 단계형 손절 | 안 C. 관측용 shadow 손절 |
|---|---|---|---|
| **내용** | 손실률 &gt; 임계치(예: -10%) → 즉시 `EXIT` | 예: -7% → `REDUCE`, -12% → `EXIT` | 실제 주문 개입 없음, "손절이었으면 발동했을 케이스"만 기록 |
| **목적 적합성** | 손실 하한선 보장에는 직접적이나, "기대값 극대화"가 아니라 "절대 손실 회피" 철학에 가까움 | A보다 완만하지만 여전히 절대 손실 회피 축 | 목적과 완전히 정합 — 실측 없이 정책을 확정하지 않는다는 이 프로젝트의 반복 원칙(`[PRIORITY_MAP]` 공통 판단 원칙)과 정확히 일치 |
| **기대효과** | tail loss 즉시 차단 | tail loss 차단 + 조기 반응 완충 | 효과 자체는 0(관측만) — 대신 "도입 시 효과"를 사후 성과로 검증 가능하게 함 |
| **위험** | AI가 "지금은 조정일 뿐, thesis 유효"라고 판단한 포지션도 기계적으로 강제 청산 — 회복 국면 포지션을 저점에 파는 역선택 위험 | A보다 완충되나 동일 역선택 위험이 두 단계로 분산 | 없음(주문 미개입) |
| **기존 held_position exit 로직과 충돌 가능성** | **높음** — 이미 AI risk_score/opinion, hysteresis, holding_profile이 REDUCE/EXIT를 판정하는데, 손실률 하드 게이트가 이들과 **동시에 발동하거나 반대로 판단**할 때 우선순위가 미정의 상태(§4 참고) | 동일하게 높음, 다만 REDUCE 단계는 기존 "완화된 축소" 개념과 겹칠 여지가 더 큼 | 없음 — 관측만 하므로 기존 로직에 개입하지 않음 |
| **기대수익률 철학과의 정합성** | **낮음** — "손실 0이 목적이 아니라 허용 손실 제약 아래 기대값 극대화"(이 저장소의 확정 목표, `[PRIORITY_MAP]` 07-14 재정렬)와 정면으로 배치될 수 있음. 손실 중인 포지션이 이후 반등해 기대값을 개선하는 경우를 원천 차단 | 중간 — A보다는 낫지만 여전히 "손실 크기"만으로 판단, edge/기대값을 재평가하지 않음 | **가장 높음** — 실제로 기대값을 개선하는지 먼저 확인 후 정책화하는 접근 |
| **구현 난이도** | 낮음 — 조건 하나 추가 | 중간 — 두 임계치 + 우선순위 로직 | 낮음 — 기존 `validate_r3b_stop_loss_ablation.py` 패턴을 상시 shadow 계산기로 승격(`shadow_regime_conditional_entry_signal.py`류 선례 있음) |
| **검증 가능성** | 낮음 — 도입 즉시 실제 주문에 영향을 주므로 되돌리기 전에 이미 비용 발생 | 낮음(동일) | **높음** — 실제 개입 없이 누적 로그로 사후 성과 비교 가능 |
| **지금 바로 구현 추천 여부** | **비추천** | **비추천** | **추천(다만 이번 턴 범위 아님 — 별도 착수 턴 필요)** |

## 3. 설정 경로 비교 — `env` vs `config_versions`(Admin API/CLI)

이미 이 저장소에는 정확히 같은 계열의 선례가 있다:
**`risk.max_single_position_pct`가 `.env`가 아니라 `config_versions` +
Admin API/CLI(`POST /config-versions/risk/max-single-position-pct`,
`scripts/publish_max_single_position_pct.py`)로 관리된다**
(`06_config_schema.md` §9, `services/config_version_admin.py`). Loss-cut
임계치는 성격상 이것과 **완전히 같은 계열의 운영 정책값**이다 — 둘 다
(1) 계좌/전략의 리스크 허용도를 나타내는 숫자, (2) `risk.*` config
네임스페이스에 속함, (3) 잘못 바꾸면 즉시 실주문에 영향, (4)
`paper`/`live`처럼 환경별로 다를 수 있음. 아래 비교도 이 판단을 그대로
뒷받침한다.

| 기준 | A. `.env` / env variable | B. `config_versions` + Admin API/CLI | C. 절충(shadow는 env, 정식 정책은 config version) |
|---|---|---|---|
| **운영 정책값으로서의 성격** | env는 원래 "배포 환경 차이"(DB 접속정보, feature flag)를 위한 것 — **거래 정책 숫자**를 담기엔 의미가 맞지 않음 | `config_versions`는 애초에 "client×environment별 거래 정책 버전"을 위해 설계된 테이블 — 정확히 맞는 그릇 | shadow 실험 단계에서는 env도 허용 가능(단, 그마저도 로컬 실험용 스크립트 인자로 충분해 env가 꼭 필요하지도 않음) |
| **audit trail 필요성** | `.env`는 변경 이력이 git/배포 로그에만 남고, "누가 왜 이 값으로 바꿨는지"가 거래 정책 감사 목적에 맞게 구조화되지 않음 | `audit_logs`에 before/after+`reason`+`activated_by`가 구조화되어 남음(§9에서 이미 검증된 경로) | shadow 관측 단계는 audit 요구가 약함(실주문에 영향 없으므로) — 정식 도입 시점에 B로 전환 |
| **환경별(`paper`/`live`) 관리 적합성** | `.env`는 배포 단위로 파일이 갈리므로 관리는 되지만, "같은 배포에서 paper/live만 다른 손절률"을 표현하려면 별도 접두사 규약을 새로 만들어야 함 | `config_versions`가 `(client_id, environment)`를 기본 키로 이미 갖고 있어 자연스럽게 분리됨 | 동일하게 B가 유리 |
| **변경 이력 보존(replay)** | env는 배포 시점 스냅샷만 남고, "그 시점에 어떤 손절률이 활성이었는지"를 재현하려면 배포 이력을 별도로 추적해야 함 | `get_active_at()`으로 임의 시점의 활성 정책을 그대로 재현 가능(§9에서 이미 설계된 replay 의미론) | B가 유리 |
| **운영자 self-service 가능성** | `.env` 변경은 배포/재기동을 동반해야 반영됨(즉시성 없음, 원복도 재배포 필요) | CLI(`--dry-run`/`--apply`) 또는 Admin API로 **재배포 없이 즉시 발행** 가능(`max_single_position_pct` 10→5 사례로 이미 실증) | shadow 단계는 재배포 필요해도 무방(실험이므로) |
| **잘못된 값 입력 방지** | env는 타입/범위 검증이 로딩 시점 코드에 흩어지기 쉬움 | `validate_max_single_position_pct`류 함수로 단일 지점 검증(0 초과/100 이하 같은 규칙을 재사용 가능) — 이미 확립된 패턴 | 동일 |
| **향후 종목별/계좌별/source_type별 세분화 확장성** | env로는 사실상 불가능(키 폭발) | `config_json`이 이미 JSONB라 `risk.loss_cut.by_source_type.held_position` 같은 중첩 구조로 자연 확장 가능(스키마 변경 없이) | 세분화가 필요해지는 시점에 자연히 B로 수렴 |

**결론: `env`가 아니라 `config_versions` + Admin API/CLI가 맞다.**
이유는 위 표 전체지만, 가장 결정적인 두 가지는 (1) 이미 같은
`risk.*` 네임스페이스의 `max_single_position_pct`가 이 경로로
성공적으로 운영되고 있어 **새 관리 경로를 발명할 필요가 없고**,
(2) Loss-cut처럼 "잘못 바꾸면 즉시 실주문에 영향을 주는 값"은
audit trail과 즉시 원복 가능성(새 버전 재발행)이 `.env` 재배포보다
압도적으로 안전하기 때문이다. C(shadow=env)는 채택할 이유가 약하다 —
아래 §4처럼 shadow 계산 자체가 실행 스크립트의 CLI 인자만으로
충분하고, env를 거칠 이유가 없다.

## 4. 설계 시 세부 질문 — 판단 요지 (구현 아님, 다음 착수 시 확정 필요)

- **손실률 계산 기준 가격**: `position_snapshot.average_price`가
  1차 후보다(현재 held_position 판정이 이미 이 필드를 참조 가능한
  구조). `position_cost_basis_state.average_cost`(이동평균 원가)는
  실현손익 원장 전용으로 설계된 값이라 혼용 시 두 계산 체계가
  갈릴 위험 — **단일 소스로 고정해야 한다**(둘 다 쓰면 "손실률이
  기준에 따라 달라지는" 혼란 발생).
- **트리거 기준 가격**: 장중이면 실시간 quote/market_price, 종가
  기준이면 스냅샷 지연을 감안해야 함 — 이 저장소는 이미
  `data_quality.max_quote_delay_seconds`류 신선도 게이트가 있어(
  `06_config_schema.md` §3.5) 그 프레임을 재사용하는 것이 안전.
- **평가 주기**: held_position 사이클마다 평가하는 것이 기존
  `_check_held_position_sell_override` 호출 빈도와 자연스럽게
  맞음(신규 스케줄러 불필요).
- **재진입 cooldown**: 손절 후 즉시 재진입하면 "손절 → 반등 → 재진입"
  왕복 손실(whipsaw) 위험 — `holding_profile_policy.py`가 이미
  `minimum_hold_until`/`reentry_cooldown_until` 필드를 갖고 있어
  같은 메커니즘 재사용이 자연스러움.
- **REDUCE/EXIT 동시 허용 시 우선순위**: 안 B(단계형)를 검토한다면
  손실률 임계치와 기존 AI risk_opinion이 상충할 때(예: 손실률은
  REDUCE만 요구하는데 AI는 EXIT를 요구) 어느 쪽이 이기는지 명시
  규칙이 필요 — 이번 조사에서는 규칙을 정하지 않았다(다음 설계
  단계 질문으로 남김).
- **기존 holding_profile/hysteresis/EV anchor와 충돌 시 우선순위**:
  마찬가지로 미정 — 이 저장소의 반복 원칙("차단 장치는 기대값을
  실제로 개선했는가로 판단, 빈도만으로 판단 금지")에 따르면, 손실률
  게이트가 다른 게이트보다 우선하려면 그 우선순위 자체도 사후 성과로
  뒷받침돼야 한다.
- **기대수익률 철학과의 정합 조건**: "절대 손실 회피"가 아니라
  "기대값 개선" 관점을 지키려면, 손실률 게이트는 최소한 (a) 도입 전
  shadow 관측으로 실제 개입했을 경우의 사후 성과를 먼저 확인하고,
  (b) 그 성과가 "손절 없이 들고 있었을 경우"보다 나은 경우에만
  정식 전환하는 guardrail이 필요하다. 이것이 안 C를 1차 추천으로
  삼은 핵심 근거다.

## 5. 요약 판정

- **현재 운영 코드에는 손실률 기반 Loss-cut이 없다** — §1에서 소스
  기준으로 재확인.
- **3안 중 지금 즉시 구현할 안은 없다.** 안 A/B는 이 프로젝트가
  이미 확정한 "기대값 극대화" 목표와 충돌 위험이 있고 되돌리기 전에
  이미 비용이 발생하는 구조다. **안 C(관측용 shadow)가 유일하게
  지금 착수해도 안전하지만, 이번 턴 범위(설계 조사)에는 포함하지
  않는다** — 별도 착수 턴에서 `scripts/validate_r3b_stop_loss_
  ablation.py` 패턴을 상시 shadow 계산기로 승격하는 방식을 검토한다.
- **설정 경로는 `env`가 아니라 `config_versions` + Admin API/CLI가
  맞다** — `risk.max_single_position_pct` 선례와 동일한 논리가 그대로
  적용된다.
- 이 결정들은 **정책 결정 대기** 상태로 backlog에 등록한다
  (`[BACKLOG] backlog.md` 참고). 다음 주력 작업은 `SPPV-3` 미해결
  항목으로 넘어간다(`[PRIORITY_MAP] remaining_work_priority_map.md`
  참고).
