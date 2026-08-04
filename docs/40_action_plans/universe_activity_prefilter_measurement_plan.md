# Universe 활동성 사전 필터 보정 — 실측 분석 실행 계획

## 목적

이 문서는 유니버스 선정 단계에서 활동성 부족 후보를 얼마나 더 일찍 걸러야 하는지 다일자 실측으로 판단하기 위한 실행 계획이다.

핵심 질문은 다음 하나다.

- 현재 `pre-AI` 단계의 `활동성 부족` 차단이 유효하다는 전제 아래, 어떤 활동성 기준을 유니버스 단계로 당겨와야 **후보 손실을 최소화하면서** 불필요한 BUY 평가 대상을 줄일 수 있는가

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

- [ ] 최근 `20~30` 거래일의 대상 실행 집합을 확정한다.
- [ ] 실행 시점을 `pre_open`, `open_30m`, `intraday`, `after_close` 버킷으로 분류한다.
- [ ] 실행 단위별 유니버스 종목과 `source_type`을 복원한다.
- [ ] 실행 단위별 `pre-AI` 차단 사유를 복원한다.
- [ ] 실행 단위별 signal feature 지표를 조인한다.
- [ ] market overlay 활성/비활성 여부를 분리 기록한다.

완료 기준:

- 분석 대상 실행 수와 날짜 범위가 확정되어 보고된다.
- 각 실행 단위에 대해 `symbol`, `source_type`, `activity_block_reason`, signal feature 주요 지표가 연결된다.

### P1 — baseline 지표 계산

목표: 현행 로직에서 `활동성 부족` 차단이 얼마나 자주, 어떤 이유로, 어떤 source에서 발생하는지 정량화한다.

- [ ] 실행 단위별 `universe_count`를 계산한다.
- [ ] 실행 단위별 `new_buy_candidate_count`를 계산한다.
- [ ] 실행 단위별 `pre_ai_activity_block_count`와 비율을 계산한다.
- [ ] `eligibility_low_average_volume`, `eligibility_low_turnover`, `eligibility_low_relative_activity` 사유별 건수를 계산한다.
- [ ] `source_type`별 차단 비율을 계산한다.
- [ ] 시간대별 차단 비율을 계산한다.

완료 기준:

- baseline `활동성 부족` 차단 비율이 날짜별/시간대별/source_type별로 보고된다.
- 차단 사유 3종의 분포가 함께 보고된다.

### P2 — universe 사전 필터 가설 비교

목표: 어떤 사전 필터를 universe 단계로 당길 때 차단 감소 대비 후보 손실이 가장 작은지 비교한다.

- [ ] 가설 A: `average_volume_20d >= 3000` 하한을 시뮬레이션한다.
- [ ] 가설 B: `average_turnover_20d >= 50_000_000` 하한을 시뮬레이션한다.
- [ ] 가설 C: A+B 동시 적용을 시뮬레이션한다.
- [ ] 가설 D: C를 `source_type=core`에만 적용하는 예외 정책을 시뮬레이션한다.
- [ ] 가설 E: `relative_activity >= 1.10`를 shadow-only로 측정한다.
- [ ] 각 가설의 차단 감소량과 후보 손실률을 비교한다.

완료 기준:

- 최소 `5`개 비교군의 결과가 같은 기준표로 비교된다.
- 차단 감소량, 후보 손실률, 효율 점수가 모두 보고된다.

### P3 — 권고안 도출

목표: 바로 구현할 후보와 shadow-only 유지 후보를 구분한다.

- [ ] `core` 중심 예외 정책이 필요한지 판단한다.
- [ ] `held_position`, `reconciliation_overlay`, `event_overlay`, `manual` 예외 유지 여부를 정리한다.
- [ ] `relative_activity`를 universe에 바로 반영하지 않을 근거를 정리한다.
- [ ] 1순위 권고안과 보류안을 구분한다.

완료 기준:

- `권장안`, `보류안`, `기각안`이 각각 최소 1개 이상 정리된다.
- 왜 그 판단을 했는지 차단 감소량/손실률 근거가 붙는다.

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
