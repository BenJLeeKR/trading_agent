# Universe 활동성 사전 필터 보정 — 실측 분석 실행 계획

## 목적

이 문서는 유니버스 선정 단계에서 활동성이 부족한 종목을 더 앞단에서 걸러내고, 그 자리를 더 나은 거래 후보로 대체할 수 있도록 사전 필터 보정 기준을 다일자 실측으로 판단하기 위한 실행 계획이다.

핵심 질문은 다음 하나다.

- 현재 `pre-AI` 단계의 `활동성 부족` 차단이 유효하다는 전제 아래, 어떤 활동성 기준을 유니버스 단계로 당겨와야 **후보 손실을 최소화하면서** 불필요한 BUY 평가 대상을 줄일 수 있는가

즉, 이 계획의 목적은 단순히 `활동성 부족` 차단 건수를 낮추는 것이 아니라, BUY 단계에서 반복적으로 탈락할 종목을 유니버스 앞단에서 미리 제외함으로써 유니버스의 한정된 슬롯을 더 우수한 종목에 배분할 수 있게 만드는 데 있다.

이 문서는 구현 지시가 아니라 측정 계획, 지표 정의, read-only 분석 스크립트 설계안을 고정한다.

## 배경

- 현재 유니버스 선정의 유동성/거래 가능성 필터와 BUY 직전 `활동성 부족` 필터는 정책 계층이 다르다.
- 그러나 최근 약 1개월 실측에서 유니버스 내부 종목 중 `활동성 부족` 차단 비율이 높게 반복 관측되었다.
- 사용자는 `활동성 부족` 필터 자체의 기능적 적정성을 실측으로 확인했고, 따라서 다음 과제는 BUY 단계 필터 완화가 아니라 **유니버스 단계 사전 차단 강화** 여부를 판단하는 것이다.

## 범위

- 포함:
  - 최근 `20~30` 거래일 다일자 실측
  - 유니버스 구성 결과와 `pre-AI` 차단 결과의 연결 분석
  - `source_type`별 분포와 시간대별 분포 분석
  - read-only 시뮬레이션 기반 후보 사전 필터 비교
- 제외:
  - 운영 DB 쓰기
  - 외부 API/KIS 호출
  - 유니버스 정책 변경 구현
  - BUY 필터 threshold 변경

## 상태 표기

- `[ ]`: 미착수
- `[~]`: 진행 중
- `[x]`: 완료
- `[!]`: 보류 또는 사용자 판단 필요

## 작업 체크리스트

### P0 — baseline 실측 데이터셋 확보

목표: 날짜/실행 시점/유니버스/차단 사유를 한 테이블로 복원할 수 있는 read-only 분석 입력을 만든다.

- [x] 최근 `20~30` 거래일의 대상 실행 집합을 확정한다. **[2026-08-06 실측]** `2026-06-19~2026-08-06`(34거래일), `Entrypoint Paper` 계정, run 2105건.
- [x] 실행 시점을 `pre_open`, `open_30m`, `intraday`, `after_close` 버킷으로 분류한다.
- [x] 실행 단위별 유니버스 종목과 `source_type`을 복원한다.
- [x] 실행 단위별 `pre-AI` 차단 사유를 복원한다.
- [x] 실행 단위별 signal feature 지표를 조인한다.
- [x] market overlay 활성/비활성 여부를 분리 기록한다.

완료 기준:

- 분석 대상 실행 수와 날짜 범위가 확정되어 보고된다.
- 각 실행 단위에 대해 `symbol`, `source_type`, `activity_block_reason`, signal feature 주요 지표가 연결된다.

### P1 — baseline 지표 계산

목표: 현행 로직에서 `활동성 부족` 차단이 얼마나 자주, 어떤 이유로, 어떤 source에서 발생하는지 정량화한다.

- [x] 실행 단위별 `universe_count`를 계산한다.
- [x] 실행 단위별 `new_buy_candidate_count`를 계산한다.
- [x] 실행 단위별 `pre_ai_activity_block_count`와 비율을 계산한다.
- [x] `eligibility_low_average_volume`, `eligibility_low_turnover`, `eligibility_low_relative_activity` 사유별 건수를 계산한다.
- [x] `source_type`별 차단 비율을 계산한다.
- [x] 시간대별 차단 비율을 계산한다.

완료 기준:

- baseline `활동성 부족` 차단 비율이 날짜별/시간대별/source_type별로 보고된다.
- 차단 사유 3종의 분포가 함께 보고된다.

### P2 — universe 사전 필터 가설 비교

목표: 어떤 사전 필터를 universe 단계로 당길 때 차단 감소 대비 후보 손실이 가장 작은지 비교한다.

- [x] 가설 A: `average_volume_20d >= 3000` 하한을 시뮬레이션한다.
- [x] 가설 B: `average_turnover_20d >= 50_000_000` 하한을 시뮬레이션한다.
- [x] 가설 C: A+B 동시 적용을 시뮬레이션한다.
- [x] 가설 D: C를 `source_type=core`에만 적용하는 예외 정책을 시뮬레이션한다.
- [x] 가설 E: `relative_activity >= 1.10`를 shadow-only로 측정한다.
- [x] 각 가설의 차단 감소량과 후보 손실률을 비교한다.

완료 기준:

- 최소 `5`개 비교군의 결과가 같은 기준표로 비교된다.
- 차단 감소량, 후보 손실률, 효율 점수가 모두 보고된다.

### P3 — 권고안 도출

목표: 바로 구현할 후보와 shadow-only 유지 후보를 구분한다.

- [x] `core` 중심 예외 정책이 필요한지 판단한다. **[2026-08-06 실측 결론]** 불필요 — 가설 D(core 한정)도 가설 C(전체)와 동일한 효율(0.3155)로, core 한정이 결과를 개선하지 못한다.
- [x] `held_position`, `reconciliation_overlay`, `event_overlay`, `manual` 예외 유지 여부를 정리한다. **[결론]** 그대로 유지. 이번 실측은 `EXEMPT_SOURCE_TYPES`(`held_position`/`reconciliation_overlay`) 예외를 깨지 않았고, 그럴 근거도 발견되지 않았다.
- [x] `relative_activity`를 universe에 바로 반영하지 않을 근거를 정리한다. **[결론]** shadow-only 유지가 옳다 — 아래 실측 결과 참고(fail_rate 77.3%가 실제 차단율 18.7%와 크게 어긋남, 시점 민감성 확인).
- [x] 1순위 권고안과 보류안을 구분한다. **[결론]** 1순위 권고안 없음 — 전 가설이 보류 또는 기각(아래 실측 결과 참고).

완료 기준:

- `권장안`, `보류안`, `기각안`이 각각 최소 1개 이상 정리된다.
- 왜 그 판단을 했는지 차단 감소량/손실률 근거가 붙는다.

## 실측 결과(2026-08-06 KST, 34거래일)

### 실행 개요

- 컨테이너: `agent_trading-app-1`
- 명령: `python3 scripts/analysis/analyze_universe_activity_gap.py --date-from 2026-06-19 --date-to 2026-08-06 --account-alias 'Entrypoint Paper' --output-json /tmp/uag_full/summary.json --output-csv-dir /tmp/uag_full/csv`
- 날짜 범위: `2026-06-19`~`2026-08-06`(34거래일), 계정 `Entrypoint Paper`
- 파생 실행 단위(run) `2105`건, decision 행 `42245`건 — 무겁거나 비정상적인 징후 없이 정상 완료됐다.

### baseline

- `universe_count=42245`, `new_buy_candidate_count=40984`, `pre_ai_activity_block_count=7653`(**18.67%**)
- 사유 분포: `eligibility_low_relative_activity` `7599`건(차단의 **99.3%**), `eligibility_low_average_volume` `54`건(0.7%), `eligibility_low_turnover` `0`건(34거래일 전체에서 단 한 번도 발생하지 않음)
- `source_type`별 차단율: `market_overlay` **42.27%**(최고) > `core` 20.15% > `event_overlay` 15.95% > `reconciliation_overlay` 0%(예외 유지, 예상대로)
- 시간대별 차단율: `pre_open` 19.04%, `open_30m` 20.35%, `intraday` 18.54%, `after_close` 17.65% — 시간대 간 큰 편차 없음
- `market_overlay_enabled` 추정 run `550`건 vs 비활성 `1555`건 — 활성 run의 차단율(14.59%)이 비활성 run(20.65%)보다 낮음(활성 시점이 오히려 활동성이 더 커서 차단이 덜 걸리는 방향)
- **일별 편차가 매우 크다**: `daily_summary.csv` 기준 차단율이 `0%`(2026-07-30)~`88.24%`(2026-08-04) 사이로 요동친다. `2026-07-30`을 표본 조회해 원인을 확인했다 — 그날은 `eligibility_low_*` 활동성 사유가 아니라 `eligibility_risk_off_block`/`eligibility_negative_overall_floor` 같은 레짐(risk_off) 관련 사유가 차단을 지배했고, 활동성 사유는 그날 단 한 건도 마지막 차단 사유로 기록되지 않았다. 즉 **활동성 게이트가 꺼진 것이 아니라, 그날은 다른 게이트가 먼저/더 많이 차단한 것**이며 스크립트의 `is_pre_ai_activity_blocked`(마지막 사유가 활동성 3종인지 판정)는 이를 올바르게 반영하고 있다. 이 편차는 활동성 사전 필터 논의와는 별개로, baseline 차단율이 레짐 조건에 크게 좌우된다는 사실을 보여준다.

### 가설 A/B/C/D/E 비교

| 가설 | 적용 모수 | universe 제외 | 차단 감소 | 후보 손실 | 손실률 | 효율 점수 | 결측 feature |
|---|---|---|---|---|---|---|---|
| A(평균거래량<3000 제외) | 37878 | 221 | 53 | 168 | 0.44% | **0.3155** | 862(2.28%) |
| B(평균거래대금<50M 제외) | 37878 | 0 | 0 | 0 | 0% | (해당없음) | 862(2.28%) |
| C(A or B) | 37878 | 221 | 53 | 168 | 0.44% | **0.3155** | 862(2.28%) |
| D(C, core 한정) | 26015 | 221 | 53 | 168 | 0.65% | **0.3155** | 284(1.09%) |
| E(relative_activity<1.10, shadow) | 37972(측정 37099) | — | — | — | — | fail_rate **77.26%** | — |

### 권장안 / 보류안 / 기각안

- **권장안: 없음.** 어떤 가설도 `efficiency_score >= 3.0`(스크립트가 임시로 쓰는 권장 임계값 — 차단 감소가 후보 손실의 3배 이상) 기준을 충족하지 못했다.
- **보류안**: A, C, D — 효율 점수 `0.3155`는 권장 임계값의 약 `1/10`에 불과하다. 즉 이 절대 임계값(`average_volume_20d>=3000`)으로 유니버스를 앞단에서 걸러내면, 실제로 차단되던 종목 `53`건을 줄이는 대신 **차단되지 않았을(=멀쩡했을 수 있는) 후보 `168`건을 함께 잃는다** — 손실이 이득의 약 `3.2`배다. `core` 한정(D)도 개선되지 않는다.
- **기각안**: B — `average_turnover_20d>=50,000,000` 임계값은 34거래일 전체에서 단 한 건도 걸러내지 못했다(제외 `0`건). 이 임계값은 현재 데이터 분포에서 사실상 항상 통과되는 비유효 조건이다.
- **관찰(정책 미반영, shadow 유지)**: E의 `relative_activity` fail_rate(`77.26%`)가 실제 `pre_ai_activity_block_rate`(`18.67%`)보다 4배 이상 높다. 두 수치가 정확히 대응해야 한다는 가정을 세웠다면 이 가정은 **깨졌다** — production의 `eligibility_low_relative_activity` 판정은 `relative_activity>=1.10`만으로 결정되지 않고(다른 상위 게이트가 먼저 통과/차단을 가르거나, reasons 리스트의 다른 앞선 항목이 먼저 최종 사유를 결정하는 구조 등), 단순 shadow 지표 하나로 그대로 대체할 수 없다. 이는 계획 문서가 원래 `relative_activity`를 "시점 민감성이 높아 바로 정책에 반영하지 않는다"고 잡아둔 판단이 옳았음을 실측으로 재확인한 결과다 — shadow-only를 그대로 유지한다.

### 구조적 한계와 미확인 가정

- baseline 차단율의 일별 편차(0%~88%)는 활동성 사전 필터와 무관한 레짐(risk_off 등) 게이트의 영향을 크게 받는다 — 이 34일 평균 하나로 "전형적인" 날을 대표한다고 보기는 어렵다.
- `market_overlay_enabled`는 여전히 결과 기반 추정치(저장된 플래그 아님) — §상단 구조 확인 결과 참고.
- 이번 실측은 `Entrypoint Paper` 계정 1개 기준이다. 다른 계정이 있다면 별도 실측이 필요하다.

### 결론

**Path A(분석 유지) — 이번 턴에서는 유니버스 선정 로직에 정책 구현을 넣지 않는다.** 34거래일 실측 결과, 절대 임계값 기반 사전 필터(A/B/C/D) 전부가 권장 효율 기준에 크게 못 미쳤고, 실제 차단을 지배하는 `relative_activity` 신호는 여전히 shadow 지표와 실제 차단 판정이 크게 어긋나 하드 필터로 쓸 근거가 없다. 억지로 구현하기보다, 이 결과를 근거로 "현재 절대 임계값 사전 필터는 유니버스 슬롯 재배분에 유효하지 않다"는 부정적 결론을 문서화하는 것이 이번 실측의 정당한 결과다.

## `market_overlay × eligibility_low_relative_activity` 원인 분해(2026-08-06 KST)

위 34거래일 실측에서 `market_overlay`의 `pre-AI 활동성 부족` 차단율(42.27%)이 `core`(20.15%)/`event_overlay`(15.95%)보다 눈에 띄게 높게 관측됐다. 유니버스 hard filter를 구현하기 전에 **왜** 그런지 구조적으로 분해했다. 새 read-only 스크립트 `scripts/analysis/analyze_market_overlay_relative_activity_gap.py`를 추가해 분석했다(정책 구현 없음).

### 실행 개요

- 컨테이너: `agent_trading-app-1`
- 명령: `python3 scripts/analysis/analyze_market_overlay_relative_activity_gap.py --date-from 2026-06-19 --date-to 2026-08-06 --account-alias 'Entrypoint Paper' --split-date 2026-06-26 --output-json /tmp/uag_overlay/result.json`
- 날짜 범위: `2026-06-19`~`2026-08-06`(34거래일), 계정 `Entrypoint Paper`
- `core`/`event_overlay`/`market_overlay` BUY 경로 decision 행 `38074`건 수집(run 클러스터링 없이 행 단위, 반복 빈도 자체가 분석 대상이라 의도적으로 유지)

### 핵심 발견 — 시간적으로 완전히 집중된 현상이다

`market_overlay`의 `eligibility_low_relative_activity` 차단 `807`건은 **고유 종목 `13`개**, **거래일 `6`일**(`2026-06-19`~`2026-06-26`)에만 존재한다. `--split-date 2026-06-26` 기준으로 나눠보면:

- `2026-06-19`~`2026-06-26`(분할 포함): `1423`건 중 `807`건 차단(**block_rate 56.71%**)
- `2026-06-29`~`2026-08-06`(분할 이후, 28거래일): `492`건 중 **차단 0건(block_rate 0.0%)**

즉 원래 34일 평균(42.27%)이 시사하는 "`market_overlay`는 구조적으로 활동성 기준과 상시 충돌한다"는 가정은 **깨졌다**. 실제로는 최초 6거래일에 국한된, 이후 28거래일 동안 재현되지 않은 현상이다. 이 6일 동안에도 상위 2개 종목(`402340` `219`건, `009150` `214`건)이 전체 차단의 53.7%를 차지한다 — 소수 종목이 하루에도 수십~수백 번 재평가되며 반복 차단된 결과다.

### `core` / `event_overlay` / `market_overlay` 비교

| 항목 | core | event_overlay | market_overlay |
|---|---|---|---|
| 차단 행 수 | 5255 | 1603 | 807 |
| 차단 고유 종목 수 | 38 | 17 | 13 |
| 차단 발생 거래일 수(전체 34일 중) | 31 | 18 | **6** |
| 차단 발생 날짜 범위 | 06-19~08-06(전체) | 06-19~08-06(전체) | **06-19~06-26만** |
| `relative_activity` 분위(차단 행, p50) | 0.694 | 0.710 | **0.079** |
| `entry_score` 분위(차단 행, p50) | 0.457 | 0.523 | 0.565 |
| `entry_score` 분위(비차단 행, p50) | 0.063 | 0.073 | 0.500 |
| `buy_candidate=true` 비율(차단 행) | 0% | 0% | 0% |
| 사유 동반 패턴 | regime_pass 등 통과 마커만, 레짐 실패 사유 동반 없음 | 동일 | 동일 |

핵심 차이: `core`/`event_overlay`의 차단 종목은 `relative_activity`가 `1.10` 기준선에 가깝게 못 미치는(p50 0.69~0.71) "경계선 근처 미달"이지만, `market_overlay`의 차단 종목은 p50 `0.079`로 **거의 활동이 없는(거의 0) 수준**이다 — 단순히 기준을 살짝 못 넘는 게 아니라 활동성이 거의 완전히 식은 종목이 반복 선정됐다는 뜻이다. 반면 `market_overlay`의 `entry_score`는 차단 여부와 무관하게 다른 source_type보다 전반적으로 높다(비차단 p50 0.50 vs core 0.06) — 신호/뉴스 강도 기준으로는 우수하게 평가됐지만 활동성 축에서는 거의 죽어 있던 종목이라는 조합이다.

### 필수 분석 질문에 대한 답

1. **선정 직후 activity가 식어서 그런가?** 아니다. `volume_surge_ratio`/`turnover_surge_ratio`는 일 단위 signal feature라 같은 날 반복 평가에서 완전히 동일한 값이 유지된다(하루 안에서 "식는" 현상은 관측되지 않는다). 대신 **여러 날에 걸쳐(최대 5~6거래일) 같은 종목이 계속 낮은 값으로 재선정**됐다 — 일별이 아니라 다일 단위의 "정체된 저활동 종목의 지속적 재선정" 문제다.
2. **원래부터 relative activity 기준과 다른 축으로 선발돼서 그런가?** 그렇다 — 가장 설득력 있는 가설이다. `entry_score`는 높은데 `relative_activity`는 거의 0인 조합이 반복된다. `market_overlay`는 뉴스/이벤트 신호 강도를 기준으로 종목을 선정하는 것으로 보이고, 그 기준이 거래 활동성과 독립적이다 — 신호는 유효해도 실제 거래는 냉각된 종목을 선정할 수 있는 구조로 보인다(코드 레벨 확인은 이번 턴 범위 밖).
3. **특정 시간대에 몰리는가?** 뚜렷한 시간대 편중은 없다(`intraday`가 88%로 가장 많지만, 이는 `intraday` 버킷 자체가 하루 중 가장 넓은 시간대라 다른 source_type도 동일한 패턴).
4. **특정 레짐에서만 심한가?** 확인 불가 수준으로 약함 — `eligibility_reasons` 동반 패턴이 `core`/`event_overlay`와 동일하게 "통과 마커만 존재, 레짐 실패 사유 없음"이라 레짐과 직접 결부됐다는 증거는 없다. 다만 이 6일이 특정 시장 국면(예: 특정 이벤트 캠페인 기간)과 겹칠 가능성은 이번 분석 범위에서 확인하지 못했다.
5. **레짐 관련 사유와 동반되는가, 순수 activity 문제인가?** 순수 activity 문제다. 차단된 모든 행의 `eligibility_reasons`는 `eligibility_regime_pass`(레짐 통과)를 포함하고 있고 별도 레짐 실패 사유는 동반되지 않는다.

### 가장 가능성 높은 원인 가설(우선순위)

1. **(1순위) `market_overlay` 후보 재선정/decay 로직 문제.** 특정 기간(06-19~06-26)에 동일한 소수 종목이 활동성이 거의 0인 상태로도 계속 `market_overlay`로 재선정됐다 — 선정 이후 활동성이 회복되지 않아도 후보 풀에서 빠지지 않는 구조로 보인다. 06-26 이후 이 현상이 완전히 사라진 것은, 그 캠페인/이벤트가 종료되며 후보 풀이 자연 갈아치워졌기 때문일 가능성이 높다(코드 변경 이력에서는 확인되지 않음 — git log에 해당 기간 `market_overlay` 관련 커밋 없음).
2. **(2순위) `market_overlay` 선정 기준이 애초에 relative_activity와 무관한 축(뉴스/이벤트 신호)이라는 설계 특성.** 이는 버그가 아니라 의도된 설계일 수 있다 — 문제는 선정 기준 자체가 아니라, 활동성이 회복되지 않는 종목을 얼마나 오래 후보로 유지하는지에 있어 보인다.
3. **(3순위, 낮은 확신) 34거래일이라는 표본 창이 우연히 한 번의 이벤트 캠페인만 포착했을 가능성.** 다른 기간에 유사한 캠페인이 다시 발생하면 같은 패턴이 재현될 수 있다 — 1회성으로 단정하기엔 표본이 짧다.

### 후속 작업 권장안

**우선순위: 관측 지표 추가 > market_overlay 로직 보정 > 조건부 필터. universe 공통 hard filter는 후순위(현재로선 부적합).**

- **1순위 — 관측 지표 추가**: `market_overlay` 후보가 후보 풀에 머무는 기간과 그 기간 동안의 `relative_activity` 추이를 추적하는 지표를 추가해, "얼마나 오래 냉각 상태로 유지되는지"를 정량화한다. 이번 분석은 이미 발생한 사고를 사후 재구성한 것이라, 실시간/준실시간 관측이 없으면 다음 발생을 놓친다.
- **2순위 — `market_overlay` 후보 로직 보정(코드 레벨 확인 필요, 이번 턴 범위 밖)**: `market_overlay` 선정/유지 로직에 활동성 회복 여부에 따른 decay(자동 제외) 조건이 있는지 코드에서 직접 확인한다. 없다면 최소 범위로 도입을 검토할 수 있다 — 단, 이는 다음 턴의 별도 코드 조사 작업이다.
- **3순위 — 조건부 필터**: universe 공통 hard filter보다는, `market_overlay`에 한정된(그리고 아마도 "N일 연속 relative_activity 미달" 같은 지속성 조건이 붙은) 조건부 필터가 더 적합해 보인다. 다만 표본이 6일/13종목으로 작아, 지금 조건부 필터를 설계하기엔 근거가 아직 얇다.
- **기각**: universe 공통 hard filter(A/B/C/D류) — 이미 이전 실측에서 비효율(0.3155)로 확인됐고, 이번 원인 분해도 "전체 유니버스에 적용할 절대 임계값"보다 "`market_overlay`에 국한된, 지속성 있는 문제"라는 그림을 뒷받침한다.

### 분석 한계

- 이 분석은 `Entrypoint Paper` 계정 1개, `market_overlay` 차단 표본이 13개 종목·6거래일로 작다 — 일반화하기엔 이르다.
- "왜 06-26 이후 재현되지 않았는가"의 정확한 코드/운영 원인은 이번 턴에서 코드를 직접 조사하지 않아 확인하지 못했다 — git log에서 해당 기간 `market_overlay` 관련 커밋은 발견되지 않았지만, 이것이 "코드가 안 바뀌었다"는 증거는 아니다(운영 데이터/이벤트 소스 자체가 바뀌었을 수도 있다).
- `relative_activity`는 이번에도 `decision_json.metadata`에 박힌 값을 그대로 읽었을 뿐, universe 정책에 반영하지 않았다(shadow 유지 원칙 그대로).

## 실측 질문

- 날짜별 유니버스 종목 수 대비 `활동성 부족` 차단 비율은 얼마인가
- 차단 종목의 `source_type`은 어디에 집중되는가
- `eligibility_low_average_volume`, `eligibility_low_turnover`, `eligibility_low_relative_activity` 중 어떤 사유가 지배적인가
- 장전/장초반/장중/장후에 분포가 어떻게 달라지는가
- 어떤 사전 필터 조합이 후보 손실을 최소화하면서 `활동성 부족` 차단을 가장 많이 줄이는가

## 필요 지표 정의

### 실행 단위 식별

- `business_date`: 거래일
- `run_started_at`: 실행 시작 시각
- `time_bucket`: `pre_open` | `open_30m` | `intraday` | `after_close`
- `market_overlay_enabled`: market overlay 활성 여부

### 유니버스 분포

- `universe_count`: 최종 유니버스 종목 수
- `core_count`
- `event_count`
- `market_count`
- `held_count`
- `reconciliation_count`
- `manual_count`

### BUY 평가 모수

- `new_buy_candidate_count`: `held_position` 제외 후 신규 BUY 평가 대상 수
- `pre_ai_activity_block_count`: `활동성 부족` 사유로 차단된 종목 수
- `pre_ai_activity_block_rate`: `pre_ai_activity_block_count / new_buy_candidate_count`

### 차단 사유 분포

- `low_average_volume_count`
- `low_turnover_count`
- `low_relative_activity_count`
- `block_rate_by_source_type`
- `block_rate_by_time_bucket`

### feature 분포

- `average_volume_20d_p10`
- `average_volume_20d_p25`
- `average_volume_20d_p50`
- `average_turnover_20d_p10`
- `average_turnover_20d_p25`
- `average_turnover_20d_p50`
- `relative_activity_fail_count`

### 가설 비교 지표

- `simulated_universe_filtered_count`
- `simulated_activity_block_reduction`
- `simulated_candidate_loss_count`
- `simulated_candidate_loss_rate`
- `simulated_block_rate_after_filter`
- `efficiency_score`

`efficiency_score`는 기본적으로 아래 둘 중 하나를 사용한다.

- `simulated_activity_block_reduction / simulated_candidate_loss_count`
- 또는 `simulated_block_rate_after_filter` 개선량 대비 `candidate_loss_rate`

## 분석 가설

### 가설 A — 평균 거래량 하한

- 조건: `average_volume_20d >= 3000`
- 의도: 극단적으로 비활성 종목을 universe 단계에서 먼저 제외한다.

### 가설 B — 평균 거래대금 하한

- 조건: `average_turnover_20d >= 50_000_000`
- 의도: 주문 실행 가능성이 낮은 저거래대금 종목을 universe 단계에서 먼저 제외한다.

### 가설 C — 절대 활동성 동시 하한

- 조건: 가설 A + 가설 B 동시 만족
- 의도: 절대 활동성 부족을 더 확실히 줄인다.

### 가설 D — core 한정 절대 활동성 하한

- 조건: 가설 C를 `source_type=core`에만 적용
- 의도: `held/reconciliation/event/manual` 안전 경로는 유지하고, core 후보 과다 유입만 줄인다.

### 가설 E — 상대 활동성 shadow 분석

- 조건: `max(volume_surge_ratio, turnover_surge_ratio) >= 1.10`
- 의도: 시점 민감도가 높은 상대 활동성을 바로 정책으로 넣지 않고 관측만 한다.

## `core × eligibility_low_relative_activity` 반복 차단 원인 분해(최근 10영업일, 2026-08-06 KST)

최근 10영업일(`2026-07-24`~`2026-08-06`)에 `활동성 부족` 차단이 다시 높게(23.93%) 나타났고, 이번에는 `market_overlay`(0%)가 아니라 `core`(25.85%) 경로가 중심이었다. `2026-06-19`~`2026-06-26`은 이번 결론의 근거로 쓰지 않는다(과거 이상치 사례로만 참고). 새 read-only 스크립트 `scripts/analysis/analyze_core_relative_activity_repeat_gap.py`로 원인을 분해했다 — 정책 구현은 하지 않았다.

### 실행 개요

- 컨테이너: `agent_trading-app-1`
- 명령: `python3 scripts/analysis/analyze_core_relative_activity_repeat_gap.py --date-from 2026-07-24 --date-to 2026-08-06 --account-alias 'Entrypoint Paper' --surge-dates 2026-08-04,2026-08-05,2026-08-06 --normal-dates 2026-07-24,2026-07-27,2026-07-28,2026-07-29,2026-07-31 --output-json /tmp/uag_core/result.json`
- 날짜 범위: `2026-07-24`~`2026-08-06`(10영업일), 계정 `Entrypoint Paper`
- BUY 경로(core/event_overlay/market_overlay) decision 행 `11512`건 수집(행 단위, 반복 빈도 자체가 분석 대상)

### 핵심 수치

- `core`: 9079행 중 2299건 차단(**25.32%**), 고유 종목 63개 중 **차단 고유 종목은 27개뿐** — 종목당 평균 85.15회 반복(rows_per_distinct_blocked_symbol)
- `core` 일별 유니버스 크기(`distinct_symbols`)는 대부분 **12개로 고정**(07-24, 07-30, 07-31, 08-03~06), `07-27`~`07-29`만 일시적으로 23~30개로 커졌다가 다시 12개로 돌아옴 — 급등일(08-04~06)과 무관하게 상시적으로 작은 core 풀이다.
- 반복 차단 종목 지속성(상위): `000810`(5거래일, `07-24`~`08-03`, **block_rate 100%**), `001800`(7거래일, `07-24`~`08-06`, block_rate 64.7%), `081660`(3거래일, block_rate 100%), `021240`(2거래일, block_rate 100%), `001450`(7거래일이지만 block_rate 25.97%로 대부분은 통과)
- **[재실행 확인]** 같은 명령을 라이브 DB에 다시 실행하면 행 수가 소폭 흔들린다(`core total_rows` 9079→9103, `blocked_rows` 2299→2317, 차단율 25.32%→25.45%) — 조회 시점에 마지막 날짜(`08-06`, 당일)가 계속 새 decision을 쌓고 있어 생기는 정상적인 변동으로 보이며, 아래 결론 수준에는 영향을 주지 않는다.

### 질문별 답

1. **같은 종목이 계속 재선정되는가, 매일 새 종목이 우연히 낮은가?** → **같은 종목이 계속 재선정된다.** 차단 2299건이 고유 종목 27개에서만 나왔고(85배 반복), `000810`/`081660`/`021240` 등은 등장할 때마다 100% 차단됐다.
2. **`core` 유니버스 내에서 오래 잔류하는가?** → 그렇다. `000810`은 5거래일(`07-24`~`08-03`) 연속 등장, `001800`은 7거래일(`07-24`~`08-06`)에 걸쳐 등장 — 상세는 `core_repeated_blocked_symbol_persistence_top20`(JSON) 참고.
3. **"신호는 괜찮지만 activity만 낮은 종목"인가, 전반적으로 약한 종목인가?** → **혼재돼 있다, 단일 유형이 아니다.** "만성적으로 반복 차단된다"(block_rate 82~100%)는 공통점을 가진 그룹 안에서도 활동성 수준 자체는 균질하지 않다 — 극저활동 종목과 중간 수준 저활동 종목이 혼재된 것으로 보인다.
   - **극저활동 예시**(`relative_activity` p50이 `0.1` 미만): `329180`(≈0.0088), `196170`(≈0.0234), `042700`(≈0.0744), `402340`(≈0.0787) — 활동성이 거의 없는 수준으로, "activity≈0" 표현이 적절하다.
   - **중간 수준 저활동 예시**(block_rate는 마찬가지로 82~100%로 높지만, `relative_activity` p50은 `0.1`을 뚜렷이 넘는 구간): `000810`(≈0.5785), `021240`(≈0.6591), `055550`(≈0.6935), `081660`(≈0.8444), `090430`(≈0.8920) — 임계값(`1.10`)에는 지속적으로 못 미치지만, 활동성이 아예 없다기보다는 경계선보다 충분히 낮은 구간에 반복적으로 머무는 쪽에 가깝다. 이들을 "activity≈0"로 표현하는 것은 과장이다.
   - **경계선 변동형** 예시(`001450`/`316140`/`004370`/`009240`/`008930`): block_rate 26~50%로 대부분은 통과하고, `relative_activity` p50이 오히려 `1.10` 이상(1.27~1.63)인 경우도 있다 — 가끔만 경계선 아래로 떨어진다.
   - `entry_score`는 위 세 그룹 모두 0.27~0.78 범위로 겹쳐, `entry_score` 하나로 그룹을 가르지 못한다.
4. **급등일(08-04~06) vs 평시(07-24~07-31, 07-30 제외) 비교** — 예상과 다른 방향으로 나왔다(가정이 깨진 지점):
   - 유니버스 크기: 급등일 3일 합산 고유종목 25개(일 평균 ~8.3) vs 평시 5일 합산 41개(일 평균 ~8.2) — **거의 동일**, "급등일에 후보 풀이 비정상적으로 수축"이라는 가정은 지지되지 않는다.
   - 반복 집중도: 급등일 `rows_per_distinct_blocked_symbol=53.05`(차단 고유종목 19개) vs 평시 `114.8`(차단 고유종목 10개) — **급등일이 오히려 더 넓게(더 많은 종목에) 퍼져서 차단됐다**, 소수 종목에 집중된 게 아니다.
   - source_type 분포: 급등일 차단은 `core` 1008건 + `event_overlay` 356건(둘 다 영향), 평시는 `core` 1148건 + `event_overlay` 53건 — 급등일에는 `event_overlay`도 함께 영향받아, **core만의 국지적 문제가 아니라 여러 source_type에 걸친 동시 현상**으로 보인다.
   - `relative_activity` 분포(차단 행): 급등일 p50 **0.847**(p10 0.670) — 임계값(1.10) 바로 아래 **"경계선 근접 미달"**. 평시 p50 **0.578**(p10 0.023) — 더 넓게 퍼지고 **콜드(0에 가까운) 꼬리가 훨씬 두껍다**. 즉 급등일은 "더 나쁜 종목"이 아니라 "여러 종목이 동시에 임계값 근처로 낮아진 날"이고, 평시는 "소수의 만성적으로 매우 낮은 종목"이 반복 잡히는 패턴이다.
   - 시간대: 두 구간 모두 `intraday`에 압도적으로 집중(버킷 자체가 가장 넓어서 자연스러운 결과) — 뚜렷한 차이 없음.
   - 레짐: 급등일(`bullish_trend` 620 / `range_bound` 388)과 평시(653/495) 비율이 비슷 — 레짐 하나로 급등일을 설명하기는 어렵다.
5. **원인이 어디에 더 가까운가?**
   - **1순위: 후보 유지/decay 로직이 약하다.** `000810`이 5거래일 동안 activity 회복 없이 매번 차단되면서도 계속 core 후보로 유지된 것이 가장 강한 신호다.
   - **부분적으로 참: 선정 기준이 activity와 독립적이다.** 만성적으로 반복 차단되는 그룹(극저활동 + 중간 수준 저활동 혼재)의 존재가 이를 뒷받침하지만, 경계선 변동형 그룹(`001450` 등)은 대체로 activity가 정상이라 "선정 기준 자체"보다는 "차단된 뒤에도 안 빠지는 것"이 더 핵심으로 보인다.
   - **약한 증거: 특정 일자에 후보 풀이 비정상적으로 수축.** core 유니버스 크기는 급등일과 무관하게 대체로 12개로 일정 — 이 가설은 이번 core 분석에서는 뒷받침되지 않는다.
   - **부분적으로 참: 반복 평가 구조로 인한 "행 개수" 착시.** row 수 기준 절대값(2299건)은 85배 반복으로 부풀려져 있다. 그러나 차단 비율(25.32%)과 차단 고유 종목 수(27개) 자체는 반복과 무관한 실질 수치이므로, "완전히 착시"는 아니다.

### 다음 단계 우선순위 제안

**1순위: `core` 선정/유지 로직 코드 조사(구현 아님).** `000810`류가 며칠씩 activity 회복 없이 유지되는 메커니즘을 코드에서 직접 확인해야 한다(decay/TTL/재평가 주기 존재 여부) — 이번 턴 범위 밖, 다음 턴 권장.
**2순위: 관측 지표 추가.** 종목별 "연속 차단일수(streak)"를 상시 계산하는 지표를 추가하면, 이번처럼 사후 재구성하지 않고도 만성 콜드 종목을 조기에 포착할 수 있다.
**3순위(보류): 조건부 prefilter 가설 추가 실측.** 아직 이르다 — 차단 고유 종목이 27개/10일로 표본이 작고, 무엇보다 "선정 유지" 문제(코드 확인 필요)가 우선이라 prefilter 설계는 그 다음 단계다.

### 확인된 사실 vs 아직 가정인 부분

- **확인된 사실**: 반복 재선정(질문 1), 다일 잔류(질문 2), 만성 콜드/경계선 변동 두 유형 혼재(질문 3), 급등일이 "더 나쁜 종목"이 아니라 "더 넓게 퍼진 경계선 근접 미달"이라는 패턴(질문 4) — 전부 위 실측 수치로 직접 확인됨.
- **아직 가정인 부분**: "후보 유지/decay 로직이 약하다"는 코드를 직접 조사하지 않은 상태의 데이터 기반 추론이다 — 실제 코드에 decay 로직이 있는지, 있다면 왜 작동하지 않는지는 확인하지 못했다. 급등일 3건이 우연히 겹친 시장 전반의 저활동 국면인지, 아니면 다른 구조적 원인이 있는지도 확정하지 못했다.
- **이번 분석만으로 바로 정책 구현이 가능한가**: 아니다. 코드 레벨 확인(1순위) 없이 "유지/decay 로직 보정"을 구현하면 추측에 기반한 변경이 된다. 이번 턴은 원인 분해까지가 정당한 범위다.

## `core` 선정/유지 구조 코드 조사(2026-08-06 KST)

위 실측에서 도출된 "1순위: `core` 선정/유지 로직 코드 조사"를 이번 턴에서 수행했다. **정책 구현은 하지 않았고, 코드 변경도 없다** — read-only 코드 조사 결과만 정리한다.

### 확인한 핵심 파일

- `src/agent_trading/services/universe_selection.py`(`UniverseSelectionService._add_core_universe`/`_is_core_seed_instrument`/`_index_membership_values`)
- `src/agent_trading/services/core_universe_seed.py`(`APPROVED_CORE_UNIVERSE_SYMBOLS`)
- `src/agent_trading/services/index_membership_staleness.py`
- `src/agent_trading/repositories/postgres/instrument_index_memberships.py`
- `src/agent_trading/repositories/postgres/universe_freeze_runs.py`(`get_latest`)
- `src/agent_trading/services/deterministic_trigger_engine.py`(`_assess_buy_eligibility`)
- `src/agent_trading/services/decision_factory.py`
- `scripts/run_decision_loop.py`(`_load_intraday_frozen_universe_with_anchor`)
- `scripts/import_instrument_index_membership_seed.py`, `scripts/sync_kis_instrument_master.py`(index membership 갱신 호출부)

### 질문별 답(코드 근거 포함)

**1. `core` 후보는 어디서 생성되는가?** `UniverseSelectionService._add_core_universe()`(`universe_selection.py:1089-1114`)가 매 `compose()` 호출마다 활성 종목을 순회하며 `_is_core_seed_instrument()`(892-902행)로 판정한다. 판정 우선순위는 (a) `instrument.metadata["core_universe"]` 명시 플래그 → (b) KOSPI segment + `_CORE_INDEX_MEMBERSHIP_CODES`(지수 편입 코드) 일치 → (c) 정적 코드 allowlist `APPROVED_CORE_UNIVERSE_SYMBOLS`(`core_universe_seed.py:17-33`, 약 80개 심볼 하드코딩). 활동성 지표(`volume_surge_ratio`/`turnover_surge_ratio`/`average_volume` 등)는 이 판정 어디에도 등장하지 않는다.

**2. `core` 후보는 어떻게 유지/재사용/교체되는가?** 이중 구조다. (a) `compose()` 자체는 stateless — 매번 allowlist/membership을 재평가한다(carry-over 코드 없음). (b) 그러나 실제 decision loop는 이 결과를 직접 쓰지 않고, `scripts/run_decision_loop.py:385-439`의 `_load_intraday_frozen_universe_with_anchor()`가 `universe_freeze_runs.get_latest(business_date, freeze_purpose)`(`universe_freeze_runs.py:59-73`, `business_date` 단위 스코프)로 하루 1회 materialize된 freeze snapshot을 하루 종일 재사용한다(`freeze_reused=True`). **freeze는 매 영업일마다 새로 생성**되므로(다일 캐리오버 아님), 여러 거래일에 걸친 반복은 "freeze 재사용" 때문이 아니라 **매일 재계산되는 `compose()`가 매번 같은 정적 소스(allowlist+membership)를 다시 core로 포함**시키기 때문이다.

**3. TTL/decay/eviction/refresh 규칙이 존재하는가?** **존재하지 않는다.** `universe_selection.py`/`core_universe_seed.py` 전체에서 `ttl|decay|evict|cooldown|expire` 키워드 grep 결과 0건(직접 재확인 완료). `DEFAULT_CORE_SIGNAL_FRESHNESS_MAX_AGE_DAYS`(`universe_selection.py` 부근)가 유일하게 "날짜 경과"를 다루지만, 이는 정렬 우선순위를 FRESH/STALE/MISSING 계층으로 낮추는 용도일 뿐 core 포함 여부를 바꾸지 않는다.

**4. 활동성 지표는 선정 단계에서 고려되는가?** **고려되지 않는다 — 선정과 차단이 완전히 분리된 구조다.** `_is_core_seed_instrument()`와 core에 적용되는 유일한 exclusion인 `LiquidityFilterService.check()`(정지/관리종목/비활성/틱사이즈 등 정적 instrument 상태 필터) 어디에도 활동성 지표가 없다. `volume_surge_ratio`/`turnover_surge_ratio`/`average_volume_20d`는 `deterministic_trigger_engine.py:_assess_buy_eligibility()`(511-561행)에서 **처음이자 유일하게** 등장한다: `avg_daily_volume < 3000.0` → `eligibility_low_average_volume`, `estimated_average_turnover < 50_000_000.0` → `eligibility_low_turnover`, `max(volume_surge_ratio, turnover_surge_ratio) < 1.10` → `eligibility_low_relative_activity`(값 직접 재확인 완료). 이 게이트는 `source_type`(core/event_overlay/market_overlay)을 구분하지 않고 동일하게 적용된다.

**5. `universe_freeze_runs`/`universe_freeze_run_items`/`universe_anchor`와의 관계.** freeze는 `business_date` 단위로 스코프되어 매일 재생성되므로, "하루 안 반복"의 원인이지 "여러 날 반복"의 원인이 아니다. `decision_json.universe_anchor`(`decision_factory.py`)는 감사/재현용 메타데이터를 그대로 복사해 기록할 뿐, core 후보 구성 로직에 어떤 피드백도 주지 않는다.

### [초기 조사 결과에 대한 자체 재검증 — 중요한 정정]

초기 코드 조사는 "core는 정적 Python allowlist 하나로만 결정된다"는 인상을 줬으나, **직접 재확인한 결과 이는 부정확하다.** 최근 10영업일 실측에서 반복 차단된 core 종목(`000810`/`001800`/`081660`/`021240`/`042700`/`402340`/`329180`/`196170`/`055550`/`090430`/`316140`/`004370`/`009240`/`008930`/`111770`/`023530`/`000240`/`003490`/`138040`) 중 `000810`/`001450`/`402340`/`329180`/`196170`/`055550`/`003490`/`138040` 등 절반가량만 `APPROVED_CORE_UNIVERSE_SYMBOLS`에 실제로 포함되어 있고, `001800`/`081660`/`021240`/`111770`/`042700`/`023530`/`316140`/`004370`/`009240`/`008930`/`090430`/`000240`은 이 목록에 없다 — 즉 **이들은 (b) 지수 편입(index membership) 경로로 core에 편입되고 있을 가능성이 높다.**

이 경로를 추가로 확인한 결과: `instrument_index_memberships` 테이블은 자동 스케줄러가 아니라 **수동 업로드 스크립트**(`scripts/import_instrument_index_membership_seed.py`, `scripts/sync_kis_instrument_master.py`)를 통해서만 갱신된다. `src/agent_trading/services/index_membership_staleness.py`의 docstring이 명시하듯("KIS에 지수 구성종목 전체 목록 API가 확인되지 않아 자동 갱신 파이프라인 대신 ... 읽기 전용으로 감시만 한다. 주문 경로/게이트 로직에는 어떤 영향도 주지 않는다"), staleness 감시는 존재하지만 **관측 전용**이고 실제 게이트/선정 로직에 반영되지 않는다(기본 staleness 임계값은 21일).

**정정된 결론**: core 선정은 하나의 정적 소스가 아니라 **정적 Python allowlist + 수동 갱신되는 DB 인덱스 편입 테이블, 두 개의 사실상 정적인 소스**로 구성된다. 두 경로 모두 활동성과 무관하고, 자동 갱신/decay 메커니즘이 없다는 점에서 핵심 결론("선정 앞단이 activity와 완전히 독립적이고 반영구적으로 유지된다")은 오히려 더 강하게 뒷받침된다 — 다만 "정적 allowlist 하나가 원인"이라는 단순화된 설명은 부정확했다.

### 존재하는 규칙 vs 존재하지 않는 규칙

**존재하는 규칙**
- core 선정: 정적 allowlist(`APPROVED_CORE_UNIVERSE_SYMBOLS`) + 수동 갱신 DB 인덱스 편입 테이블(`instrument_index_memberships`) + `instrument.metadata` override
- core에 적용되는 유일한 제외 조건: 정지/관리종목/비활성/asset_class/틱사이즈 등 정적 instrument 상태 필터
- 정렬(우선순위) 조정: 신호 점수 기반 랭킹 + freshness 계층(FRESH/STALE/MISSING) — 포함 여부가 아니라 순서만 바꿈
- 활동성 기반 BUY 차단: `deterministic_trigger_engine._assess_buy_eligibility()`의 3개 임계값(평균거래량/평균거래대금/상대활동성)
- 하루 단위 universe freeze 재사용(`business_date` 스코프, 매일 재생성)
- 인덱스 편입 데이터 staleness **관측**(21일 임계값, 게이트에 영향 없음)

**존재하지 않는 규칙**
- core 심볼에 대한 TTL/decay/자동 만료 — 없음
- 활동성 저하 시 core에서 자동 제외(eviction) — 없음(선정 로직에 활동성 지표 참조 자체가 없음)
- 반복 차단 이력에 따른 재평가 빈도 감소/쿨다운 — 없음
- freeze의 여러 날 캐리오버 — 없음(매일 재생성)
- 인덱스 편입 staleness가 게이트/선정에 미치는 영향 — 없음(관측 전용, docstring에 명시)

### 반복 차단 현상을 설명하는 가장 유력한 원인(우선순위)

1. **(1순위) 구조적 분리**: `core` 선정(정적 allowlist + 수동 갱신 인덱스 편입)과 활동성 게이트(`deterministic_trigger_engine`)가 완전히 독립된 레이어다. 두 소스 모두 활동성과 무관하고 피드백 루프가 없어, 저활동 상태가 되어도 선정 단계에서 걸러지지 않고 매 영업일 그대로 재선정된다.
2. **(2순위) 정렬 로직이 저활동 core 종목을 배제하지 않고 순위만 조정**: freshness 계층 로직은 신호가 오래돼도 core에서 배제하지 않고 정렬만 뒤로 미룬다 — 활동성이 낮아도 daily cap 안에 들어와 반복 평가될 수 있다.
3. **(3순위, 부차 요인) 하루 내 freeze 재사용으로 인한 반복 횟수 증폭**: 하루 동안 같은 스냅샷을 재사용하므로 관측되는 차단 "행" 수 자체가 증폭된다(여러 날 반복의 근본 원인은 아님).

### 확인된 사실 vs 아직 추론인 부분

- **확인된 사실**(코드 직접 확인·grep 재검증 완료): 선정 로직에 활동성 지표 미참조, TTL/decay 부재(grep 0건), freeze의 일 단위 재생성, 활동성 게이트의 정확한 임계값과 위치, 반복 차단 종목이 allowlist와 index membership 두 경로에 걸쳐 있다는 사실.
- **아직 추론인 부분**: `instrument_index_memberships` 테이블에 실제로 언제 마지막 반영됐는지, 그 시점이 이번 10영업일 반복 차단과 시간적으로 어떻게 겹치는지는 DB 조회 없이는 확정할 수 없다(이번 턴은 코드 조사로 한정, DB 조회는 하지 않았다). "event_overlay/market_overlay는 후보 생성 자체가 최근 활동에 조건화되어 core와 대비된다"는 설명도 코드 구조상 타당해 보이지만 이번 턴에서 `event_overlay`/`market_overlay` 선정 로직 자체를 상세히 재조사하지는 않았다.

### 다음 단계 제안

**최소 계측이 다음 단계로 적합하다(설계안 작성은 아직 이르다).** 코드 구조는 명확히 확인됐으나, "실제로 그 인덱스 편입 테이블이 마지막으로 언제 갱신됐는지"와 "그 갱신 주기가 반복 차단 패턴과 어떻게 맞물리는지"를 확인하지 않고 바로 코드 수정안(예: core 선정에 활동성 사전 필터 추가, 반복 차단 이력 기반 강등 규칙)을 설계하면 근거가 절반만 채워진 상태가 된다. 다음 턴에서 `instrument_index_memberships` 테이블의 실제 최신 반영 시각을 read-only로 확인하는 것을 권장한다.

## 해석 기준

- `low_average_volume` 또는 `low_turnover` 비중이 높으면 universe 사전 필터 강화 후보로 본다.
- `low_relative_activity` 비중이 높으면 시간대/장세 영향 가능성을 먼저 의심한다.
- 가설 D가 차단 감소 대비 후보 손실률이 가장 낮으면 1순위 권고안으로 검토한다.
- `held_position`, `reconciliation_overlay`가 많이 잘리면 정책 위반 가능성이 있으므로 기본 예외 유지가 우선이다.

## read-only 분석 스크립트 설계안

### 경로

- 권장 파일: `scripts/analysis/analyze_universe_activity_gap.py`

### 실행 원칙

- DB read-only 조회만 수행한다.
- 외부 API/KIS 호출 없이 저장된 스냅샷과 런타임 산출물만 사용한다.
- 쓰기/마이그레이션/캐시 갱신을 하지 않는다.

### 입력 인자

- `--date-from YYYY-MM-DD`
- `--date-to YYYY-MM-DD`
- `--account-alias <alias>`
- `--time-buckets pre_open,open_30m,intraday,after_close`
- `--output-json <path>`
- `--output-csv-dir <path>`

### 입력 데이터 소스

- 유니버스 결과:
  - `decision_loop` summary/freeze/preview 계열 저장 결과 중 `symbol`, `source_type`, `inclusion_reason`
- 차단 결과:
  - `guardrail_evaluations`
  - `trade_decisions`
  - `decision_contexts`
- feature 결과:
  - `signal_feature_snapshots`

정확한 테이블/JSON 경로는 구현 전에 현재 저장 구조를 한 번 더 확인한다.

**[구현 착수 시 확인 결과, 2026-08-04 KST]** `scripts/analysis/
analyze_universe_activity_gap.py` 초안 구현 전 실제 저장소 구조를
확인한 결과, 위 가정과 아래와 같은 차이가 있어 스크립트에 그대로
반영했다(계획의 의도는 바꾸지 않는다 — 데이터 소스 경로만 정정).

- **"실행 단위(run)" 전용 테이블이 없다.** decision loop 개별 사이클을
  기록하는 run 테이블이 존재하지 않아, `trading.decision_contexts.
  created_at`을 시간 간격 클러스터링해 파생 재구성한다(근사치,
  스크립트 상단 docstring 참고).
- **차단 사유는 `guardrail_evaluations`가 아니라 `trade_decisions.
  decision_json.deterministic_trigger.eligibility_reasons`에 있다.**
  `guardrail_evaluations`는 주문 단계 validation(사이징/규정 준수)
  결과 테이블이며, `eligibility_low_average_volume`/
  `eligibility_low_turnover`/`eligibility_low_relative_activity`
  차단 사유 코드는 이 테이블을 전혀 거치지 않는다.
- **유니버스 종목/`source_type` 복원은 `universe_freeze_run_items`
  대신 `trade_decisions.source_type`을 직접 사용한다.** 이미 각
  decision 행에 그 순간의 평가 대상 `source_type`이 컬럼으로 있어
  더 직접적이다. `universe_freeze_run_id`는
  `decision_json.universe_anchor`를 통해 보조 메타데이터로만
  조인한다.
- **`market_overlay_enabled`는 저장된 플래그가 없다.**
  `MarketOverlayDiagnostics.enabled`는 API 응답 전용이라 DB에
  남지 않는다 — 해당 실행 단위에 `source_type='market_overlay'`
  행 존재 여부로 추정한다(결과 기반 추정치임을 명시).

**[초안 실행 가능성 보정 시 추가 확인, 2026-08-04 KST]** 위 4가지에
더해 아래 사실을 추가로 확인해 스크립트에 반영했다.

- **`trade_decisions.decision_context_id`는 UNIQUE 제약이 없다**
  (`db/migrations/0019_remove_td_context_unique.sql`: "동일
  decision_context에 대해 여러 TD row 허용(INSERT-only 정책)").
  같은 context에 재시도/정정으로 여러 행이 쌓일 수 있어, 단순 조회는
  어떤 행이 채택되는지 비결정적이 된다 — `DISTINCT ON(created_at
  DESC, trade_decision_id DESC)`으로 그 마이그레이션이 추가한 인덱스
  (`idx_trade_decisions_context_created`)와 동일한 정렬 기준을 써서
  가장 최신 행만 결정론적으로 채택하도록 스크립트를 고쳤다.

**[실측 실행 검증 결과, 2026-08-04 KST]** `agent_trading-app-1` 컨테이너에서
`Entrypoint Paper` 계정, 2026-08-03~08-04 범위로 read-only 실행 검증을
1회 수행했다. 실행 자체는 정상 종료됐고 baseline/by_source_type/
by_time_bucket/by_market_overlay/hypotheses/recommendation이 모두
출력됐으며 JSON/CSV 산출물도 정상 생성됨을 확인했다. 이 과정에서
클러스터링된 실행 단위(run) 하나에 동일 종목이 여러 decision 행으로
중복되는 사례(표본 29건)가 실제로 존재함을 발견했고, 가설 시뮬레이션의
분자·분모 granularity 불일치를 스크립트에서 고쳤다(자세한 내용은
스크립트 상단 `[2026-08-04 KST 실측 실행 검증 중 발견/보정]` 참고).
이 표본에서는 `market_overlay_enabled` 추정 run이 0건이었다 — 이 기간
동안 `market_overlay` source_type이 실제로 없었기 때문이며, 분리
집계 로직 자체의 결함은 아니다.

### 내부 처리 단계

1. 날짜 범위의 대상 실행 집합을 수집한다.
2. 실행 시점을 `time_bucket`으로 분류한다.
3. 실행 단위별 유니버스 종목과 `source_type`을 복원한다.
4. 실행 단위별 `pre-AI` 차단 사유를 복원한다.
5. 종목별 최신 signal feature를 조인한다.
6. baseline 지표를 계산한다.
7. 가설 A~E를 메모리 상에서 시뮬레이션한다.
8. 날짜별/시간대별/source_type별 요약표를 만든다.
9. 권장안 초안을 자동 생성한다.

### 함수 설계안

- `load_runs(date_from, date_to, account_alias)`
- `classify_time_bucket(run_started_at)`
- `load_universe_members(run_id)`
- `load_pre_ai_blocks(run_id)`
- `load_signal_features(run_id, symbols)`
- `build_baseline_rows(...)`
- `simulate_filter_hypothesis(rows, hypothesis_name)`
- `summarize_daily(rows)`
- `summarize_by_source_type(rows)`
- `summarize_by_time_bucket(rows)`
- `build_recommendation(summary)`

### 출력 파일

- `daily_summary.csv`
- `hypothesis_comparison.csv`
- `blocked_symbols_detail.csv`
- `summary.json`

### JSON 출력 구조 예시

```json
{
  "date_range": {
    "from": "2026-07-01",
    "to": "2026-08-04"
  },
  "run_count": 0,
  "baseline": {
    "pre_ai_activity_block_rate": 0.0,
    "reason_distribution": {}
  },
  "hypotheses": [],
  "recommendation": {
    "recommended": [],
    "hold": [],
    "rejected": []
  }
}
```

## 보고 포맷

완료 보고에는 아래 항목을 반드시 포함한다.

- 날짜 범위
- 총 실행 수
- 시간대 분포
- baseline `활동성 부족` 차단 비율
- 사유별 분포
- `source_type`별 분포
- 비교군별 `차단 감소량 / 후보 손실률 / 효율 점수`
- `권장안 / 보류안 / 기각안`
- 구조적 한계와 미확인 가정

## 추가 보정사항

- `relative_activity`는 시점 민감성이 높으므로 바로 universe 정책으로 넣지 않고 shadow-only로 먼저 측정한다.
- `held_position`, `reconciliation_overlay`는 실측 대상에는 포함하되, 사전 필터 비교군에서는 기본 예외로 둔다.
- market overlay 활성 시점과 비활성 시점을 반드시 분리 집계한다.
- 장전/장초반에서는 `F5 low_volume` 및 `relative_activity` 왜곡 가능성을 별도로 표시한다.

## 그 외 유지해야할 원칙

- read-only DB 조회만 사용한다.
- 외부 API/KIS 호출 없이 저장된 feature와 guardrail 결과만 사용한다.
- universe 정책과 BUY 정책을 혼동하지 않고, 사전 필터를 어디까지 당길지에만 집중한다.
- 안전 경로(`held_position`, `reconciliation_overlay`, 필요 시 `event_overlay`)는 손실 최소화보다 우선 보호한다.

## 완료 후 보고에 대한 가이드

- baseline 차단율과 사유 분포를 먼저 제시한다.
- 그 다음 비교군별 `차단 감소량 / 후보 손실률 / 효율 점수`를 같은 표에서 제시한다.
- 마지막에 `권장안`, `보류안`, `기각안`을 구분한다.
- 구현 전환이 필요하면, 어떤 가설을 왜 코드 정책으로 승격할지 한 문단으로 정리한다.
