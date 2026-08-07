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

## `core` 동적 강등(demotion) 레이어 설계 검토(2026-08-06 KST)

바로 위 절이 제안한 "다음 단계"는 `instrument_index_memberships` 최신화 시각 확인이었다. 이번 작업은 그 방향을 명시적으로 대체한다 — **membership 자동화/최신화는 이번 설계의 대상이 아니다.** 정적 core seed(`APPROVED_CORE_UNIVERSE_SYMBOLS` + `instrument_index_memberships` + metadata override)는 그대로 유지하는 것을 전제로 하고, 그 위에 **운영 시점에 반복 차단 종목을 일시 강등하는 동적 보정 레이어**를 어떻게 설계할지만 다룬다. 이번 절은 **설계 검토이며 구현은 하지 않았다** — 코드 변경 없음.

### 조사한 근거

`compose_with_diagnostics()`(`universe_selection.py:998-1055`)의 실제 단계 순서를 확인했다:

```
Step 1: _add_core_universe(seen, ctx)          — core seed 판정
Step 2: _add_held_positions(seen, ctx)         — 강제 override
Step 3: _add_reconciliation_overlay(seen, ctx) — 강제 override
Step 4: _add_event_overlay(seen, ctx)
Step 5: _add_manual_overlay(seen, ctx)
Step 6: _add_market_overlay(seen, ctx)
Step 7: _apply_exclusions(seen)                — 유동성/상태 필터(source_type 공통)
Step 8: 우선순위 정렬
```

`held_position`/`reconciliation_overlay`는 Step 2/3에서 `seen` 딕셔너리를 override하므로, Step 1에서 `core`로 잡힌 심볼이라도 이후 단계에서 다른 source_type으로 바뀔 수 있다. 이는 강등 레이어의 적용 위치 판단에 직접 영향을 준다(아래 질문 5 참고). `self._repos.signal_feature_snapshots`는 이미 이 서비스 안에서 사용 중이다(`universe_selection.py:783`, freshness 계층 판정용) — 즉 signal snapshot 조회는 기존 의존성을 재사용할 수 있다. 반면 `trade_decisions`(차단 이력)는 `RepositoryContainer`에는 존재하지만(`repositories/container.py:62`) 이 서비스에서 아직 쓰인 적이 없다 — 종목별 최근 차단 이력을 조회하는 repository 메서드는 신규로 필요하다.

### 질문 1~2 — 후보 방식 비교

| 방식 | 설명가능성 | 운영단순성 | 오탐/과잉제외 위험 | 기존 구조 정합성 | 구현난이도 | 실측 문제와의 직접 연결성 |
|---|---|---|---|---|---|---|
| **A. 최근 차단 이력 기반**(N영업일 `eligibility_low_relative_activity` 최종 차단 횟수/비율/streak) | 매우 높음 — "실제로 N일 중 M일 이 사유로 차단됐다"는 문장 그대로 설명 가능 | 중간 — 신규 repository 조회(decision_json 파싱) 필요 | 낮음 — 실제 차단 결과 누적을 요구하므로 단발성 노이즈에 둔감 | 높음 — 뒤단 게이트의 실제 판정 결과를 그대로 재사용, 새 임계값 개념을 안 만듦 | 중간 — 신규 repo 메서드 1개 필요 | 매우 높음 — 실측에서 관측한 "반복 차단"을 정의 그대로 입력값으로 씀 |
| **B. 최신 signal/activity snapshot 기반**(현재 `relative_activity`/`average_volume_20d` 값 직접 재사용) | 중간 — "오늘 시점 activity가 낮다"는 설명은 되지만, 왜 지금 강등하는지(과거 이력 없이)는 약함 | 높음 — 기존 `signal_feature_snapshots` 조회 재사용, 신규 repo 불필요 | 높음 — 단일 시점 스냅샷 노이즈에 취약. `relative_activity`는 이미 문서에서 "시점 민감성이 높아 shadow-only 유지"로 명시된 지표다 — 이를 선정 단계의 직접 입력으로 승격하면 그 원칙과 긴장 관계가 생긴다 | 낮음~중간 — shadow-only 원칙과 충돌 소지 | 낮음 — 기존 조회 경로 그대로 사용 | 중간 — activity 낮음은 확인되지만 "반복"이라는 실측 핵심을 직접 담지 못함 |
| **C. 하이브리드**(차단 이력을 주 신호로, snapshot 값을 보조 확인용으로) | 높음 | 낮음 — 두 데이터 소스를 함께 유지·정합 확인해야 함 | 낮음(A와 유사) | 중간 — 복잡도는 늘지만 원칙 위반은 없음 | 높음 — 두 경로 모두 구현 | 높음 |

**결론: A(최근 차단 이력 기반)를 1차안으로 권장한다.** B는 `relative_activity`를 shadow에서 실질적 선정 입력으로 승격시켜, 문서가 반복적으로 지켜온 "시점 민감성 때문에 바로 정책화하지 않는다"는 원칙과 정면으로 부딪힌다(사용자 지시의 "뒤단 `eligibility_low_relative_activity`는 유효한 안전장치로 유지"라는 전제와도, 그 안전장치의 원재료를 앞단에 그대로 복제해 넣는 셈이라 방향이 어긋난다). A는 뒤단 게이트가 이미 내린 판정 결과(이력)만 사용하므로 새로운 판단 기준을 만드는 게 아니라 "그 판정이 반복됐는지"만 관측한다 — 원칙 훼손이 없다. C(하이브리드)는 v2 이후 보강 옵션으로 남겨둔다.

### 질문 3 — 입력 변수 제안

1순위로 아래 조합을 제안한다(전부 A 방식, `trade_decisions.decision_json`의 실제 차단 이력에서 유도):

- **최근 N영업일 core 등장일 대비 `eligibility_low_relative_activity` 최종 차단 비율**(streak 단독보다 안정적 — 등장 자체가 적은 종목의 우연한 연속 차단을 과대평가하지 않음)
- **연속 차단일수(streak)** — `analyze_core_relative_activity_repeat_gap.py`가 이미 유사 개념(`distinct_blocked_dates`)을 계산 중이라 재사용 가능
- **최근 N영업일 최종 차단 횟수(절대 건수)** — 반복 평가로 인한 "행 개수 부풀림"을 그대로 쓰면 안 되므로, 반드시 **거래일(day) 또는 decision_context 단위로 dedup한 값**을 써야 한다(이전 turn에서 확인한 "분자·분모 granularity 불일치" 교훈을 그대로 적용)
- (보조, C 하이브리드에서만) 최근 `relative_activity`/`average_volume_20d`/`average_turnover_20d` — 1차안에서는 입력으로 넣지 않는다.

### 질문 4 — 1차 설계안(규칙 조합 예시)

아래는 1차 설계안의 형태 예시이며, 정확한 임계값은 이번 턴에서 확정하지 않는다(실측 검증 전 확정은 시기상조):

- 조건(예시): 최근 5영업일 중 core로 등장한 날 대비 `eligibility_low_relative_activity` 최종 차단 비율이 80% 이상이거나, 연속 차단일수(streak)가 3일 이상
- 강등 방식: **하루 단위 제외(day-level exclusion)** — 강등된 날의 유니버스 compose에서만 제외하고, 다음 날 조건을 다시 평가한다(자동 영구 제외 아님)
- 재진입 조건: 강등 다음 날에도 여전히 `core` seed 자격(allowlist/membership)은 유지되므로, 그날 다시 조건을 평가해 차단 비율/streak가 기준 밑으로 내려오면 즉시 재진입 — 별도의 "냉각 기간(cooldown)"을 두지 않는 것이 단순하다(사용자가 요청한 "정말 최소" 범위에 부합)

### 질문 5 — 설계 위치

| 위치 후보 | 장점 | 단점 | 권장 여부 |
|---|---|---|---|
| `_add_core_universe()` 직후 | core 전용 로직과 가장 가깝다 | Step 2/3(`held_position`/`reconciliation_overlay`)이 이후 override할 수 있어, 강등 여부와 무관하게 어차피 override될 심볼까지 미리 평가하는 낭비/오판 소지가 있다 | 비권장 |
| `_apply_exclusions()` 확장 | 기존 exclusion 파이프라인 재사용 | 이 함수는 **모든 source_type에 공통 적용**되는 유동성/상태 필터다. `core`에만 적용해야 하는 이번 요구사항과 섞으면 다른 source_type에 실수로 영향을 줄 위험이 생긴다 | 비권장 |
| 별도 `core_prefilter_service` | 완전히 독립된 모듈, 테스트 격리 용이 | 신규 서비스 하나를 배선(wiring)해야 하는 오버헤드 — "최소 범위" 요청과는 다소 어긋남 | 조건부(2차 확장 시 고려) |
| **Step 6과 Step 7 사이에 새 Step 삽입**(`_apply_core_activity_demotion`, 가칭) | Step 1~6이 끝난 시점의 `seen`을 보고 `source_type == CORE`로 **여전히 남아있는** 심볼만 골라 강등 판단 — held/reconciliation/event/market/manual override가 이미 반영된 뒤라 다른 경로를 침범할 위험이 없다. 기존 `compose_with_diagnostics`의 단계형 구조에 자연스럽게 끼워 넣는 신규 함수 1개로 끝난다 | 신규 repository 조회(차단 이력) 1개가 필요하다 | **권장** |

freeze는 `business_date` 단위로 하루 1회만 materialize되므로(§상단 "선정/유지 구조 코드 조사" 참고), 이 강등 판단도 **하루 1회, freeze materialize 시점에 한 번 평가하면 충분**하다 — decision cycle마다 재평가할 필요가 없다.

### 질문 6 — 예외 정책

- `held_position`/`reconciliation_overlay`: 당연히 예외(기존 정책 그대로, 이미 Step 2/3 override로 구조적으로 보장됨).
- `event_overlay`/`market_overlay`/`manual`: 강등 대상에서 **제외**해야 한다. 이번 설계는 "`core`로서" 반복 차단되는 것을 대상으로 하며, 같은 심볼이 뉴스/이벤트 신호로 `event_overlay`나 `market_overlay`에 독립적으로 편입된다면 그건 core 강등과 무관한 별개의 근거다. Step 6 이후 `source_type == CORE`로 필터링해서 판단하면, 이 경계는 자연히 지켜진다(다른 source_type으로 override된 심볼은 애초에 대상에서 빠짐).
- 같은 심볼이 `core`에서는 강등되고 `market_overlay`로는 여전히 들어올 수 있어야 하는가? — **그렇다.** 강등은 `core` inclusion reason에 대해서만 적용하고, symbol 전역 차단이 아니다. 이는 "activity 부족 종목을 아예 막자"가 아니라 "정적 core 슬롯을 반복 실패 종목이 계속 점유하지 않게 하자"는 이번 목적과 정확히 일치한다.
- `manual`: 운영자가 명시적으로 넣은 watchlist는 강등 로직이 덮어써서는 안 된다 — 사람의 명시적 의도를 자동 규칙이 무시하면 신뢰가 깨진다.

### 질문 7 — 로그/관측 메타데이터

강등이 적용된 각 심볼에 아래를 기록해야 한다(값 이름은 예시, 최종 스키마는 구현 턴에서 확정):

- `demotion_reason`(예: `"repeated_low_relative_activity"`)
- `lookback_window_days`
- `appearance_count_in_window` / `blocked_count_in_window` / `block_ratio_in_window`
- `current_streak`
- `last_blocked_business_date`
- `last_seen_business_date`
- `previous_source_type`(강등 전 `core`였다는 사실 자체를 기록)
- `demotion_effective_business_date`
- `re_entry_evaluated`(다음날 재평가에서 재진입했는지 여부, 관측용)
- `is_shadow_only`(아래 단계적 도입안의 현재 단계가 shadow인지 실제 강등인지 구분하는 플래그)

### 질문 8 / 사용자 기대 방향에 대한 비판적 검토

사용자가 제시한 기본 방향(정적 seed 유지 + 강한 절대 컷 배제 + 반복 차단 이력 기반 동적 강등 + shadow → soft demotion → hard exclusion 단계적 도입)은 **현재 구조·실측과 정합적이며, 반박할 근거를 찾지 못했다.** 오히려 `src/AGENTS.md`의 "매매, 리스크, 주문 제출, 정합성, 스케줄러 경계는 명시적 근거와 테스트 없이 변경하지 않는다"는 원칙이 이 방향을 추가로 뒷받침한다 — `core` 유니버스 구성은 정확히 이 경계 안에 있고, TTL/decay 로직 자체가 이 코드베이스에 전례가 없는 신규 개념이므로, 첫 도입은 **shadow 관측(강등 후보만 로그로 기록, 실제 compose 결과에는 영향 없음) → soft demotion(강등은 하되 정렬 우선순위만 낮추고 완전 배제는 아님) → hard exclusion(day-level 완전 제외)**의 3단계로 blast radius를 점진적으로 넓히는 것이 타당하다.

**추천 결론**: 이번 설계 검토만으로 바로 구현 설계안(코드 diff 레벨)으로 넘어가기에는 이르다. 아래 두 가지가 먼저 필요하다:
1. **shadow 계측**: 위 1차 설계안의 규칙(예: "5영업일 중 80% 차단 또는 streak 3일")을 실제 최근 10영업일 데이터에 read-only로 적용해봤을 때, 실제로 몇 개 종목이 강등 후보가 되는지, 그 중 이후 며칠 안에 activity가 회복돼 재진입했을 종목이 얼마나 되는지(=오탐 가능성) 사전 확인이 필요하다 — 이건 새 정책 코드 없이 기존 두 분석 스크립트의 산출물만으로도 시뮬레이션 가능하다.
2. 위 시뮬레이션 결과가 "강등 대상이 소수·안정적"임을 뒷받침하면, 그다음에 shadow-only 코드(로그만 남기고 compose 결과는 바꾸지 않는 버전)를 구현 대상으로 논의하는 것이 순서에 맞다.

### 다음 턴 제안

**shadow-only 계측 시뮬레이션(read-only, 규칙 후보 검증)이 다음 턴으로 적합하다.** 구현 프롬프트로 바로 가기에는 규칙의 임계값(5일/80%/streak 3 등)이 아직 실측으로 검증되지 않았고, 추가 실측(예: 다른 계정, 더 긴 기간)이 필요하다고 보기에는 이미 확보한 10영업일 실측만으로도 규칙 후보를 시뮬레이션하기에 충분하다.

### 결정을 미뤄야 할 항목

- 정확한 임계값(N일, 비율 %, streak 수) — shadow 계측 없이 확정하면 근거가 약하다.
- 강등 지속 기간(당일만 vs 익일까지) — 재진입 조건과 함께 시뮬레이션 후 결정.
- 하이브리드(signal snapshot 보조 입력) 도입 여부 — v1에서는 배제, v2 검토 대상으로만 남긴다.
- 별도 서비스 분리 여부(`core_prefilter_service`) — 최소 구현(새 Step 함수)으로 시작하고, 복잡도가 커지면 그때 분리 검토.

## `core` 동적 강등 규칙 후보 shadow-only 시뮬레이션(2026-08-06 KST)

위 설계 검토가 제안한 다음 단계("shadow-only 계측 시뮬레이션")를 이번 턴에서 수행했다. **정책 구현이 아니다** — universe 선정/BUY 게이트 코드는 전혀 건드리지 않았고, 새 read-only 스크립트 `scripts/analysis/simulate_core_demotion_rules.py`로 과거 데이터에 규칙을 "재생"만 해봤다.

### 실행 개요

- 컨테이너: `agent_trading-app-1`
- 명령: `python3 scripts/analysis/simulate_core_demotion_rules.py --lookback-date-from 2026-06-29 --eval-date-from 2026-07-24 --date-to 2026-08-06 --account-alias 'Entrypoint Paper' --output-json /tmp/uag_demotion/result.json`
- 룩백 창 계산에는 `2026-06-29`~`2026-08-06`(보조 구간 포함) 데이터를 쓰되, 강등 이벤트 집계는 주 구간 `2026-07-24`~`2026-08-06`(10영업일)에서만 수행했다. `2026-06-19`~`2026-06-26`은 사용하지 않았다.
- `core` 종목 64개, 거래일 캘린더 29일(`2026-06-29`~`2026-08-06`) 수집

### 규칙 후보 정의와 결과

| 규칙 | 정의 | 강등 이벤트 | 고유 종목 | 강등 발생일 | 회복률(다음 등장일 통과 비율) |
|---|---|---|---|---|---|
| A1 | 최근 5영업일 중 등장일 대비 차단비율 ≥80% | 31 | 18 | 10 | 22.58%(7/31) |
| A2 | 최근 5영업일 중 등장일 대비 차단비율 ≥60% | 41 | 21 | 10 | 19.51%(8/41) |
| A3 | 연속 차단일수(streak) ≥3 | 11 | 6 | 6 | 27.27%(3/11) |
| A4 | 연속 차단일수(streak) ≥2 | 16 | 7 | 7 | 18.75%(3/16) |
| A5 | 최근 5영업일 중 차단일수 ≥3일(연속 아니어도 됨) | 18 | 6 | 8 | 33.33%(6/18) |
| A6(추가, 보수적 대조군) | 최근 5영업일 중 차단일수 ≥4일 | 10 | 4 | 5 | 50.00%(5/10) |

**"회복률" 해석 주의**: 강등이 day-level 제외(당일만, 익일 재평가)로 설계되어 있음을 전제하면, 이 수치는 "강등 정책이 틀렸다"는 뜻이 아니라 **"day-level 제외가 짊어지는 하루짜리 기회비용의 크기"**로 읽어야 한다. `relative_activity`는 원래 시점 민감성이 높은 지표라(계획 문서 상단 참고) 만성적으로 반복 차단되는 종목도 어느 날은 우연히 통과할 수 있다 — day-level 재진입 설계가 정확히 이 변동성을 흡수하기 위한 것이므로, 회복률이 0이 아니라는 사실 자체는 설계 의도와 배치되지 않는다. 다만 회복률이 높을수록 "하루 제외로 놓치는 정상 통과일"이 많다는 뜻이므로, 규칙 선택 시 참고 지표로는 유효하다.

### 종목별 상세(발췌)

- A1(가장 느슨): `001800`(5회, streak 최대5), `000810`(4회, streak 최대6), `001450`(3회, streak 최대4), `081660`(3회) 외 14개 종목 — 그 중 다수가 **flagged_day_count=1, max_streak_observed=1**로, 단 하루 등장에 그날 차단 1건만으로도 "5일 중 80%"(분모=1) 조건을 만족해버린 사례다(`042700`/`402340`/`329180`/`023530`/`196170`/`008930`/`090430`/`180640`/`483650`/`175330`/`009420` 등 11개 종목이 이 유형).
- A3(가장 엄격, streak): `000810`/`001800`/`000240`/`001450`/`138040`/`081660` 6종목 — 이전 원인분해(§`core` 반복 차단)에서 이미 만성 반복 차단 종목으로 식별했던 것들과 대부분 겹친다.
- `001450`(경계선 변동형, 사용자가 명시적으로 확인 요청): A1/A2/A3/A4/A5 모두에서 걸린다 — 다만 A3(streak≥3) 기준으로는 **`2026-07-24` 단 1회만** 걸렸고, 그 즉시 다음 등장일에 통과(`passed`)로 회복했다. 즉 "경계선 변동형까지 과도하게 잡는가"라는 질문에는 **부분적으로 그렇다** — A3/A5 같은 엄격한 규칙도 `001450`을 완전히 배제하지는 못한다(다만 A1/A2보다는 걸리는 빈도가 훨씬 낮다: 1회 vs 3회).

### 질문별 평가

**"쓸 만한지" 평가(질문 3)**:
- A1: **설계 결함 발견** — `appeared_in_window`(분모)에 최소 등장일수 하한이 없어, 단 하루 등장+그날 차단만으로도 "80% 비율" 조건이 성립한다. 결과적으로 "반복 실패"가 아니라 "단발 실패"까지 강등 후보로 잡는다(18개 종목 중 11개가 이 유형) — 이대로는 부적합, 최소 등장일수(예: ≥2 또는 ≥3) 조건을 추가해야 의미가 있다.
- A2: A1과 같은 결함을 가지면서 임계값만 낮아 더 넓게 잡는다(21개 종목) — 더 부적합.
- A3(streak≥3): 결함 없음(streak는 정의상 이미 "연속 등장+연속 차단"을 요구), 6개 종목으로 범위가 타이트하고 이전 원인분해와 잘 겹친다 — **가장 쓸 만하다.**
- A4(streak≥2): A3보다 느슨해 `111770` 1종목이 추가되지만 여전히 타이트(7종목) — 준수한 대안.
- A5(5일 창 내 차단일수≥3): streak를 요구하지 않아 "연속은 아니지만 자주 걸리는" 케이스도 잡을 수 있는 설계지만, 이번 표본에서는 A3와 종목 집합이 동일하게 나왔다(우연히 이 구간의 반복 차단이 대부분 연속형이었기 때문으로 보인다) — A3의 안전한 대안으로 병행 관찰할 가치가 있다.
- A6(5일 중≥4일): 가장 보수적(4종목)이지만, A3/A5의 부분집합에 가까워 별도 규칙으로 쓸 실익이 적다.

### 오탐 가능성 평가(질문 4)

- A1/A2는 위에서 확인했듯 **단발성 극저활동 종목까지 잡는 구조적 결함**이 있어, 이 상태로는 오탐 위험이 가장 크다.
- A3/A4/A5는 `001450` 사례처럼 "경계선 변동형"을 완전히 피하지는 못하지만, 걸리는 빈도가 낮고(1회) 걸린 즉시 다음 날 회복하는 패턴이 확인돼 — day-level 제외 설계라면 그 비용은 "하루 하나 놓침" 정도로 제한적이다.
- "강등했으면 아까운 종목이었을 가능성이 높은 패턴"은 A6(회복률 50%)에서 가장 두드러진다 — 다만 이는 A6이 가장 보수적으로 진짜 만성 종목만 잡기 때문에, 그 만성 종목들조차 하루하루 변동성이 크다는 사실을 보여줄 뿐, "강등 자체가 나쁘다"는 근거는 아니다(위 해석 주의 참고).

### 단계별 적합성 평가(질문 5)

| 규칙 | shadow 적합 | soft demotion 적합 | hard exclusion 적합 |
|---|---|---|---|
| A1/A2 | 결함 수정 전에는 비적합 | 비적합 | 비적합 |
| A3 | 적합 | 적합 | 이르다(오탐 사례 확인됨, `001450`) |
| A4 | 적합 | 적합(A3보다 넓게 관찰) | 이르다 |
| A5 | 적합 | 적합(A3 대안/대조군) | 이르다 |
| A6 | 적합(대조군으로 관찰용) | 과도하게 좁아 실효성 낮음 | 이르다 |

### 최종 제안(질문 6)

- **1차 shadow 계측 추천 규칙**: **A3(streak≥3)를 주 규칙으로, A5(5일 창 내 차단일수≥3)를 병행 관찰 규칙으로** 추천한다. 둘 다 결함이 없고, 이번 표본에서 동일한 6개 종목을 잡아 상호 검증이 가능하며, 더 긴 기간에서 둘이 갈라지는지 관찰하면 어느 쪽이 더 안정적인지 판단할 추가 근거가 쌓인다.
- **soft demotion 후보 규칙**: **A4(streak≥2)** — A3보다 한 단계 느슨해 더 많은 후보를 "정렬 순위만 낮추는" 수준으로 관찰하기에 적합하다(완전 배제가 아니므로 A3보다 넓게 잡아도 리스크가 낮다).
- **버려야 할 규칙**: **A1/A2를 현재 정의 그대로는 기각한다** — 최소 등장일수 하한 없이 "비율"만으로 판단하는 방식은 이번 시뮬레이션에서 명백한 결함(단발 실패를 반복 실패로 오판)이 드러났다. 재검토한다면 "최근 5영업일 중 등장일수≥3 AND 비율≥X%"처럼 최소 등장 조건을 추가한 개정판으로 다시 시뮬레이션해야 한다(이번 턴 범위 밖).
- **hard exclusion**: 어떤 규칙도 아직 이르다 — `001450` 같은 경계선 변동형이 가장 엄격한 A3에서도 완전히 걸러지지 않는 사례가 실측으로 확인된 이상, 완전 배제로 가려면 최소 1~2개월의 shadow 관측 후 재판단해야 한다.

### 이번 시뮬레이션만으로 바로 shadow 구현 가능한가

**A3(및 병행 A5)는 바로 shadow-only 코드 구현으로 넘어갈 근거가 충분하다.** 규칙 정의가 단순하고(streak 계산은 이미 `analyze_core_relative_activity_repeat_gap.py`가 유사 개념을 다루고 있어 코드화가 어렵지 않다), 결함이 없으며, 강등 후보 규모가 6종목/10일로 작아 초기 리스크가 낮다. 다만 **shadow 단계에서는 로그만 남기고 실제 compose 결과는 바꾸지 않아야 한다** — soft/hard 단계로의 전환은 이번 시뮬레이션 범위 밖이며 추가 실측(더 긴 기간, 다른 계정)을 거쳐야 한다.

## `core` 동적 강등 A3/A5 shadow-only 관측 구현(2026-08-06 KST, 착수)

위 시뮬레이션에서 결함이 없다고 확인된 A3(streak≥3)/A5(최근 5영업일 중 차단일수≥3)를 운영 코드에 **관측 로직으로만** 추가했다. **실제 exclusion/soft demotion은 아직 아니다** — universe 선정 결과(`compose()`/`compose_with_diagnostics()`의 반환 종목 목록·순서·source_type·cap)는 이 구현 전후로 완전히 동일하다.

### 구현 위치

`UniverseSelectionService.compose_with_diagnostics()`의 **Step 6(market overlay)과 Step 7(`_apply_exclusions`) 사이에 Step 6.5**로 `_evaluate_core_activity_demotion_shadow()`를 추가했다 — 이전 설계 검토(§`core` 동적 강등 레이어 설계 검토)가 권장한 위치 그대로다. 이 시점에는 Step 2/3(`held_position`/`reconciliation_overlay` override)이 이미 반영돼 있어, `source_type == CORE`로 여전히 남아 있는 심볼만 대상으로 판정한다 — `event_overlay`/`market_overlay`/`manual`로 override된 심볼은 자동으로 제외된다.

### 데이터 접근

`TradeDecisionRepository`에 `list_recent_core_eligibility_reasons(account_id, symbols, business_date_from, business_date_to)`를 신규로 추가했다(Postgres/in-memory 양쪽 구현). `source_type='core'` decision의 최종 `eligibility_reasons` 표본을 읽기만 하는 순수 SELECT 경로다 — 쓰기/마이그레이션 없음.

### 어디에 기록되는가

`MarketOverlayDiagnostics`에 `core_demotion_shadow_evaluated: bool`, `core_demotion_shadow_signals: tuple[CoreActivityDemotionShadowSignal, ...]` 필드를 추가했다(기존 UNIV-3 shadow 필드들과 같은 컨벤션). 각 신호에는 `symbol`, `matched_rules`(`"A3"`/`"A5"`), `streak`, `appearance_count_in_window`, `blocked_count_in_window`, `last_blocked_business_date`, `evaluation_date`가 담긴다. 강등 후보가 있으면 `logger.info()`로도 남긴다.

### compose 결과 불변 보장

- shadow 계산 함수는 `seen` 딕셔너리를 **읽기만** 하고 수정하지 않는다 — 반환값은 `MarketOverlayDiagnostics`에만 (`dataclasses.replace`로) 첨부된다.
- shadow 계산이 예외를 던져도 `try/except`로 감싸 compose 자체는 계속 진행된다(로그만 남기고 신호는 빈 튜플로 처리).
- `_apply_exclusions()`, `_apply_cap()`, 우선순위 정렬(Step 8) 등 실제 선정 로직은 전혀 건드리지 않았다.
- `accept backend-file src/agent_trading/services/universe_selection.py`가 매칭한 기존 테스트(`tests/services/test_universe_selection.py`, `tests/scripts/test_evaluate_market_overlay_runtime_validation.py`)가 이 변경 후에도 그대로 통과해, 기존 compose 시나리오의 결과가 바뀌지 않았음을 확인했다.

### 다음 단계

**아직 soft demotion으로 넘어가지 않는다.** 이번 shadow 관측을 실제 운영 데이터에서 일정 기간(예: 최소 몇 주) 쌓은 뒤, 강등 후보 수/오탐 패턴이 이전 시뮬레이션과 일치하는지 확인하고 나서 soft demotion(정렬 우선순위만 낮추는 단계) 전환 여부를 판단한다.

### 아직 검증하지 못한 가정

- Postgres 구현(`list_recent_core_eligibility_reasons`)에 대응하는 통합 테스트(`tests/repositories/test_postgres_trade_decisions.py`)는 이 환경에서 DB 인증 실패(`InvalidPasswordError`)로 실행하지 못했다 — 이는 이번 변경과 무관한 기존 환경 제약(호스트에서 라이브 DB 접속 자격 증명 불일치)이며, 사용자 승인 없이 DB 접속 설정을 바꾸지 않았다. 이 read-only SELECT 경로 자체가 실제 운영 DB에서 올바르게 동작하는지는 다음 실제 배포/운영 관측으로 재확인이 필요하다.

## `core` soft demotion 설계안(2026-08-06 KST)

A3/A5 shadow-only 관측이 운영 코드에 들어간 상태를 전제로, 그 다음 단계인 **soft demotion**(core seed 자격 박탈도, hard exclusion도 아니고 `core` 내부 정렬/우선순위만 조정)을 설계했다. **이번 절은 설계안이며 코드 변경은 없다.**

### 조사한 근거

- `_core_signal_sort_rank()`(`universe_selection.py:866-899`)가 이미 **정확히 이런 종류의 "core 내부 보조 정렬 키" 메커니즘**을 갖고 있다 — `(tier, -overall_score, symbol)` 튜플로 정렬하고, `tier`는 `CORE_SIGNAL_TIER_FRESH=0` / `STALE=1` / `MISSING=2`(`universe_selection_types.py:94-100`) 중 하나다. "신선도가 낮으면 완전히 빼지 않고 계층으로 하향시킨다"는 계약이 이미 이 코드에 있다 — soft demotion은 이 메커니즘에 새 계층을 하나 추가하는 것과 정확히 같은 모양이다.
- 이 `core_rank`는 Step 8 정렬에서 `(s.priority, core_rank.get(s.symbol, 0) if s.source_type == CORE else 0)`(`universe_selection.py:1118` 부근)로 쓰인다 — **`priority`는 전혀 건드리지 않고, `source_type == CORE`가 아니면 보조 키가 항상 `0`이라 다른 source_type과 무관**하다. 이는 사용자가 기대한 방향과 코드 구조가 이미 정확히 일치한다.
- 이 정렬은 `ctx.core_ranking_mode == CORE_RANKING_MODE_SIGNAL_SCORE`일 때만 적용되는데, `scripts/run_decision_loop.py:750`에서 **실제로 이 모드를 명시적으로 사용 중**임을 확인했다 — 즉 이 메커니즘은 이미 운영 경로에서 살아있다.
- `_apply_cap()`(`universe_selection.py:2033-2078`)은 **정렬이 끝난 순서 그대로** 순회하며 `core_cap`으로 자른다. `scripts/run_decision_loop.py:307`의 `DEFAULT_TRADING_UNIVERSE_CORE_CAP = 12`를 확인했다 — **`core_cap`은 실제로 12로 운영 중이며 None(무제한)이 아니다.** 이전 실측에서 관측한 "core 유니버스가 대체로 12개로 고정"된 것과 정확히 일치한다. 즉 core 후보 풀(전체 allowlist+membership 기준으로는 수십~80여 종목)이 매일 12개로 잘리는 구조이므로, **정렬 순서를 뒤로 미루는 것만으로도 실제로 그날 유니버스에서 빠질 수 있다** — soft demotion이 공허한 조치가 아니라는 근거다.

### 질문 1~2 — soft demotion 정의와 구현 위치

**가장 자연스러운 정의: `_core_signal_sort_rank()`의 기존 tier 메커니즘에 새 tier를 하나 추가하는 것.** 별도 penalty score나 새 정렬 파이프라인을 만들 필요가 없다 — 이미 있는 "계층으로 하향" 계약을 그대로 재사용한다.

| 구현 위치 후보 | 장점 | 단점 | 권장 |
|---|---|---|---|
| `_core_signal_sort_rank()` 내부에 tier 추가 | 기존 메커니즘 그대로 재사용, diff 최소, 다른 source_type 자동 격리(이미 `if s.source_type==CORE else 0`로 보장됨) | freshness 개념과 "반복 실패" 개념이 하나의 tier 축에 섞인다(아래 참고) | **권장** |
| sort 직전 별도 `core_rank` 보정 레이어 | 개념적으로 freshness와 demotion을 분리 | 정렬 파이프라인이 두 단계로 늘어나고, 두 랭크를 어떻게 합성할지(더하기? 우선순위?) 새 규칙이 필요 — 복잡도 증가 | 비권장(1차안으로는) |
| `SelectedSymbol.priority`를 core 내부에서만 미세 조정 | — | `priority`는 held/reconciliation/event/market/manual을 포함한 **전역 우선순위**다. core만 건드릴 방법이 없어 다른 source_type을 침범할 위험이 구조적으로 존재 — 사용자가 명시적으로 금지한 방향과 충돌 | **기각** |

freshness와 demotion을 같은 tier 축에 섞는 것에 대한 우려는 실재하지만, 완화 가능하다 — **demotion tier를 별도 정수 상수(`CORE_SIGNAL_TIER_DEMOTED`)로 두고, `MISSING`보다 더 나쁜 최하위 tier로 배치**하면 두 개념이 값 하나로 뭉개지지 않고 여전히 구분 가능한 계층으로 남는다.

### 질문 3 — 실제로 영향이 나는가

- `core_cap`이 `None`이면(무제한) soft demotion은 **순서만 바꾸고 실제 포함 여부는 바꾸지 않는다** — 관측 가치는 있지만 실질 효과는 없다.
- 그러나 위에서 확인했듯 **운영 기본값은 `core_cap=12`로 바인딩되어 있다.** core 후보 풀 크기(`APPROVED_CORE_UNIVERSE_SYMBOLS` + membership, 수십~80여 종목)가 매일 12개로 잘리므로, 정렬 순서 변경은 **실제로 그날 어떤 종목이 유니버스에 들어오는지를 바꿀 수 있는 실질적 개입**이다. `max_cap=30`(기본값)은 held 등을 포함한 전체 상한이라 core_cap보다 항상 느슨하게 작용한다 — 실질적 절단은 `core_cap`이 담당한다고 봐도 된다.
- 결론: **soft demotion은 장식이 아니다.** 이 사실 자체가 "왜 처음부터 강하게 반영하면 안 되는가"의 근거이기도 하다 — 즉시 실제 유니버스 구성을 바꿀 수 있으므로, 오탐 시 대가가 결코 작지 않다.

### 질문 4 — A3/A5를 입력으로 쓰는 방식 비교

| 방식 | 장점 | 단점 | 권장 |
|---|---|---|---|
| A3 매칭 시에만 demotion tier 부여, A5 단독은 관측만(미반영) | 가장 보수적, A3는 이미 "결함 없음"으로 확인된 규칙, A5는 여전히 병행 관찰 단계 | A5가 잡는 (A3와 겹치지 않는) 케이스는 이번 단계에서 효과가 없음 | **1차안으로 권장** |
| A3=강한 페널티(최하위 tier), A5=약한 페널티(STALE과 MISSING 사이) | A5도 어느 정도 반영 | tier 3단계 이상 관리 필요, 복잡도 증가, A5의 오탐 검증이 아직 A3만큼 축적되지 않음 | 2차안(추후 검토) |
| A3/A5 매칭 개수 기반 penalty score(연속형) | 세밀한 조정 가능 | tier 메커니즘과 안 맞음(연속 점수를 새로 도입해야 함), "최소 개입" 원칙과 배치, 설명이 더 복잡해짐 | 기각 |
| `demotion_active` boolean만 사용(A3 or A5 매칭 여부만 보고 강도 구분 없음) | 가장 단순 | 001450류 오탐 위험을 규칙별로 차등화할 수 없음 | 기각 |

### 질문 5 — 보수적 설계 강도

`001450`(경계선 변동형)이 가장 엄격한 A3에서도 1회 걸렸다가 바로 다음 날 회복한 사례(이전 시뮬레이션 §참고)를 감안하면, 아래가 가장 보수적인 조합이다:

- **완전 맨 뒤가 아니라 "MISSING보다 한 단계 더 아래"** — MISSING(신선도 정보 자체가 없음)보다도 나쁜 취급을 하되, 그 안에서는 여전히 `overall_score` 내림차순 2차 정렬이 살아 있어 "같은 demotion tier 안에서도 신호가 나은 종목이 앞선다."
- **하루 1회 평가, 자동 재진입** — 이미 shadow 구현이 매 compose마다(사실상 매일 freeze 시점에 한 번) 재평가하므로, 조건을 벗어나면 다음 날 즉시 demotion tier에서 빠진다. 별도 냉각 기간(cooldown)을 추가로 두지 않는 것이 이전 시뮬레이션의 "day-level 재진입" 전제와 일치한다.
- **A3만 트리거, A5 단독은 미반영**(질문 4 권장안과 동일) — `001450` 같은 케이스가 A5에는 더 자주 걸리므로, A5를 아직 반영하지 않는 것 자체가 오탐 방어선이다.

### 질문 6 — 관측 메타데이터

기존 `CoreActivityDemotionShadowSignal`(shadow 구현에서 이미 추가됨)에 있는 필드를 그대로 재사용하고, soft demotion 반영 여부만 추가하면 충분하다:

- 이미 있음: `matched_rules`, `streak`, `appearance_count_in_window`, `blocked_count_in_window`, `last_blocked_business_date`, `evaluation_date`
- 추가 필요: `demotion_applied: bool`(A3 매칭 여부, 즉 실제로 tier가 내려갔는지), `assigned_tier`(부여된 tier 값 — 관측 시 freshness tier와 구분 가능해야 함)
- **불필요**: `demotion_strength`(연속 강도 개념은 기각됐으므로), `prior_core_rank`/`adjusted_core_rank`(정렬 결과 전체를 비교하려면 compose 함수 바깥에서 별도로 재구성 가능 — diagnostics에 매 compose마다 전체 랭킹 스냅샷을 남기는 것은 과하다)

### 질문 7 — 단계적 도입 순서

권장 순서: **① 설계 확정(이번 턴) → ② soft demotion shadow(순위를 실제로 바꾸지 않고, "만약 반영했다면 어떻게 바뀌었을지"만 계산·로그) → ③ soft demotion 실제 반영 → ④(그 이후 판단) hard exclusion 검토.**

②를 건너뛰고 바로 ③으로 가면, "정렬이 실제로 바뀐 뒤에야" 오탐 여부를 알 수 있다 — 이미 `core_cap=12`가 실질적 절단을 한다는 게 확인된 이상 위험이 실재한다. ②는 코드로는 "A3 매칭 시 가상의 demotion tier를 적용했을 때 core_rank가 어떻게 달라지는지"를 계산해 로그/diagnostics에만 남기고, 실제 정렬 키 계산에는 아직 반영하지 않는 단계다 — shadow 구현 때 이미 확립한 "관측 먼저" 원칙을 정렬에도 그대로 적용한다.

### 사용자 기대 방향에 대한 검토

사용자가 제시한 방향(`priority` 불변, 다른 source_type 불가침, core 내부 보조 정렬 키만 추가, A3 강하게/A5 약하게, rank 조정 영향 관측부터 시작)은 **`_core_signal_sort_rank()`의 실제 코드 구조와 정확히 일치하며 반박 근거를 찾지 못했다.** 다만 한 가지는 더 보수적으로 조정을 권한다 — "A5도 약한 페널티로 반영"보다는 **A5는 이번 단계에서 아직 반영하지 않는(관측만 유지) 쪽이 더 안전**하다. 이유: A5는 여전히 "병행 관찰 규칙"(1차 shadow 계측 시뮬레이션 결론)일 뿐, A3만큼 결함 없음이 반복 검증되지 않았고, `core_cap=12`가 실질적 절단을 한다는 사실이 확인된 이상 첫 반영 범위는 가장 신뢰도 높은 신호(A3) 하나로 좁히는 것이 맞다.

### 권장 1차 설계안 요약

- `universe_selection_types.py`에 `CORE_SIGNAL_TIER_DEMOTED = 3`(MISSING=2보다 나쁜 최하위)을 추가한다.
- `_core_signal_tier()` 또는 `_core_signal_sort_rank()`의 `_key()`에서, 해당 심볼이 최근 shadow 판정(`matched_rules`에 `"A3"` 포함)이면 freshness tier 계산 결과를 무시하고 `CORE_SIGNAL_TIER_DEMOTED`를 반환한다.
- A5 단독 매칭은 이번 단계에서 tier에 영향을 주지 않는다(계속 관측만).
- 같은 tier 안에서는 기존과 동일하게 `-overall_score`, `symbol` 순으로 2차 정렬한다(demotion됐다고 완전히 무작위가 아니라, 그 안에서도 신호 좋은 종목이 우선한다).
- `priority`, 다른 source_type의 정렬/포함은 전혀 건드리지 않는다.

### hard exclusion과의 경계

soft demotion은 **"유니버스에서 빼는 것"이 아니라 "core 내부에서 뒤로 보내는 것"**이다 — `core_cap`이 헐거우면(그날 core 후보가 12개 미만이면) demotion되어도 여전히 포함된다. hard exclusion(완전 배제, cap과 무관하게 항상 빠짐)은 이번 설계 범위가 아니며, soft demotion을 충분히 관측한 뒤(②③ 단계를 거친 뒤) 별도로 재검토해야 한다.

### 아직 결정 유보가 필요한 항목

- `CORE_SIGNAL_TIER_DEMOTED`를 MISSING(2)보다 나쁘게 둘지, STALE과 MISSING 사이에 둘지 — 이번 문서는 "MISSING보다 나쁨"을 권장했지만, 이는 "확인된 반복 실패가 데이터 결측보다 더 나쁜 신호"라는 판단 하나의 근거일 뿐 — soft demotion shadow(②) 단계에서 실제 순위 변화를 보고 재확인할 수 있다.
- A5를 언제 A3와 함께(또는 A3보다 약하게) 반영할지 — 이번 문서는 "아직 아니다"로 결론냈다.
- soft demotion shadow(②) 단계의 관측 기간을 얼마나 둘지(예: 1~2주) — 다음 턴에서 구체화한다.

## `core` soft demotion 실제 구현(2026-08-07 KST)

위 설계안을 실제 운영 코드에 반영했다. **hard exclusion이 아니다** — `core` seed 자격은 그대로 유지되고, `core` 내부 정렬 tier만 조정된다. Step ②(soft demotion shadow, 순위 계산만 하고 반영하지 않는 중간 단계)는 건너뛰고 곧바로 A3 반영으로 진행했다 — 이유는 A3가 이미 shadow-only 관측(PR #178)과 시뮬레이션(PR #174) 두 단계 모두에서 결함 없음이 확인됐고, `_core_signal_sort_rank()`가 이미 "계층으로 하향" 계약을 갖고 있어 새 tier 추가가 기존 메커니즘을 그대로 재사용하는 최소 변경이었기 때문이다.

### 무엇이 바뀌었는가

- `universe_selection_types.py`: `CORE_SIGNAL_TIER_DEMOTED = 3`(MISSING=2보다 나쁜 최하위 tier) 추가. `CoreActivityDemotionShadowSignal`에 `demotion_applied: bool`, `assigned_tier: int | None` 필드 추가.
- `universe_selection.py`:
  - `_core_signal_sort_rank()`에 `demoted_symbols: frozenset[str] = frozenset()` 파라미터를 추가 — 이 집합에 속한 심볼은 freshness tier 계산과 무관하게 `CORE_SIGNAL_TIER_DEMOTED`를 부여받는다(같은 tier 안에서는 여전히 `overall_score` 내림차순 2차 정렬). 빈 집합(기본값)이면 이전과 100% 동일하다.
  - `_evaluate_core_activity_demotion_shadow()`가 만드는 각 신호에 `demotion_applied = "A3" in matched_rules`, `assigned_tier = DEMOTED if demotion_applied else None`를 채운다.
  - Step 8 정렬 호출부가 Step 6.5에서 **이미 계산된** `demotion_signals`에서 `demotion_applied=True`인 심볼만 뽑아 `_core_signal_sort_rank(..., demoted_symbols=...)`로 넘긴다 — 같은 판단(A3 매칭 여부)을 중복 계산하지 않고 shadow 관측과 soft demotion 반영이 동일한 단일 계산 결과를 공유한다.

### A3만 반영하고 A5는 아직 반영하지 않는 이유

A5(최근 5영업일 중 차단일수≥3, 비연속 허용)는 shadow 시뮬레이션에서 `001450`(경계선 변동형) 같은 케이스를 A3보다 더 자주 잡는 경향이 확인됐다 — A3는 "연속" 조건이라 우연한 산발적 차단에는 반응하지 않지만, A5는 반응할 수 있다. 첫 실제 반영은 오탐 위험이 가장 낮은 신호(A3) 하나로 좁히는 것이 계획 문서의 일관된 결론이다. `CoreActivityDemotionShadowSignal.matched_rules`에는 A5도 계속 기록되므로 관측은 끊기지 않는다.

### 다른 source_type을 침범하지 않는 이유(코드 근거)

- `demoted_symbols`는 `_core_signal_sort_rank()`의 `core_symbols`(이미 `source_type == CORE`로 필터링된 목록) 안에서만 참조된다.
- Step 8 정렬 키 `core_rank.get(s.symbol, 0) if s.source_type == SourceType.CORE else 0`는 기존 코드 그대로 유지 — CORE가 아닌 심볼은 보조 키가 항상 `0`이라 이번 변경으로 전혀 영향받지 않는다.
- `SelectedSymbol.priority`, `_apply_exclusions()`, `_apply_cap()`은 이번 구현에서 손대지 않았다.

### soft demotion 실패 시 fallback

- Step 6.5의 `try/except`가 그대로 유지되어, shadow 평가/이력 조회가 실패하면 `demotion_signals = ()`가 되고, 그 결과 `a3_demoted_symbols`도 빈 집합이 되어 **soft demotion 반영 자체가 자동으로 무효화되고 기존 정렬로 조용히 되돌아간다**(로그는 남는다). 별도의 추가 예외 처리를 두지 않았다 — 이미 있는 안전장치가 그대로 이 경로도 보호한다.

### 검증

- 신규 단위 테스트 추가(`tests/services/test_universe_selection.py::TestCoreRankingModeSignalScore::test_demoted_symbols_sort_below_missing_regardless_of_score`): `demoted_symbols`가 비어 있으면 기존 정렬과 동일하고, 특정 심볼을 demote하면 최고 점수라도 MISSING보다 뒤로 밀리는 것을 직접 확인. `tests/services/test_universe_selection.py` 전체 115개 통과.

### 다음 단계

운영 관측을 일정 기간(1~2주 권장, §soft demotion 설계안 참고) 쌓은 뒤, 실제로 얼마나 자주 A3 강등이 발생했는지, 강등된 심볼이 이후 어떻게 됐는지(회복/지속)를 확인하고 나서 **A5 반영 여부와 강도**를 재판단한다. hard exclusion은 이번 구현 이후에도 여전히 범위 밖이다.

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
