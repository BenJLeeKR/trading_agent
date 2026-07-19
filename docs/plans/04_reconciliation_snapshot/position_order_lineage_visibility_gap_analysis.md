# Position vs Order Lineage Visibility Gap 분석

## 목적

Admin UI에서 `계좌` 메뉴에는 체결된 것으로 보이는 포지션이 보이는데, `주문` 메뉴에서는 같은 포지션에 대응하는 주문이 잘 보이지 않는 이유를 코드와 실제 데이터 기준으로 분석한다.

이 문서는 다음 두 질문에 답한다.

1. 현재 포지션이 정말 `order_requests` 경로를 거치지 않고 생겼는가
2. 아니라면, 왜 운영자가 UI에서 같은 주문을 찾기 어렵게 보이는가

---

## 결론 요약

### 결론 1 — 이번 사례는 “주문 테이블을 거치지 않은 포지션”이 아니다

현재 포지션(005930, 10주, 평균단가 267,000원)은 내부 주문/브로커 주문과 정합한다.

확인된 내부 주문 lineage:

- `order_request_id`: `50c7032e-dba7-45a0-9914-6f0264a4d21a`
- `instrument_id`: `44444444-4444-4444-4444-444444444444`
- `symbol`: `005930`
- `requested_quantity`: `10`
- `requested_price`: `267000`
- `status`: `reconcile_required`

연결된 브로커 주문:

- `broker_order_id`: `ebb4113a-a34b-4cca-8602-7d9902ed6d00`
- `broker_native_order_id`: `0000011317`
- `broker_status`: `reconcile_required`

현재 포지션 스냅샷:

- `quantity`: `10`
- `average_price`: `267000`
- `instrument_id`: 동일
- `symbol`: `005930`

즉, **데이터상으로는 내부 주문 경로를 거친 포지션**이다.

### 결론 2 — 운영자가 “주문이 안 보인다”고 느끼는 진짜 원인은 UI/API 가시성 부족이다

문제는 lineage 부재보다 **가시성 부재**다.

운영자가 찾기 어려운 이유:

1. `GET /orders`가 `symbol=None`으로 응답한다
2. `계좌` 화면의 포지션 테이블이 `instrument_id` UUID만 보여준다
3. `계좌 -> 주문`으로 바로 이어지는 drill-down이 없다

즉, 같은 데이터라도 화면에서 사람 눈에 **같은 종목/같은 주문으로 연결되지 않는다.**

---

## 코드/데이터 근거

## 1. 포지션 데이터는 스냅샷 기반이다

`계좌` 화면은 `getPositions(accountId)`를 호출한다.

- [AccountsView.tsx](../admin_ui/src/components/AccountsView.tsx)
- [client.ts `/positions`](../admin_ui/src/api/client.ts)
- [positions.py](../src/agent_trading/api/routes/positions.py)

이 경로는 `position_snapshots` 저장소에서 최신 스냅샷을 그대로 읽는다.

현재 `GET /positions`는 다음 특성이 있다.

- 스냅샷 데이터만 반환
- `symbol`/`name` 같은 instrument 표시 정보 없음
- `instrument_id` UUID만 내려줌

관련 스키마:

- [PositionSnapshotView](../src/agent_trading/api/schemas.py)

현재 Admin UI 표시 방식:

- [AccountsView positionColumns](../admin_ui/src/components/AccountsView.tsx)
- `종목` 컬럼에 `instrument_id`의 축약 UUID만 표시

즉, 운영자는 `005930`이 아니라 `44444444…` 같은 UUID를 보게 된다.

## 2. 주문 화면은 내부 `order_requests`만 본다

`주문` 화면은 `getOrders()`를 호출한다.

- [OrdersView.tsx](../admin_ui/src/components/OrdersView.tsx)
- [client.ts `/orders`](../admin_ui/src/api/client.ts)
- [orders.py](../src/agent_trading/api/routes/orders.py)

이 경로는 `order_requests`를 조회해서 `OrderSummary`로 변환한다.

그런데 현재 구현은 `_order_to_summary()`에서:

- `instrument_id`는 알고 있음
- 하지만 `symbol`은 아예 해석하지 않고
- `symbol=None`을 내려준다

문제 코드:

- [orders.py `_order_to_summary`](../src/agent_trading/api/routes/orders.py)

현재 주석도 명시적이다.

- `symbol=None,  # resolves from instrument_id (skipped for now)`

이 때문에 주문 목록에서 종목 기준 식별이 어렵다.

## 3. 실제 데이터는 포지션과 주문이 맞물린다

실데이터 조회 결과:

- position snapshot: `005930`, `10주`, `평균단가 267000`
- latest order_request: `10주 @ 267000`, `status=reconcile_required`
- linked broker_order 존재: `broker_native_order_id=0000011317`

즉, 이번 사례는 “주문이 없는데 포지션만 있다”가 아니라:

**주문은 있는데, UI/API가 symbol/name과 lineage를 충분히 노출하지 않아 운영자가 연결해 보기 어렵다.**

---

## 실제 문제를 만드는 구체 요소

## P0 문제

### 1. `/orders` 응답에 symbol이 없다

영향:

- Orders 목록에서 종목 검색/확인성이 떨어진다
- 운영자가 “005930 주문이 없다”고 오판할 수 있다

### 2. Accounts 포지션 화면에 symbol/name이 없다

영향:

- 포지션이 종목이 아니라 UUID처럼 보인다
- 주문 화면과 육안 매칭이 어렵다

### 3. 계좌 화면에서 관련 주문 drill-down이 없다

영향:

- 포지션을 보고 바로 “이 포지션을 만든 주문”으로 이동할 수 없다

## P1 문제

### 4. `symbol` 기반 cross-screen 탐색 흐름이 약하다

현재 `주문` 화면의 검색은 `symbol` 또는 `order_request_id`를 기준으로 동작하지만,
실제로 API 응답의 `symbol`이 비어 있어 search utility가 약하다.

---

## 권장 수정안

## 권장안 A — 최소 수정, 효과 큼

### A-1. `/orders`에서 `instrument_id -> symbol` 해석

수정 대상:

- [orders.py](../src/agent_trading/api/routes/orders.py)

의도:

- `OrderSummary.symbol`을 실제 symbol 값으로 채움
- Orders 목록에서 005930 같은 종목 식별 가능

권장 구현:

- `_order_to_summary()`를 비동기 enrich 패턴으로 바꾸거나
- `repos.instruments.get(order.instrument_id)`로 symbol/name 조회

최소 결과:

- 주문 목록에 `symbol=005930` 표시

### A-2. `/positions`에 symbol/name 표시 정보 추가

수정 대상:

- [schemas.py `PositionSnapshotView`](../src/agent_trading/api/schemas.py)
- [positions.py](../src/agent_trading/api/routes/positions.py)

의도:

- 포지션 목록에서 UUID 대신 종목코드/종목명을 보여줌

권장 필드:

- `symbol: str | None`
- `instrument_name: str | None`

### A-3. AccountsView 포지션 컬럼을 UUID가 아니라 종목 기준으로 표시

수정 대상:

- [AccountsView.tsx](../admin_ui/src/components/AccountsView.tsx)
- [admin_ui/src/types/api.ts](../admin_ui/src/types/api.ts)

의도:

- `종목` 컬럼을 `005930 / 삼성전자` 형태로 표시

---

## 권장안 B — 운영 UX 개선

### B-1. 계좌 화면에서 “관련 주문 보기” 액션 추가

의도:

- 선택 포지션 기준으로 `주문` 화면 이동
- account + symbol 필터 적용

예:

- 버튼: `관련 주문 보기`
- 이동: `/orders?symbol=005930`

### B-2. 주문 상세에 instrument name 노출

현재 `instrument_id`만 노출되거나, symbol이 빈 경우 운영자가 이해하기 어렵다.

---

## 비권장 오해

이번 사례를 아래처럼 해석하면 안 된다.

- “브로커 포지션이 주문 시스템을 우회했다”
- “주문 테이블을 거치지 않고 체결됐다”

현재 확인된 데이터상으로는 **최신 포지션은 내부 주문 lineage와 연결된다.**

문제는 **lineage가 없는 것보다, lineage가 보여지지 않는 것**이다.

---

## 권장 우선순위

### P0

1. `/orders`에서 symbol 채우기
2. `/positions`에서 symbol/name 채우기
3. AccountsView에서 종목 표시 개선

### P1

4. Accounts -> Orders drill-down 추가
5. Orders 상세의 instrument 표시 개선

---

## 최종 판정

- **운영 데이터 정합성 문제**: 아님
- **주문 lineage 부재**: 이번 사례 기준 아님
- **운영 UI/API 가시성 문제**: 맞음
- **수정 필요 여부**: 필요

가장 작은 수정으로도 운영자의 혼란을 크게 줄일 수 있다.

