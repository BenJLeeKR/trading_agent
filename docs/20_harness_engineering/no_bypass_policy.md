# 우회 행동 금지 정책

이 문서는 AI와 사람이 검증을 통과시키기 위해 안전장치나 정답 판정기를 우회하는 행동을 방지하기 위한 기준이다. 목적은 모든 의심 패턴을 즉시 실패시키는 것이 아니라, 실패 조건과 검토 대상을 분리해 오판을 줄이는 것이다.

## 기본 원칙

- 테스트를 통과시키기 위해 트레이딩 안전 불변식, 하네스 계약, secret 보호 정책을 약화하지 않는다.
- 명확한 안전 위반은 `Hard Fail`로 판정한다.
- 맥락 판단이 필요한 우회 의심은 `Review Flag`로 표시하고, 완료 보고에 카운트와 사유를 남긴다.
- 예외가 필요하면 코드에 숨기지 말고 하네스 승인 플래그, 문서화된 baseline, 또는 PR 설명에서 명시한다.

## Hard Fail

다음 항목은 발견되면 실패 조건으로 다룬다.

- `.env` 파일 직접 수정 또는 `.env` 키값 노출.
- risk gate, sell guard, submit-lane gate, reconciliation lock, broker contract check를 비활성화하거나 우회하는 변경.
- GitHub Actions safe job이나 하네스 기본 경로에서 사용자 승인 없이 heavy 검증 플래그를 켜는 변경.
- 운영 배포 경로에서 `Safe harness contracts` 또는 동등한 하네스 게이트를 우회하는 변경.
- 실패한 브로커, KIS, DB, 스케줄러 작업을 성공으로 조용히 변환하는 변경.

## Review Flag

다음 항목은 즉시 실패시키지 않고 검토 대상으로 표시한다.

- `# noqa`, `type: ignore`, `pragma: no cover` 같은 정적 검사 예외.
- `pytest.skip`, `xfail`, 테스트 selector 축소, 테스트 파일 제외.
- `HARNESS_ALLOW_*` 플래그 사용.
- mock, stub, monkeypatch 확장.
- 넓은 `except Exception`, `except:`, `return True` 기반 성공 처리.

Review Flag는 실패가 아니다. 다만 완료 보고에는 `review_bypass_count`와 대표 위치를 남기고, 해당 우회가 타당한 이유 또는 후속 정리 계획을 제시해야 한다.

## 하네스 판정

우회 행동 검사는 다음 명령으로 실행한다.

```bash
bash scripts/harness/run.sh accept no-bypass
```

주요 출력 지표는 다음과 같다.

- `changed_file_count`: 검사 대상으로 잡힌 변경 파일 수.
- `added_line_count`: 검사한 추가 라인 수.
- `hard_bypass_count`: 실패 조건에 해당하는 우회 수.
- `review_bypass_count`: 검토 대상으로 표시된 우회 후보 수.
- `allowlisted_bypass_count`: 정책 문서나 하네스 검사기처럼 예외적으로 스캔에서 제외된 설명성 패턴 수.
- `new_bypass_candidate_count`: `hard_bypass_count + review_bypass_count`.

현재 정책은 `hard_bypass_count > 0`일 때만 실패한다. `review_bypass_count > 0`은 완료 보고와 리뷰 대상으로 남긴다.

CI의 `Safe harness contracts`는 이 검사를 실행한다. PR에서는 `origin/<base>` 기준 변경분을 검사하고, `main` push에서는 직전 커밋인 `HEAD^` 기준 변경분을 검사한다.
