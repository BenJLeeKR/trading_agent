# SPPV-3 OOS 일봉 cache 일 1회 자동 갱신 배치 — 설계 문서(2026-08-25 KST, read-only 조사 전용)

## 0. 이 문서의 성격

- 이번 턴은 **설계·read-only 조사만** 수행한다. 코드 구현, GitHub Actions 워크플로 수정,
  cron 등록, 컨테이너 재기동, 외부 KIS API 호출, DB write, 주문 제출은 **하지 않았다**.
- 근거는 저장소 내 코드/문서 조사(Explore 서브에이전트 위임 + 직접 확인)로만 수집했다.
  실측(실제 KIS 응답 관찰)이 필요한 항목은 "미확정"으로 명시하고 보수적 후보를 제시한다.
- 이 문서가 확정하는 것은 **아키텍처와 실행 시각 후보**이며, 실제 구현·배치 등록·외부
  API 호출은 사용자 승인 후 별도 구현 턴에서 진행한다(§6 참조).

## 1. 배경

- `scripts/analysis/build_sppv3_oos_bar_cache.py`(2026-08-24, PR #347)로 OOS bar cache
  수집 도구가 이미 존재하고, 1회 수동 실행으로 88종목 성공(`logs/_bars_cache_core87_3y_2026-08-24/`,
  `ready_for_oos=true`)했다.
- `scripts/analysis/measure_sppv3_oos_candidate_performance.py`(2026-08-24, PR #348)로
  OOS 성과 계산 도구도 존재하며, 현재 표본(27거래일)은 `PENDING_INSUFFICIENT_OOS_SAMPLE`이다.
- 다음 공식 판정(§36.3 Go/Watch/Hold/No-Go)을 받으려면 OOS 표본이 시간이 지나며 계속
  누적돼야 하는데, 지금까지는 사람이 수동으로 스크립트를 실행해야만 표본이 늘어난다.
  **이 배치가 자동화하는 것은 표본 축적 그 자체이며, 어떤 정책 판단도 자동화하지 않는다.**

## 2. 질문별 조사 결과

### 2.1 KRX 정규장 종료와 KIS 일봉 확정 시각 (사실 / 미확정 분리)

**사실**
- 저장소 코드가 명시하는 정규장 마감 경계값은 두 곳에서 발견된다.
  - `scripts/run_ops_scheduler.py:182` — `MARKET_CLOSE = dtime(15, 30, 30)`
  - `.github/workflows/harness.yml:329` 부근 — `market_hours_guard`가 "hour_min_kst >= 0900 && < 1530"
    (09:00:00~15:29:59 KST를 "장중"으로 판정)
  - 이 두 값은 배포 가드/스케줄러 운영 목적으로 정의된 근사치이며, KRX 공식 정규장
    마감 규정 자체를 검증한 출처는 아니다.
- `scripts/run_ops_scheduler.py:111` — 기존 signal feature batch가 `DEFAULT_SIGNAL_FEATURE_BATCH_TIME
  = dtime(20, 10)`(20:10 KST)에 실행되도록 이미 설계되어 있다. 이는 "장 마감 후 몇 시간
  지나야 안전하다"는 기존 운영 판단의 유일한 코드상 선례다.
- KIS `inquire_daily_itemchartprice` 클라이언트 코드(`src/agent_trading/brokers/koreainvestment/rest_client.py`)에는
  당일 일봉이 "언제 확정되는지"에 대한 주석/문서화된 가정이 **없다**.
- 저장소 전체를 `일봉 확정`, `EOD`, `장마감`, `당일 데이터` 등 키워드로 검색한 결과,
  KIS가 당일 일봉을 몇 시에 확정 제공하는지에 대한 실측 기록은 발견되지 않았다.

**결론: 미확정.** 정확한 확정 시각은 실측하지 못했다.

**보수적 후보 시각 (근거를 함께 명시)**
- KRX 정규장 마감(코드상 근사치 15:30 KST) 이후, 시간외 단일가/시간외 종가 매매
  세션(통상 15:30~18:00 국내 관행)까지 고려하면, 당일 일봉이 최종 확정되지 않았을
  가능성이 있는 구간은 최소 15:30~16:00까지로 보수적으로 잡는다.
- 기존 signal feature batch(20:10 KST)가 이미 "장 마감 후 충분히 늦은 시각"이라는
  운영 판단의 전례이므로, OOS 수집도 **최소 20:10 KST 이후**로 잡는 것이 안전하다.
- 최종 권장 시각은 §2.2에서 결정한다.

### 2.2 장중 잡과 충돌하지 않는 KST 배치 시각 후보

**기존 스케줄러 잡 시간대(`scripts/run_ops_scheduler.py`, KST)**
| 시각 | 잡 |
|---|---|
| 04:50 | instrument master sync |
| 05:05 | instrument status snapshot |
| 08:00~08:50 | pre-market |
| 08:50~15:30:30 | 장중 decision loop / snapshot sync / post-submit sync(반복) |
| 15:30:30~16:30 | after-hours(EOD snapshot, fill-sync) |
| 20:10 | signal feature batch(1회) |

**배치 시각 후보**

| 후보 | 시각(KST) | 근거 | 위험 |
|---|---|---|---|
| A | 20:30 | signal feature batch(20:10) 직후 20분 여유, 장중 주문 경로와 6시간 이상 이격 | 20:10 batch가 지연되면 겹칠 수 있음(완료 확인 없이 시각만 겹치지 않게 하는 설계) |
| B(권장) | 21:00 | signal feature batch 완료를 충분히 지나고, KIS 서버 측 부하가 낮은 심야 시간대 진입 전, 익일 04:50 master sync와도 충분히 이격 | 없음 — 가장 보수적 |
| C(기각) | 16:00(장마감 직후) | 표본을 가장 빨리 확보 | §2.1의 "미확정" 리스크 그대로 노출, EOD 잡(~16:30)과 겹침 |

**권장안: 21:00 KST 1회.** 이유: (1) §2.1의 확정 시각 불확실성에 대해 가장 큰 안전 여유를
확보, (2) 기존 20:10 signal feature batch와 시간상 완전히 분리되어 리소스/락 경합이
발생하지 않음, (3) 익일 04:50 master sync와도 충분히 이격.

### 2.3 실행 주체: 기존 `ops-scheduler` vs 별도 one-shot 분리

| 기준 | `ops-scheduler`에 통합 | 별도 one-shot 컨테이너/워크플로 |
|---|---|---|
| 주문 경로와의 격리 | 같은 프로세스·같은 컨테이너(`docker-compose.yml:268-330`) — 장애 시 주문 스케줄러 자체에 영향 가능 | 완전 격리, crash가 나도 주문 스케줄러 무관 |
| 재시도 | 기존 프로세스의 idle/heartbeat 로직에 얹혀야 하고, 실패 시 프로세스 전체 재시작 전에는 재시도 어려움 | 독립적인 재시도 정책(예: exit code 기반 워크플로 재실행) 설계 자유 |
| 로그 보존 | 기존 ops-scheduler 로그 스트림에 섞임 | 독립 로그 스트림, SPPV 연구 전용으로 분리 보존 쉬움 |
| 장애 영향 | 배치 코드 버그가 `ops-scheduler` 컨테이너 크래시로 번지면 실주문 경로에 영향 가능(같은 `restart: unless-stopped` 컨테이너) | 배치 실패가 주문 스케줄러에 전혀 영향 없음 |
| 배포 단위 | 이미 배포된 이미지 재사용, 별도 배포 불필요 | 별도 컨테이너/워크플로 정의·배포 필요(운영 표면 증가) |
| KIS 자격증명 | 이미 `KIS_LIVE_INFO_*`가 주입되어 있어 재사용 가능(§37.4 안전장치: `_build_kis_live_quote_client`는 `account_number=""`로 구조적 read-only) | 동일 자격증명을 별도 주입해야 함(관리 지점 증가) |
| 운영 관행 부합 | `ops_scheduler_canonicalization_2026-05-16.md`가 "canonical entrypoint 단일화"를 명시 — 이 원칙과 충돌 | 연구용 read-only 배치는 애초에 이 canonicalization 대상이 아님(주문/포지션 관련 잡이 아니므로) |

**권장: 별도 one-shot(주문 스케줄러와 프로세스/컨테이너 분리).** 이유: SPPV-3 OOS 수집은
연구 목적의 read-only 배치이며, 매매 로직과 동일한 장애 도메인에 묶일 이유가 없다.
`ops_scheduler_canonicalization_2026-05-16.md`의 "canonical entrypoint 단일화" 원칙은
주문/포지션 관련 운영 잡을 대상으로 하며, 이 배치는 그 범주 밖이다. 다만 KIS 자격증명은
`agent_trading-ops-scheduler` 컨테이너가 이미 보유(PR #347에서 실측 검증)하고 있으므로,
같은 자격증명을 **별도 one-shot 실행**(예: `docker exec` 기반 스케줄 잡, 또는 동일
이미지의 별도 컨테이너에 같은 env-file을 주입)에 재사용하되 프로세스/장애 도메인은
분리하는 방식을 권장한다. 구체적 실행 메커니즘(systemd timer / cron on host / GitHub
Actions self-hosted runner 등)은 다음 구현 턴에서 사용자와 함께 확정한다(§6 목록 참조).

### 2.4 cache 저장 전략: 매일 신규 디렉토리 vs append-only

**현재 코드 구조 사실(`scripts/analysis/build_sppv3_oos_bar_cache.py`)**
- `cache_run_date = now_kst.strftime("%Y-%m-%d")`; `new_cache_dir = f"{NEW_CACHE_DIR_PREFIX}{cache_run_date}"`
  (L588-589) — 실행 시점의 KST 날짜로 디렉토리명이 결정되며, 실행할 때마다 새 디렉토리가 생성된다.
- `collect_one_symbol`은 매번 고정된 `BASE_CACHE_DIR`(`2026-07-14`)만 base로 읽는다(L437) —
  전날 만든 `_bars_cache_core87_3y_<어제날짜>/`는 base로 보지 않는다.
- `measure_sppv3_oos_candidate_performance.py`는 `--oos-cache-dir`를 CLI 인자로 직접 받고,
  `EXPECTED_BASE_CACHE_ID/PATH`는 `2026-07-14`로 하드코딩되어 있다(L82-84) — 실행할 때마다
  특정 날짜 디렉토리를 명시적으로 가리켜야 한다.

**비교**

| 기준 | 매일 신규 디렉토리(현행 유지) | 단일 append-only cache |
|---|---|---|
| base cache 불변 원칙 | 그대로 준수(base cache는 여전히 손대지 않음) | 그대로 준수 가능(병합 로직은 이미 "기존값 유지, 신규값 버림" 정책 보유, `overlap_with_base_discarded`) |
| manifest/provenance | 디렉토리마다 독립 `manifest.json` — 특정 시점 재현 시 그 디렉토리만 보면 됨 | 하나의 `manifest.json`을 계속 갱신 — 과거 시점 재현이 어려움(덮어써짐) |
| checksum/재현성 | 특정 날짜 실행 결과가 통째로 보존되어 사후 재현·회귀비교 쉬움 | 최신 상태만 남아 "그 시점에 무엇이 있었는지" 재구성이 어려움 |
| 구현 난이도 | 이미 구현됨, 변경 불필요 | 디렉토리명 고정/`latest` 링크 도입, `load_base_bars`가 누적본을 읽도록 변경 필요 — 신규 구현 필요 |
| 저장 공간 | 매일 신규 디렉토리 누적 → 디스크 사용량 증가(단, 일봉 87종목 규모라 절대량은 작음) | 디렉토리 1개로 유지, 공간 효율 좋음 |
| `measure_sppv3_oos_candidate_performance.py`와의 정합성 | 이미 `--oos-cache-dir`로 특정 날짜를 가리키는 현재 계약과 정합 | 이 도구도 "최신 디렉토리 자동 탐색" 또는 "고정 경로 사용"으로 수정 필요 |

**권장: 매일 신규 디렉토리 방식을 유지하되, 배치가 “최신 디렉토리를 가리키는 안정적인
방법”만 추가한다.** append-only로 바꾸는 것은 재현성·회귀비교 이점을 잃는 대가가 구현
난이도 절감보다 크다고 판단한다. 대신 다음 두 가지 보완만 추가한다.
1. 매일 실행 시 그날 디렉토리 전체를 새로 만들되(현행), 성공 시에만 `logs/_bars_cache_core87_3y_latest`
   심링크(또는 `latest_manifest_pointer.json` 같은 작은 포인터 파일)를 그날 디렉토리로 갱신한다.
   실패한 날은 포인터를 갱신하지 않아, "가장 최근 성공한 완전한 cache"를 항상 안전하게
   가리킬 수 있다.
2. `measure_sppv3_oos_candidate_performance.py`의 `--oos-cache-dir`는 그대로 명시적 인자로
   유지하되(암묵적 최신 탐색은 오탐 위험), 포스트프로세싱 단계(§2.6)에서만 포인터 파일을
   읽어 "가장 최근 성공 cache"를 자동으로 넘겨준다.

### 2.5 실패 모드 설계 (중복 실행 / 휴장일 / KIS 지연 / 부분 수집 실패 / 당일 데이터 미확정)

| 상황 | 설계 |
|---|---|
| 중복 실행(동일 KST 날짜에 두 번 트리거됨) | 그날 디렉토리(`_bars_cache_core87_3y_<date>`)가 이미 존재하고 `manifest.json.ready_for_oos==true`이면 즉시 스킵(exit 0, "이미 완료" 로그만 남김) — KIS 재호출 방지. 존재하지만 `ready_for_oos!=true`(이전 실행이 실패로 끝남)이면 재시도 허용. |
| 휴장일 | 기존 `MarketSessionProvider.is_trading_day()`(`src/agent_trading/services/market_session.py`)를 그대로 재사용해 실행 전에 확인. 휴장일이면 수집을 건너뛰고 "휴장일 스킵" 상태만 기록(실패 아님). |
| KIS 지연/타임아웃 | 종목별 fetch는 이미 개별 `fetch_status`(`ok`/실패)로 관리됨(§2.4 근거). 배치 wrapper 차원에서 전체 타임아웃(예: 30분)을 두고, 초과 시 그때까지 수집된 부분 결과로 manifest만 생성 후 `ready_for_oos=false`로 명확히 표시. |
| 부분 수집 실패(일부 종목만 실패) | 기존 `determine_ready_for_oos()`가 이미 "전 종목 `fetch_status=ok`여야 `ready_for_oos=True`" 정책을 갖고 있음(§2.3 근거) — 그대로 재사용. 실패 종목 리스트를 manifest와 알림(§2.7)에 명시. |
| 당일 데이터 미확정(그날 일봉이 아직 없거나 이상치) | KIS 응답에 그날 날짜가 없으면 해당 종목은 "해당일 데이터 없음"으로 처리하고 `ready_for_oos` 판정에서 그 거래일을 "미확정"으로 별도 표시(억지로 채우거나 이전 값을 복제하지 않는다 — 불변식 위반 금지). |

공통 원칙: **"성공"으로 가장하지 않는다.** 부분 실패/미확정 상태는 `ready_for_oos=false`
또는 별도 `notes` 필드로 항상 명시적으로 드러나야 하며, 배치 wrapper의 exit code도
이 상태를 반영해야 한다(운영 지표·알림이 exit code에 의존할 수 있으므로).

### 2.6 수집 직후 OOS 성과 계산 자동 실행 여부

**권장: 분리하되, 수집 성공 시에만 순차 트리거한다(같은 배치 잡 내 2단계, 실패 전파는
독립).** 이유:
- `measure_sppv3_oos_candidate_performance.py`는 이미 완전히 read-only이고, 표본
  부족 시 `PENDING_INSUFFICIENT_OOS_SAMPLE`만 반환하도록 설계되어 있어(§2.2 조사에서
  재확인, `EXPECTED_BASE_CACHE_ID` 등 계약 검증 포함) 자동 실행해도 정책적 위험이 없다.
- 다만 수집이 실패(`ready_for_oos=false`)했는데 분석을 실행하면 무의미하거나 오해를
  부를 수 있으므로, **수집 성공(`ready_for_oos=true`) 시에만** 분석 단계를 실행한다.
- 분석 결과(JSON)는 알림(§2.7)에 요약만 포함하고, Go/Watch/Hold/No-Go 판정이 나오더라도
  **이 배치의 어떤 출력도 정책 변경이나 Stage B 착수의 근거가 되지 않는다**(§4 불변식과
  동일 원칙 — 자동화가 판정을 만들어도 사람이 검토하기 전까지는 운영 신호가 아니다).

### 2.7 알림·운영 지표 최소 계약

배치 완료(성공/실패 무관) 시 다음 필드를 포함하는 구조화 로그(JSON) 1건을 남긴다. 비밀값·계좌정보는 절대 포함하지 않는다.

```json
{
  "run_at_kst": "2026-08-25T21:00:00+09:00",
  "target_trade_date": "2026-08-25",
  "universe_symbol_count": 88,
  "fetch_success_count": 88,
  "fetch_failed_symbols": [],
  "fetch_missing_trade_date_symbols": [],
  "cache_id": "sppv3_oos_bar_cache_2026-08-25",
  "cache_relative_path": "logs/_bars_cache_core87_3y_2026-08-25",
  "manifest_sha256_of_manifest": "...",
  "ready_for_oos": true,
  "skipped_reason": null,
  "oos_total_trading_days": 28,
  "oos_analysis_status_by_candidate": {
    "overnight_reversal_v1": "PENDING_INSUFFICIENT_OOS_SAMPLE",
    "intraday_reversal_v1": "PENDING_INSUFFICIENT_OOS_SAMPLE",
    "low_volatility_rank_20d": "PENDING_INSUFFICIENT_OOS_SAMPLE"
  }
}
```

- `skipped_reason`: 휴장일/중복 실행 스킵 시에만 값 존재(예: `"non_trading_day"`, `"already_completed"`).
- 계좌번호, API 키, 토큰 등은 필드 목록에 존재하지 않는다 — 로깅 코드 리뷰 시 이 계약을
  기준으로 검사한다.

## 3. 종합 비교표

| 항목 | 후보 1 | 후보 2 | 권장 |
|---|---|---|---|
| 배치 시각 | 20:30 KST | 21:00 KST | **21:00 KST** |
| 실행 주체 | `ops-scheduler`에 잡 추가 | 별도 one-shot(주문 경로와 프로세스 분리) | **별도 one-shot** |
| cache 저장 전략 | append-only 단일 cache | 매일 신규 디렉토리 + `latest` 포인터 | **매일 신규 디렉토리 + latest 포인터** |
| 실패/재시도 | 배치 wrapper 없이 스크립트 그대로 재사용 | 배치 wrapper에서 휴장일 가드·중복 스킵·부분타임아웃·`ready_for_oos` 기반 재시도 판단 | **배치 wrapper 도입** |

## 4. 권장 아키텍처

1. **실행 시각**: 매 거래일 21:00 KST 1회.
2. **실행 주체**: 주문 스케줄러(`ops-scheduler`)와 프로세스/컨테이너가 분리된 one-shot
   실행(구체 메커니즘은 §6에서 사용자 승인 후 확정 — 후보로는 host cron, systemd timer,
   또는 이미 존재하는 `agent_trading-ops-scheduler` 컨테이너 내부의 완전히 독립된
   서브프로세스 진입점 등이 있으며 이번 턴에서는 어느 것도 등록하지 않았다).
3. **cache 저장**: 현행 매일 신규 디렉토리 방식 유지 + 성공 시에만 `latest` 포인터 갱신.
4. **실패 처리**: 배치 wrapper가 휴장일 가드 → 중복 스킵 → 수집 실행(전체 타임아웃) →
   `ready_for_oos` 판정 → (성공 시만) 분석 실행 → 알림 순으로 진행.
5. **분석 자동 실행**: 수집 성공 시에만 트리거, 항상 read-only, `PENDING_INSUFFICIENT_OOS_SAMPLE`
   포함 어떤 결과도 정책 자동 반영 없음.
6. **알림**: §2.7 계약을 그대로 따르는 구조화 로그 1건.

## 5. 구현 작업 분해 (다음 구현 턴 대상, 이번 턴에서는 미실행)

1. **수집기 확장 여부**: `build_sppv3_oos_bar_cache.py` 자체는 확장 불필요(이미 멱등한
   단일 실행 단위). 다만 "이미 완료된 날짜면 스킵" 판단을 스크립트 내부가 아니라
   wrapper 책임으로 둘지, 스크립트에 `--skip-if-ready` 플래그를 추가할지는 다음 턴에서
   결정.
2. **배치 wrapper 신규 작성**: 휴장일 가드 → 중복 스킵 → 수집 호출 → 타임아웃 관리 →
   `ready_for_oos` 판정 후 분기.
3. **거래일/시간 가드**: `MarketSessionProvider.is_trading_day()` 재사용, 실행 시각
   자체는 배치 스케줄러(cron/timer) 레벨에서 21:00 KST로 고정.
4. **lock/idempotency**: PostgreSQL advisory lock(`try_scheduler_lock()`) 재사용
   가능 여부 검토, 또는 파일 기반 lock(그날 디렉토리 존재 여부)만으로 충분한지 판단.
5. **manifest/checksum**: 기존 `build_manifest()`/`sha256_of_file()` 그대로 재사용,
   `latest` 포인터 파일 스키마만 신규 정의.
6. **OOS 분석 후처리**: `measure_sppv3_oos_candidate_performance.py` 호출을 wrapper에서
   `latest` 포인터 경유로 연결.
7. **알림/관측성**: §2.7 JSON 로그 emit, 민감정보 미노출 검증(코드 리뷰 체크리스트화).
8. **테스트**: 휴장일 스킵, 중복 실행 스킵, 부분 실패 시 `ready_for_oos=false` 전파,
   타임아웃 시 부분 manifest 생성, 분석 자동 실행 조건부 트리거, 알림 페이로드에
   비밀값 없음 확인 — DB/네트워크 미사용 단위 테스트로 구성.

## 6. 구현 전 반드시 사용자 승인이 필요한 항목

- 실제 KIS `inquire_daily_itemchartprice` 호출을 주기적으로(매일) 실행하는 배치 등록
  (cron/systemd timer/GitHub Actions schedule 등 어떤 메커니즘이든).
- 새 컨테이너 또는 기존 컨테이너 내 신규 진입점 배포(운영 표면 변경).
- `logs/` 하위 신규 cache 디렉토리의 매일 자동 생성 시작(현재는 수동 1회만 존재).
- `latest` 포인터 파일/심링크 도입 여부와 정확한 스키마.
- 배치 실행 주체의 구체적 메커니즘 선택(host cron vs systemd timer vs 기존 컨테이너
  서브프로세스 vs 신규 컨테이너) — 이 문서는 "주문 경로와 분리"까지만 확정했고,
  구체 수단은 사용자와 함께 다음 턴에서 확정한다.

## 7. 사실 / 해석 / 미확인 사항 요약

- **사실**: `MARKET_CLOSE=15:30:30`, `signal_feature_batch=20:10`(코드 상수), OOS cache
  디렉토리 명명 규칙과 `ready_for_oos` 정책, `measure_sppv3_oos_candidate_performance.py`의
  manifest 계약 필드 — 모두 코드 인용으로 확인됨.
- **해석**: 21:00 KST 권장 시각, one-shot 분리 권장, `latest` 포인터 도입 권장 — 이번
  조사에서 나온 판단이며, 실측이 아닌 안전 마진 기반 설계 결정이다.
- **미확인**: KIS가 당일 일봉을 정확히 몇 시에 확정 제공하는지는 실측하지 못했다.
  다음 구현 턴에서 실제 배치를 가동하기 전, 최소 1회 이상 21:00 KST 실행을 수동으로
  관찰해 "그 시점에 당일 일봉이 실제로 존재했는지"를 확인하는 것을 권장한다.

## 8. 2026-08-25 21:03 KST 단발 수동 관찰(read-only, 사용자 명시 승인 하 실행)

§7의 "미확인"에 대해, 사용자 승인 하 21:00 KST 이후 1회 수동 실행으로 다음을
관찰했다(상세: `docs/10_signal_research_sppv/[DESIGN] signal_predictive_power_
validation.md` §46).

- 실행 시각 21:03:28 KST, 88/88 종목 전부 `fetch_status="ok"`이고
  `new_last_trade_date == "20260825"`(실행 당일) — 즉 88/88 종목의 **당일** 일봉이
  21:03 KST 시점에 이미 확정 제공되고 있었다.
- `ready_for_oos=true`. base cache·기존 성공 OOS cache 모두 체크섬·mtime 불변 확인.
- **이것은 1회 관찰이다.** 21:00 KST가 모든 거래일에 항상 안전한 시각이라는 보장은
  아니며(변동성이 큰 날, 시스템 지연 등 예외 상황은 검증되지 않음), 반복 관찰이
  필요하다는 §7의 결론 자체는 이번 관찰로 해소되지 않았다 — "1회 관찰상 21:00은
  충분했다"로만 격상한다.

## 9. 배치 정의 코드/systemd 템플릿 구현(2026-08-25/26 KST, read-only 구현 턴)

이 절은 §4의 권장 아키텍처를 실제 코드·설정 파일로 구현한 기록이다. **이번
구현은 "배치 정의 추가"일 뿐, 실제 자동 실행 활성화가 아니다.** 이번 턴에서
실제 KIS 호출, systemd timer 등록·enable·start, 컨테이너 재기동, DB write, 주문
경로 변경은 전혀 수행하지 않았다.

- **배치 wrapper**: `scripts/run_sppv3_oos_batch.py`(신규). KST 21:00 시간 가드
  (`is_time_gate_open`), `MarketSessionProvider.is_trading_day()` 휴장일 가드(단,
  이 wrapper의 compose 환경은 `KIS_LIVE_INFO_ENABLED`를 항상 `"false"`로 고정
  배선해 `create_session_provider()`가 076 API를 호출하지 않고 항상
  `FallbackSessionProvider`로 폴백하게 만든다 — §5의 "호출 API는 `inquire_daily_
  itemchartprice`만 허용" 원칙을 배치 전체로 확장 적용), 같은 날짜 cache에
  `ready_for_oos=true` manifest가 이미 있으면 즉시 skip, 실패·불완전 cache는
  재시도 허용(기존 성공 cache·base cache는 절대 건드리지 않음 — 기존
  `build_sppv3_oos_bar_cache.py`가 이미 보장하는 불변성을 wrapper가 다시 깨지
  않는다), 전체 timeout(기본 1800초), 파일 기반 `flock` exclusive/non-blocking
  lock(프로세스 종료 시 커널이 자동 해제 — 전통적 PID 파일과 달리 stale lock이
  구조적으로 발생하지 않는다), 수집 성공(`ready_for_oos=true`) 시에만 기존
  `measure_sppv3_oos_candidate_performance.py`를 read-only로 1회 호출하고
  `PENDING_INSUFFICIENT_OOS_SAMPLE`을 정상 종료로 처리, 민감정보 없는 JSON 요약
  로그 1건을 stdout에 emit한다.
- **Compose one-shot service**: `docker-compose.yml`의 `sppv3-oos-batch` 서비스
  (신규). `profiles: [sppv3-oos-batch]`로 `docker compose up -d`가 무심코 상시
  기동시키지 않도록 가둠, `restart` 정책 없음(one-shot), 주문 `ops-scheduler`와
  완전히 별도 실행 경로. DB 연결 설정·계좌/주문용 KIS 환경변수(`KIS_APP_KEY`/
  `KIS_ACCOUNT_NO` 등)는 추가하지 않았다 — 오직 read-only quote client 자격증명
  (`KIS_LIVE_INFO_APP_KEY`/`APP_SECRET`/`BASE_URL`)과 토큰 캐시 설정만 배선했다.
  `scripts/harness/contracts/runtime_env_wiring.json`에 이 서비스의 필수 env 3개
  (`KIS_LIVE_INFO_ENABLED`/`APP_KEY`/`APP_SECRET`)를 등록해 `accept env`가 배선
  누락을 하드 실패로 잡도록 했다.
- **systemd 템플릿**: `ops/systemd/sppv3-oos-batch.service`(oneshot,
  `docker compose run --rm sppv3-oos-batch`만 호출 — 실행 중인 `ops-scheduler`
  컨테이너에 `docker exec`하지 않음), `ops/systemd/sppv3-oos-batch.timer`
  (`OnCalendar=Asia/Seoul *-*-* 21:00:00`, `Persistent=true`). `Persistent=true`
  채택 근거를 timer 파일 자체에 상세히 기록했다 — 요지: wrapper가
  `target_trade_date`를 항상 "실행 시점의 KST 오늘 날짜"로 계산하고 자체
  21:00 시간 가드를 다시 검사하므로, 같은 날 재부팅 후 만회 실행은 안전하게
  정상 수집으로 이어지고, 날짜가 넘어간 재부팅 후 만회 실행은 시간 가드에 막혀
  조용히 no-op되며 그 놓친 날짜는 소급 수집되지 않고 그대로 표본 공백으로
  남는다(과거 날짜를 실제 수집 시점과 다르게 소급 기록하지 않는다는 원칙을
  우선했다). `ops/systemd/install_sppv3_oos_batch_systemd.sh`(설치 스크립트,
  `--yes` 없이는 dry-run만 수행) — **이번 턴에서 실행하지 않았다.**
- **테스트**: `tests/scripts/test_run_sppv3_oos_batch.py`(46건 중 wrapper 부분),
  `tests/ops/test_sppv3_oos_batch_ops_contracts.py`(Compose/systemd 템플릿 계약)
  — 전부 DB/네트워크 미사용, 실 KIS 미호출.
- **다음 단계(사용자 승인 필요)**: `AGENT_TRADING_REPO_ROOT`를 운영 checkout
  경로로 지정해 `install_sppv3_oos_batch_systemd.sh --yes` 실행, `latest` 포인터
  도입(§2.4의 유보 그대로 유지 — 최소 3~5회 성공 관측 후 별도 작업), 실제 21:00
  자동 실행을 며칠간 관찰해 §8의 "1회 관찰"을 반복 검증으로 격상.
