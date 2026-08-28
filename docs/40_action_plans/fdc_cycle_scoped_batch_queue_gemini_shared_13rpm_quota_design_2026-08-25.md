# FDC Cycle-Scoped Batch Queue + Gemini Shared 13 RPM Quota (PostgreSQL Atomic Reservation) — 설계 확정

> **상태(2026-08-25, Phase 1 구현 완료)**: 이 문서 §8의 영속 스키마(3-테이블),
> §6의 atomic reservation 로직, §11/§12의 shadow 관측 경로를 **Phase 1
> 범위로 구현 완료**했다 — `db/migrations/0068_add_fdc_quota_lifecycle_
> tables.sql`, `src/agent_trading/repositories/contracts.py`(`FdcQuotaRepository`
> Protocol), `src/agent_trading/repositories/postgres/fdc_quota.py`,
> `src/agent_trading/repositories/memory.py`(`InMemoryFdcQuotaRepository`),
> `src/agent_trading/services/fdc_quota_coordinator.py`(`FdcQuotaCoordinator`),
> `src/agent_trading/services/decision_orchestrator.py`(lifecycle shadow
> 관측 메서드). **실제 cycle-scoped dispatcher, FDC one-shot 인터페이스,
> live/fake provider 타입 분리, held_position lane 실제 전환은 아직
> 구현하지 않았다** — 이들은 후속 PR 범위다(§16 참고). 현재도 기존
> `fdc_rate_limiter.py`의 10 RPM strict limiter가 실제 Gemini HTTP 요청의
> 유일한 제한 장치이며, 이 문서의 13 RPM은 `FDC_BATCH_QUEUE_LIFECYCLE_
> SHADOW_ENABLED=true`일 때만 작동하는 **shadow 판단값**일 뿐 실제
> provider 호출량을 바꾸지 않는다.
>
> **개정 이력**: 2026-08-25(2차) — 최초 확정본에 남아있던 4개 계약 충돌(reservation
> 이중 소유 위험, 수동 호출 job 모델 미확정, retry/pre-HTTP 실패 계수 혼재, sliding
> 60초 경계 규칙 불일치)을 보정했다. §4·§6·§7·§8·§9·§11·§12·§14·§15가 이번 개정의
> 영향을 받는다(하단 각 절에 명시).
>
> **개정 이력**: 2026-08-25(3차) — accounting 정의 내부 불일치를 보정했다:
> `dispatch_attempt_no`가 "reservation을 실제로 받아 넘긴 횟수"(§9 정의)와
> "reservation 거부 시 증가"(사례 설명)로 서로 모순되게 서술돼 있던 문제를
> "성공 시에만 증가"로 통일하고, 이전에 accounting 표에만 있고 `fdc_queue_jobs`
> 스키마 표에는 누락됐던 `reservation_denied_count`를 스키마에 추가했다.
> §8·§9·§14·§15·§16이 이번 개정의 영향을 받는다.
>
> **개정 이력**: 2026-08-25(4차) — `queue_poll_count = reservation_denied_
> count + dispatch_attempt_no` 항등식과 DB/coordinator 오류 fail-closed
> 경로 사이의 불일치를 보정했다. coordinator 오류(DB unavailable/lock
> timeout/transaction 오류)는 `GRANTED`도 `DENIED`도 아니므로 이 세 카운터
> 중 어느 것도 증가시키지 않는다(A안 채택)는 것을 명시하고, coordinator
> 오류 전용 상태·backoff·최소 관측 계약을 신설했다. §5·§6·§9·§13·§15·§16이
> 이번 개정의 영향을 받는다.
>
> **개정 이력**: 2026-08-25(5차, PR #351 1차 보정) — Phase 1 초기 구현이
> `mode='real'` attempt만 세는 판정 로직을 그대로 shadow 경로에 재사용해
> shadow window_count가 항상 0이 되던 결함과, shadow 관측 시점이 기존 FDC
> permit 대기·HTTP 호출 이후(잘못된 시점)였던 결함을 보정했다. **정정된
> 표현**: "13 RPM이면 지금 승인됐을까"가 아니라 "**같은 cycle 내 앞선
> shadow FDC-ready job까지 포함한 FIFO 가상 큐에서 지금 승인 가능한가**"이다
> — 판정은 오직 같은 `quota_scope`의 `mode='shadow'` 행만 보고(`mode='real'`
> 행은 절대 보지 않음). **주의**: 이 개정에서 "FIFO 순서는 DB가 발급한
> `enqueue_sequence`(INSERT와 함께 원자적으로 채번)로 정하므로 Python
> task 완료 순서에 의존하지 않는다"고 서술했으나, 이는 **틀렸다** — DB
> INSERT 자체가 `assemble()` 도착 시점에 일어났기 때문에, INSERT 순서는
> 여전히 "여러 심볼이 동시 처리되는 중 어느 것이 먼저 `assemble()`에
> 도착했는가"(=기존 limiter 대기·provider 응답·subprocess 종료 순서에
> 좌우됨)를 반영했을 뿐, 진짜 `fdc_ready_at` 순서를 반영하지 못했다.
> 이 오류는 6차 개정에서 바로잡았다.
>
> **개정 이력**: 2026-08-25(6차, PR #351 2차 보정) — 5차 개정이 남긴
> "DB INSERT 순서가 곧 FDC-ready FIFO 순서"라는 서술을 정정했다. 실제
> FIFO 기준은 **`(fdc_ready_at, cycle_index)`**다 — `fdc_ready_at`이
> 1차 기준, 동일 시각이면 같은 cycle 내 `cycle_index`(universe 열거
> 시점에 고정, `asyncio.gather()`가 입력 순서를 그대로 보존하는 성질을
> 이용 — 어떤 subprocess/코루틴 완료 순서에도 의존하지 않음)가 2차
> tie-breaker다. 기존 limiter 대기 완료 순서·provider 응답 순서·
> subprocess 종료 순서·`assemble()` 호출 순서는 전혀 사용하지 않는다.
> 이를 구현하기 위해 `assemble()`은 더 이상 shadow를 DB에 직접 등록하지
> 않고(`FdcReadyShadowEvent`만 노출), 사이클의 모든 심볼 처리
> (`asyncio.gather()`)가 끝난 뒤 호출자(`run_decision_loop.py`)가 이
> 이벤트들을 `(fdc_ready_at, cycle_index)` 기준으로 정렬해 **순차** 재생한다
> — `enqueue_sequence`는 이제 이 정렬된 재생 순서를 그대로 반영하는
> 값이며, 더 이상 "단순 도착 순서"를 의미하지 않는다. `decision_cycle_id`
> 도 `request.correlation_id`(심볼별 고유 문자열)에서 진짜 cycle-scoped
> 식별자로 교체했다. 자동 dispatcher가 아직 없으므로 Phase 1이 신뢰성
> 있게 관측하는 것은 여전히 "**즉시 shadow grant 가능**"(`SHADOW_WOULD_
> GRANT`)과 "**shadow queued**"(`SHADOW_QUEUED`) 두 상태뿐이며, "몇 분
> 후 실제로 grant될지"는 후속 dispatcher 단계(§16 "구현 후 실측 필요")
> 범위다. `SHADOW_QUEUED`는 실패·timeout이 아니다. 상세는 `docs/30_
> work_log/2026-08-25_fdc_quota_lifecycle_shadow_phase1_correction_2.md`
> 참고.
>
> **상태(2026-08-27, Phase 1 운영 실측 완료)**: PR #351/#355로 병합된 Phase 1
> shadow 관측이 `fdc_ready_at` subprocess payload 누락 결함(PR #356으로 수정)
> 때문에 한동안 `fdc_queue_jobs`가 0행으로 남아 있었으나, PR #356 배포 이후
> 정상 거래일 장중 연속 5개 cycle(총 96건 FDC-ready)에서 shadow FIFO/전역
> sliding 60초 13 RPM 판정이 **완전히 정확함**을 read-only 실측으로 확인했다
> (FDC-ready↔shadow 1:1 정합성 100%, FIFO 시간 역전 0건, 재계산 판정 불일치
> 0건, `mode='real'` row 0건). 이로써 §6/§9/§14의 coordinator 판단 로직·
> accounting·감사 SQL 설계가 실제 운영 데이터로 검증됐다 — 이 문서의 판정
> 로직 자체(§4~§14)는 더 이상 가설이 아니라 **실측 확인된 계약**이다.
>
> **상태(2026-08-27, 후속 PR 설계 착수 — 구현 전 조사에서 새 제약 발견)**:
> Phase 2(실제 dispatcher 구현) 착수를 위해 코드베이스를 조사한 결과, 이
> 문서 §4 "사이클 초반에 종목별 EI/AR/AC/deterministic_trigger를 먼저 전부
> 실행(기존과 동일, 변경 없음)"이라는 전제가 **틀렸다**는 사실이 드러났다 —
> 실제로는 EI/AR/AC/FDC 4개 agent가 전부 **단일 subprocess**(`scripts/
> run_agent_subprocess.py::main()`) 안에서 한 번의 stdin/stdout 왕복으로
> 순차 실행되며, 서비스 레이어(`decision_orchestrator.assemble()`)가 아니라
> **subprocess 프로세스 경계 자체**가 pre-FDC와 FDC를 분리하지 못하게 막고
> 있다. 이는 "최소 리팩터링"이 아니라 subprocess 아키텍처의 실질적 재설계를
> 요구하므로, 이 문서에 새 **§17 Pre-FDC/FDC subprocess 분리 설계**를
> 신설해 이 공백을 메운다. §17 이후 §18~§22도 함께 신설했다(provider
> one-shot 리팩터링 상세, live provider 진입점별 게이팅, feature flag 배선,
> 테스트 계획 통합, PR 실행 계획). §4~§16은 dispatcher/coordinator/
> accounting 설계로서는 그대로 유효하며 변경하지 않는다 — §17이 그 앞단
> (pre-FDC/FDC 분리)을 보강할 뿐이다.
>
> **상태(2026-08-27 2차, PR #357 리뷰 보정 — §17~§22 내부 설계 충돌 3건
> 해소)**: §17~§22 최초 작성분에서 다음 3개 결함이 발견돼 보정했다.
>
> 1. **PR A/PR B 순서 충돌**: 최초 작성분은 §19(live provider 게이팅)를
>    PR A에 배정하면서도, 게이팅 대상 중 하나(진입점 #2, subprocess FDC
>    호출)가 §17(PR B 범위)에서 신설되는 `--mode fdc_only`에서만 존재하는
>    모순이 있었다. 이대로면 PR A가 병합되는 순간 "FDC live provider는
>    coordinator 없이 생성 불가"라는 게이팅이 적용되는데, 정작 그 시점의
>    운영 FDC 호출은 여전히 `--mode full`(레거시 경로, 아직 coordinator를
>    쓰지 않음)이라 **레거시 FDC 경로 자체가 막히는 회귀**가 발생했을
>    것이다. **보정**: `LiveGeminiProviderClient` 클래스 신설과 coordinator
>    필수화는 PR A에서 "아직 아무 운영 경로도 쓰지 않는 추가적(dormant)
>    구현체"로만 도입하고, **레거시 `--mode full`의 FDC 호출부(진입점 #2)를
>    이 클래스로 전환하는 것은 PR B**(§17 `--mode fdc_only` 신설과 동시)로
>    옮겼다. "모든 live FDC 호출이 coordinator를 거친다"는 계약은 **PR B
>    병합 + `FDC_ACTUAL_DISPATCH_ENABLED=true` 별도 승인 활성화 이후에만
>    성립**함을 §19·§22에 명시했다. §19·§22·§21이 이번 보정의 영향을
>    받는다.
> 2. **carryover 재기동/프로세스 종료 계약 누락**: 최초 작성분은 carryover를
>    "in-memory로만 보관"한다고만 서술하고, dispatcher 프로세스가 죽거나
>    재시작될 때 DB에 남은 미종결 job(`QUEUED`/`RESERVATION_GRANTED`/
>    `FDC_RUNNING`/`RETRY_QUEUED`)을 어떻게 처리하는지 정의하지 않았다.
>    **보정**: 신규 §17.7(재기동/프로세스 종료 복구 계약)을 추가해, carryover가
>    소실된 미종결 job을 recovery scan이 기존 §5 `CANCELLED` 3사유 중
>    "프로세스 종료"를 구체화한 `reason=process_terminated_carryover_lost`로
>    1회성·idempotent하게 정리하도록 확정했다. 새 `CANCELLED` 사유 범주를
>    추가하지 않았다(기존 3종 유지). §17·§21이 이번 보정의 영향을 받는다.
> 3. **`FDC_ACTUAL_DISPATCH_ENABLED`의 `runtime_env_wiring.json` 등록값
>    오류**: 최초 작성분은 이 키를 "관측 전용 키"에 준해 `required_in_
>    compose: false`로 제안했으나, 이 키는 실제로 dispatcher 분기와 provider
>    호출 방식(레거시 `--mode full` vs `--mode fdc_only`)을 바꾸는 **런타임
>    실행 경로 선택 키**다(기본값이 `false`라는 것과 "관측 전용"이라는 것은
>    다른 개념이다 — 혼동한 것이 결함이었다). **보정**: `required_in_compose:
>    true`로 정정하고, `settings.py`/`.env.example`/`docker-compose.yml`/
>    `runtime_env_wiring.json` 4곳이 함께 변경돼야 하며 `accept env`가 이
>    배선을 강제 검증해야 함을 명시했다. §20이 이번 보정의 영향을 받으며,
>    §20 전체를 PR B 범위로 재배정했다(1번 보정과 일관성 유지 — flag가
>    실제로 소비되는 시점과 같은 PR에서 도입).
>
> **상태(2026-08-27 3차, PR #358 실제 구현 반영 — §18/§19 서술 정정)**:
> PR A(PR #358)가 실제로 구현되면서 §18에 남아있던 "PR A 시점에는 아무
> 운영 경로도 `generate_structured_once()`를 호출하지 않는다"는 서술이
> 사실과 달라졌다 — 독립 분석 스크립트 2개(§19 진입점 #3·#4)가 실제로
> 이 메서드를 호출하는 `call_with_coordinator()`/`CoordinatedFdcProvider
> Client`(신규, `AIProviderClient` Protocol wrapper)를 PR A에서 이미
> 사용 중이다. §18을 이 사실에 맞게 정정했다(§4~§17, §19~§22의 다른
> 계약은 변경 없음 — ops-scheduler 운영 경로가 PR B 전까지 이 메서드를
> 쓰지 않는다는 핵심 계약은 그대로 유효). 또한 PR A 리뷰 과정에서
> `LiveGeminiProviderClient.generate_structured()` 의도적 차단과, 실제
> `client.post()` 직전에만 호출되는 `on_http_start` 콜백(`http_started_at`
> 정밀 기록용)이 §18에 새로 추가됐다 — 둘 다 최초 설계 문서에는 없던
> 내용이며, PR A 리뷰에서 발견된 결함(coordinator 우회 가능성,
> `http_started_at` 부정확 기록)을 보정하며 확정됐다.
>
> **상태(2026-08-27 4차, "좁은 PR B" 실제 구현 — §17 전체가 아닌 부분
> 구현으로 범위를 좁힘)**: 사용자가 §22 "PR B(전부 한 PR)" 대신, **held_
> position lane의 REDUCE_CANDIDATE/SELL_CANDIDATE에 한정한 실제 dispatch
> 전환만** 요청했다. 조사 결과, 이 좁은 범위에서는 §17이 요구하는
> subprocess 분리(`--mode pre_fdc`/`--mode fdc_only`, dispatcher 본체,
> `pending_fdc_dispatch_sink`, carryover, §17.7 recovery scan)가
> **불필요**하다는 것이 확인됐다 — 근거:
>
> 1. `deterministic_trigger.primary_candidate`(REDUCE_CANDIDATE/
>    SELL_CANDIDATE 판정)는 `decision_orchestrator.py`가 agent subprocess를
>    호출하기 **전에** 이미 계산되어 stdin payload(`AgentSubprocessInput.
>    context`)에 포함된다 — "FDC 이전 상태를 나중에 재개하기 위한 별도
>    프로세스"가 필요 없다.
> 2. `deterministic_trigger_engine.py`상 `SELL_CANDIDATE`/`REDUCE_
>    CANDIDATE`는 `source_type == "held_position"`일 때만 생성되므로,
>    별도 lane 식별자 없이 `primary_candidate` 값 하나로 lane+후보 범위를
>    안전하게 특정할 수 있다.
> 3. `run_agent_subprocess.py`의 EI/AR/AC는 전부 deterministic bot(LLM
>    미사용)이라 `_build_agent_triplet(provider_client=..., acquire_
>    permit=...)`은 사실상 FDC에만 영향을 준다 — 같은 단일 subprocess
>    호출 안에서 FDC의 provider client만 (`OpenAICompatibleClient` + 기존
>    10 RPM limiter) → (PR A의 `CoordinatedFdcProviderClient` + coordinator)
>    로 교체하는 것으로 충분하다.
>
> **실제 구현 범위**(브랜치 `feat/fdc-actual-dispatch-held-position-
> 2026-08-27`): `scripts/run_agent_subprocess.py::main()`에
> `_is_fdc_actual_dispatch_target()`(순수 판별 함수)와
> `_build_actual_dispatch_fdc_client()`(coordinator/repo/DB pool 구성,
> PR A의 `ar_fdc_provider_validation.py`와 동일한 `create_pool()`/
> `close_pool()` lifecycle)를 신설하고, `FDC_ACTUAL_DISPATCH_ENABLED`
> (기본값 `false`)와 대상 lane/후보 판정이 **둘 다** 참일 때만 이 경로로
> 분기한다. `caller_id="ops-scheduler:held_position_reduce_sell"`
> (`"manual:"` 접두사 아님)을 써서 §11 fail-closed 정책(manual 전용)의
> 대상이 되지 않게 했다 — PR A에서 이미 "비-manual 호출자는 완전히
> 우회한다"고 확정된 계약을 그대로 재사용.
>
> **이번 범위에 포함하지 않은 것(§17 전체 중 여전히 미구현)**: `--mode
> pre_fdc`/`--mode fdc_only` 신설, dispatcher 본체(§4/§6/§7의 batch
> queue/worker pool), carryover 계약(§17.3), 재기동/프로세스 종료 복구
> scan(§17.7), 진입점 #1·#2(운영 부트스트랩/subprocess FDC 호출)의 core
> lane 전환, `assemble()`의 `assemble_pre_fdc()`/`assemble_post_fdc()`
> 분리. 이들은 held_position lane 범위를 넘어 **core lane까지 포함한
> 전체 dispatcher**가 필요해질 때(§15 "③ 전체 lane 전환" 단계) 별도 PR로
> 진행한다 — 이번 PR은 §15 "② held_position lane 한정 실전 전환" 단계만
> 코드 수준으로 구현했다.
>
> **상태(2026-08-27 5차, 독립 리뷰 결함 지적 후 실제 dispatcher로 보완 —
> PR #359 리뷰 보정)**: 4차 구현은 실제로는 **단발 quota 검사**였다 —
> 13 RPM이 찬 경우 `ReservationDenied` 후 FIFO 대기·재등록·다음 slot
> 재시도가 없어 14번째 이후 job이 FDC 판단 없이 fallback HOLD로 끝날 수
> 있었고, `job_id=None`/`manual_run_id` 재사용으로 거부·재시도·최종
> 결과를 job 단위로 감사할 수 없었다(§4 "순번 탈락 금지"와 §17이 요구하는
> job lifecycle 계약 위반). 이 결함을 5차 보정으로 해소했다 —
> **"§17의 문자 그대로"가 아니라 "§17이 보장하려는 계약(FIFO 대기,
> job 단위 감사, subprocess 격리 보존)"을 다른 경계에서 구현**했다:
>
> - **`assemble()`은 여전히 건드리지 않는다.** 830줄짜리 안전 필수 메서드
>   내부 분리 대신, `DecisionAgentRunner.run_agents_in_subprocess()`
>   (기존에도 "agent를 실행하고 bundle을 반환하는" 불투명한 단일 진입점)
>   내부에서만 오케스트레이션한다 — `assemble()`은 이 메서드를 호출해
>   `AgentExecutionBundle`을 받는 기존 코드 그대로다.
> - `run_agent_subprocess.py`에 실제로 `mode="full"`(기존)/`mode=
>   "pre_fdc"`(EI/AR/AC + FDC skip 판정까지만)/`mode="fdc_only"`(이미
>   확보한 grant로 FDC one-shot만) 3가지를 신설했다 — §17.2가 요구한
>   두 CLI 진입점을 그대로 구현했다.
> - **FIFO 대기는 중앙 dispatcher 루프가 아니라 `try_reserve()` 자체의
>   FIFO 인지 admission 규칙**으로 구현했다(신규) — `job_id`가 있는 호출은
>   자신보다 먼저 등록되고 아직 `QUEUED`인 job이 있으면 window에 여유가
>   있어도 거부된다(anchor 행 잠금 하에 원자적으로 판정). 이 덕분에 여러
>   symbol의 코루틴이 각자 독립적으로 `try_reserve()`를 폴링해도(중앙
>   집중 dispatcher 없이) 새치기가 원천 차단된다 — `fdc_queue_jobs`에
>   `register_real_job()`으로 실제 job을 등록하고(§17 요구), `mark_job_
>   terminal()`/`cancel_stale_real_jobs()`로 상태를 관리한다.
> - `DecisionAgentRunner._run_agents_in_subprocess_with_actual_
>   dispatch()`가 pre_fdc → (reservation 대기, deadline 없음, coordinator
>   오류는 지수 backoff) → fdc_only → 병합을 오케스트레이션한다. quota가
>   가득 차거나 순번이 아니면 fallback으로 포기하지 않고 계속 재시도한다
>   (§4 "순번 탈락 금지" 직접 준수). provider retryable 실패는 새
>   reservation(=새 `fdc_only` subprocess spawn)을 쓴다(§7).
> - **재기동 recovery scan(§17.7)을 실제로 구현했다** — `run_decision_
>   loop.py::_run_loop()`(ops-scheduler가 cycle마다 새로 spawn하는
>   subprocess의 진입점) 시작 시 1회, flag가 켜져 있으면
>   `cancel_stale_real_jobs()`를 호출해 이전 invocation이 강제 종료돼
>   carryover를 잃은 non-terminal real job을 `CANCELLED(reason=
>   process_terminated_carryover_lost)`로 정리한다(idempotent).
>
> **여전히 포함하지 않은 것**: `pending_fdc_dispatch_sink`/전 cycle
> 단위의 중앙 집중 batch dispatcher(§4/§6/§7의 "worker slot" 개념 —
> FIFO 인지 `try_reserve()`가 그 역할을 대체), `assemble_pre_fdc()`/
> `assemble_post_fdc()` 분리(불필요해짐), 진입점 #1·#2의 core lane 전환.
> core lane까지 포함한 전체 dispatcher가 필요해지면(§15 "③ 전체 lane
> 전환") 이 FIFO 인지 `try_reserve()` 설계를 그대로 재사용할 수 있다 —
> job 등록 대상만 core lane까지 넓히면 되고, 새 아키텍처가 필요하지
> 않다.
>
> **상태(2026-08-28 6차, 3~5차 리뷰로 §17.3/§17.7이 실제 구현과 어긋난
> 부분을 정정 — PR #359 4~5차 리뷰 보정)**: 5차까지의 구현이 진행되며
> §17.3("carryover는 in-memory 전용")과 §17.7("recovery scan이 QUEUED를
> 포함한 모든 non-terminal 상태를 CANCELLED로 정리")의 전제가 실제
> 아키텍처와 어긋나게 됐다 — 아래 §17.3/§17.7 본문을 이 상태에 맞게
> 직접 정정했다. 핵심 변경 요지만 요약한다.
>
> 1. **carryover는 더 이상 in-memory 전용이 아니다.** ops-scheduler는
>    항상 `scripts.run_decision_loop --count 1`로 단발 프로세스를
>    spawn하므로("cycle 하나 끝나면 프로세스도 끝난다"), in-memory
>    carryover만으로는 이 job이 quota 포화로 이번 cycle 안에
>    완결되지 못했을 때 재개할 방법이 전혀 없었다. `fdc_queue_jobs`에
>    `pre_fdc_result_json`(JSONB)/`correlation_id`(TEXT) 컬럼을 최소
>    추가해(migration `0069`), `register_real_job()`이 pre_fdc(EI/AR/
>    AC) 완료 직후 이 값을 함께 영속화한다.
> 2. **저장하는 필드 vs. freshness-sensitive해서 저장하지 않는 필드**
>    — §17.3의 원래 표(`assembled_context` 전체 직렬화 포함)는 채택되지
>    않았다. 실제로 저장하는 것은 pre_fdc의 EI/AR/AC 산출물(`pre_fdc_
>    result`, 그 자체가 이미 JSON-safe dict)과 `correlation_id`뿐이다.
>    position/cash/risk snapshot 등 시간에 따라 낡을 수 있는 context는
>    저장하지 않는다 — override→EV-gate→sizing→submit 단계는 재개
>    시점에 항상 새로 조회한 fresh context로 재계산하는 기존
>    `precomputed_agent_bundle` 경로(`DecisionOrchestratorService.
>    assemble()`)를 그대로 쓴다. `complete_fdc_actual_dispatch()`도
>    이 원칙에 맞춰 `assembled_context`를 아예 받지 않도록 바뀌었고,
>    EV anchor 적용은 `assemble()`의 `precomputed_agent_bundle` 분기로
>    옮겨졌다(그 분기가 이미 fresh context를 갖고 있으므로).
> 3. **정상 `QUEUED` job의 resume 절차**: 새 `run_decision_loop.py`
>    프로세스는 시작 시(universe를 읽은 직후, recovery scan 다음
>    순서로) `list_resumable_real_jobs()`를 호출해 이 quota_scope의
>    모든 `status='QUEUED'` real job을 조회한다. 해당 symbol이 현재
>    universe에 있으면 agent(EI/AR/AC)를 다시 호출하지 않고 저장된
>    `pre_fdc_result`를 그대로 재사용해 `complete_fdc_actual_dispatch()`
>    → `_run_one_cycle(precomputed_agent_bundle=...)`로 완결한다.
>    없으면(예: 포지션이 이미 청산됨) 조용히 버리지 않고 `FDC_FAILED_
>    FINAL`(`reason=deadline_carryover_symbol_no_longer_in_universe`)로
>    감사 가능하게 종결한다.
> 4. **불완전한 carryover row의 fail-closed 처리(FIFO head 차단 방지,
>    5차 보정)**: `list_resumable_real_jobs()`는 `pre_fdc_result_json`
>    또는 `correlation_id`가 없는 `QUEUED` row(migration 이전 데이터,
>    부분 실패, 수동 복구 오류, 향후 코드 결함 등으로 발생 가능)를
>    조용히 건너뛰지 않는다 — `try_reserve()`의 FIFO admission("나보다
>    먼저 등록된 QUEUED job이 있으면 양보")이 그런 row 하나 때문에
>    뒤따르는 모든 real job을 영구 대기시킬 수 있기 때문이다. 발견
>    즉시 `FDC_FAILED_FINAL`(`reason=fdc_carryover_payload_missing_
>    data_integrity_error` 또는 `fdc_carryover_correlation_id_missing_
>    data_integrity_error`)로 전이시켜 FIFO head를 비운다(idempotent —
>    이미 terminal이 된 row는 다음 조회부터 대상에서 빠진다). 등록
>    시점에서도 `DecisionAgentRunner._run_agents_in_subprocess_with_
>    actual_dispatch()`가 `correlation_id`가 비어 있으면 애초에
>    등록하지 않고 fail-closed하도록 이중으로 막는다 — 불완전한 row를
>    만들지 않는 예방이 사후 정리보다 우선한다.
> 5. **`RESERVATION_GRANTED` crash recovery와 `QUEUED` deadline defer
>    resume의 책임 분리**: `cancel_stale_real_jobs()`(recovery scan)는
>    더 이상 `QUEUED`를 다루지 않는다 — 그 job들은 이제
>    `list_resumable_real_jobs()`가 안전하게 재개하므로 "재개할 방법이
>    없어 취소한다"는 원래 전제가 성립하지 않는다. `cancel_stale_real_
>    jobs()`는 정확히 "reservation을 실제로 받았지만(`status=
>    'RESERVATION_GRANTED'`) process crash로 결과가 불명확하게 남은"
>    job만 tri-state attempt lifecycle(`AttemptHttpLifecycle`)로
>    분기해 처리한다 — HTTP가 나가지 않았으면 `CANCELLED`, HTTP가
>    나갔을 수 있으면(`STARTED`) 중복 호출 위험 때문에 `FDC_FAILED_
>    FINAL`로 fail-closed 종결한다. 이 좁아진 범위가 "process crash로
>    결과가 불명확한 reservation만 정리하라"는 요구와 문자 그대로
>    일치한다.
>
> §17.3/§17.7 본문 자체도 위 내용에 맞게 아래에서 직접 갱신했다 —
> 이 blockquote는 변경 이력 요약이고, 실제 계약 문구는 각 절 본문이
> 최신 근거다.

## 1. 배경과 문제 정의

held_position 매도 후보의 FDC(FinalDecisionComposer) 판단이 `provider_queue_timeout`으로
소실되는 문제를 여러 차례 read-only 실측·설계 검토로 추적한 결과, 근본 원인은 다음과
같이 확인됐다.

- FDC provider(Gemini) 호출은 공유 rate limiter(`fdc_rate_limiter.py`)로 `10 RPM`(현재
  하드코딩 상수)만 허용하는데, 사이클당 실제 FDC 대상 수(held_position+core 합산 최대
  수십 건)가 이를 크게 초과한다.
- 현재 in-cycle FIFO 재대기열(PR #313)은 "1차 대기 18초 + 재대기 18초 = 최대 36초"
  후 확정 실패(`provider_queue_timeout`)한다. 실측(2026-08-24~25, 2거래일) 결과 **재대기
  128건 중 재대기 후 실제 HTTP 성공 사례는 0건**이었다 — 재대기 상한(36초)이 sliding
  window의 slot 회복 주기(약 60초)보다 짧아 구조적으로 회복 전에 예산이 바닥난다.
- 이 병목은 재대기 정책의 미세조정이 아니라, "탈락 없이 순서대로 전원 처리"라는 근본적
  아키텍처 전환으로만 해소된다.

추가로, 설계 검토 과정에서 아래 2개의 사전에 알려지지 않았던 사실을 확인했다.

- **운영 `ops-scheduler`의 EI/AR/AC는 Gemini를 전혀 호출하지 않는다** — `runtime/
  bootstrap.py`의 factory가 항상(always) `Deterministic*Agent`를 반환한다(코드 확인).
  **운영에서 Gemini를 호출하는 것은 FDC 하나뿐이다.**
- `scripts/ar_fdc_output_measurement.py --with-provider`, `scripts/
  ar_fdc_provider_validation.py` 두 개의 수동 분석 스크립트가 `acquire_permit` 콜백
  없이 provider client를 직접 생성/호출해, **현재 limiter를 완전히 우회할 수 있는 경로가
  실재**한다. 이 스크립트들은 `app` 컨테이너(`docker exec`용 유휴 컨테이너)에서 실행
  가능하며, `app`은 `ops-scheduler`와 **동일한 `GEMINI_API_KEY`**를 갖는다(값 자체는
  비공개, 존재만 확인).

## 2. 목표 · 비목표

### 목표

- Gemini 실제 HTTP 요청(최초+retry 합산)이 임의의 sliding 60초 구간에서 **13건을
  넘지 않는다**(Gemini 공식 한도 15보다 여유 2건을 둔 운영 목표).
- `ops-scheduler`의 FDC 요청과 수동 분석 스크립트의 요청이 **하나의 공용 quota를
  공유**해, 두 주체가 각자 13 RPM씩 써서 합계 26 RPM이 되는 위험을 없앤다.
- 사이클 내 FDC 대상 30건이면 약 3개 이상, 40건이면 약 4개 이상의 60초 window에
  걸쳐 **전원이 순서상 밀린다는 이유만으로 탈락하지 않고** 최소 1회 실제 HTTP 호출
  기회를 받는다.
- FDC job이 완료되는 즉시(배치 전체 종료를 기다리지 않고) 기존 `assemble()`/저장/
  주문 제출 경로로 합류한다(현재 코드가 이미 이렇게 동작하므로 이 성질을 보존한다).
- 재기동 시 사이클의 진행 상태(대기/완료/취소)를 DB에서 사후 확인할 수 있다.

### 비목표

- EI/AR/AC의 결정론적 bot 로직, held_position sell override, EV gate, translation,
  sizing, sell guard, 주문 제출 조건, freshness 게이트 — **어느 것도 변경하지 않는다.**
- Gemini의 실제 quota 적용 단위(API 키/프로젝트/모델)를 확정하는 것은 이 문서의
  목표가 아니다(외부 provider 정책, 미확인 사항으로 명시).
- 사이클 병행 실행, cross-cycle supersede — 채택하지 않는다(순차 cycle을 그대로
  유지하는 것이 확정 계약).

## 3. 현재 구조와 탈락 원인(코드 근거 요약)

- `run_decision_loop.py`: 사이클은 완전 순차 — 모든 종목 처리(세마포어 `_SEMAPHORE_
  MAX=5`) + T3 drain이 끝난 뒤 `interval`(900초, `OPS_SCHEDULER_DECISION_INTERVAL_
  SECONDS`) 만큼 sleep 후 다음 사이클. **`interval`은 "사이클 완료 후 sleep"이지
  "사이클 시작 간격 고정"이 아니다** — 사이클이 길어지면 다음 사이클 시작이 그만큼
  밀릴 뿐, 코드 변경 없이 3~4분 이상의 사이클을 자연스럽게 수용한다.
- `decision_agent_runner.py::run_agents_in_subprocess()`: EI+AR+AC+FDC 4개 에이전트를
  **하나의 subprocess**에서 순차 실행, 부모가 90초로 감싸 SIGTERM(10초 유예)→SIGKILL.
- `run_agent_subprocess.py`: `_FDC_PER_AGENT_TIMEOUT=70`초가 **permit 대기와 HTTP
  실행을 합쳐서** 제한한다(코드 주석에 명시) — 이것이 "36초 재대기 상한이 70초/90초
  예산 안에 갇혀 있다"는 구조적 제약의 근거다.
- `fdc_rate_limiter.py`: `DEFAULT_MAX_CALLS_PER_WINDOW=10`(모듈 상수, env/settings/
  compose 배선 전무), `DEFAULT_WINDOW_SECONDS=60`, `DEFAULT_MAX_WAIT_SECONDS=18`,
  `DEFAULT_MAX_REQUEUE_COUNT=1`. 상태 파일은 `tempfile.gettempdir()`(컨테이너 로컬
  `/tmp`)에 있다 — **`app`과 `ops-scheduler`가 이미 `./tmp:/app/tmp`를 공유
  bind-mount하고 있음에도(둘 다 host의 같은 `./tmp` 디렉터리), limiter가 이 공유
  경로가 아니라 컨테이너별 로컬 `/tmp`를 쓰고 있어 공유되지 않는다.**
- `provider_client.py::generate_structured()`: `MAX_RETRIES=3`은 **총 HTTP 시도
  횟수**(최초 1회+추가 재시도 최대 2회, `for attempt in range(3)`). 매 attempt마다
  `acquire_permit()`을 다시 호출, permit 거부 시 HTTP 시도로 집계되지 않는다.
  429/5xx/timeout/DNS 오류는 retry, 그 외 4xx·파싱 오류는 즉시 확정 실패.
- `app` 컨테이너는 `DATABASE_HOST: trading_db`로 **ops-scheduler와 동일한
  PostgreSQL**에 접근 가능(확인) — DB 기반 공용 coordinator가 신규 인프라 없이
  실현 가능한 근거.
- 기존 저장소에 **이미 확립된 행 잠금 관례**: `repositories/postgres/
  kis_fill_cumulative_state.py`가 "미리 존재하는 행을 `SELECT ... FOR UPDATE`로
  잠근 뒤 read-modify-write"하는 패턴을 실사용 중 — 이번 quota reservation 설계의
  직접적 선례.

## 4. 확정 아키텍처

**Cycle-scoped strict batch queue**(사이클 안에서 FDC 대상 전원을 끝까지 처리,
사이클 병행 없음) + **PostgreSQL 기반 공용 13 RPM quota coordinator**(anchor 행
잠금) + **dispatcher 완전 소유 permit ownership**(provider client는 1회 시도만
수행) 조합을 채택한다.

- 사이클 초반에 종목별 EI/AR/AC/deterministic_trigger를 먼저 전부 실행(기존과 동일,
  변경 없음). 결정론적 skip(risk_reject/NO_ACTION/WATCH-safe 등 기존 조건)은 즉시
  `assemble()`으로 저장(큐에 들어가지 않음).
- FDC가 필요한 대상만 `fdc_queue_jobs`에 `QUEUED`로 등록.
- 중앙 dispatcher(사이클 본문 안, 별도 장기 상주 프로세스 아님)가 사이클이 끝날
  때까지(=큐가 빌 때까지) worker slot·quota reservation을 관리하며 반복.
- job이 `FDC_SUCCEEDED`/`FDC_FAILED_FINAL`에 도달하는 즉시 기존 `assemble()`으로
  저장(배치 전체 종료를 기다리지 않음 — 기존 코드의 "종목별 즉시 저장" 성질 보존,
  `decision_orchestrator.py:1603 await self._repos.trade_decisions.add(td_entity)`가
  `assemble()` 내부에서 이미 동기 저장하는 것을 확인).
- 사이클은 전 job이 `FDC_SUCCEEDED`/`FDC_FAILED_FINAL`/`CANCELLED`에 도달해야 종료.

> **보정 1(reservation 단일 소유권, 2026-08-25 2차)**: "dispatcher가 permit을
> 완전히 소유한다"는 문장이 §12의 `LiveGeminiProviderClient.generate_structured_
> once()`도 coordinator를 호출한다는 서술과 병존해 이중 reservation처럼 읽힐
> 여지가 있었다. **정확한 계약은 다음과 같다**: quota coordinator에게 실제로
> reservation을 요청하는 주체는 **dispatcher 하나뿐**이다. dispatcher가 요청해
> 발급받은 `ReservationGrant`(§6)를 FDC one-shot 호출에 **값으로 전달**하고,
> `generate_structured_once(grant)`는 그 grant를 **소비만** 할 뿐 coordinator에게
> 새 reservation을 절대 요청하지 않는다. 즉 "provider client도 coordinator를
> 호출한다"는 것은 "결과를 attempt row에 기록하기 위해 같은 DB 접근 계층을
> 쓴다"는 뜻이지 "reservation을 다시 얻는다"는 뜻이 아니다 — 상세 계약과
> `generate_structured()`/`generate_structured_once()`의 reservation 경로 분리는
> §12에서 표로 확정한다.

## 5. 상태 전이도

> **보정 3(retry/pre-HTTP 실패 계수 분리, 2026-08-25 2차) 반영**: 아래 상태
> 전이도는 `RETRY_QUEUED`를 발생 사유별로 분리해 표기한다 — HTTP가 실제로
> 시작된 뒤의 재등록(`provider_retry_count` 증가)과, reservation은 받았으나
> HTTP 시작 전에 실패한 재등록(`pre_http_execution_failure_count` 증가)은
> **서로 다른 계수**이며, 둘 다 FIFO tail 재등록이라는 점만 같다(§9 참고).

```
[Job lifecycle]
QUEUED
  → (worker slot 확보 성공 && quota reservation 성공 → ReservationGrant 발급)
  → RESERVATION_GRANTED
  → FDC_RUNNING(발급받은 grant로 HTTP one-shot 실행 — 새 reservation 요청 없음)
    → HTTP_SUCCEEDED → FDC_SUCCEEDED → 즉시 assemble()/저장
    → HTTP_FAILED_RETRYABLE(429/5xx/timeout/DNS)
        → provider_retry_count += 1
        → RETRY_QUEUED(provider 사유, 새 queue_entry_id, FIFO tail) → QUEUED로 복귀
        → (provider_retry_count가 max_http_attempts-1=2 소진)
            → FDC_FAILED_FINAL(reason=provider_429_exhausted|provider_5xx_exhausted|provider_timeout_exhausted)
    → HTTP_FAILED_NONRETRYABLE(4xx/파싱오류) → FDC_FAILED_FINAL(즉시, reason=provider_nonretryable)
  → (reservation 성공 후 HTTP 시작 전 worker/subprocess 생성 실패)
      → RESERVED_BUT_HTTP_NOT_STARTED(quota는 그 60초 동안 계속 소비된 것으로 기록)
      → pre_http_execution_failure_count += 1
      → (pre_http_execution_failure_count가 max_pre_http_execution_failures 미만)
          → RETRY_QUEUED(pre-HTTP 사유, 새 queue_entry_id, FIFO tail) → QUEUED로 복귀
      → (소진) → FDC_FAILED_FINAL(reason=worker_start_exhausted)
  → (coordinator 호출이 COORDINATOR_UNAVAILABLE/COORDINATOR_LOCK_TIMEOUT/
     COORDINATOR_TRANSACTION_ERROR로 실패, 보정 4차 — §6 "coordinator 오류
     경로" 참고)
      → worker slot 즉시 반환, job은 QUEUED 유지(탈락 아님)
      → 지수 backoff 후 재시도(queue_poll_count/reservation_denied_count/
        dispatch_attempt_no 어느 것도 증가하지 않음 — 로그/in-memory
        counter로만 관측)
CANCELLED ← 시장 종료 / 운영자 명시 취소 / 프로세스 종료(오직 이 세 사유만 —
             coordinator 오류가 아무리 지속돼도 이 사유가 자동 추가되지 않음)
```

`queue_reenqueue_count = provider_retry_count + pre_http_execution_failure_count`
(§9) — 위 두 재등록 경로를 합친 값으로, "FIFO tail에 총 몇 번 다시 섰는지"를
보고 싶을 때만 참조하는 파생 지표다. 상태 전이의 종결 사유(`FDC_FAILED_FINAL`의
`reason`)는 항상 두 계수 중 **어느 쪽이 소진됐는지**로 명확히 구분된다 — 어느
경로든 순번 탈락이나 `CANCELLED`가 아니다.

```
[Cycle lifecycle]
전 종목 pre-FDC(EI/AR/AC) 완료
  → FDC-ready job 전원 QUEUED
  → dispatcher 반복(전원 종결 상태 도달까지, deadline 없음 — 명시적 취소만 종료 사유)
  → 사이클 종료 → interval(900초) sleep → 다음 사이클
```

`provider_queue_timeout`이라는 기존 reason code는 **이 신규 경로에서 사용하지
않는다** — 순번 대기로 인한 확정 실패라는 개념 자체가 새 계약에는 존재하지 않는다.

> **실제 구현 확정(2026-08-28 6차 리뷰 보정 — PR #359)**: 위 상태 전이도의
> "새 queue_entry_id로 FIFO tail 재등록"을 구현 PR에서 다음과 같이 확정했다 —
> **새 row/새 job_id를 만들지 않고, 기존 row의 `enqueue_sequence`를 원자적으로
> 새로 발급해 FIFO tail로 옮긴다**(`apply_retry_failure()`, `contracts.py`/
> `postgres/fdc_quota.py`/`memory.py`). `job_id`(audit identity)는 그대로
> 유지되므로, `fdc_provider_attempts`의 `(job_id, attempt_no)` 유일 제약과
> attempt 행 히스토리가 하나의 job_id 아래 연속적으로 남는다 — "새
> queue_entry_id"는 이 구현에서 "새 `enqueue_sequence` 값"으로 구체화됐다
> (별도 `queue_entry_id` 컬럼은 추가하지 않았다 — 기존 `enqueue_sequence`가
> 이미 그 역할을 한다).
>
> `RETRY_QUEUED`라는 별도 persisted 상태값도 도입하지 않았다 — 재등록 시
> `status`를 곧바로(그리고 유일하게) `QUEUED`로 되돌린다. 기존 `try_reserve()`
> FIFO admission 쿼리("나보다 작은 enqueue_sequence를 가진 QUEUED job이
> 있으면 양보")가 이 값을 그대로 재사용하므로 admission 로직 자체는 전혀
> 바뀌지 않는다 — `RETRY_QUEUED`라는 중간 상태를 별도로 두면 `list_
> resumable_real_jobs()`(§17.7, `status='QUEUED'`만 조회)와 recovery scan
> (`status='RESERVATION_GRANTED'`만 조회)의 WHERE 절을 모두 넓혀야 했는데,
> 그 복잡도 증가분에 걸맞은 실익이 없다고 판단했다 — "재시도로 몇 번
> 재등록됐는지"는 `queue_reenqueue_count`(job 단위 counter)가 이미 감사
> 가능하게 기록하므로, 상태값 자체를 분리할 필요가 없다.
>
> **counter 증가 시점(설계 문서 §9 순서 그대로 구현)**: `provider_retry_
> count`/`pre_http_execution_failure_count`(및 파생 지표 `queue_reenqueue_
> count`)는 `will_retry` 여부와 **무관하게** 그 실패 유형이 발생한 사실
> 자체로 항상 증가한다 — exhaustion으로 이어지는 마지막 실패도 포함된다
> (§5 상태 전이도가 exhaustion 판정 이전에 counter를 올리는 순서와 일치).
> `will_retry=True`일 때만 실제로 `enqueue_sequence`를 새로 발급하고
> `status`를 `QUEUED`로 되돌린다. `http_attempt_count`/`http_429_count`는
> `record_http_attempt_counters()`로 별도 관리하며, HTTP가 실제로 시작된
> attempt(성공/provider 레벨 실패/crash-after-http-start 전부)마다 정확히
> 1회 호출한다 — pre-HTTP 실패(HTTP 미시작)는 호출하지 않는다.

## 6. Atomic reservation transaction 계약

> **보정 1 반영**: 이 트랜잭션의 유일한 호출자는 **dispatcher**다. 트랜잭션이
> 성공하면 dispatcher는 `ReservationGrant(reservation_id, quota_scope, job_id,
> attempt_no)`를 발급받아 FDC one-shot 호출에 값으로 전달한다. one-shot은 이
> grant의 네 필드가 자신이 실행하려는 job과 일치하는지 검증한 뒤 HTTP 1회만
> 실행하며, **coordinator에게 새 reservation을 절대 요청하지 않는다**(§12 표
> 참고).

```sql
BEGIN;  -- 기본 isolation level(READ COMMITTED), 명시적 상향 불필요

  SELECT * FROM fdc_quota_state
    WHERE quota_scope = 'gemini:shared-operational'
    FOR UPDATE;
    -- 이 행은 배포 시 1회 seed(migration의 INSERT)로 항상 존재한다.
    -- "최근 reservation 행"이 아니라 "항상 존재하는 고정 anchor 행"을 잠그므로,
    -- reservation이 0건인 순간에도 잠금 대상이 없어 발생하는 phantom insert
    -- 경쟁 조건(두 트랜잭션이 동시에 count=0을 보고 각자 INSERT)이 원천 차단된다.

  SELECT count(*) FROM fdc_provider_attempts
    WHERE quota_scope = 'gemini:shared-operational'
      AND outcome IN ('reservation_granted','http_started',
                       'http_succeeded','http_failed_retryable',
                       'http_failed_final','reserved_but_http_not_started')
      AND reserved_at > now() - interval '60 seconds';
    -- reservation 성공 순간부터 60초 동안 quota를 소비한 것으로 간주 —
    -- HTTP 시작 전 worker 실패(reserved_but_http_not_started)도 포함해야
    -- 슬롯 이중 사용을 막는다(보수적 정책).

  IF count < 13:
    INSERT INTO fdc_provider_attempts(attempt_id, job_id, quota_scope, attempt_no, ...,
      outcome='reservation_granted', reserved_at=now())
      RETURNING attempt_id AS reservation_id;
    UPDATE fdc_queue_jobs SET status='reservation_granted', ... WHERE job_id=...;
    -- dispatcher는 이 reservation_id를 ReservationGrant에 담아 FDC one-shot에 전달한다.
  ELSE:
    ROLLBACK;  -- job은 QUEUED에 그대로 남는다. 탈락이 아니다.

COMMIT;
-- ── 불변식: 이 COMMIT 이전에 Gemini HTTP 호출이 발생하지 않는다.
--    트랜잭션/행 잠금을 쥔 채 네트워크 I/O를 수행하지 않는다.
--    commit 이후에만 worker가 즉시 HTTP one-shot을 시작한다.
```

- **DB 장애/lock timeout/트랜잭션 오류 시**: live Gemini HTTP 호출은 **fail-closed**
  — coordinator에 접근할 수 없으면 그 job은 시도하지 않고 `QUEUED`에 남는다(탈락
  아님, 다음 재시도 기회를 기다림). 상세 계약은 바로 아래 "coordinator 오류 경로"
  절에서 확정한다.

### coordinator 오류 경로(보정, 4차 개정 — `queue_poll_count` 항등식과의 충돌 해소)

**충돌 확인**: 이전 초안은 `queue_poll_count = 모든 reservation 확인 시도`와
`queue_poll_count = reservation_denied_count + dispatch_attempt_no`를 동시에
정의했는데, coordinator 오류(DB unavailable/lock timeout/transaction 오류)는
`GRANTED`도 `DENIED`도 아닌 **"결론 자체를 받지 못한" 시도**라 이 항등식에
끼워 넣을 자리가 없었다.

**A/B 비교**:

| 안 | 설명 | 평가 |
|---|---|---|
| **A(채택)** | `queue_poll_count`를 "coordinator가 정상적으로 `GRANTED`/`DENIED` 결론을 반환한 시도"로 재정의. 오류는 이 세 카운터에 전혀 포함하지 않고 별도 로그/메트릭으로만 관측 | DB 자체가 unavailable이면 `fdc_queue_jobs` row를 UPDATE할 방법이 없다는 근본 제약과 정확히 들어맞는다 — "저장할 수 없는 값을 저장하기로 계약해두는" 모순을 피한다 |
| B(`reservation_error_count` 추가, `queue_poll_count = denied + dispatch + error`) | 오류도 영속 카운터로 관리 | **기각** — DB 자체가 내려간 상황에서 "이 job의 `reservation_error_count`를 `+1`하라"는 UPDATE 자체를 실행할 수 없다. 즉 B안이 요구하는 영속 저장이 정확히 그 순간에 불가능한 경우가 이 오류 경로의 **핵심 시나리오**라, "정의는 있으나 저장할 수 없는 필드"라는 자기모순이 생긴다 |

**확정 계약(A안)**:
```
queue_poll_count:
  coordinator가 정상적으로 GRANTED 또는 DENIED 결론을 반환한 횟수만 계산

reservation_denied_count:
  정상 coordinator 응답 중 quota가 가득 차 DENIED된 횟수

dispatch_attempt_no:
  정상 coordinator 응답 중 GRANTED되어 ReservationGrant가 발급된 횟수

queue_poll_count = reservation_denied_count + dispatch_attempt_no
  (오류 경로는 이 항등식 계산에 전혀 참여하지 않으므로 오류가 아무리 나도 깨지지 않는다)
```

**coordinator 오류 상태와 동작(확정 계약)**:
```
QUEUED
  → coordinator 호출(§6 트랜잭션 시도)
  → COORDINATOR_UNAVAILABLE(DB 연결 자체 실패)
    또는 COORDINATOR_LOCK_TIMEOUT(anchor 행 잠금 대기 초과)
    또는 COORDINATOR_TRANSACTION_ERROR(그 외 트랜잭션 실행 오류)
  → Gemini HTTP 미호출(fail-closed)
  → local worker slot 즉시 반환
  → job은 QUEUED 유지
  → backoff 후 재시도(아래 backoff 원칙)
```

1. **오류 분류**: `COORDINATOR_UNAVAILABLE`/`COORDINATOR_LOCK_TIMEOUT`/
   `COORDINATOR_TRANSACTION_ERROR` 3종으로 분류한다. 이 분류는 **DB row가
   아니라 프로세스 로그/메트릭 계층에서만** 기록된다(A안의 핵심 — DB 자체가
   내려간 경우 이 분류값을 그 job의 DB row에 영속 기록할 수 없으므로, 애초에
   그런 계약을 하지 않는다).
2. **`CANCELLED`/`FDC_FAILED_FINAL`/`provider_queue_timeout`이 아닌 이유**:
   - `CANCELLED`가 아닌 이유: `CANCELLED`는 시장 종료/운영자 명시 취소/프로세스
     종료 **오직 세 사유만**으로 한정된 확정 계약(§5)이다 — infra 오류는 이
     셋 중 어디에도 해당하지 않고, job에게 다시 기회를 줘야 하므로 종결
     상태로 보내지 않는다.
   - `FDC_FAILED_FINAL`이 아닌 이유: 이 상태는 **provider(Gemini) 자신의
     실패**(HTTP가 실제로 나갔으나 429/5xx/파싱오류 등으로 실패)를 뜻하는데,
     coordinator 오류는 HTTP 시도 자체가 발생하기 **이전** 단계의 인프라
     문제라 provider 실패와 원인이 다르다.
   - `provider_queue_timeout`이 아닌 이유: 이 reason code는 폐기된 구
     FIFO 설계(§5)의 "시간 경과로 인한 포기" 개념이다. 새 계약에는 "시간이
     지나서 포기"라는 개념 자체가 없으므로 이 이름을 재사용하지 않는다.
3. **worker slot 반환 시점**: coordinator 호출이 예외로 실패하는 **즉시**
   (reservation `DENIED`를 받았을 때와 동일한 원칙 — worker slot을 쥐고
   backoff 대기까지 하지 않는다, §7의 실행 순서와 일치).
4. **hot-loop 방지 backoff 원칙**: **지수 백오프(exponential backoff)를
   권고**한다(고정 간격이 아님) — DB 장애가 지속되는 동안 고정 짧은 간격으로
   재연결을 반복하면 이미 불안정한 DB에 재연결 시도 자체가 부하를 더해
   회복을 늦출 위험이 있다. 권고 초기값 1초, 배수 2, **상한 30초**(신규 설정
   `FDC_COORDINATOR_ERROR_BACKOFF_MAX_SECONDS`, 구현 PR에서 배선). 이 backoff은
   **그 job 하나의 재시도 간격**이며, cycle 전체는 사이클-scoped 순차 모델
   그대로 이 job(과 같은 처지의 다른 job들)이 종결 상태에 도달할 때까지
   순차적으로 대기한다(§4의 순차 cycle 원칙과 동일 — cycle이 병행되지
   않는다는 계약은 DB 오류 상황에서도 변하지 않는다).
5. **DB 복구 후 재시도 조건**: 별도의 "복구 확인" 절차는 두지 않는다 —
   backoff이 끝난 뒤 다음 폴링 시도가 §6 트랜잭션을 그대로 다시 실행하고,
   DB가 응답 가능한 상태로 돌아와 있으면 그 시도가 곧 "정상적인 `GRANTED`
   또는 `DENIED` 응답"이 되어 `queue_poll_count`에 자연스럽게 편입된다.
6. **DB 자체가 내려가 DB row 기록도 불가능한 경우의 최소 관측 근거**(A안의
   핵심 트레이드오프, 구현 후 실측 필요 항목으로도 별도 명시):
   - **프로세스 로그**: dispatcher 프로세스가 구조화된 로그 라인(오류
     분류/`job_id`/타임스탬프)을 표준 출력/로그 파일에 남긴다 — DB와
     무관한 유일한 즉시 기록 수단.
   - **in-memory counter**: dispatcher 프로세스 메모리 안에서만 오류
     발생 횟수를 집계한다 — **재기동 시 소실되는 휘발성 정보**임을
     명시한다(직전 개정에서 확립한 "휘발성 정보 허용" 원칙과 동일선상).
   - **scheduler cycle summary**: 사이클 종료 시 그 사이클 동안 발생한
     coordinator 오류 총량을 in-memory counter로부터 집계해 1줄 로그로
     요약 출력한다(DB 저장 아님, 로그 전용).
   - **DB 복구 후 final job 상태 기록**: DB가 복구된 뒤에는 해당 job의
     `fdc_queue_jobs` row가 정상적으로 계속 갱신되므로, "그 job이 결국
     `FDC_SUCCEEDED`/`FDC_FAILED_FINAL`/`CANCELLED` 중 무엇으로 끝났는가"는
     DB에 남는다 — 다만 **그 사이에 있었던 개별 오류 발생 횟수 자체**는
     DB에 남지 않고 로그로만 남는다는 한계를 명시적으로 인정한다.
7. **DB 오류가 장기간 지속될 때 cycle의 무한 대기 허용 여부**: 사용자의
   "순번이 늦다는 이유로 탈락하지 않는다"는 요구와 **DB 장애로 인한 대기는
   원인이 다르지만, 계약상으로는 동일하게 다뤄진다** — 둘 다 "명시적
   취소 사유(시장 종료/운영자/프로세스 종료) 외에는 시간 경과만으로 자동
   종료하지 않는다"는 원칙을 따른다. 즉 **새로운 자동 시간제한(예: "DB
   오류가 N분 지속되면 자동으로 `CANCELLED`")은 도입하지 않는다** — 이는
   §5가 이미 확정한 "`CANCELLED` 사유 3종 한정"과 상충하기 때문이다. 다만
   이것이 실무적으로 "장애가 나면 그날 장이 끝날 때까지 사이클이 멈춰
   있을 수 있다"는 운영 위험을 그대로 남긴다는 뜻이므로, **이 경우 운영자가
   기존 `CANCELLED(operator_cancel)` 경로로 수동 개입**하는 것을 표준
   대응 절차로 문서화한다(자동 메커니즘 신설이 아니라 기존 사유를 수동으로
   발동하는 운영 절차 — 구현 후 실측/운영 런북 대상, 12절 미확인 사항에도
   중복 명시).

- **60초 경계의 판단 SQL과 사후 검증 SQL 일치(보정 4)**: 판단 SQL은 `reserved_at
  > now() - interval '60 seconds'`(반열림 구간 `(t-60초, t]`, 즉 **정확히 60초
  이전 시각의 reservation은 이번 window에서 제외**된다 — `>`이지 `>=`가 아니다).
  §14의 사후 검증 SQL은 이전 초안에서 `RANGE BETWEEN INTERVAL '60 seconds'
  PRECEDING AND CURRENT ROW` window frame을 썼는데, 이 frame은 **경계값을
  포함**해 판단 SQL의 반열림 규칙과 불일치했다 — §14에서 self-join 기반으로
  같은 `>` 규칙을 쓰도록 정정했다. coordinator 판단, 사후 감사 SQL, fake clock
  테스트(§15) **셋 모두 이 반열림 규칙을 동일하게 적용**하는 것이 13 RPM strict
  계약의 일부다.

## 7. worker·retry·freshness·즉시 저장 계약

**실행 순서(확정)**:
```
local FDC worker slot 확보(asyncio.Semaphore 또는 동등)
→ PostgreSQL atomic reservation(§6)
→ commit
→ 즉시 FDC one-shot HTTP 실행
→ 결과 기록(fdc_provider_attempts UPDATE)
→ local worker slot 반환
```
worker slot을 **먼저** 확보하는 이유: reservation과 실제 HTTP 시작 사이의 시간차를
최소화해, "permit은 받았는데 worker가 없어 대기"로 60초 window의 슬롯이 낭비되는
상황을 막는다.

> **보정 1 반영**: "PostgreSQL atomic reservation" 단계는 dispatcher가
> §6 트랜잭션으로 `ReservationGrant`를 발급받는 것을 뜻하며, "즉시 FDC one-shot
> HTTP 실행" 단계는 그 grant를 값으로 전달받아 소비만 한다 — one-shot 내부에서
> coordinator를 다시 호출하지 않는다(§12 표).

- **reservation 거부**: worker slot 즉시 반환, job은 `QUEUED` 유지.
- **reservation 성공 후 worker 시작 실패**: `RESERVED_BUT_HTTP_NOT_STARTED` 기록
  (quota는 60초간 소비 유지), `pre_http_execution_failure_count`(§9)를 1 증가시킨다.
  `max_pre_http_execution_failures`(신규 설정, 권고 초기값 3) 소진 전엔
  `RETRY_QUEUED`, 소진 시 `FDC_FAILED_FINAL(reason=worker_start_exhausted)` —
  **이 종료는 순번 탈락도 `CANCELLED`도 아닌, `provider_retry_count`와 무관하게
  별도로 집계되는 내부 실행 실패 사유다(보정 3).**
- **`FDC_WORKER_CONCURRENCY`**: 기존 `_SEMAPHORE_MAX`(종목 처리 동시성, 5)와는
  **별개의 설정**으로 신설한다. **초기값 5를 제안하되, 이는 확정값이 아니라
  실측 전 보수적 시작값**이다 — 13 RPM을 실제로 소진할 만큼 충분한지는 구현 후
  실측이 필요하다(13절 미확인 사항).
- **즉시 저장**: job이 `FDC_SUCCEEDED`/`FDC_FAILED_FINAL`에 도달하는 즉시 기존
  `assemble()` 경로로 저장한다 — 배치 전체 종료를 기다리는 방식은 **채택하지
  않는다**(기존 코드의 종목별 즉시 저장 동작을 그대로 보존).
- **freshness**: 기존 `stale_threshold_seconds=900`(계좌 스냅샷)과 주문 직전
  실시간 시세 재조회(`_resolve_quote()`) 메커니즘을 **변경하지 않고 그대로 재사용**
  한다. 배치가 길어져도(§10 계산상 최악 약 9분) 900초 임계값에는 여유가 있다.

## 8. 영속 스키마와 migration 계획(설계, 이번 턴에서 migration 파일 작성 안 함)

### `fdc_quota_state`(신규, singleton anchor 행)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| `quota_scope` | text PK | 고정값 `'gemini:shared-operational'`, migration에서 1행 seed |
| `created_at` | timestamptz | |

### `fdc_queue_jobs`(신규)
| 컬럼 | 비고 |
|---|---|
| `job_id` | UUID PK |
| `decision_cycle_id`, `decision_context_id`, `symbol`, `source_type` | |
| `status` | 인덱스 필요(재기동 후 미완료 조회) |
| `queue_poll_count`, `reservation_denied_count`, `dispatch_attempt_no` | §9 정의(**보정 A** — `reservation_denied_count`가 이전 초안의 스키마 표에서 누락돼 있었음, 이번 개정으로 추가) |
| `provider_retry_count`, `pre_http_execution_failure_count`, `queue_reenqueue_count` | **보정 3** — §9에서 3개로 분리 정의(기존 단일 `retry_count` 폐기) |
| `permit_consumed_count`, `http_attempt_count`, `http_429_count`, `reserved_but_http_not_started_count` | §9 정의 |
| `queued_at`, `completed_at` | |
| `trade_decision_id` | nullable FK → `trade_decisions` |
| `failure_or_cancel_reason` | nullable |
| `created_at`, `updated_at` | |

**`reservation_denied_count`의 저장 위치(보정 — A안 채택)**: 이 필드는 `fdc_queue_
jobs`에 저장한다(대안 B — 별도 event 테이블만으로 재구성하는 안은 채택하지 않음.
이유: 거부는 "이 job이 몇 번이나 순서를 기다리며 밀렸는지"를 나타내는 job 단위
누적 카운터일 뿐, `fdc_provider_attempts`(reservation **성공** 1건=1행 원칙, §8
"원칙" 참고)에 넣으면 "성공한 attempt만 기록한다"는 그 테이블의 불변식이 깨진다).
- **초기값**: `0`(job이 `QUEUED`로 INSERT될 때).
- **증가 시점**: coordinator가 §6 트랜잭션에서 `count ≥ 13`으로 `DENIED`를
  반환할 때마다, 그 job의 `fdc_queue_jobs.reservation_denied_count`를 원자적으로
  `+1`한다(같은 UPDATE 문 안에서 `queue_poll_count`도 함께 `+1`, `dispatch_
  attempt_no`는 증가시키지 않음 — 아래 불변식 참고). **주의**: `DENIED`(정상
  응답)와 coordinator 오류(DB unavailable 등, §6 "coordinator 오류 경로")는
  다른 개념이다 — `DENIED`만 이 카운터를 증가시키고, 오류는 이 카운터에
  전혀 관여하지 않는다(§9의 4차 보정 참고).
- **사용 목적**: `reservation_denied_count`가 특정 lane(예: held_position)이나
  특정 사이클에서 유독 높게 나오면 "그 lane의 job들이 quota 경쟁에서 계속 밀리고
  있다"는 lane 공정성 신호가 된다 — ①단계(lifecycle 관측 shadow, §15)에서 배포
  전 기준선을 잡고, ②③단계 실전 전환 후 이 값의 lane별 분포 변화를 비교하는
  것이 배포 후 실측 계획(§15)의 핵심 지표 중 하나다.
- **job 상태와 attempt 행 집계의 정합성 검증**: `reservation_denied_count`는
  정의상 `fdc_provider_attempts`에 대응 행이 없으므로(거부는 attempt로 기록되지
  않음), 이 필드의 정합성은 다른 방식으로 검증한다 — `queue_poll_count =
  reservation_denied_count + dispatch_attempt_no`(폴링 시도는 거부 아니면
  성공 둘 중 하나로만 귀결되므로)라는 항등식을 job별로 SQL 검증한다(§14).

### `fdc_provider_attempts`(신규, append-only — reservation 1회=attempt 1행)
| 컬럼 | 비고 |
|---|---|
| `attempt_id` | UUID PK(= `reservation_id`로도 사용, §6) |
| `job_id` | **nullable** FK → `fdc_queue_jobs`(보정 2 — 비운영 수동 호출은 `fdc_queue_jobs` row 자체를 만들지 않으므로 NULL 허용) |
| `manual_run_id` | nullable, 수동 호출 전용 식별자(§11, `job_id`가 NULL일 때만 사용) |
| `quota_scope`, `caller_id`(`"ops-scheduler"` / `"manual:<script명>"`), `queue_entry_id` | |
| `attempt_no`, `provider_retry_count` | 이 attempt가 몇 번째 provider retry인지(§9) — pre-HTTP 재시도 횟수는 여기 담지 않고 `fdc_queue_jobs.pre_http_execution_failure_count`로만 집계(attempt row는 매 재시도마다 새로 생기므로 job 쪽에서 누적) |
| `reserved_at`, `http_started_at`(nullable), `completed_at`(nullable) | `(quota_scope, reserved_at)` 인덱스 필수(§14 self-join 감사용) |
| `outcome`, `http_status`(nullable), `error_class`(nullable), `http_429_observed` | |
| unique 제약 `(job_id, attempt_no)` | `job_id IS NOT NULL`일 때만 의미(운영 FDC), 수동 호출은 `(manual_run_id, attempt_no)`로 별도 unique 고려 — 구현 PR에서 부분 unique index로 확정 |

**테이블 이름 확정(보정 2 반영)**: `job_id`가 nullable이고 `caller_id`/`manual_
run_id`로 이미 운영·수동 트래픽을 함께 수용하는 범용 구조이므로, **테이블 이름을
`gemini_provider_attempts`로 바꾸지 않고 `fdc_provider_attempts`를 유지**한다 —
FDC가 이 quota_scope의 유일한 운영 소비자이고, 수동 호출은 예외적 부가 사용자일
뿐이라 이름을 일반화할 실익이 적다고 판단했다(구현 PR에서 재검토 가능).

**원칙**: attempt row는 reservation 시 INSERT하고, 이후 같은 row를 HTTP 시작/종료
정보로 UPDATE한다(하나의 "실행 기회"는 하나의 사건이므로 별도 event 테이블로 더
쪼개지 않는다 — 현재 규모에서 과잉 정규화). **삭제·재사용 없음**(append-only).

## 9. Accounting 정의(확정, 보정 3 반영 — retry 계수 3분리)

| 필드 | 정의 |
|---|---|
| `queue_poll_count` | **coordinator가 정상적으로 `GRANTED` 또는 `DENIED` 결론을 반환한** 확인 시도 횟수(보정 — coordinator 오류로 결론 자체를 못 받은 시도는 포함하지 않는다, §6·§9 하단 오류 경로 참고) |
| `reservation_denied_count` | 정상 coordinator 응답 중 13 RPM window가 가득 차 `DENIED`를 받은 횟수 |
| `dispatch_attempt_no` | 정상 coordinator 응답 중 `GRANTED`되어 `ReservationGrant`가 발급된 횟수 — `DENIED` 시에는 증가하지 않는다(보정, 이전 초안의 모순 표현 정정) |
| **`provider_retry_count`** | 실제 HTTP가 **시작된 뒤** retryable provider 오류(429/5xx/timeout/DNS)로 FIFO tail에 재등록된 횟수 — `http_started_at IS NOT NULL`인 attempt에서만 증가 |
| **`pre_http_execution_failure_count`** | reservation 성공 후 **HTTP 시작 전**(`http_started_at IS NULL`)에 worker/subprocess 생성·취소 등으로 실패해 재등록된 횟수 |
| **`queue_reenqueue_count`** | `= provider_retry_count + pre_http_execution_failure_count`(파생 지표, "FIFO tail에 총 몇 번 재등록됐는지"만 알고 싶을 때 참조) |
| `permit_consumed_count` | 성공 reservation 수(`fdc_provider_attempts`에 `reservation_granted` 이상으로 기록된 행 수) |
| `http_attempt_count` | `http_started_at IS NOT NULL`인 attempt 수 |
| `http_429_count` | `http_status=429`인 attempt 수 |
| `reserved_but_http_not_started_count` | `outcome='reserved_but_http_not_started'`인 attempt 수(= `pre_http_execution_failure_count`의 attempt-행 기준 합계와 일치해야 함, §14 정합성 검증 대상) |

**불변식(보정 후 확정)**:
```
provider_retry_count <= max_http_attempts - 1        (= 2, MAX_RETRIES=3 기준)
pre_http_execution_failure_count <= max_pre_http_execution_failures
queue_reenqueue_count = provider_retry_count + pre_http_execution_failure_count
http_attempt_count <= permit_consumed_count
queue_poll_count = reservation_denied_count + dispatch_attempt_no   (보정 — 폴링 시도는 거부/성공 둘 중 하나로만 귀결)
reservation count <= 13 per any sliding 60-second window  (§6 트랜잭션이 보장)
```

**reservation 거부/성공 시 정확한 증가 규칙(보정, 이전 초안의 모순 정정)**:
```
reservation denied(coordinator가 count>=13으로 DENIED 반환):
  queue_poll_count += 1
  reservation_denied_count += 1
  dispatch_attempt_no 증가 없음
  permit_consumed_count 증가 없음
  http_attempt_count 증가 없음
  job은 QUEUED 유지(§6 ROLLBACK 경로)

reservation granted(coordinator가 count<13으로 승인, ReservationGrant 발급):
  queue_poll_count += 1
  dispatch_attempt_no += 1
  permit_consumed_count += 1
  (이후 실제 HTTP 시작 여부는 §7의 worker 실행 결과에 달려 있으며, 그 결과에
   따라 http_attempt_count 또는 pre_http_execution_failure_count가 추가로
   증가한다 — 아래 사례 참고)

coordinator error(DB unavailable / lock timeout / transaction 오류 — GRANTED도
DENIED도 아닌 "결론 자체를 못 받은" 경우, 아래 §6-보정 참고):
  queue_poll_count 증가 없음
  reservation_denied_count 증가 없음
  dispatch_attempt_no 증가 없음
  → 이 세 카운터의 항등식(queue_poll_count = reservation_denied_count +
    dispatch_attempt_no)은 오류 경로에서 애초에 셋 다 건드리지 않으므로
    깨지지 않는다.
```

**세 계수가 항상 같지 않은 이유(사례별)**:
- `reservation_denied_count`만 증가하고 `dispatch_attempt_no`/`permit_consumed_
  count`/`http_attempt_count`는 불변 — reservation이 **거부**된 경우(worker
  slot만 반환, HTTP는 애초에 시도되지 않음, 위 불변식 참고).
- `dispatch_attempt_no`와 `permit_consumed_count`는 증가했으나 `pre_http_
  execution_failure_count`만 추가로 증가 — reservation은 받았으나 worker 시작
  자체가 실패한 경우(`http_attempt_count`는 불변).
- `dispatch_attempt_no`/`permit_consumed_count`/`http_attempt_count`/
  `provider_retry_count`가 모두 증가 — HTTP가 실제로 나갔으나 429/5xx로
  실패한 경우.

이전 초안의 단일 `retry_count`는 위 두 계수를 혼재시켜 `retry_count ≤ max_http_
attempts-1` 불변식이 pre-HTTP 실패 재등록까지 포함하면 깨지는 문제가 있었다 —
이번 보정으로 **`retry_count`라는 이름은 이 문서에서 더 이상 쓰지 않는다**(전부
`provider_retry_count`/`pre_http_execution_failure_count`/`queue_reenqueue_
count` 중 하나로 대체).

**명명 전환**: `MAX_RETRIES=3`(총 HTTP 시도 수)이라는 기존 이름이 실제 의미와
혼동되므로, **신규 설계 문서·신규 코드에서는 `max_http_attempts=3`으로 명명**한다
(기존 `provider_client.py`의 모듈 상수 자체는 이번 문서화 턴에서 변경하지 않음 —
구현 PR에서 리네이밍 여부와 영향 범위 전수 확인 후 결정).

## 10. 13 RPM 용량 계산(확정 계산식, 실측 아님)

```
필요 dispatch 묶음 수 = ceil(A / 13)   (A = 실제 총 HTTP 시도 수)
마지막 HTTP 시작 기준 ≈ (ceil(A/13) - 1) × 60초 + worker 지연
마지막 완료 기준 ≈ 위 값 + provider 실행 시간(+ 재시도 backoff 누적)
```

- **40개 최초 job, 전원 첫 시도 성공(A=40)**: `ceil(40/13)=4` → 마지막 HTTP 시작
  ≈ 180초, 완료 ≈ **약 3.3분**.
- **총 HTTP 시도 120회 극단(A=120, `max_http_attempts=3` 전원 소진)**: `ceil(120/13)
  =10` → 마지막 HTTP 시작 ≈ 540초, 완료 ≈ **약 9~9.5분**(재시도 backoff 포함).

## 11. 수동 provider 호출 정책(확정, 보정 2 — A안 채택으로 정정)

**정책 비교**:

| 안 | 평가 |
|---|---|
| **A(운영 중 기술적 fail-closed 차단, 비운영 수동 호출은 coordinator reservation만 사용하고 FDC queue job은 만들지 않음)** | **채택** — 운영 FDC 판단 기회를 전혀 지연시키지 않는다(수동 호출이 FDC FIFO에 아예 들어오지 않으므로 worker slot·FIFO 순서 경쟁 자체가 없음). `fdc_queue_jobs.job_id` FK는 항상 실제 FDC job만 가리키면 되므로 정합성이 단순하다. 구현 복잡성 최소(synthetic job lifecycle을 별도로 설계할 필요 없음). 13 RPM strict는 quota_scope 공유만으로 유지된다 |
| B(수동 호출도 synthetic `fdc_queue_job`을 만들어 FDC와 같은 전역 FIFO에 편입) | 기각 — synthetic job의 lifecycle·source_type·우선순위·worker slot 정책을 전부 새로 정의해야 하는데, 수동 분석 호출은 애초에 FDC의 실행 결과(assemble/저장)와 결합될 필요가 없어 "FDC job"이라는 개념 자체가 이 트래픽에 맞지 않는다. 정의가 불완전한 채로 채택하지 않는다(사용자 지침대로 B안은 완전한 정의가 없으면 배제) |

**이전 초안 정정**: "수동 호출도 `fdc_queue_jobs.job_id`가 필요하다"는 이전 문장을
**폐기**한다. 확정 정책은 다음과 같다.

1. **운영 시간(정규장 중) 수동 live provider 호출은 기술적으로 차단된다** —
   절차적 금지 문구만으로 충분하다고 서술하지 않는다. 기술적 강제는 §12의
   `LiveGeminiProviderClient` 생성자가 coordinator 없이는 인스턴스화 자체를
   거부하는 것과, coordinator 쪽에서 운영 시간대에는 `caller_id`가
   `"manual:*"`인 reservation 요청을 무조건 거부(fail-closed)하는 것 **둘
   다**로 구성한다(운영 시간 판정은 기존 `Market-hours` 관련 코드/설정을
   재사용 — 이번 문서에서 새로 발명하지 않음, 구현 PR에서 정확한 재사용
   지점을 확인).
2. **비운영 시간 수동 호출**은 공용 quota coordinator를 통해 `reservation`을
   얻는다 — 즉 `fdc_quota_state`(§6)의 같은 anchor 행을 잠그고 같은 60초
   sliding window 집계에 참여한다. 다만 **FDC batch dispatcher의 FIFO 큐나
   `FDC_WORKER_CONCURRENCY` slot을 전혀 점유하지 않는다** — 수동 호출은 자체
   프로세스 안에서 스스로 worker 역할을 겸한다.
3. 비운영 수동 호출의 provider attempt는 `fdc_provider_attempts.job_id=NULL`,
   `manual_run_id`(호출 시각+스크립트명 기반, 구현 PR에서 생성 규칙 확정)로
   연결한다(§8).
4. 위 3번에 따라 `fdc_provider_attempts.job_id`는 **nullable**이다(§8에서
   이미 반영). 테이블 이름은 `fdc_provider_attempts`를 유지한다(§8 근거).
5. `fdc_queue_jobs`에는 수동 호출 row를 **만들지 않는다** — 이 테이블은 순수
   FDC batch job 전용으로 남는다.

**수동 트래픽이 FDC 판단 기회를 늦추지 않는 방법**: A안 채택으로 수동 호출은
FDC FIFO에 전혀 편입되지 않으므로 "늦춘다"는 상황 자체가 구조적으로 발생하지
않는다 — 유일한 공유 지점은 `fdc_quota_state` anchor 행의 60초 sliding window
집계뿐이며, 운영 시간대에는 그 지점조차 fail-closed로 차단되므로 실질적인
경쟁이 없다.

## 12. Live provider fail-closed 경계(확정, 보정 1 — reservation 경로 표로 명확화)

- 실제 Gemini HTTP를 낼 수 있는 구현체(`LiveGeminiProviderClient`, 신규 명명 제안)는
  **coordinator 의존성 없이는 생성·실행 불가능**하게 한다(생성자 필수 인자).
- fake/test provider는 **별도 구현체**(`FakeProviderClient`)로 분리 — `live_provider
  =False` 같은 **플래그 방식은 채택하지 않는다**(오설정 우회 위험, 사용자 지적 반영).
- FDC 전용 `generate_structured_once()`는 dispatcher가 permit/retry/backoff를
  전담하기 위한 **최소 신규 인터페이스**다. 기존 공용 `generate_structured()`(EI/AR/
  AC 구식 클래스가 참조하나 운영 비활성)는 **무근거로 변경하지 않는다**.
- raw provider client 직접 호출(`ar_fdc_provider_validation.py` 등)과 두 분석
  스크립트 모두 **같은 강제 지점**(`LiveGeminiProviderClient` 생성자)을 통과해야
  하므로 개별적으로 막을 필요가 없다.

**reservation 경로 분리표(보정 1의 핵심 산출물)** — 어느 함수가 coordinator에게
"새 reservation을 요청"하는지, 아니면 "이미 발급된 grant를 소비만" 하는지를
명확히 구분한다:

| 호출 경로 | reservation을 새로 요청하는가? | 실행 주체 |
|---|---|---|
| FDC batch dispatcher | **예** — §6 트랜잭션의 유일한 호출자 | dispatcher(cycle-scoped) |
| `generate_structured_once(grant)`(FDC 전용, 신규) | **아니오** — dispatcher가 전달한 `ReservationGrant`를 검증·소비만 함, coordinator를 호출하지 않음 | FDC worker(HTTP 1회) |
| `generate_structured()`(공용, 기존 유지) | **경로에 따라 다르다** — 운영 EI/AR/AC 경로에서는 애초에 호출되지 않음(비활성). 비운영 수동 스크립트가 이 함수를 직접 쓴다면, `LiveGeminiProviderClient`가 **자체적으로** coordinator에 reservation을 요청(운영 시간대엔 fail-closed 거부, §11 정책 1) | 수동 스크립트 프로세스 |
| raw HTTP client(coordinator 완전 우회 시도) | 시도 자체가 **생성 단계에서 차단**(`LiveGeminiProviderClient` 생성자가 coordinator 의존성 없이는 인스턴스화 거부) | — |

이 표가 **보정 1의 확정 계약**이다: dispatcher가 발급받은 reservation을 FDC
one-shot이 다시 요청하는 이중 소유는 구조적으로 발생하지 않으며, `generate_
structured()`는 FDC 배치 경로에서는 아예 쓰이지 않고 오직 "coordinator를
직접 호출하는 다른 경로"(비운영 수동 스크립트)에서만 자체 reservation을 요청
한다 — 두 함수가 "같은 job에 대해 동시에" reservation을 다투는 경우가 없다.

## 13. 설정 계약(확정, 값은 구현 PR에서 실제 배선)

| 키 | 기본값 | 용도 |
|---|---|---|
| `FDC_PROVIDER_TARGET_RPM` | `13` | 운영 목표 |
| `FDC_PROVIDER_RATE_WINDOW_SECONDS` | `60` | sliding window 길이 |
| `GEMINI_PROVIDER_DECLARED_RPM_LIMIT` | `15` | 문서/startup validation 전용(코드가 강제 호출하는 값 아님) |
| `FDC_WORKER_CONCURRENCY` | `5`(실측 전 보수적 시작값) | FDC 전용 동시 실행 수 |
| `FDC_QUOTA_COORDINATOR_BACKEND` | `"postgres"` | 백엔드 선택(현재 단일 값만 지원) |
| `FDC_COORDINATOR_ERROR_BACKOFF_INITIAL_SECONDS` | `1` | coordinator 오류(§6) 시 job 재시도 지수 backoff 초기값 |
| `FDC_COORDINATOR_ERROR_BACKOFF_MAX_SECONDS` | `30` | 위 backoff 상한(hot-loop 방지) |

startup validation(구현 PR 대상): `FDC_PROVIDER_TARGET_RPM < GEMINI_PROVIDER_
DECLARED_RPM_LIMIT`, 모든 수치형 값 `> 0`. 배선 경로: `.env.example` 주석 추가 →
`settings.py` 필드 → dispatcher가 `settings`에서 읽어 명시적으로 전달(현재처럼
함수 기본값에 암묵 의존하지 않음) → `docker-compose.yml`의 `ops-scheduler`
`environment:` 블록. **이번 문서화 턴에서 `.env`/`.env.example`/compose/migration
실제 수정 없음** — 구현 PR 대상.

## 14. 관측(감사) SQL 요구사항(보정 4 — 60초 경계 규칙을 §6 판단 SQL과 일치시킴)

**정정 사유**: 이전 초안의 `RANGE BETWEEN INTERVAL '60 seconds' PRECEDING AND
CURRENT ROW` window frame은 **정확히 60초 이전 행을 포함**하는데(Postgres RANGE
frame은 경곗값 포함), §6의 coordinator 판단 SQL은 `reserved_at > now() -
interval '60 seconds'`로 **경곗값을 제외**한다 — 이 불일치가 있으면 coordinator가
"13개 미만이라 승인"한 상황을 감사 SQL이 "실제로는 14개였다"고 다르게 셀 수
있었다. 아래는 self-join으로 **동일한 `>` 반열림 규칙**을 적용한 정정판이다.

```sql
-- 임의 sliding 60초 구간 reservation 수 최댓값(13 초과 여부 검증)
-- ── §6 판단 SQL과 동일한 반열림 구간 (t-60초, t] 규칙을 self-join으로 재현
SELECT max(window_count) FROM (
  SELECT anchor.reserved_at,
         count(candidate.attempt_id) AS window_count
  FROM fdc_provider_attempts anchor
  JOIN fdc_provider_attempts candidate
    ON candidate.quota_scope = anchor.quota_scope
   AND candidate.reserved_at > anchor.reserved_at - interval '60 seconds'
   AND candidate.reserved_at <= anchor.reserved_at
   AND candidate.outcome IN ('reservation_granted','http_started','http_succeeded',
                              'http_failed_retryable','http_failed_final',
                              'reserved_but_http_not_started')
  WHERE anchor.quota_scope = 'gemini:shared-operational'
  GROUP BY anchor.reserved_at
) w;
-- 정확히 60초 이전(anchor.reserved_at - 60초)의 reservation은 `>` 조건에 의해
-- 이번 window에서 제외된다 — §6 coordinator 판단과 동일한 규칙.

-- 실제 HTTP 시작 수 최댓값도 같은 self-join 패턴을 http_started_at 기준으로 적용
-- reserved_at은 있으나 http_started_at 없는 attempt(reserved_but_http_not_started)
-- caller_id별 quota 소비량
-- job별 permit_consumed_count와 attempt 행 수 정합성(HAVING 불일치)
-- 재기동 뒤 미완료 job 및 마지막 상태(status NOT IN 종결상태)
-- provider_queue_timeout reason code가 신규 경로에서 생성되지 않았는지(기대값 0)

-- (보정) job별 queue_poll_count = reservation_denied_count + dispatch_attempt_no 정합성 검증
SELECT job_id, queue_poll_count, reservation_denied_count, dispatch_attempt_no
FROM fdc_queue_jobs
WHERE queue_poll_count <> reservation_denied_count + dispatch_attempt_no;
-- 기대 결과: 0 rows. 1행이라도 나오면 coordinator 호출 지점이 두 카운터 중
--하나를 누락하고 있다는 뜻이다.
```

fake clock 기반 테스트(§15)도 이 self-join 규칙과 동일한 경계(정확히 60초 전
= 제외)로 어서션을 작성해야 한다 — coordinator, 감사 SQL, 테스트 셋 모두 같은
반열림 규칙을 쓰는 것이 13 RPM strict 계약의 일부다.

(전체 SQL 원문은 이전 설계 검토 세션 로그에 보존, 구현 PR에서 뷰/함수로 정리 예정.)

## 15. 테스트 · shadow · 단계적 전환 계획

**필수 테스트 시나리오**(구현 PR 대상, fake clock/fake PG repository/fake provider,
실제 sleep·외부 API 없음): (1) 동시 2 caller가 합산 13건까지만 승인, (2) reservation
0건 상태에서 phantom insert 미발생, (3) DB 장애 시 fail-closed, (4) worker slot
확보 전 reservation 미소비, (5) reservation 후 HTTP 전 실패 시 quota 60초 소비 +
`reserved_but_http_not_started` 기록 + `pre_http_execution_failure_count` 증가
(보정 3), (6) `generate_structured_once(grant)`가 전달받은 grant만 소비하고
coordinator에게 새 reservation을 절대 요청하지 않음(보정 1의 핵심 검증), (7) 임의
60초 구간 reservation/HTTP 시작 수 ≤ 13이며 **정확히 60초 전 reservation은 제외**
(보정 4의 경계 규칙, §14 self-join과 동일 어서션), (8) 운영 시간대 `caller_id=
"manual:*"` reservation이 fail-closed로 거부됨 + 비운영 시간대는 승인되나 FDC
FIFO/worker slot을 점유하지 않음(보정 2, A안), (9) coordinator 없는 raw 호출
차단, (10) fake provider는 coordinator 없이도 정상 동작, (11) job 상태와 attempt
기록 수치 일관(`provider_retry_count`/`pre_http_execution_failure_count`/
`queue_reenqueue_count` 각각 별도 검증), (12) 40개/120개 극단 조건의 dispatch
스케줄이 §10 계산과 일치, (13) reservation 거부 시 `dispatch_attempt_no`는
증가하지 않고 `reservation_denied_count`만 증가함 + 승인 시 반대(§9 보정 규칙
직접 검증), (14) 임의 job에 대해 `queue_poll_count = reservation_denied_count
+ dispatch_attempt_no` 항등식이 항상 성립, (15) DB connection 실패를 fake
repository로 재현했을 때 Gemini HTTP 시도가 0회임을 확인, (16) lock timeout/
transaction 오류 시 local worker slot이 즉시 반환됨, (17) coordinator 오류가
`reservation_denied_count`/`dispatch_attempt_no`/`queue_poll_count` 어느 것도
증가시키지 않아 (14)의 항등식이 오류 경로에서도 깨지지 않음(A안 핵심 검증),
(18) 지수 backoff이 고정 간격이 아니라 매 실패마다 증가하며 상한
(`FDC_COORDINATOR_ERROR_BACKOFF_MAX_SECONDS`)에서 멈추고, fake DB가
"복구"(성공 응답으로 전환)되면 다음 폴링에서 즉시 정상 재개됨, (19)
coordinator 오류가 반복되는 동안에도 `CANCELLED`(시장 종료/운영자/프로세스
종료 3사유 외)가 자동으로 발동하지 않음(job이 순번·오류 어느 이유로도
자동 제거되지 않는다는 계약의 직접 검증).

**단계적 도입**: ① lifecycle 관측(quota_state/queue_jobs/attempts 스키마 + shadow
기록, 실제 dispatch 동작은 미변경) → ② held_position lane 한정 실전 전환 → ③ 전체
lane(core 포함) 전환. 각 단계에서 §14 SQL로 실측(FDC 대상 수/permit grant 수/queue
대기 분포/timeout/cancellation/HTTP attempt·429/cycle wall-clock/stale 차단/최종
decision·order 영향/lane 공정성)을 수행한다.

## 16. 위험 · 롤백 · 확정된 구현 계약 vs 구현 후 실측 필요

### 확정된 구현 계약(이번 문서로 확정, 구현 PR은 이를 그대로 따른다)
- Cycle-scoped(순차 유지), dispatcher 완전 소유 permit(FDC one-shot은 발급받은
  `ReservationGrant`를 소비만 하고 재요청하지 않음 — 보정 1), PostgreSQL
  anchor-row atomic reservation(§6), FDC one-shot 인터페이스 신설(공용
  `generate_structured()` 불변), 즉시 저장(배치 종료 대기 안 함), `CANCELLED`
  사유 3종 한정, `fdc_queue_jobs`+`fdc_provider_attempts`(`job_id` nullable)+
  `fdc_quota_state` 3-테이블 스키마, 운영 시간 수동 호출 기술적 fail-closed
  차단 + 비운영 시간 수동 호출은 coordinator만 공유하고 FDC FIFO/worker slot은
  점유하지 않음(A안 — 보정 2), `provider_retry_count`/`pre_http_execution_
  failure_count`/`queue_reenqueue_count` 3분리 accounting(보정 3), coordinator
  판단·감사 SQL·테스트 전부 동일한 `(t-60초, t]` 반열림 경계 규칙 사용(보정 4),
  `dispatch_attempt_no`는 reservation **성공 시에만** 증가하고 `reservation_
  denied_count`는 `fdc_queue_jobs`에 저장해 `queue_poll_count = reservation_
  denied_count + dispatch_attempt_no`를 항상 만족(accounting 정합성 보정),
  coordinator 오류(DB unavailable/lock timeout/transaction 오류)는 위 세
  카운터 어디에도 포함하지 않고 프로세스 로그/in-memory counter로만 관측하며
  (A안), 그 오류로 job이 `CANCELLED`/`FDC_FAILED_FINAL`로 자동 전이되지
  않고 지수 backoff 후 계속 재시도(4차 보정).

### 구현 후 실측 필요(이번 문서로 확정하지 않음, 값·성능은 구현 후 검증)
- `FDC_WORKER_CONCURRENCY=5`가 13 RPM을 실제로 소진하기에 충분한지.
- PG 행 잠금이 사이클 실제 트래픽에서 유발하는 지연 정도(이론상 미미하나 실측 없음).
- `MAX_RETRIES`→`max_http_attempts` 리네이밍의 전체 참조처 영향 범위.
- 두 분석 스크립트를 `LiveGeminiProviderClient`로 전환했을 때 기존 사용 방식(비교
  검증 등)에 미치는 영향.
- Gemini의 실제 quota 적용 단위(API 키/프로젝트/모델) — 외부 provider 정책, 이
  문서로 확정 불가.
- §11에서 "운영 시간 판정은 기존 market-hours 관련 코드/설정을 재사용한다"고
  명시했으나, 정확히 어느 기존 함수/설정을 재사용할지는 구현 PR에서 확인이
  필요하다(이번 문서화 턴에서 코드 근거로 특정하지 않음, 보정 2 관련).
- coordinator 오류 시 dispatcher 프로세스 로그/in-memory counter만으로
  운영자가 "DB 장애로 몇 개 job이 얼마나 오래 대기했는지"를 사후 파악하기에
  충분한지는 구현 후 실제 장애 상황(또는 fault-injection 테스트)으로 검증이
  필요하다 — 이번 설계는 "저장 불가능한 상황에서는 로그로만 관측한다"는
  원칙만 확정했고, 그 로그의 구체적 포맷/보존 기간/알림 연동은 구현 PR 대상.
- `FDC_COORDINATOR_ERROR_BACKOFF_INITIAL_SECONDS=1`/`_MAX_SECONDS=30`이
  적정한 값인지는 실제 DB 장애 복구 시간 분포에 대한 실측 없이 제안한
  보수적 시작값이다.

### 롤백
전부 신규 테이블·신규 인터페이스 추가이며 기존 `fdc_rate_limiter.py`/`run_agent_
subprocess.py`의 기존 경로를 즉시 제거하지 않고 병행 가능(①단계 shadow 방식) —
문제 발생 시 신규 dispatcher 호출부만 되돌리면 기존 경로로 즉시 복귀 가능하다(구현
PR에서 feature flag로 전환 여부를 감쌀 것을 권고).

---

## 17. Pre-FDC/FDC subprocess 분리 설계(신설, 2026-08-27)

### 17.1 현재 구조(코드 근거)

- `decision_orchestrator.py:2946` — `assemble()`이 `self._run_agents_in_
  subprocess(request=agent_request, assembled_context=ai_policy_context)`를
  호출한다. subprocess 미사용 시 대안 경로는 `2959`행 `self._run_agents(...)`
  (in-process, `AGENT_SUBPROCESS_ISOLATION=0`일 때만 — 운영 기본값은 `"1"`).
- `_run_agents_in_subprocess()`(`decision_orchestrator.py:3687-3696`)는 얇은
  wrapper로 `DecisionAgentRunner.run_agents_in_subprocess()`(`decision_
  agent_runner.py:654-788`)에 위임한다. 이 메서드가 입력 전체를 직렬화(682행)해
  `python -m scripts.run_agent_subprocess`를 **단일 subprocess로 1회** spawn(698행)
  하고 `proc.communicate()`로 stdin/stdout 전체를 주고받는다(706-710행).
- `scripts/run_agent_subprocess.py::main()`(1212행~) 내부에서 **EI(1273-1315)
  → AR(1317-1347) → AC(1349-1384) → FDC skip 판정(`_check_fdc_skip()`, 1387행)
  → (skip 아니면) FDC 실제 HTTP 호출(1460행대)**이 전부 한 프로세스 안에서
  순차 실행된다.
- 즉 오늘 기준으로 "pre-FDC(EI/AR/AC)만 먼저 끝내고 FDC는 나중에"라는 개념이
  **프로세스 수준에서 물리적으로 존재하지 않는다** — 한 번의 subprocess
  invocation이 EI/AR/AC/FDC를 통째로 처리하고 끝난다.

### 17.2 확정 아키텍처: 두 개의 CLI 진입점

기존 `run_agent_subprocess.py`를 폐기하지 않고, **동일 파일 안에** 두 번째
진입점을 신설한다(완전히 새 파일로 쪼개면 EI/AR/AC 실행 코드를 중복해야 하므로
"최소 변경"에 위배된다).

- **`run_agent_subprocess.py --mode pre_fdc`**(신규 인자, 기본값 `full`=기존
  동작 그대로 보존): EI(1273-1315) → AR(1317-1347) → AC(1349-1384) →
  `_check_fdc_skip()`(1387)까지만 실행하고, **FDC skip이면 기존과 동일하게
  결정론적 fallback까지 끝내 최종 output을 반환**(FDC-ready가 아니므로 분리할
  이유가 없다). **FDC-ready(skip 아님)면 FDC를 호출하지 않고 즉시 반환** —
  대신 `AgentSubprocessOutput`에 신규 필드 `pre_fdc_carryover: dict | None`을
  추가해, FDC 재개에 필요한 최소 상태(17.3)를 JSON-safe dict로 담아 반환한다.
- **`run_agent_subprocess.py --mode fdc_only`**(신규): stdin으로 `pre_fdc_
  carryover` dict + FDC 실행에 필요한 provider 설정(기존과 동일하게 stdin으로
  전달)을 받아, `_run_fdc_with_outer_timeout()`(1138-1200, 기존 함수 그대로
  재사용)부터 시작해 FDC 결과만 담은 `AgentSubprocessOutput`을 반환한다.
  EI/AR/AC 관련 필드는 호출자가 `pre_fdc` 단계의 output과 병합하므로 이
  모드에서는 채우지 않는다(또는 placeholder로 채워 스키마를 그대로 재사용).
- **`--mode full`**(기존 동작, 신규 feature flag가 꺼져 있을 때 유일하게
  쓰이는 경로): 오늘과 완전히 동일 — EI→AR→AC→FDC를 한 번에 실행. **분리
  모드는 신규 feature flag(§20)가 켜졌을 때만 선택된다.**

### 17.3 pre-FDC 결과 보관에 필요한 최소 상태(carryover 계약, 2026-08-28
6차 보정 — PR #359 4~5차 리뷰 보정으로 아래 표/결정을 실제 구현에 맞게
정정)

**최종 결정(원래 안과 다름)**: carryover는 **in-memory 전용이 아니다** —
ops-scheduler는 항상 `scripts.run_decision_loop --count 1`로 단발
프로세스를 spawn하므로, cycle 하나가 끝나면 이 job의 carryover를 들고
있던 프로세스도 함께 종료된다. in-memory carryover만으로는 quota
포화로 이번 cycle 안에 완결되지 못한 job을 **다음 프로세스가 재개할
방법이 전혀 없다.** 이 때문에 `fdc_queue_jobs`에 최소 payload를
영속화하는 쪽으로 방향을 바꿨다(migration `0069_add_fdc_queue_jobs_
carryover_columns.sql`).

| 필드 | 저장 여부 | 근거 |
|---|---|---|
| `pre_fdc_result`(EI/AR/AC structured output 병합 dict, `requires_fdc_dispatch`/`fdc_ready_at` 포함) | **저장한다**(`fdc_queue_jobs.pre_fdc_result_json JSONB`) | pre_fdc subprocess가 이미 만드는 JSON-safe dict를 그대로 저장 — agent를 재호출하지 않고 재개하는 데 필수 |
| `correlation_id` | **저장한다**(`fdc_queue_jobs.correlation_id TEXT`) | fdc_only payload 구성과 audit trail 연결에 필수 |
| `symbol`/`source_type`/`decision_cycle_id`/`decision_context_id`/`fdc_ready_at` | **저장한다** | §8 원래 설계의 job 메타데이터 컬럼을 그대로 재사용(신규 컬럼 아님) |
| `assembled_context`(position/cash/risk snapshot·recent_events·score 등) | **저장하지 않는다** | freshness-sensitive — 재개 시점에 이미 낡았을 수 있는 값을 그대로 쓰면 안전 가드(risk/EV/sizing)가 stale 데이터로 판정할 위험이 있다 |
| `market`/`market_segment`/`index_memberships`/`universe_anchor` 등 cycle-local 메타데이터 | **저장하지 않는다** | resume 시점에 새 프로세스가 이미 다시 읽은 현재 universe에서 조회한다 — symbol이 더 이상 universe에 없으면 §17.7이 정의하는 fail-closed 종결로 처리 |

**핵심 원칙**: override→EV-gate→sizing→submit 단계는 **항상 fresh
context로 재계산**한다(`DecisionOrchestratorService.assemble()`의
`precomputed_agent_bundle` 분기가 그 시점에 새로 조회한 context를 그대로
쓴다) — resume이 같은 프로세스 안에서 일어나든(cross-cycle) 다른
프로세스에서 일어나든(durable, §17.7) 이 원칙은 동일하다. `complete_
fdc_actual_dispatch()`는 이 원칙에 따라 `assembled_context`를 아예
받지 않으며, EV anchor 적용도 `assemble()`의 `precomputed_agent_bundle`
분기로 옮겨졌다 — freshness-sensitive한 값을 durable하게 들고 다닐
필요를 원천적으로 없앤다. EI/AR/AC의 structured output(`pre_fdc_
result`) 자체는 "그 시점의 분석 결과"이므로 freshness 문제가 없다 —
재분석이 아니라 재사용이 목적이다.

### 17.4 dispatcher 통합 지점(§15 재사용)

`run_decision_loop.py`의 기존 Pass 1.5/Pass 2 패턴(`_run_general_lane_
pass2`/`_submit_general_lane_candidate`, 2967-3250행)을 뼈대로 재사용한다 —
"cycle 전체 `asyncio.gather()` 완료 직후(3639-3644행) → 보류 상태 수집 →
정렬/우선순위화 → 순차 후속 처리"라는 흐름은 동일하되, Pass2가 이미 FDC까지
끝난 `intent`를 보관하는 것과 달리, 신규 dispatcher는 **FDC 이전** 상태
(carryover)를 보관한다:

```
_process_one() 각 심볼(§17.2 --mode pre_fdc)
  → FDC-ready면 carryover를 pending_fdc_dispatch_sink에 적재(기존
    pending_general_candidates와 동형의 sink)
  → FDC skip이면 기존과 동일하게 즉시 assemble() 경로로 저장

asyncio.gather() 완료(3639-3644행, 기존 지점 그대로)
  → (신규) FDC dispatcher 실행: pending_fdc_dispatch_sink의 모든 job을
    §4/§7 계약대로 처리(worker slot → reservation → --mode fdc_only
    subprocess 실행 → 결과 수신)
  → job이 종결(FDC_SUCCEEDED/FDC_FAILED_FINAL)되는 즉시 carryover와 FDC
    output을 병합해 decision_orchestrator의 override→EV→sizing→submit
    경로(2976행 이후, 기존 코드 그대로 재사용)를 호출 — 배치 전체 종료를
    기다리지 않는다(§7 "즉시 저장" 원칙)
  → 전 job 종결까지 다음 cycle 시작 안 함(§4 "사이클 종료" 조건 그대로)
```

override→EV→sizing→submit 경로(2976행 이후)를 재사용하려면 이 경로가 현재
`assemble()` 내부에 있으므로, **`assemble()`을 두 개의 public 메서드로
분리**해야 한다: `assemble_pre_fdc()`(EI/AR/AC 호출까지, carryover 반환)와
`assemble_post_fdc(carryover, fdc_output)`(override 이후 로직, 기존 2976행
이후 코드를 그대로 이동). 이 분리는 서비스 레이어 코드 이동이며 로직 변경이
아니다.

### 17.5 EI/AR/AC 재실행 방지 보장 방법

- `--mode pre_fdc`는 EI/AR/AC를 **정확히 1회만** 실행하고 그 output을
  carryover에 담아 반환한다. `--mode fdc_only`는 EI/AR/AC 관련 코드를 전혀
  import·호출하지 않는다(파일은 공유하지만 실행 경로가 분기됨, 17.2).
  retry로 FIFO tail에 재등록되는 것은 **FDC job만**(§5 상태 전이도의
  `RETRY_QUEUED`)이며, carryover는 최초 pre-FDC 단계에서 만든 것을 재사용하지
  다시 만들지 않는다 — dispatcher가 `job_id`로 carryover를 계속 들고 있다가
  재시도 시 그대로 재사용한다.
- 이 보장의 테스트 가능성: `--mode fdc_only`가 EI/AR/AC 관련 함수를 호출하지
  않는다는 것은 **모듈 수준에서 직접 검증 가능**하다(fdc_only 실행 경로에서
  `EventInterpretationAgent`/`AIRiskAgent`/`AIComplianceAgent` 클래스의 `run()`이
  전혀 호출되지 않음을 mock/spy로 확인) — §21 테스트 계획에 명시.

### 17.6 위험과 대안 비교

| 대안 | 평가 |
|---|---|
| **두 CLI 진입점 분리(채택)** | subprocess 격리 원칙(§1 배경의 프로세스 크래시 격리 목적) 유지, 기존 EI/AR/AC 코드 재사용(중복 없음), `--mode full` 기본 보존으로 flag off 시 완전 무변경 |
| in-process로 EI/AR/AC/FDC 전체 재작성(subprocess 제거) | subprocess 격리가 존재하는 이유(개별 agent 크래시가 전체 cycle을 죽이지 않게 하기 위함으로 추정)를 되돌리는 것 — 이번 문서 조사 범위에서 원 설계 의도를 확정할 근거가 부족해 채택하지 않음 |
| 매 FDC retry마다 EI/AR/AC까지 통째로 재실행 | 요구사항("EI/AR/AC 재실행 방지")에 정면 위배, 비용·지연 모두 악화 — 기각 |

### 17.7 재기동/프로세스 종료 복구 계약(신설, 2026-08-27 2차 보정;
2026-08-28 6차 보정 — PR #359 4~5차 리뷰 보정으로 durable resume 신설에
맞춰 전면 정정)

17.3에서 확정한 대로 pre_fdc_result/correlation_id는 이제 `fdc_queue_
jobs`에 durable하게 저장된다. 이 절은 재기동 시 이 두 가지를 **서로
다른 방식으로** 처리해야 함을 확정한다 — **책임을 명확히 분리한다**:

- **`status='QUEUED'`인 job(reservation을 한 번도 받지 못함)**: pre_fdc가
  이미 끝나 durable resume 정보를 갖고 있으므로 **재개 가능하다** —
  `list_resumable_real_jobs()` + resume 절차(아래)가 담당한다. 더 이상
  "재개할 방법이 없어 취소한다"고 보지 않는다.
- **`status='RESERVATION_GRANTED'`인 job(reservation은 받았지만 process
  crash로 결과가 불명확하게 남음)**: 이 job은 fdc_only HTTP 호출이 실제로
  나갔을 수도, 안 나갔을 수도 있는 애매한 상태다 — `cancel_stale_real_
  jobs()`(recovery scan)가 tri-state attempt lifecycle로 안전하게
  정리한다. **recovery scan은 이 상태만 다룬다.**

**A. `cancel_stale_real_jobs()`(recovery scan) 계약 — 대상 축소**:

- **실행 주체**: `run_decision_loop.py::_run_loop()`(ops-scheduler가
  cycle마다 새로 spawn하는 `--count 1` subprocess) 시작 루틴(cycle 루프
  진입 전, 1회) — 별도 상시 프로세스나 cron이 아니다.
- **대상**: `fdc_queue_jobs`에서 `mode='real'` AND 이 dispatcher가
  다루는 `quota_scope` AND **`status='RESERVATION_GRANTED'`인 것만**
  (`QUEUED`는 대상이 아니다 — durable resume이 담당).
- **처리**: 대상 job의 가장 최근 attempt를 `get_latest_real_job_
  attempt_lifecycle()`(tri-state: `NOT_FOUND`/`NOT_STARTED`/`STARTED`)로
  조회해 분기한다.
  - `NOT_FOUND`(데이터 정합성 이상, ERROR 로깅) 또는 `NOT_STARTED`(HTTP가
    실제로 나가지 않음): 안전하게 `CANCELLED`(`reason=process_
    terminated_carryover_lost` — §5가 이미 확정한 3종 `CANCELLED` 사유
    중 "프로세스 종료"를 구체화한 것, 새 4번째 범주를 만들지 않는다).
  - `STARTED`(HTTP가 실제로 나갔을 수 있음): 자동으로 안전하다고 볼 수
    없으므로 `CANCELLED`가 아니라 `FDC_FAILED_FINAL`(`reason=fdc_only_
    subprocess_crashed_after_http_start_result_unknown` — `complete_
    fdc_actual_dispatch()`의 라이브 crash 판정과 동일한 reason)로
    fail-closed 종결한다(중복 호출 위험 회피).
- **idempotency**: `status='RESERVATION_GRANTED'` 조건만으로 동작하므로,
  두 번 연속 실행해도 두 번째 실행의 영향 행 수는 0이다.
- **이미 terminal인 job은 건드리지 않는다.**

**B. `list_resumable_real_jobs()` + resume 절차(신설) — `status='QUEUED'`
job의 durable resume**:

- **실행 주체**: recovery scan 직후, `_run_loop()`가 첫 cycle의 universe를
  읽은 뒤 1회.
- **대상**: 이 `quota_scope`의 `status='QUEUED'`인 모든 `mode='real'`
  job — FIFO 순서(`enqueue_sequence` 오름차순)로 반환된다.
- **정상 절차**: 해당 symbol이 새 프로세스가 읽은 현재 universe에
  존재하면, 저장된 `pre_fdc_result`를 그대로 재사용해 `complete_fdc_
  actual_dispatch()`(reservation 대기 → fdc_only 1회 실행 → 병합,
  17.2/§7 그대로) → `_run_one_cycle(precomputed_agent_bundle=...,
  decision_context_id_override=...)`로 override→EV-gate→sizing→submit을
  완결한다. **EI/AR/AC(pre_fdc)는 재호출하지 않는다** — 이것이 durable
  resume의 핵심 목적이다.
- **재개 불가 시(symbol이 더 이상 universe에 없음 — 예: 포지션 청산)**:
  조용히 버리지 않고 `FDC_FAILED_FINAL`(`reason=deadline_carryover_
  symbol_no_longer_in_universe`)로 감사 가능하게 종결한다.
- **불완전한 carryover row의 fail-closed 처리(FIFO head 차단 방지)**:
  `pre_fdc_result_json` 또는 `correlation_id`가 없는 `QUEUED` row(migration
  이전 데이터, 부분 실패, 수동 복구 오류, 향후 코드 결함 등으로 발생
  가능)는 조용히 건너뛰지 않는다 — `try_reserve()`의 FIFO admission
  ("나보다 먼저 등록된 QUEUED job이 있으면 양보")이 그런 row 하나 때문에
  뒤따르는 모든 real job을 영구 대기시킬 수 있기 때문이다(§4 "순번 탈락
  금지"의 정신을 데이터 정합성 이상이 위반하지 않도록). 발견 즉시
  `FDC_FAILED_FINAL`(`reason=fdc_carryover_payload_missing_data_
  integrity_error` 또는 `fdc_carryover_correlation_id_missing_data_
  integrity_error`)로 전이시켜 FIFO head를 비운다 — idempotent(이미
  terminal이 된 row는 다음 조회부터 대상에서 빠진다). 등록 시점에서도
  `DecisionAgentRunner._run_agents_in_subprocess_with_actual_dispatch()`
  가 `correlation_id`가 비어 있으면 애초에 등록하지 않고 fail-closed
  하도록 이중으로 막는다.
- **동일 job 중복 처리 방지**: resume은 항상 `complete_fdc_actual_
  dispatch()`의 `try_reserve()` 원자적 admission을 그대로 거친다 —
  resume 경로가 별도의 reservation 로직을 우회하지 않으므로, 같은
  `job_id`가 두 번 grant를 받거나 fdc_only가 중복 실행될 수 없다.

**accounting 정합성(reservation은 소비됐으나 HTTP가 시작되지 않은 경우)**:

- 크래시 시점에 이미 `RESERVATION_GRANTED`(§6 트랜잭션이 grant를 발급하고
  commit까지 끝난 상태)였다면, 그 reservation은 §7이 이미 정의한 대로 **그
  60초 window에서 소비된 것으로 유지**한다 — recovery scan이 `fdc_provider_
  attempts`의 `reserved_at`이나 quota 소비 기록을 소급 취소하지 않는다(quota
  계산의 감사 가능성을 보존하기 위함 — §14 감사 SQL이 "그 시점에 실제로
  reservation이 있었다"는 사실을 그대로 봐야 한다).
- `pre_http_execution_failure_count`/`RESERVED_BUT_HTTP_NOT_STARTED` 관련
  카운터(§9)도 recovery scan이 **증가시키지 않는다** — 이 카운터들은 "같은
  프로세스가 살아있는 동안 재시도가 실패한 횟수"를 뜻하는데, 프로세스 종료는
  재시도 실패가 아니라 완전히 다른 종결 경로(`CANCELLED`/`FDC_FAILED_
  FINAL`)이기 때문이다. recovery scan은 오직 `status` 컬럼과 `failure_
  or_cancel_reason`만 갱신한다.

**"순번 탈락 금지" 원칙과의 구분**: recovery scan/resume 모두 §1/§4가
금지하는 "순번이 늦어서 탈락"과 **무관**하다 — recovery scan의 취소
사유는 순번이 아니라 "그 job의 reservation 결과를 알 방법이 없는 프로세스
crash"라는 물리적 사실이고, resume은 오히려 순번 탈락을 **막기 위한**
메커니즘이다(불완전 row가 FIFO head를 막는 것을 적극적으로 정리한다).

**다음 cycle과의 관계(재시도/재개 vs 재평가 구분)**:

- **같은 job의 재시도**(§5 `RETRY_QUEUED`, `complete_fdc_actual_
  dispatch()`의 provider-retryable 실패 시 새 reservation)와 **같은
  job의 durable resume**(다른 프로세스가 `list_resumable_real_jobs()`로
  이어받음)은 모두 `pre_fdc_result`를 재사용하며 EI/AR/AC를 재실행하지
  않는다(17.5 그대로).
- **다음 cycle의 동일 종목 재평가**는 **완전히 새로운 `job_id`**로 시작하는
  독립적인 pre-FDC 실행이다 — 이전 job이 `CANCELLED`/`FDC_FAILED_FINAL`
  (recovery로든, resume 실패로든, 시장 마감으로든)였는지 `FDC_SUCCEEDED`
  였는지와 무관하게, 새 cycle은 그 종목을 처음부터(EI/AR/AC부터) 다시
  평가한다. 즉 "다음 cycle의 재평가"는 이전 job의 재시도/재개가
  **아니며**, `job_id`로 서로 연결되지 않는다.

**신규 테스트 항목**(§21에 병합): recovery scan이 `status='RESERVATION_
GRANTED'` job만(tri-state attempt lifecycle로 분기해) 전이하고 `QUEUED`는
건드리지 않는지, `list_resumable_real_jobs()`가 정상 `QUEUED` job을
agent 재호출 없이 재개하는지(EI/AR/AC subprocess 미호출 assert 포함),
symbol이 universe에서 사라진 경우 fail-closed 종결되는지, 불완전한
carryover row(payload 또는 correlation_id 없음)가 FIFO head를 막지 않고
즉시 정리되는지(InMemory + 실제 PostgreSQL 양쪽), 두 scan 모두
idempotent한지, reservation/attempt accounting 카운터를 recovery scan이
전혀 변경하지 않는지, 다음 cycle에서 생성되는 새 job이 이전 종결된 job과
`job_id`로 연결되지 않는 독립 행인지.

### 17.8 미확인 사항(구현 후 확인 필요)

- `AssembledContext`(position/cash/risk snapshot 포함)가 `dataclass_to_dict()`로
  완전히 JSON 직렬화 가능한지, 아니면 non-serializable 필드(예: 커넥션 핸들,
  Decimal 등 커스텀 인코더 필요)가 있는지는 실제 구현 시점에 해당 dataclass
  전체를 읽고 확인이 필요하다(이번 설계 문서 조사 범위에서 필드 단위까지
  전수 확인하지 않음).
- `--mode pre_fdc`/`--mode fdc_only`로 subprocess를 2회 spawn하는 것이 기존
  1회 대비 프로세스 생성 오버헤드(수십~수백 ms 추정)를 cycle 전체에 얼마나
  더하는지는 구현 후 실측 필요.

## 18. Provider one-shot 리팩터링 상세(2026-08-27 3차 보정 — 실제 PR A 구현 반영)

> **PR 배정(§22 2차 보정과 일관)**: 이 절 전체는 **PR A** 범위다.
>
> **상태 정정(2026-08-27 3차 보정)**: 최초 작성분은 "PR A 시점에는
> dispatcher도 `--mode fdc_only`도 없으므로 아무 운영 경로도 이 메서드를
> 호출하지 않는다 — PR B가 §17을 구현할 때 비로소 실제로 호출된다"고
> 서술했으나, 이는 실제 PR A 구현(PR #358)과 다르다 — **`generate_
> structured_once()`는 PR A에서 이미 실제로 호출된다.** 다만 그 호출자는
> dispatcher가 아니라 §19 진입점 #3·#4(독립 분석 스크립트 2개)다:
> `ar_fdc_provider_validation.py`는 `scripts/fdc_manual_provider_gate.py::
> call_with_coordinator()`를 통해 직접 호출하고, `ar_fdc_output_
> measurement.py`는 `FinalDecisionComposerAgent.run()` 같은 기존 고수준
> 인터페이스를 유지하기 위해 그 함수를 감싼 `CoordinatedFdcProviderClient`
> (``AIProviderClient`` Protocol wrapper)를 거쳐 간접 호출한다. **ops-
> scheduler의 실제 운영 FDC 경로(§19 진입점 #1·#2, `--mode full`)는
> 여전히 PR B 전까지 이 메서드를 호출하지 않는다** — "PR B/dispatcher
> 전까지 아무도 호출하지 않는다"는 원래 서술이 틀렸을 뿐, "운영 경로는
> 아직 이 메서드를 쓰지 않는다"는 핵심 계약(flag=false 레거시 보존)
> 자체는 그대로 유효하다.

- `provider_client.py::OpenAICompatibleClient.generate_structured()`(255-412행)의
  retry 루프(`for attempt in range(MAX_RETRIES)`, 335행)를 **단일 시도 내부
  헬퍼**(초기 설계 명칭은 `_generate_structured_single_attempt()`였으나, 실제
  구현에서는 `_single_http_attempt()`라는 이름으로 신설된 private 메서드다 —
  이하 본문은 실제 식별자를 쓴다)로 추출한다 — HTTP 요청 1회, 응답 파싱,
  에러 분류(retryable/non-retryable)까지만 담당하고 retry 여부 판단은 하지
  않는다.
- 기존 `generate_structured()`는 이 헬퍼를 `MAX_RETRIES`만큼 루프 호출하는
  **얇은 wrapper**로 재정의한다 — 외부에서 관측 가능한 동작(재시도 횟수, backoff,
  `acquire_permit` 호출 시점)은 **1바이트도 바뀌지 않는다**(순수 내부 추출
  리팩터링, §16 "공용 `generate_structured()` 불변" 계약 그대로 준수).
- 신규 `generate_structured_once(grant: ReservationGrant, ...)`(`LiveGemini
  ProviderClient` 전용 메서드, §12)는 `_single_http_attempt()`를 **정확히
  1회** 호출하고 끝낸다 — retry 루프 없음, `acquire_permit` 호출 없음
  (기존 10 RPM strict limiter를 아예 거치지 않는다 — 13 RPM coordinator가
  이를 대체).
- `MAX_RETRIES`라는 이름은 **변경하지 않는다**(§16 "구현 후 실측 필요"의
  "리네이밍 영향 범위 확인" 항목은 이번 설계로 "리네이밍하지 않는다"로
  확정 — 참조처가 많고(§16 위험 인지) 이름 자체는 여전히 정확하므로 무근거
  변경 금지 원칙에 따라 그대로 둔다).
- **`LiveGeminiProviderClient.generate_structured()`는 의도적으로 차단된다**
  (PR A 구현, 최초 설계 문서에 없던 내용) — 상속받은 이 메서드를 그대로
  열어두면 reservation 없이 live HTTP를 보내는 우회로가 생기기 때문이다.
  FDC live HTTP의 유일한 경로는 `generate_structured_once()`뿐이다.
- **`on_http_start` 콜백(2026-08-27 2차 리뷰 보정 신설)**: `_generate_
  structured_single_attempt()`(구현체명 `_single_http_attempt()`)는 실제
  `client.post()` **바로 직전**에 호출자가 넘긴 무인자 코루틴을 정확히
  1회 호출할 수 있다(``generate_structured()``의 기존 retry 루프는 이
  인자를 넘기지 않으므로 기존 동작은 완전히 보존된다). `call_with_
  coordinator()`가 이 콜백에서 `coordinator.record_attempt_outcome(
  outcome="http_started", http_started_at=now())`를 호출해, "HTTP가
  실제로 시작된 시각"만을 정확히 감사 기록에 남긴다 — 이전에는 호출
  직전에 타임스탬프를 미리 잡아, client 준비/body 조립 단계의 실패까지
  "HTTP가 시작됐다"고 잘못 기록하는 결함이 있었다. 콜백(DB 기록) 자체가
  실패하면 `client.post()`는 호출되지 않으며, 그 attempt는 기존 상태
  어휘의 `reserved_but_http_not_started`로 기록된다(§5/§9 기존 상태를
  재사용 — 새 상태를 만들지 않음).

## 19. Live provider 진입점별 게이팅 계획(2026-08-27 2차 보정 — PR 배정 정정)

> **보정 사유**: 최초 작성분은 5개 진입점 전부를 PR A에 일괄 배정했으나,
> 진입점 #2(subprocess FDC 호출)는 §17(PR B 범위)에서 신설되는 `--mode
> fdc_only`가 존재해야만 게이팅 지점이 실존한다 — PR A 시점에는 아직
> `--mode full`(레거시, coordinator 미사용)만 있으므로 #2를 PR A에서
> 게이팅하면 **레거시 FDC 경로 자체가 막힌다**. 아래 표는 이 모순을
> 제거하고 진입점별 **PR 배정**을 명시적으로 분리했다.

조사로 확인된 5개 provider 생성 진입점과 각각의 처리 방침:

| # | 진입점 | 현재 상태 | 처리 방침 | PR 배정 |
|---|---|---|---|---|
| 1 | `src/agent_trading/runtime/bootstrap.py:466` | 정상 운영 부트스트랩 | `LiveGeminiProviderClient` **클래스 자체**는 PR A에서 신설(coordinator 필수 생성자)하되, 이 경로가 실제로 그 클래스를 **사용하도록 전환**하는 것은 dispatcher 본체가 coordinator를 필요로 하는 시점(PR B)까지 미룬다 — PR A 시점에는 아직 아무도 호출하지 않는 dormant 클래스일 뿐이다 | 클래스 신설: **PR A** / 실제 사용 전환: **PR B** |
| 2 | `scripts/run_agent_subprocess.py:1239` | subprocess에서 stdin의 api_key/base_url로 직접 생성, `--mode full`(레거시)의 FDC 호출이 여기를 그대로 지나감 | `--mode fdc_only`(§17.2, PR B 신설)에서만 `LiveGeminiProviderClient`를 생성하도록 제한한다. **`--mode full`은 PR B 병합 후에도 이 진입점을 그대로 쓰며(플레인 `OpenAICompatibleClient`, 기존 10 RPM limiter 경유), `FDC_ACTUAL_DISPATCH_ENABLED=true`로 활성화되기 전까지는 게이팅의 영향을 전혀 받지 않는다** — PR A에서는 이 진입점을 손대지 않는다 | **PR B 전용** — PR A에서 변경 없음 |
| 3 | `scripts/ar_fdc_provider_validation.py:362` | coordinator 의존 없이 live HTTP 가능, ops-scheduler 런타임과 무관한 독립 분석 스크립트 | §11 정책대로 비운영 시간 수동 호출 경로로 전환 — `LiveGeminiProviderClient` 생성 시 coordinator를 필수로 전달하도록 스크립트 수정. **이 스크립트는 `FDC_ACTUAL_DISPATCH_ENABLED`가 제어하는 운영 런타임 경로가 아니므로**, PR A에서 즉시 전환해도 "flag=false 시 레거시 동작 보존" 계약과 충돌하지 않는다 | **PR A** |
| 4 | `scripts/ar_fdc_output_measurement.py:1071` | 위와 동일 | 위와 동일 | **PR A** |
| 5 | `scripts/verify_ei_subprocess_failure.py:32` | EI(FDC 아님) 검증 스크립트 | **FDC 전용 게이팅 대상 아님** — EI는 Gemini 13 RPM quota 대상이 아니므로(§1 배경, FDC만 대상) 변경 불필요. 다만 같은 `OpenAICompatibleClient`를 쓴다면 `LiveGeminiProviderClient`와는 별도 클래스(§12 "fake/test provider는 별도 구현체")이므로 영향 없음을 구현 PR에서 재확인 | 해당 없음(변경 불필요) |

**flag=false 레거시 동작 보존 근거(핵심)**: PR A가 병합돼도 진입점 #2(운영
FDC 호출의 유일한 실제 경로)는 전혀 손대지 않으므로, `--mode full`은 PR A
병합 전후로 바이트 단위까지 동일하게 동작한다 — coordinator 의존성도, 새
클래스 사용도 없다. PR B가 병합돼도 `FDC_ACTUAL_DISPATCH_ENABLED=false`인
동안은 §17.2의 분기가 항상 `--mode full`을 선택하므로(§17.2 "분리 모드는
신규 feature flag가 켜졌을 때만 선택된다") 마찬가지로 동작이 보존된다. 즉
"모든 live FDC 호출이 coordinator를 거친다"는 계약은 **PR B 병합 AND
`FDC_ACTUAL_DISPATCH_ENABLED=true`(별도 승인 활성화)** 두 조건이 모두
성립할 때만 참이다.

## 20. Feature flag 배선 계획(2026-08-27 2차 보정 — `required_in_compose` 정정 + PR B로 재배정)

> **보정 사유**: 최초 작성분은 이 절 전체를 PR A 범위로 뒀고
> `runtime_env_wiring.json`의 `required_in_compose`를 `false`로 제안했다.
> 두 가지 모두 정정한다.
>
> 1. **PR 배정**: 이 flag는 §17.2(`--mode pre_fdc`/`--mode fdc_only` 분기
>    선택)와 dispatcher 활성화를 직접 제어하는데, 그 소비자(§17 subprocess
>    분리, dispatcher 본체)가 전부 PR B 범위다. flag를 아무도 읽지 않는
>    PR A 시점에 미리 도입하면 "값은 있는데 아무 코드도 참조하지 않는
>    죽은 설정"이 생기고, `accept env` 배선 요구와도 앞뒤가 맞지 않는다 —
>    이 절 전체를 **PR B 범위**로 재배정한다.
> 2. **`required_in_compose` 정정**: 이 키는 "관측 전용(shadow처럼 켜도
>    꺼도 실제 실행 경로가 안 바뀌는 것)"이 아니라, **켜지는 순간 실제
>    FDC 호출 방식(레거시 `--mode full` vs 신규 `--mode fdc_only` +
>    coordinator 강제)이 바뀌는 런타임 실행 경로 선택 키**다. 이런 키는
>    compose 배선이 실제로 존재하는지(즉 운영자가 이 값을 바꿀 수 있는
>    통로가 실제로 연결돼 있는지)를 `accept env`가 강제 검증해야 한다 —
>    `required_in_compose: true`로 정정한다.

기존 `fdc_batch_queue_lifecycle_shadow_enabled` 패턴(settings.py `_resolve_
xxx()` 함수 + dataclass field)을 그대로 따르되, 위 보정을 반영한다.

- 신규 플래그명: `FDC_ACTUAL_DISPATCH_ENABLED`(기본값 `"false"`) — §17.2의
  `--mode pre_fdc`/`--mode fdc_only` 분기와 dispatcher 활성화를 함께 제어하는
  **단일 스위치**로 둔다(§4 "합산 quota 초과 구조 허용 안 함" 요구사항 —
  core/held_position을 분리한 별도 플래그를 두면 이 요구사항을 어길 위험이
  생기므로 처음부터 단일 스위치로 설계). lane별 단계적 전환(§15 "① → ② →
  ③")은 코드 배포 시점이 아니라 **운영 트래픽 구성**(예: 비core 시간대에만
  관찰)으로 수행하며, 별도 lane 플래그를 코드에 추가하지 않는다.
- 배선 파일(4곳 전부 **PR B에서 함께** 변경, §19 정정과 일관됨 — flag가
  실제로 소비되는 코드와 같은 PR에서 도입):
  - `settings.py`: `_resolve_fdc_actual_dispatch_enabled()` + `fdc_actual_
    dispatch_enabled: bool = field(default_factory=...)` (기존 패턴 그대로)
  - `.env.example`: `FDC_ACTUAL_DISPATCH_ENABLED=false` 한 줄 추가(기존
    `FDC_BATCH_QUEUE_LIFECYCLE_SHADOW_ENABLED=false` 옆)
  - `docker-compose.yml`: `ops-scheduler` 서비스 `environment:` 블록에
    `FDC_ACTUAL_DISPATCH_ENABLED: "${FDC_ACTUAL_DISPATCH_ENABLED:-false}"`
    — **필수 배선**(생략 시 §19 정정의 "PR B 병합 후에도 flag=false 보존"
    전제가 운영에서 실제로 성립하는지 확인할 방법이 없어진다)
  - `scripts/harness/contracts/runtime_env_wiring.json`: 신규 entry 등록,
    **`"required_in_compose": true`**(2차 보정 — 실행 경로 선택 키이므로
    `accept env`가 compose 배선 누락을 하드 실패로 잡아야 함)
  - §13의 나머지 설정(`FDC_WORKER_CONCURRENCY` 등)도 같은 파일들에 동일
    패턴·동일 `required_in_compose: true`로 배선(전부 실행 경로/동시성에
    직접 영향을 주는 값이므로 §20과 동일한 근거 적용)

## 21. 테스트 계획 통합(2026-08-27 2차 보정 — PR 배정 및 recovery 시나리오 추가)

§15의 19개 시나리오(동시성/reservation/accounting/coordinator 오류)는 **그대로
유효**하며 dispatcher/coordinator 계층을 대상으로 한다(PR B). 여기에 §17(subprocess
분리) 전용으로 다음을 추가한다 — 중복 없이 병합한 최종 목록, 항목별 **PR 배정**
명시(§19/§22 정정과 일관):

**§17 전용 신규 시나리오**(1~5, 9는 PR B / 6~7은 PR A / 8은 PR A·PR B 분리):
1. `--mode pre_fdc`가 EI/AR/AC를 정확히 1회 실행하고 FDC를 호출하지 않는지
   (FDC agent `run()`이 전혀 호출되지 않음을 spy로 확인) — **PR B**
2. `--mode fdc_only`가 EI/AR/AC 관련 클래스를 전혀 import·호출하지 않는지
   — **PR B**
3. FDC retry(§5 `RETRY_QUEUED`)가 발생해도 carryover가 재생성되지 않고
   최초 pre-FDC 결과가 그대로 재사용되는지(EI/AR/AC 재실행 방지 핵심 검증)
   — **PR B**
4. FDC 완료 job이 배치 전체 종료를 기다리지 않고 즉시 `assemble_post_fdc()`
   경로로 합류하는지(다른 job이 아직 `QUEUED`인 상태에서 검증) — **PR B**
5. `--mode full`(기존 경로)이 `FDC_ACTUAL_DISPATCH_ENABLED=false`일 때
   완전히 그대로 동작하는지(회귀 없음 — carryover 필드가 채워지지 않아도
   기존 output 스키마와 100% 호환) — **PR B**(flag와 `--mode` 분기 자체가
   PR B에서 신설되므로 이 시나리오도 PR B에서만 실행 가능)
6. 40개 FDC-ready job이 13/13/13/1로 여러 60초 window에 걸쳐 전부 처리되고,
   순번이 늦은 job이 18초/36초 timeout으로 탈락하지 않는지(기존 `fdc_rate_
   limiter.py`의 `DEFAULT_MAX_WAIT_SECONDS=18.0`/`DEFAULT_MAX_REQUEUE_
   COUNT=1` 탈락 경로가 신규 dispatcher 경로에서는 전혀 쓰이지 않음을 확인)
   — **PR B**(dispatcher 본체 대상)
7. `generate_structured_once()`가 `_single_http_attempt()`를
   정확히 1회만 호출하고(§18), 기존 `generate_structured()`의 외부 동작이
   리팩터링 전후로 완전히 동일한지(회귀 테스트) — **PR A**(§18은 PR A
   범위, dispatcher 없이 독립 검증 가능)
8. §19의 5개 진입점 중 coordinator 필수 대상의 검증은 PR 배정을 따라
   분리한다: **PR A**에서는 진입점 #3·#4(분석 스크립트)가 coordinator
   없이는 `LiveGeminiProviderClient`를 생성할 수 없음과, 클래스 자체의
   생성자 계약(coordinator 필수 인자)만 검증한다. **PR B**에서는 진입점
   #1·#2(운영 부트스트랩/subprocess FDC 호출)가 실제로 그 클래스를
   사용하도록 전환됐는지, 그리고 `--mode full`(flag=false)은 이 게이팅의
   영향을 전혀 받지 않는지(§19 "flag=false 레거시 동작 보존 근거" 직접
   검증)를 확인한다. EI 전용(#5)은 어느 PR에서도 영향받지 않음을 PR B에서
   1회 재확인
9. cycle 종료·프로세스 취소 시 job lifecycle이 명확히 기록되는지(§5 `CANCELLED`
   3사유 한정 확인) — **PR B**
10. held_position/core 두 source_type의 live FDC HTTP 시작을 합산해도 임의
    60초 구간에서 13건을 넘지 않는지(§19 단일 스위치 설계의 핵심 검증 —
    lane을 분리해도 quota가 분리되지 않음을 직접 증명) — **PR B**

**§17.7 전용 신규 시나리오(재기동/프로세스 종료 복구, 2026-08-27 2차 보정
신설) — 전부 PR B**:
11. recovery scan이 non-terminal `mode='real'` job만
    `CANCELLED(reason=process_terminated_carryover_lost)`로 전이하는지
12. 이미 terminal 상태(`FDC_SUCCEEDED`/`FDC_FAILED_FINAL`/기존
    `CANCELLED`)인 job은 recovery scan이 건드리지 않는지
13. recovery scan을 연속 2회 실행했을 때 두 번째 실행의 영향 행 수가
    0인지(idempotency)
14. recovery scan이 `fdc_provider_attempts`의 reservation/attempt
    accounting 카운터(§9)를 전혀 변경하지 않는지
15. recovery로 `CANCELLED`된 job과, 다음 cycle에서 같은 종목에 대해 새로
    생성되는 job이 서로 다른 `job_id`로 완전히 독립적인지(재시도로
    오인되지 않는지)

모든 테스트는 fake clock/fake PG repository/fake provider만 사용하며 실제
sleep·외부 Gemini/KIS 호출은 하지 않는다(§15 원칙 그대로).

## 22. PR 실행 계획(2026-08-27 2차 보정 — PR A/PR B 내용 재배정)

1. **이번 문서화 턴에서는 코드를 변경하지 않는다** — §17~§21이 이번에 신설한
   설계 전부이며, 구현은 별도 PR(들)로 진행한다.
2. 구현 PR은 규모상 최소 2단계로 분리하되, **flag=false 레거시 FDC 경로가
   두 PR 어느 단계에서도 깨지지 않도록** 아래처럼 내용을 나눈다(§19/§20
   2차 보정 반영 — 최초 작성분의 진입점 #2/flag를 PR A에 넣던 배정을
   철회):
   - **PR A(provider one-shot + 독립 스크립트 게이팅, dispatcher/flag 없음)**:
     - §18 전체(`generate_structured_once()` one-shot 추출) — 기존
       `generate_structured()`는 순수 내부 리팩터링만, 외부 동작 불변
     - `LiveGeminiProviderClient` 클래스 **신설**(coordinator 필수
       생성자) — 이 시점엔 **아무 운영 경로도 이 클래스를 사용하지
       않는 dormant 구현체**
     - §19 진입점 #3·#4(독립 분석 스크립트 2개)만 이 클래스로 전환 —
       ops-scheduler 런타임과 무관하므로 flag 존재 여부와 상관없이
       안전
     - **포함하지 않는 것**: §17(subprocess 분리), §20(feature flag),
       진입점 #1·#2(운영 부트스트랩/subprocess FDC 호출) 전환, dispatcher
       코드 — PR A 병합 후에도 `--mode full`(유일한 실제 운영 FDC 경로)은
       PR A 이전과 **완전히 동일하게** 동작한다(§19 "flag=false 레거시
       동작 보존 근거" 참고)
   - **PR B(subprocess 분리 + dispatcher + flag 배선, 전부 한 PR)**: PR A
     병합 후 진행.
     - §17 전체(pre-FDC/FDC subprocess 분리, `--mode pre_fdc`/`--mode
       fdc_only` 신설, §17.7 재기동 recovery scan 포함)
     - dispatcher 본체(§4/§6/§7, 이미 확정된 설계를 실제 코드로 구현)
     - §20 전체(feature flag 4곳 배선, `required_in_compose: true`)
     - §19 진입점 #1·#2의 실제 전환(운영 부트스트랩이 coordinator를
       `LiveGeminiProviderClient`에 배선, subprocess FDC 호출이
       `--mode fdc_only`에서만 그 클래스를 쓰도록 제한)
     - `FDC_ACTUAL_DISPATCH_ENABLED=false` 상태로 병합해 기존 운영
       동작을 보존한다 — **§17.2의 `--mode` 분기 자체가 flag를 직접
       읽으므로, flag=false인 한 `--mode full`(레거시)만 선택되고 신규
       코드 경로는 전혀 실행되지 않는다**(이 사실이 "PR B 병합 ≠ 즉시
       동작 변경"의 근거).
3. 각 PR은 harness 검증에 다음을 포함한다(변경 파일에 맞춰 좁게 선택):
   - **PR A**: `accept backend-file`(provider_client.py 등), 대상
     `test-file`, `accept backend-runtime`, `accept architecture`,
     `accept no-bypass`, `accept style`, `accept docs`(이 문서 갱신 시).
     `accept env`/`accept db-structure`는 PR A에 변경 대상이 없으므로
     불필요.
   - **PR B**: `accept backend-file`/`accept script-file scripts/
     run_agent_subprocess.py`, 대상 `test-file`, `accept backend-runtime`,
     `accept db-structure`(schema 변경 시), `accept architecture`,
     **`accept env`(필수 — §20 2차 보정으로 `required_in_compose: true`
     로 등록되므로, compose 배선이 없으면 이 명령이 하드 실패한다)**,
     `accept no-bypass`, `accept style`.
4. PostgreSQL 전용 FDC quota CI(`fdc_quota_postgres_integration`)는 현재
   `detect_fdc_quota_postgres_relevance.sh`의 `default_pattern`에 dispatcher
   신규 파일이 매칭되지 않는다(조사 확인 완료) — PR B가 `fdc_quota_
   coordinator.py`/`postgres/fdc_quota.py`를 실제로 수정한다면 자동으로
   relevant=1이 되어 실행되지만, dispatcher 전용 신규 파일만 추가하는 경우
   `.github/workflows/harness.yml`의 `fdc_quota_postgres_relevant` job
   호출부에 5번째 인자(pattern override, `postgres_fixture_loop_scope_
   integration` job이 이미 쓰는 방식)를 추가해 실제 실행되도록 워크플로를
   함께 수정해야 한다 — PR B 본문에 relevance 판정 결과와 근거를 명시할 것.
   PR A는 이 CI의 대상 파일을 건드리지 않으므로 relevance 판정과 무관하다.
5. 운영 활성화(`FDC_ACTUAL_DISPATCH_ENABLED=true`)는 §15 단계적 도입(①→②→③)
   그대로, PR B 병합 후 **별도 사용자 승인**으로만 수행한다 — 이 문서와
   구현 PR 어느 것도 활성화 자체를 포함하지 않는다.
