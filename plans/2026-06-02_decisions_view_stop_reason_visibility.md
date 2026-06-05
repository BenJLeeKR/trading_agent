# 2026-06-02 의사결정 화면 stop reason 가시성 보강

## 배경
BUY 차단 카드에서 드릴다운 링크를 추가한 뒤에도, `의사결정` 목록 화면에서 각 row의 차단 원인을 한눈에 읽기 어려웠다.

- source_type은 상세 패널을 열어야 확인 가능
- execution 상태는 표에서 바로 드러나지 않음
- latest_stop_reason도 표에는 노출되지 않음

드릴다운 진입 후 다시 상세 패널을 여는 비용을 줄일 필요가 있었다.

## 목표
- `의사결정` 목록 표에서 다음 정보를 바로 보여주기
  - 소스
  - 실행 상태
  - 차단 사유
- 드릴다운 필터 배너의 raw query 값을 사람이 읽을 수 있는 문구로 치환

## 구현
- `admin_ui/src/components/DecisionsView.tsx`
  - helper 추가
    - `executionStatusVariant()`
    - `sourceTypeLabel()`
    - `stopReasonLabel()`
  - 목록 컬럼 추가
    - `소스`
    - `실행`
    - `차단 사유`
  - 드릴다운 배너 문구 개선
    - `source core` → `소스 core`
    - `stop_reason general_submit_disabled_core` → `사유 core 제출 비활성`

## 테스트
- `admin_ui/src/__tests__/decisions.test.tsx`
  - 컬럼 헤더 존재 검증 추가
  - 드릴다운 query param 상태에서
    - 필터 배너 표시
    - 사람이 읽을 수 있는 stop reason 라벨 표시
    - execution 상태 배지 표시

## 기대 효과
- 운영자가 드릴다운 진입 후 row 목록만 봐도 차단 원인 파악 가능
- 상세 패널을 열어야만 알 수 있던 stop reason 확인 비용 감소
- BUY 차단 카드 → 의사결정 목록 → 원인 판독 흐름이 자연스러워짐
