# v0.dev 입력 문서 — Near-Real 운영 모니터링 화면

## 사용 목적

이 문서는 v0.dev에 전달할 **운영 모니터링 UI 생성 프롬프트**다.

기존 Admin UI 전체를 새로 만드는 것이 아니라, 현재 운영 환경(`KIS_ENV=paper`, 운영상 live 취급)에서 부족한 **운영 모니터링 화면**을 보강하는 목적이다.

## 전달 원칙

- **한글 메뉴명 / 한글 카드명 / 한글 경고 문구**를 기본으로 사용
- desktop-first
- 내부 운영자 도구
- read-mostly / inspect-first
- chart-heavy analytics보다 **표 + 상태 카드 + 경고 패널** 우선
- 소비자용 SaaS 느낌 금지
- 마케팅 랜딩 페이지 스타일 금지

## v0.dev 기본 프롬프트

아래 프롬프트를 그대로 사용:

Create a desktop-first internal operations console extension for an AI multi-agent trading system.

This is not a marketing page and not a consumer SaaS dashboard.
It is a near-real trading operations monitoring UI for operators.

Important context:

- The current environment is operationally treated as live, even though the broker environment label may still be `paper`.
- The UI should be designed as a real operations console, not a mock trading toy.
- Use Korean labels, Korean menu names, Korean card titles, and Korean warning texts wherever possible.

Design goals:

- fast operator judgment within 10 seconds
- high information density
- strong warning visibility
- table + detail + summary card layout
- left navigation sidebar
- top status strip
- desktop-first
- read-mostly operations workflow

Avoid:

- hero sections
- marketing copy
- oversized whitespace
- decorative charts
- playful gradients
- consumer fintech styling

Use a restrained enterprise console style with:

- dark-neutral or muted-light operations palette
- compact spacing
- strong error/warning contrast
- clear row selection
- clear detail panel separation

## 화면 범위

이번 요청에서는 아래 화면 또는 탭을 우선 설계:

1. 운영 대시보드
2. 운영 경고 패널
3. 주문 추적 / 실행 상태 패널
4. 포지션 / 현금 / 성과 패널
5. AI 판단 / 에이전트 실행 패널
6. 운영 루틴 체크 패널

## 메뉴명 제안

- 개요
- 주문
- 정합성 점검
- 계좌
- 판단
- 에이전트 실행
- 운영

## 화면 요구사항

### 1. 운영 대시보드

목적:
- 운영자가 로그인 직후 오늘 운영 가능한 상태인지 빠르게 판단

필수 위젯:
- `API 상태`
- `DB 상태`
- `Ready 상태`
- `브로커 용량`
- `마지막 스냅샷 동기화`
- `정합성 필요 주문 수`
- `오늘 AI 판단 수`
- `오늘 주문 제출 수`
- `운영 경고 배너`
- `최근 실행 타임라인`
- `오늘 포지션 / 현금 / 손익 요약`

### 2. 운영 경고 패널

필수 위젯:
- `즉시 확인 필요`
- `주의 상태`
- `정상 상태`
- `운영 메모`

경고 예시:
- 스냅샷 지연
- 정합성 필요 주문 증가
- sync 실패
- 토큰/인증 문제
- stale pending_submit 재발생

### 3. 주문 추적 / 실행 상태 패널

필수 위젯:
- 최근 주문 테이블
- 선택 주문 상세
- 상태 전이 타임라인
- 브로커 주문 매핑
- `ODNO`
- `last_synced_at`
- 관련 `Decision Context`
- 관련 `Trade Decision`

### 4. 포지션 / 현금 / 성과 패널

필수 위젯:
- 총 평가금액
- 현금
- 보유 종목 수
- 미실현 손익
- 포지션 테이블
- 성과 카드
- 일별 성과 추이

### 5. AI 판단 / 에이전트 실행 패널

필수 위젯:
- `APPROVE / HOLD / REJECT` 분포 카드
- 최근 판단 테이블
- 판단 상세 패널
- EI / Risk / FDC 실행 타임라인

### 6. 운영 루틴 체크 패널

필수 위젯:
- Pre-Market 체크 상태
- Intraday 체크 상태
- End-of-Day 체크 상태
- 주간 점검 상태

표현 예시:
- `정상`
- `주의`
- `미확인`
- `수동 조치 필요`

## 데이터 모델 힌트

이 화면은 아래 API 데이터를 사용한다고 가정하고 구성:

- `/health`
- `/health/readyz`
- `/broker-capacity`
- `/orders`
- `/orders/{id}`
- `/orders/{id}/events`
- `/orders/{id}/broker-orders`
- `/reconciliation/summary`
- `/reconciliation/runs`
- `/reconciliation/locks`
- `/accounts`
- `/positions`
- `/cash-balances`
- `/trade-decisions`
- `/decision-contexts/{id}`
- `/agent-runs`
- `/audit-logs`
- `/performance-summary`
- `/performance-history`
- `/performance-metrics`
- `/performance-benchmark`
- `/performance-benchmark-history`
- `/paper-go-no-go`

## 상태 표현 규칙

- 정상: 녹색 또는 차분한 청록
- 주의: 황색 / 앰버
- 위험: 적색
- 정보: 회색 / 청색

운영상 중요한 상태:
- `정합성 필요`
- `제출 대기`
- `실행 보류`
- `실행 가능`
- `경고`
- `실패`

## 레이아웃 원칙

- 상단: 상태 스트립 + 핵심 경고
- 본문 1열 또는 2열 그리드
- 표는 dense하게
- 선택 행 상세는 오른쪽 패널 또는 하단 패널
- 카드 수보다 **판단 속도**가 중요
- 차트는 최소한만 사용

## 금지 사항

- 영어 위주 메뉴
- 화려한 금융 마케팅 톤
- 의미 없는 원형 차트 남발
- 대형 히어로 배너
- 쓰기 액션 중심 UI
- 장식용 모션 과다

## 구현 우선순위

### P0

- 운영 대시보드
- 운영 경고
- 주문 추적

### P1

- 포지션 / 성과
- AI 판단 / 에이전트 실행
- 운영 루틴 체크

### P2

- 주간 운영 리뷰
- CTO 시연 모드

## v0.dev 전달 메모

- 결과물은 현재 Admin UI에 붙일 **운영 모니터링 화면 템플릿**이어야 한다
- 일반 사용자용 제품 화면처럼 만들지 말 것
- 메뉴, 카드 제목, 상태 문구는 가급적 한글로 작성할 것
- 기존 Orders / Reconciliation / Accounts / Decisions 구조와 충돌하지 않게, 운영 보강 화면으로 설계할 것
