# Admin UI Visual Direction

## 목적

이 문서는 Admin UI 리디자인/리파인 시 사용할 시각적 방향을 정의한다.

현재 목표는 완전한 브랜딩 작업이 아니라, 운영자용 read-only 콘솔을 더 정제된 엔터프라이즈 UI로 끌어올리는 것이다.

## 기준 레퍼런스

기준 스타일은 사용자가 선택한 Dribbble 레퍼런스의 방향을 따른다.

핵심은 아래와 같다.

- 프리미엄한 어드민 대시보드
- 차분한 다크 톤
- 적당한 유리 느낌(glass-like surface)
- 과하지 않은 라운드와 부드러운 패널
- 고급스럽지만 실제 운영에 쓸 수 있는 정보 밀도

중요:

- 레퍼런스를 “복제”하지 않는다
- 분위기, 밀도, 구성 방식, 시각 언어만 참고한다
- 실제 정보 구조는 현재 Admin UI와 운영 요구사항을 따른다

## 시각적 키워드

- enterprise
- premium
- operational
- dense
- composed
- restrained
- dark neutral
- glass-accented
- status-driven
- table-first

## 전체 톤

### 원하는 느낌

- 금융 운영 콘솔
- 백오피스 도구
- 통제된 전문성
- 실무자가 오래 봐도 피로가 덜한 화면
- 장식보다 정보 우선

### 피해야 할 느낌

- 마케팅 랜딩 페이지
- 소비자 SaaS
- 과도한 카드 장식
- 지나친 그라데이션
- neon / cyberpunk
- 과도한 crypto UI 느낌
- 빈 공간이 너무 많은 showcase dashboard

## 레이아웃 방향

- 좌측 고정 사이드바
- 상단 상태 표시 영역
- 중앙 메인 테이블
- 우측 또는 하단 상세 패널
- 필터 바는 테이블 상단
- overview는 summary card + recent table 조합
- detail drill-down은 modal보다 panel 우선

## 색상 시스템

### 기본 배경

- deep charcoal
- slate black
- graphite
- dark neutral blue-gray

### surface

- background보다 약간 밝은 panel
- 반투명 또는 blur 느낌 가능
- 다만 가독성 최우선

### 텍스트

- primary: near-white / very light gray
- secondary: muted gray
- tertiary/meta: dim slate gray

### 상태색

- success / healthy: muted green
- warning / attention: amber
- error / failed / lock: red
- info / neutral: blue-gray
- running / pending: subdued blue or amber

### 금지

- 보라색 위주 브랜드 톤
- 형광색
- rainbow status
- gradient-heavy panels

## 아이콘 방향

### 원칙

- outline 아이콘
- 얇고 정제된 stroke
- 기능 중심
- 작은 크기에서도 식별 가능

### 추천 계열

- lucide
- heroicons outline
- tabler-like style

### 용도

- navigation
- warning/status 보조
- section labeling

### 금지

- 3D 아이콘
- glossy 아이콘
- 이모지 중심 UI
- 과도하게 귀여운 스타일

## 표와 데이터 표현

- 데이터 테이블은 UI의 중심
- 숫자는 tabular 느낌 권장
- ID는 truncate 허용
- 상태는 color + label 동시 사용
- row hover는 subtle
- selected row는 배경 tint 또는 outline으로 명확히 표시

## 경고/오류 표현

아래 신호는 일반 정보보다 더 강하게 보여야 한다.

- active lock
- reflection failed
- degraded health
- reconcile required

표현 방식:

- tint background
- border emphasis
- warning icon
- 명확한 상태 텍스트

## 페이지별 시각 우선순위

### Overview

- 요약 카드
- 주요 경고 신호
- 최근 activity

### Orders

- 필터 바
- 주문 테이블
- detail panel
- state events
- broker mapping

### Reconciliation

- runs table
- locks table
- active lock 경고 배너

### Accounts

- accounts list
- selected account detail
- positions
- cash balance

### Decisions

- decisions list
- confidence indicator
- selected decision detail
- decision context panel

## 구현 원칙

- 스타일 토큰화 우선
- 공통 컴포넌트부터 리파인
- Layout / Card / Table / Badge / Banner / Detail Panel 기준으로 확장
- 기능 구조는 유지하고 시각 표현만 정교화

