# 2026-06-02 스케줄러 일반 submit 상한 운영값 외부화

## 배경
일반 BUY/core submit lane이 다시 열리더라도, `ops-scheduler` 컨테이너는 `run_ops_scheduler.py`의 기본값 `--max-submit-per-day 1`을 그대로 사용하고 있었다. 이 값은 직접 실행 시 보수적인 기본값으로는 의미가 있지만, 운영 컨테이너에서는 너무 낮아 BUY throughput을 과도하게 제한할 수 있다.

## 목표
- 코드의 직접 실행 기본값은 유지한다.
- 실제 운영 컨테이너(`ops-scheduler`)에서는 일반 submit 상한을 `.env`/compose 레벨에서 조정 가능하게 만든다.
- 기본 운영값은 `2`로 완화한다.

## 수정 내용
- `docker-compose.yml`
  - `ops-scheduler.command`에 다음 인자를 명시적으로 추가했다.
    - `--max-submit-per-day ${SCHEDULER_MAX_SUBMIT_PER_DAY:-2}`
- 효과
  - `.env`에 `SCHEDULER_MAX_SUBMIT_PER_DAY`가 있으면 그 값을 사용
  - 없으면 운영 컨테이너 기본값은 `2`
  - 로컬/직접 실행(`python3 scripts/run_ops_scheduler.py`) 기본값 `1`은 유지

## 이유
- 최근 BUY 0건 분석 결과, 버그 수정 후에도 `1건/일` 상한은 지나치게 보수적이다.
- 운영값을 compose 레벨로 올리면 코드 기본값을 건드리지 않고도 즉시 조정 가능하다.
- 향후 위험도에 따라 `.env`에서 `1`, `2`, `3` 등으로 쉽게 조정할 수 있다.

## 검증
- `docker-compose.yml` 변경 후 `ops-scheduler` 재기동
- 컨테이너 명령행에 `--max-submit-per-day 2` 반영 여부 확인
- health 상태 확인
