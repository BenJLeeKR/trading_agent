# FDC rate limiter `DEFAULT_MAX_WAIT_SECONDS` 15.0 → 20.0 조정

## 배경

PR #287(FDC provider 호출 shared rate limiter 도입) 배포 후 첫
decision loop 사이클(2026-08-18 13:28:00~13:29:25 KST, 36개 종목)을
read-only로 실측한 결과:

- `wait_for_fdc_slot()`이 실제로 작동함을 로그로 직접 확인(대기 후
  호출 허용 3건, 각각 13.0s/14.0s/13.0s 대기).
- `reason_codes=["provider_rate_limit"]` fallback은 4/36(11.1%)로
  직전 관측치(동시성 5→3 완화 시기 47.2%~50.0%)보다 크게 감소.
- 하지만 대기 후 성공한 3건 전부가 기존 상한(`DEFAULT_MAX_WAIT_
  SECONDS=15.0`)에 바짝 붙은 13~14초를 기다렸다 — bypass된 16건
  (`max_wait_exceeded`) 중 일부는 조금만 더 여유를 줬으면 슬롯을
  확보했을 가능성을 시사한다.

이 관측을 근거로, "15초가 짧아 보인다"는 감상이 아니라 **현재 코드의
timeout budget 구조**와 **실측된 대기-성공 시간 분포**를 근거로
`DEFAULT_MAX_WAIT_SECONDS`를 20.0으로 조정하는 게 타당한지 검토했다.

## 판단: timeout budget 구조 재확인

`wait_for_fdc_slot()`의 호출 지점(`scripts/run_agent_subprocess.py`)을
다시 확인한 결과, 이 대기는 다음 코드 순서로 일어난다:

```python
if provider_client is not None:
    rate_limit_result = await wait_for_fdc_slot()   # ← 여기서 대기
...
composer_output = await asyncio.wait_for(
    fdc_agent.run(request_with_ei_ar_ac),
    timeout=_PER_AGENT_TIMEOUT,   # 30초 — 이 블록 안이 아님
)
```

즉 **`wait_for_fdc_slot()`의 대기 시간은 FDC의 30초 per-agent
timeout(`_PER_AGENT_TIMEOUT=30`)에 전혀 포함되지 않는다** — 이 대기는
그 30초 타임아웃 블록 앞에서 독립적으로 일어나는 별개의 단계다.

**이 사실은 15.0이라는 기존 값의 근거를 재검토하게 만든다.** PR #287
당시 남긴 주석("per-agent timeout(30초)을 침범하지 않도록 대기 상한을
그보다 충분히 짧게 둔다")은 대기 시간이 30초 예산 **안에** 있다는
전제로 쓰였는데, 실제 코드 구조상 그 전제 자체가 맞지 않았다 — 15는
구조적으로 강제된 값이 아니라 **다소 보수적으로 잡은 설계값**이었다.

실제로 이 대기가 침범하지 않아야 할 진짜 예산은 subprocess 전체
timeout(`DecisionAgentRunner.subprocess_timeout`, 기본 90초 — EI/AR/AC
는 결정론적 계산이라 수 밀리초 수준이므로 사실상 FDC 단계가 이 90초를
거의 독점한다)이다. 20초(대기 상한) + 30초(FDC 자체 timeout 상한)
= 50초로, 90초 예산 안에서 40초의 여유가 여전히 남는다.

## 판단 질문에 대한 답

- **15→20이 현재 timeout budget 안에서 안전한가**: 그렇다. 위 계산대로
  50초 ≪ 90초(subprocess 전체 예산)로 안전 여유가 충분하다.
- **15→20이 bypass를 줄일 가능성이 있는가**: 있다. 실측된 대기-성공
  3건이 13~14초에 몰려 있어(기존 15초 상한에 근접), 상한을 5초 더
  늘리면 그 경계에서 bypass되던 호출 중 일부가 정상 대기로 전환될
  여지가 있다.
- **20으로 늘리면 per-agent timeout 30초와 충돌할 가능성**: 없다.
  구조적으로 이 대기는 그 30초 블록과 무관한 별개의 단계이기 때문이다
  (위 코드 인용 참고).
- **25 이상이 아닌 20이 적절한 이유**: 관측된 성공 대기가 13~14초
  구간에 몰려 있어 20초로도 그 경계값을 충분히 덮는다. 그 이상(25초+)
  으로 늘리는 것은, 이미 bypass되고 있는 호출들의 대기 시간만 늘릴 뿐
  (그들이 20초를 넘겨 25초까지 기다리면 슬롯을 얻는다는 근거가 이번
  실측 데이터에는 없음) 검증되지 않은 추측성 latency 비용을 추가하는
  것이다. 20초는 실측 데이터가 뒷받침하는 가장 작은 유의미한 조정이다.
- **주문 판단 로직에 영향이 있는가**: 없다. 이 값은 rate limiter가
  얼마나 참을성 있게 기다릴지만 결정하며, `decision_type` 정책,
  주문 gate, EV gate, sizing, EI/AR/AC/FDC 역할 분리와는 무관하다.
  간접적으로는 "bypass가 줄어 fallback이 줄면 HOLD 기본값으로 빠지는
  케이스가 줄어들 수 있다"는 효과만 있을 뿐, 판단 로직 자체는 그대로다.

**결론: 타당함 — 구현 진행.**

이번 조정은 **429 발생 자체를 줄이는 조정이 아니다**(그건
`DEFAULT_MAX_CALLS_PER_WINDOW=10`/60초 정책의 영역이며 이번 턴에서
건드리지 않았다). 이번 조정은 **limiter가 슬롯을 기다리다 포기하는
비율(bypass)을 낮춰서, 그 결과로 fallback 비율을 추가로 낮추려는
조정**이다.

## 실제 변경 내용

`src/agent_trading/services/ai_agents/fdc_rate_limiter.py`:
- `DEFAULT_MAX_WAIT_SECONDS = 15.0` → `20.0`.
- 상수 위 주석을 위 판단 근거(30초 예산과 무관, 90초 예산 기준,
  13~14초 실측 근거, 25초 이상을 피한 이유)로 교체.
- 모듈 최상단 docstring의 관련 서술("per-agent timeout(30초)을
  침범하지 않도록")도 정확한 구조(90초 subprocess 예산 기준, 30초와는
  무관)로 수정.

`DEFAULT_MAX_CALLS_PER_WINDOW`, `_PER_AGENT_TIMEOUT`, provider 재시도
정책, docker-compose, env wiring, DB schema, execution/translation/
sizing 로직 — 전부 미변경.

`tests/services/ai_agents/test_fdc_rate_limiter.py`:
- `TestDefaultMaxWaitSeconds` 클래스 신규 추가 — 기본값이 정확히
  20.0인지, 그리고 20.0+30.0(FDC timeout 상한)이 90.0(subprocess
  예산)보다 작은지를 직접 assert.
- 기존 8건의 테스트는 전부 자체 `max_wait_seconds` 파라미터를
  명시적으로 넘기고 있어 기본값 변경의 영향을 받지 않음(수정 불필요,
  실행해서 재확인만 함).

## 검증 결과

| 명령 | 결과 |
|---|---|
| `test-file tests/services/ai_agents/test_fdc_rate_limiter.py` | **10 passed**(신규 2건 포함, 기존 8건 그대로 통과) |
| `accept backend-file src/agent_trading/services/ai_agents/fdc_rate_limiter.py` | PASS — 자동 매칭된 위 테스트 파일 실행, 0 실패 |
| `accept backend-runtime` / `architecture` / `no-bypass` / `style` / `docs` | 전부 PASS |

**회귀 테스트 유효성 검증**: `DEFAULT_MAX_WAIT_SECONDS`를 임시로
15.0으로 되돌려 재실행해, `test_default_is_20_seconds`가 실제로
실패함을 확인했다(`assert 15.0 == 20.0`). 값을 20.0으로 복구해 10건
전체 재통과를 확인했다.

## 정책 영향 여부

없음. `decision_type` 정책, 주문 gate, EV gate, sizing, EI/AR/AC/FDC
역할 분리, fallback `HOLD` 정책 — 전부 미변경. `.env`/`.env.example`도
수정하지 않았다(이번 턴은 env화가 아니라 상수 조정 턴이라는 지침에
따름).

## 배포 후 실측 포인트

- 새 상한(20.0초)에서 "대기 후 호출 허용" 로그와 "bypass
  (max_wait_exceeded)" 로그의 비율이 이전(3건 대기-성공 : 16건
  bypass)에서 어떻게 바뀌는지.
- `reason_codes=["provider_rate_limit"]` fallback 비율이 11.1%에서
  추가로 낮아지는지.
- cycle wall-clock이 이전(약 87초, 상한 15초 기준)보다 얼마나
  늘어나는지 — 대기 상한이 5초 늘었으므로 bypass 대신 대기하는 호출이
  늘면 그만큼 사이클 전체 시간도 소폭 늘어날 수 있음을 감안해야 한다.
- subprocess 전체 timeout(90초)에 실제로 근접하거나 초과하는 사례가
  발생하는지(이론상 50초 이내라 여유가 있으나, 실측으로 재확인 필요).
