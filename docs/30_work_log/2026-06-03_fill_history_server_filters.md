# 체결내역 API 서버 필터 추가

## 목적
- `VTTC0081R` 기반 체결내역을 운영/분석에서 바로 추적할 수 있도록 `fill-history` API에 서버 필터를 추가한다.
- 프런트 필터 이전에 백엔드에서 바로 `order_request_id`, `symbol`, `ODNO` 기준 조회가 가능해야 한다.

## 적용 범위
- `GET /fill-history`
- `BrokerFillSnapshotRepository.list_recent()`
- Postgres / In-memory 저장소 구현

## 추가한 필터
- `order_request_id`
- `symbol`
- `broker_native_order_id`

## 구현 내용
1. `BrokerFillSnapshotRepository.list_recent()` 시그니처 확장
   - `symbol: str | None = None`
   - `broker_native_order_id: str | None = None`
2. Postgres 저장소 SQL WHERE 절 확장
   - `symbol = $n`
   - `broker_native_order_id = $n`
3. In-memory 저장소 필터 로직 추가
4. `/fill-history` 라우트 쿼리 파라미터 추가
   - `order_request_id`는 UUID 파싱
   - 나머지는 문자열 그대로 전달

## 검증
- 테스트: `pytest -q tests/api/test_fill_history.py` → `3 passed`
- 실서버 확인:
  - `symbol=001740` → 2건 반환
  - `broker_native_order_id=0000033121` → 1건 반환
  - `order_request_id=22dadd3b-24f5-4200-9246-ef810df3af84` → 1건 반환

## 실서버 응답 예시
- `symbol=001740`
  - `0000033121` / `sell` / `filled_quantity=207`
  - `0000018363` / `buy` / `filled_quantity=205`
- `broker_native_order_id=0000033121`
  - `order_request_id=22dadd3b-24f5-4200-9246-ef810df3af84`
- `order_request_id=22dadd3b-24f5-4200-9246-ef810df3af84`
  - `symbol=001740`, `broker_native_order_id=0000033121`

## 기대 효과
- 체결내역에서 주문 단건 추적이 쉬워진다.
- `paper_truth_missing`나 주문 복구 케이스를 `ODNO`/`order_request_id`로 바로 대조할 수 있다.
- 이후 `주문 상세 ↔ 체결내역` 연결 작업의 백엔드 기반이 된다.
