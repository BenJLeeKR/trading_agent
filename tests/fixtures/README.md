# 테스트 Fixture 기준

이 디렉터리는 환경 차이에 의해 테스트 결과가 달라지는 것을 막기 위한 고정 입력 데이터를 보관한다.

## 원칙

- 테스트 기대값에 필요한 입력은 가능한 한 이 디렉터리 아래에 둔다.
- `data/`, `logs/`, `tmp/`처럼 운영 중 변하는 파일을 테스트의 canonical 입력으로 직접 사용하지 않는다.
- DB 테스트용 seed는 deterministic해야 하며, migration 적용 후 seed와 cleanup 순서를 테스트 또는 helper에 명시한다.
- 외부 API, KIS, 현재 시각, 로컬 캐시, 운영 DB 상태에 의존하는 데이터는 fixture로 고정하거나 테스트에서 명시적으로 mock 처리한다.
