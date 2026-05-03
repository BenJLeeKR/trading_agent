# Database Schema Draft v1

이 디렉터리는 거래 시스템의 초기 PostgreSQL 스키마 초안을 보관한다.

## 파일

- `migrations/0001_initial_schema.sql`
  - 핵심 도메인 테이블
  - 상태/감사/재현성 저장 구조
  - 인덱스 및 주요 제약조건

## 원칙

- 현재 상태 테이블과 이벤트 테이블을 함께 유지한다.
- 브로커 원문 payload와 replay bundle은 DB에 직접 저장하지 않고 URI 참조를 저장한다.
- 주문 경로는 멱등성과 정합성 복구를 전제로 설계한다.
- 초안은 PostgreSQL 기준이며, 이후 Alembic 같은 마이그레이션 도구로 분리 가능하다.

