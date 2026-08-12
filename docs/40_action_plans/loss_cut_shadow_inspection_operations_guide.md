# Loss-cut Shadow Inspection API 운영 가이드

> **문서 성격**: 이 문서는 **loss-cut 정책 실행 가이드가 아니다.** 정책을 켜거나
> 끄는 결정, 임계치를 확정하는 결정, "이 정책을 도입해야 한다"는 결론을 이
> 문서가 대신 내려주지 않는다.
>
> 이 문서는 **inspection API 해석 가이드**다 — 이미 구현된
> `GET /trade-decisions/loss-cut-shadow/*` 계열 12개 read-only API를
> 운영자가 어떤 순서로 보고, 어떤 신호를 주의해서 읽고, 무엇을 "이상 후보"로
> 표시하고, 무엇은 성급히 단정하면 안 되는지를 정리한다.
>
> **이 API들은 인과 확정 도구가 아니다.** 모든 endpoint는 이미 저장된 shadow
> 관측값·realized PnL ledger·recompute queue 상태를 읽어 나열하거나 집계할
> 뿐이며, "이 shadow가 유효했다", "이 손실을 막았다", "queue write path가
> 고장났다" 같은 결론을 API 자체가 내리지 않는다. 이 문서도 마찬가지다 —
> 아래 체크리스트와 시나리오는 **다음에 무엇을 더 봐야 하는지**를 안내할
> 뿐, 정책 결론을 대신 내려주지 않는다.
>
> **관련 문서**:
> - 상세 설계: [`13_loss_cut_policy_specification_and_config_path_design.md`](../00_foundational_design/detailed_design/13_loss_cut_policy_specification_and_config_path_design.md)
> - 구현 실행 계획(2단계 shadow 관측 API 구현 이력 전체): [`loss_cut_policy_and_config_path_action_plan.md`](loss_cut_policy_and_config_path_action_plan.md)
> - 선행 조사: [`loss_cut_policy_investigation.md`](../20_system_analysis/loss_cut_policy_investigation.md)

## 1. 이 문서의 목적과 범위

- 목적: 이미 구현된 12개 inspection API를 운영자가 실제로 순서대로 눌러보며
  "지금 무엇을 알 수 있는지 / 무엇은 아직 모르는지"를 판단하게 돕는다.
- 범위: **읽기 전용 해석**만 다룬다. 정책 임계치 확정, `config_versions` 발행,
  실제 loss-cut 청산 로직 연결은 이 문서의 범위 밖이며, 별도 단계(설계
  문서 §5의 B단계, action plan 4단계 이후)에서 다룬다.
- 이 문서가 다루는 API는 전부 `account_id` + 기간 필터를 받는 **계좌×기간
  단위 조회**다 — 계좌를 지정하지 않은 전역 판단은 다루지 않는다.

## 2. API별 역할 요약표

| endpoint | 주 용도 | 언제 먼저 보나 | 무엇을 알 수 있나 | 무엇은 알 수 없나 | 다음으로 볼 API |
|---|---|---|---|---|---|
| `GET .../summary` | 계좌×기간 전체 발동 현황 요약 | 가장 먼저 — 문제가 있다는 신호를 처음 감지할 때 | 총 표본 수, `triggered`/`soft`/`hard` 건수, `source_type`·실제 `decision_type` 분포 | 날짜별 추이, 종목별 쏠림, 이후 실현손익 여부 | `daily`, `by-instrument` |
| `GET .../daily` | 날짜별 발동 추이 | "요즘 발동이 많아졌나?"가 궁금할 때 | KST 날짜별 표본/발동 건수, `trigger_rate` | 종목별 분포, missing 여부 | `by-instrument`, `samples` |
| `GET .../by-instrument` | 종목별 shadow 발동 이력 + realized PnL 누계 교차 조회 | "특정 종목에만 몰리나?"가 궁금할 때 | 종목별 `shadow_triggered_count`, 전체 기간 `realized_pnl_net_sum`, `recompute_required` | 개별 사례 상세, 시점 간 인과관계 | `samples`, `.../timeline` |
| `GET .../samples` | 개별 shadow 표본 목록(필터 가능) | 종목/기간을 좁혀 실제 표본을 눈으로 확인할 때 | `trade_decision_id`, `tier`, `loss_pct`, `average_price`/`market_price` 등 원시 필드 | 이후 실현손익 여부 | `.../timeline` |
| `GET .../samples/{id}/timeline` | 개별 표본 1건 + 그 이후 realized event 상세 | 특정 `trade_decision_id`를 깊게 파고들 때 | 그 표본 이후 시간순 realized event, 시간차 | 이 event가 그 표본 "때문"인지 여부 | (개별 사례 종료 지점) |
| `GET .../first-realized-event-latency` | `triggered=true` 표본의 "첫 event까지 지연" 분포 요약 | "이후 event가 늦게 붙는가, 아직도 안 붙는가?"가 궁금할 때 | 지연 시간 min/max/avg/median, `missing_first_event_rate` | 왜 missing인지 원인 | `missing-first-event-causes` |
| `GET .../missing-first-event-causes` | missing 표본을 원인 bucket으로 분류 + 집계 | "실현손익 이벤트가 안 붙는 케이스가 많나? 왜?"가 궁금할 때 | `still_holding_position`/`recompute_required`/`position_closed_but_no_realized_event` 등 bucket별 count/비율 | 개별 표본이 어느 것인지 | `missing-first-event-samples` |
| `GET .../missing-first-event-samples` | 특정 원인 bucket에 속한 표본 목록 drilldown | 특정 bucket(예: `recompute_required`)이 많다고 나왔을 때 | `cause`별 개별 표본, `position_quantity`, `recompute_required` | 아직 큐 상태와의 교차 여부 | `missing-first-event-recompute-cross-check` |
| `GET .../missing-first-event-recompute-cross-check` | `recompute_required`(ledger 관점)와 `queue_pending`(큐 관점)을 나란히 대사 | "recompute_required와 queue pending이 어긋나나?"가 궁금할 때 | match/missing/extra 3케이스 구분, 종목당 queue pending 다건 여부 | 왜 어긋나는지 원인 | `recompute-missing-queue-causes` |
| `GET .../recompute-missing-queue-causes` | 위 cross-check의 "queue pending 없음" 케이스만 원인 분류 | `queue_pending_missing_count`가 0이 아닐 때 | `queue_scan_limit_suspected`/`recent_pending_gap`/`queue_write_path_suspected` 등 bucket별 집계, 큐 스캔 한계 노출 | 그 bucket 표본이 이후 해소됐는지 | `queue-write-path-suspected-timelines` |
| `GET .../queue-write-path-suspected-timelines` | `queue_write_path_suspected` 표본들의 이후 realized event를 batch로 나열 | 그 bucket 표본을 여러 건 한 번에 확인할 때 | 표본별 이후 event 목록, 해소/미해소 여부, 지연 시간 | 종목별/구간별 요약된 그림 | `queue-write-path-suspected-timeline-summary` |
| `GET .../queue-write-path-suspected-timeline-summary` | 위 raw batch 결과를 종목별/지연구간별로 요약 | 여러 종목에 걸쳐 패턴을 한눈에 보고 싶을 때 | `by_instrument`/`by_latency_bucket`/`by_source_type`/`by_tier` 요약 | 개별 표본 상세(다시 raw로 내려가야 함) | (요약 종료 지점, 필요 시 `samples`/`timeline`로 재drilldown) |

## 3. 권장 조회 순서 — 운영 질문 → API 흐름

아래는 운영 질문별로 **어떤 순서로 어떤 API를 보면 되는지**를 정리한
흐름이다. 순서는 "위에서 아래로" 좁혀가는 방향이다.

### Q1. "요즘 발동이 많아졌나?"
1. `summary` — 기간 전체 `triggered_count`/`trigger_rate` 확인
2. `daily` — 날짜별로 쪼개서 특정 날짜 spike 여부 확인

### Q2. "특정 종목에만 몰리나?"
1. `by-instrument` — 종목별 `shadow_triggered_count` 정렬해서 확인
2. `samples`(해당 `symbol`/`tier` 필터) — 그 종목의 개별 표본 확인

### Q3. "실제 실현손익 이벤트가 안 붙는 케이스가 많나?"
1. `first-realized-event-latency` — `missing_first_event_rate` 확인
2. `missing-first-event-causes` — 왜 missing인지 bucket별 비중 확인
3. `missing-first-event-samples`(`cause` 필터) — 해당 bucket 개별 표본 확인

### Q4. "recompute_required와 queue pending이 어긋나나?"
1. `missing-first-event-recompute-cross-check` — match/missing/extra 3케이스 비율 확인
2. `recompute-missing-queue-causes` — `queue_pending_missing_count`가 왜 그런지 원인 분류 확인

### Q5. "queue_write_path_suspected가 누적되나?"
1. `recompute-missing-queue-causes` — 해당 bucket count 추이 확인(기간을 나눠 여러 번 호출)
2. `queue-write-path-suspected-timeline-summary` — 종목별/지연구간별로 몰림 여부 확인
3. `queue-write-path-suspected-timelines` — raw batch로 개별 표본 재확인

### Q6. "이후 realized event가 늦게 붙는가, 아직도 안 붙는가?"
1. `queue-write-path-suspected-timeline-summary`의 `by_latency_bucket` 확인
2. `timeline_without_events_count`가 0이 아니면 `queue-write-path-suspected-timelines`로 raw 목록 확인
3. 특정 표본이 궁금하면 `samples/{trade_decision_id}/timeline`으로 단건 상세 확인

## 4. 핵심 판단 체크리스트

체크리스트는 "무엇을 보면 된다"가 아니라 **어떤 수치/패턴이 나오면 다음
단계로 넘어갈지**를 기준으로 적었다.

- [ ] `summary`에서 `trigger_rate`가 이전 기간 대비 눈에 띄게 높아졌다
  → `daily`로 넘어가 날짜별 spike 여부 확인 가능.
- [ ] `daily`에서 특정 KST 날짜에 표본이 집중돼 있다
  → 그 날짜만 `by-instrument`/`samples`로 좁혀 재조회 가능.
- [ ] `by-instrument`에서 특정 종목의 `shadow_triggered_count`가 다른
  종목보다 뚜렷하게 크다
  → `samples`(해당 종목)로 개별 사례 확인 가능.
- [ ] `first-realized-event-latency`의 `missing_first_event_rate`가
  일정 수준 이상이다
  → `missing-first-event-causes`로 원인 분류 확인 가능.
- [ ] `missing-first-event-causes`에서 `recompute_required` bucket
  비중이 눈에 띈다
  → `missing-first-event-recompute-cross-check`로 큐 상태 교차 확인
  가능.
- [ ] cross-check에서 `queue_pending_missing_count`가 0이 아니다
  → `recompute-missing-queue-causes`로 넘어가 왜 queue에 없는지
  원인 분류 확인 가능.
- [ ] `recompute-missing-queue-causes`에서 **`queue_scan_limit_
  suspected`가 0이 아니다**
  → **다른 bucket(recency/write-path) 판정보다 이것을 먼저 확인**
  해야 한다. 스캔이 한계(100건)에 도달했다는 뜻이라, 그 아래
  분류(`recent_pending_gap`/`queue_write_path_suspected`) 자체가
  스캔 한계 때문에 왜곡됐을 수 있다.
- [ ] `queue_write_path_suspected` count가 여러 기간에 걸쳐 계속
  0보다 크게 유지된다
  → `queue-write-path-suspected-timeline-summary`로 넘어가 종목별/
  지연구간별 분포 확인 가능.
- [ ] summary의 `by_latency_bucket`에서 `over_1d`/`no_event_found`
  비중이 `under_10m`/`10m_to_1h`보다 크다
  → `queue-write-path-suspected-timelines`(raw)로 넘어가 실제
  표본 단위로 재확인 가능.

## 5. 성급히 단정하면 안 되는 것

아래는 **API가 실제로 보여주는 값**과 **거기서 성급히 끌어낼 수 있는(끌어내면
안 되는) 결론**을 구분한 목록이다.

| 관측값 | 하면 안 되는 결론 | 대신 할 수 있는 것 |
|---|---|---|
| shadow trigger 건수가 많다 | "정식 loss-cut 정책을 지금 도입해야 한다" | 표본이 쌓인 것뿐이다 — 정책 도입은 별도 4단계(정책 확정)의 몫이다 |
| `queue_pending=false` | "recompute queue writer에 버그가 있다(확정)" | `recompute-missing-queue-causes`로 넘어가 `recent_pending_gap`(아직 반영 전일 수 있음)인지 `queue_write_path_suspected`(의심)인지부터 구분해야 한다 |
| realized event가 늦게 붙는다 | "이 shadow가 손절 시점을 정확히 맞췄다" | 지연 시간은 참고 정보일 뿐, 그 event가 이 shadow "때문"이라는 인과 증거가 아니다 |
| `by-instrument`의 `realized_pnl_net_sum`이 음수다 | "이 종목은 손절이 정답이었다" | 이 값은 shadow 조회 기간과 무관한 전체 기간 누계다 — shadow와 시간적으로 나란히 놓인 참고값일 뿐이다 |
| `queue_scan_limit_reached=true` | "그 아래 bucket 분류(recency/write-path)가 정확하다" | 스캔이 한계에 도달했으면 그 판정 신뢰도가 떨어진다 — 다른 bucket으로 넘어가기 전에 스캔 한계 자체를 먼저 확인해야 한다 |
| `queue_write_path_suspected` | "queue write path가 고장났다(확정)" | 이름 그대로 "의심"이다 — `queue_write_path_bug_confirmed` 같은 확정 판단은 이 API의 몫이 아니다 |
| `timeline`에 event가 없다 | "이 종목은 앞으로도 청산되지 않는다" | 조회 시점 기준 관측일 뿐이다 — 나중에 다시 조회하면 달라질 수 있다 |
| missing 비율이 특정 `source_type`에서 높다 | "그 source_type의 신호 체계에 결함이 있다" | 표본 수가 적으면 비율만으로 판단하기 어렵다 — `by_source_type` 표본 수도 함께 확인해야 한다 |

## 6. 운영 시나리오별 읽는 법

### 시나리오 1 — 발동은 많은데 이후 event는 잘 붙는 경우

- 먼저 볼 API: `summary`(발동 건수 확인) → `first-realized-event-latency`(`missing_first_event_rate`가 낮은지 확인)
- 추가로 이어볼 API: `by-instrument`(특정 종목 쏠림 여부만 참고로 확인)
- 지금 내릴 수 있는 판단: shadow 관측 경로 자체가 정상적으로 동작하고 있다고
  **해석 가능**하다 — 관측 인프라 관점의 건강성 신호로 볼 수 있다.
- 아직 내리면 안 되는 판단: "이 정도 발동 빈도면 실제 정책을 도입해도
  안전하다" — 발동 빈도는 정책 도입 근거가 아니다(이 저장소의 "빈도가
  아니라 사후 성과로 판단" 원칙).

### 시나리오 2 — 발동은 적당한데 missing-first-event가 많은 경우

- 먼저 볼 API: `first-realized-event-latency`(`missing_first_event_rate` 확인) → `missing-first-event-causes`(원인 bucket 비중 확인)
- 추가로 이어볼 API: `missing-first-event-samples`(가장 큰 bucket으로 필터해 개별 표본 확인)
- 지금 내릴 수 있는 판단: missing의 대부분이 `still_holding_position`이면
  "아직 정상적으로 보유 중이라 청산이 안 난 것"으로 **해석 가능**하다.
- 아직 내리면 안 되는 판단: `recompute_required`나 `position_closed_but_
  no_realized_event` bucket이 섞여 있다고 해서 바로 "ledger에 결함이
  있다"고 단정하면 안 된다 — cross-check/causes 단계로 더 내려가 확인이
  필요하다.

### 시나리오 3 — `recompute_required`는 많은데 queue pending이 적은 경우

- 먼저 볼 API: `missing-first-event-recompute-cross-check`(`queue_pending_missing_count` 확인)
- 추가로 이어볼 API: `recompute-missing-queue-causes`(왜 큐에 없는지 bucket 확인) → 필요 시 `missing-first-event-samples`(`cause=recompute_required`)로 개별 표본 대조
- 지금 내릴 수 있는 판단: `recent_pending_gap`이 대다수면 "아직 큐에
  반영되기 전 시점일 가능성"으로 **해석 가능**하다.
- 아직 내리면 안 되는 판단: `queue_scan_limit_suspected`를 먼저
  확인하지 않은 상태에서 `queue_write_path_suspected` 비중을 그대로
  신뢰하면 안 된다 — 스캔 한계 때문에 왜곡된 값일 수 있다.

### 시나리오 4 — `queue_write_path_suspected`가 계속 쌓이는 경우

- 먼저 볼 API: `recompute-missing-queue-causes`(기간을 나눠 여러 번 호출해 추이 확인)
- 추가로 이어볼 API: `queue-write-path-suspected-timeline-summary`(종목별/지연구간별 분포 확인) → `queue-write-path-suspected-timelines`(raw로 개별 표본 재확인)
- 지금 내릴 수 있는 판단: 특정 종목/기간에 몰려 있는지, 시간이 지나면서
  `timeline_with_events_count`가 늘고 있는지(해소되고 있는지)는
  **추가 확인 가능**하다.
- 아직 내리면 안 되는 판단: 이 bucket이 누적된다고 해서 바로
  "recompute queue writer 자체가 고장났다"고 단정하면 안 된다 —
  `queue-write-path-suspected-timeline-summary`의 `timeline_without_
  events_count`가 실제로 줄지 않는지까지 확인한 뒤에도, 원인 확정은
  이 inspection API의 범위 밖이다(별도 코드/로그 조사가 필요하다).

### 시나리오 5 — 특정 종목에만 반복적으로 shadow가 몰리는 경우

- 먼저 볼 API: `by-instrument`(`shadow_triggered_count` 상위 종목 확인)
- 추가로 이어볼 API: `daily`(그 종목이 특정 날짜에 몰렸는지 시간축으로 확인) → `samples`(해당 종목 개별 표본 확인)
- 지금 내릴 수 있는 판단: 그 종목의 가격 변동성이나 보유 상태가 shadow
  임계치에 자주 걸리는 상태라고 **해석 가능**하다.
- 아직 내리면 안 되는 판단: 그 종목의 `realized_pnl_net_sum`(전체 기간
  누계)이 음수라고 해서 "손절이 필요했다"고 단정하면 안 된다 — 이
  값은 shadow와 시간적으로 나란히 놓인 참고 정보일 뿐이다(5절 표 참고).

### 시나리오 6 — timeline에서 상당수 표본이 여전히 event 없음으로 남는 경우

- 먼저 볼 API: `queue-write-path-suspected-timeline-summary`(`timeline_without_events_count`/`by_latency_bucket`의 `no_event_found` 확인)
- 추가로 이어볼 API: `queue-write-path-suspected-timelines`(raw로 어떤 표본이 미해소인지 확인) → 필요 시 개별 `trade_decision_id`를 `samples/{id}/timeline`으로 재확인
- 지금 내릴 수 있는 판단: 미해소 표본의 `recompute_required_since`(또는
  `created_at`)가 최근이면 "아직 시간이 더 필요할 수 있다"고 **해석
  가능**하다.
- 아직 내리면 안 되는 판단: 미해소 표본이 오래됐다고 해서 곧바로
  "이 계좌의 recompute 경로 전체가 멈췄다"고 단정하면 안 된다 —
  표본 수가 적으면 개별 사례일 수 있고, 판단 전에 표본 수/기간을
  함께 봐야 한다.

## 7. 운영 액션 레벨

| 레벨 | 의미 | 예시 |
|---|---|---|
| **Observe** | 계속 관찰만 지속. 즉시 조치 불필요 | `summary`/`daily`에서 정상 범위의 발동, `missing_first_event_rate`가 낮음 |
| **Investigate** | drilldown이 필요한 단계. 원인 후보를 좁혀야 함 | `missing-first-event-causes`에서 특정 bucket 비중 상승, `by-instrument`에서 특정 종목 쏠림 |
| **Escalate** | 구조적 점검이 필요한 단계. inspection API만으로는 원인 확정이 안 되고, 코드/로그/DB를 직접 봐야 함 | `queue_scan_limit_suspected`가 반복적으로 관측됨(스캔 깊이 재검토 필요), `queue_write_path_suspected`가 누적되며 `timeline_without_events_count`가 줄지 않음 |
| **Do Not Conclude Yet** | 데이터는 있지만 정책 결론을 내리기에는 이르다 | shadow 발동 빈도만으로 정책 도입 여부를 판단하려 할 때 — 반드시 사후 성과(4단계 정책 확정) 단계로 넘겨야 한다 |

## 8. 현재 구조적 한계

- **queue scan limit(100건) 기반 한계**: `recompute-missing-queue-causes`/
  `missing-first-event-recompute-cross-check`가 쓰는 큐 스캔은
  `list_pending(limit=100)`을 계좌 필터 없이 가져와 애플리케이션에서
  걸러낸다. 실제 미해결 큐가 이 스캔 창보다 깊으면 오래된 pending 항목을
  놓칠 수 있다(`queue_scan_limit_reached`로 노출됨).
- **timeline은 인과 매칭이 아니라 후속 event 나열**: `samples/{id}/timeline`,
  `queue-write-path-suspected-timelines` 모두 "그 시점 이후 가장 먼저
  발생한 event"를 보여줄 뿐, 그 event가 shadow 표본 "때문에" 발생했다는
  보장은 없다.
- **일부 값은 근사치**: `recompute-missing-queue-causes`의 `recent_
  pending_gap` 판정은 `position_cost_basis_state.updated_at`(없으면
  sample `created_at`)을 근사치로 쓴다 — "recompute_required가 정확히
  언제 세팅됐는지"를 기록하는 필드는 따로 없다.
- **realized PnL ledger / recompute queue / shadow 관측은 서로 다른
  축**: `recompute_required`(ledger 관점)와 `queue_pending`(큐 관점)이
  항상 같이 움직이지 않을 수 있다(그 어긋남 자체가 cross-check
  endpoint의 관측 대상이다) — 둘을 같은 뜻으로 뭉개면 안 된다.
- **inspection API는 정책 효과의 최종 증명 수단이 아니다**: 이 API들은
  전부 "이미 있는 값을 읽어 보여주는" read path다. "loss-cut 정책이
  기대값을 개선하는지"는 별도 사후 성과 분석(action plan 3~4단계)의
  몫이며, 이 API 결과만으로 답할 수 없다.
- **raw endpoint와 summary endpoint는 읽기 도구일 뿐, 실행 경로가
  아니다**: 어떤 endpoint도 주문 제출, 청산, recompute queue write,
  `config_versions` 발행을 수행하지 않는다 — 전부 read-only다.

## 9. "다음 단계" 구분

- **지금 이 문서로 가능한 운영 판단**: 위 5~7절의 체크리스트/시나리오/액션
  레벨을 이용해 "지금 무엇이 정상 범위이고, 무엇이 drilldown이 필요한
  상태인지"를 구분할 수 있다.
- **아직 추가 검토가 필요한 것**: `queue_write_path_suspected`/`queue_
  scan_limit_suspected`가 실제로 쌓이는지에 대한 시계열 관측(3단계,
  shadow 누적 실측)은 아직 진행되지 않았다. 이 문서의 시나리오들은
  "이런 패턴이 보이면 이렇게 본다"는 안내이며, 실제 축적된 표본으로
  검증된 기준선은 아니다.
- **정책 설계/실험/실행은 별도 단계**: 이 문서가 다루는 것은 순수하게
  **inspection 결과 해석**이다. 실제 loss-cut 정책 도입 판단(임계치 확정,
  `config_versions` 발행, 실제 청산 경로 연결)은 action plan의 4단계
  (정책 확정) 이후에서 별도로 다룬다 — 이 문서의 어떤 체크리스트/시나리오
  판단도 정책 도입 승인으로 치환하지 않는다.
