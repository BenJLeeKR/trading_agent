# 증권 META 시스템 메타정보 사전 — 기간계 적용 확장본 v0.5

> 본 문서는 기존 `증권 META 시스템 메타정보 사전`을 실제 증권사 기간계 구축·분석·운영에 사용할 수 있도록 확장한 표준 설계 산출물입니다.  
> 단순 테이블 목록이 아니라 **업무 도메인 맵, 원장·잔고·결제 구조, 메타 관리 모델, 코드/도메인 관리, 인터페이스·배치 메타, 데이터 품질·권한·감사·변경관리 기준**까지 포함합니다.



## v0.5 통합 반영 요약

| 구분 | v0.5 반영 내용 |
| --- | --- |
| 테이블명 표준 | `증권시스템_테이블명명규칙_v0.1.md`의 12자리 고정 길이 코드형 테이블명 체계 `SDDBBBOOTVNN`을 본 메타 사전에 반영 |
| 테이블 메타 | 기존 물리테이블명과 별도로 `표준테이블명(STD_TBL_NM)`을 관리하는 구조 추가 |
| 레거시 호환 | 기존 `TB_ORD_MST`, `MT_COLUMN` 등의 물리명은 `LEGACY_TBL_NM` 또는 `PHYS_TBL_NM`으로 유지 가능하도록 매핑 기준 보강 |
| 컬럼명 표준 | `증권시스템_컬럼명명규칙_v0.1.md`의 논리명·물리명·Suffix·도메인·Audit·보안·품질검증 Rule을 컬럼 메타 기준에 반영 |
| META 관리 | 테이블명 규칙, 컬럼명 규칙, 코드/도메인, 품질 Rule, 변경요청을 META 시스템 관리 대상에 포함 |
| 적용 전략 | 신규 차세대/META 테이블은 표준명을 우선 적용하고, 기존 기간계 테이블은 표준명-물리명-레거시명 매핑 방식으로 병행 관리 |

---

## 작업 이력

| 버전 (Version) | 변경일자 (Date) | 변경자 (Author) | 변경 내용 (Description) | 승인자 (Approver) |
| :---: | :---: | :---: | :--- | :---: |
| v0.1 | 2026-06-10 10:12 | 시스템 | 최초 범용 메타정보 템플릿 마크다운 변환 및 생성 | 메타관리팀장 |
| v0.2 | 2026-06-10 13:33 | 개발자 | 국내주식(신용/대용), 파생상품(선물/옵션), 채권 상품 원장 보강 및 도메인 값 확장 | 데이터설계총괄 |
| v0.3 | 2026-06-10 13:47 | ChatGPT | 운영 메타, 품질 규칙, 배치 재처리, 인터페이스 필드 매핑, 개인정보/권한, 변경관리, DDL 예시 보강 | 계정계운영팀장 |
| v0.4 | 2026-06-20 20:18 | ChatGPT | 핵심 테이블 컬럼 메타를 실무 적용 수준으로 대폭 확장, 테이블별 업무 컬럼·상태 컬럼·처리 추적 컬럼·공통 Audit 컬럼 보강 | 데이터설계총괄 |
| v0.5 | 2026-06-21 | ChatGPT | 테이블명명규칙 v0.1의 12자리 고정 길이 코드형 표준명 체계와 컬럼명명규칙 v0.1의 컬럼 메타 Rule을 통합 반영. 핵심 테이블 메타에 표준테이블명 매핑, 컬럼 메타에 도메인·Suffix·Audit·품질검증 Rule 적용 기준 보강 | 데이터설계총괄 |
| v0.5.1 | 2026-06-21 | ChatGPT | 기존 물리 테이블명 중심의 `04. 핵심 기간계 테이블 메타`를 제거하고, 12자리 고정 길이 표준명 체계 기반의 `04. 테이블 표준명 적용 기준`으로 대체 | 데이터설계총괄 |

---

## 목차

- [00. 문서 목적 및 적용 범위](#00-문서-목적-및-적용-범위)
- [01. META 시스템 개념 아키텍처](#01-meta-시스템-개념-아키텍처)
- [02. 메타 관리 대상 및 분류 체계](#02-메타-관리-대상-및-분류-체계)
- [03. 업무 도메인 엔터티 맵](#03-업무-도메인-엔터티-맵)
- [04. 테이블 표준명 적용 기준](#04-테이블-표준명-적용-기준)
- [05. 핵심 테이블 컬럼 메타](#05-핵심-테이블-컬럼-메타)
- [05A. 컬럼 메타 Rule 적용 기준](#05a-컬럼-메타-rule-적용-기준)
- [06. 코드/도메인 값 메타](#06-코드도메인-값-메타)
- [07. 표준 데이터 타입 및 도메인](#07-표준-데이터-타입-및-도메인)
- [08. 명명 규칙 및 표준 약어](#08-명명-규칙-및-표준-약어)
- [09. 업무별 처리 기준](#09-업무별-처리-기준)
- [10. 인터페이스 및 전문 메타](#10-인터페이스-및-전문-메타)
- [11. 배치/스케줄 메타](#11-배치스케줄-메타)
- [12. 데이터 품질 및 검증 규칙](#12-데이터-품질-및-검증-규칙)
- [13. 보안, 개인정보, 권한 메타](#13-보안-개인정보-권한-메타)
- [14. 변경관리 및 영향도 분석](#14-변경관리-및-영향도-분석)
- [15. 운영 모니터링 및 장애 대응](#15-운영-모니터링-및-장애-대응)
- [16. 표준 DDL 예시](#16-표준-ddl-예시)
- [17. 프로젝트 적용 체크리스트](#17-프로젝트-적용-체크리스트)

---

## 00. 문서 목적 및 적용 범위

### 00.1 목적

| 구분 | 내용 |
| --- | --- |
| 목적 | 증권사 기간계/META 시스템 구축 시 데이터 표준화, 테이블 설계, 코드 관리, 인터페이스 관리, 배치 운영, 품질 점검, 영향도 분석에 사용할 수 있는 기준 문서 제공 |
| 핵심 사용자 | 업무 분석가, 데이터 아키텍트, DBA, 기간계 개발자, 인터페이스 개발자, 운영자, 감사/컴플라이언스 담당자 |
| 적용 범위 | 고객, 계좌, 상품/종목, 주문, 체결, 잔고, 예수금, 결제, 신용공여, 파생상품, 채권, 권리, 수수료/세금, 채널, 공통코드, 인터페이스, 배치, 감사로그 |
| 미적용 범위 | 회사 고유의 상품 정책, 내부 리스크 산식, 거래소 세부 전문 사양, 비공개 대외기관 전문, 실시간 매매 엔진 상세 알고리즘 |

### 00.2 설계 전제

| 항목 | 전제 |
| --- | --- |
| DBMS | Oracle 기준 표기. PostgreSQL, Tibero, DB2 적용 시 타입 및 파티션 구문 변환 필요 |
| 날짜 | 기준일자성 컬럼은 `CHAR(8)` `YYYYMMDD`를 기본으로 하되, 이벤트 시각은 `TIMESTAMP(6)` 권장 |
| 금액 | 원화/외화/채권 경과이자를 고려하여 `NUMBER(20,2)` 이상 권장 |
| 수량 | 해외주식·채권·펀드·소수점거래를 고려하여 `NUMBER(18,6)`까지 확장 가능 |
| 원장 | 주문/체결/결제/잔고/예수금은 정정·취소·재처리·감사를 고려해 변경 이력 또는 스냅샷 보관을 원칙으로 함 |
| 메타 | 업무 메타와 기술 메타를 분리하되, 영향도 분석을 위해 테이블·컬럼·코드·전문·배치 간 참조 관계를 관리함 |

---

## 01. META 시스템 개념 아키텍처

### 01.1 시스템 구성

| 계층 | 구성 요소 | 주요 역할 |
| --- | --- | --- |
| 메타 포털 | 메타 조회/등록 UI, 승인 워크플로우 | 테이블/컬럼/코드/전문/배치 메타의 등록, 검색, 승인, 변경 이력 조회 |
| 표준 관리 | 표준 단어, 표준 용어, 표준 약어, 표준 도메인 | 논리명·물리명 자동 변환, 명명 규칙 검증, 데이터 타입 표준화 |
| 데이터 모델 관리 | 엔터티, 테이블, 컬럼, PK/FK, 인덱스 | 논리/물리 모델 관리, ERD 연동, DDL 생성, 모델 버전 관리 |
| 코드 관리 | 코드그룹, 코드값, 유효기간, 사용여부 | 공통코드 배포, 코드 변경 영향도 분석, 채널/기간계 동기화 |
| 인터페이스 관리 | 전문, 필드, 송수신 시스템, 매핑 | 거래소/FEP/채널/대외기관 연계 전문 관리 및 변경 영향 분석 |
| 배치 관리 | Job, Step, 선후행, 재처리 정책 | 일마감/월마감/권리/정산 배치의 순서, 상태, 오류 처리 기준 관리 |
| 품질 관리 | 품질 규칙, 검증 결과, 예외 승인 | 중복, 무결성, 유효값, 금액 대사, 결산 검증 관리 |
| 보안/감사 | 개인정보 등급, 암호화, 마스킹, 접근권한 | 개인정보 보호, 조회/변경 이력, 승인 추적, 감사 대응 |

### 01.2 메타 간 관계

| From | To | 관계 | 예시 |
| --- | --- | --- | --- |
| 업무용어 | 표준단어 | 구성 | 주문접수일시 = 주문 + 접수 + 일시 |
| 표준용어 | 컬럼 | 사용 | 주문번호 → ORD_NO |
| 도메인 | 컬럼 | 타입 지정 | AMT → NUMBER(20,2) |
| 코드그룹 | 코드컬럼 | 유효값 지정 | ORD_STS_CD → 주문상태코드 |
| 테이블 | 컬럼 | 포함 | TB_ORD_MST contains ORD_DT, ORD_NO |
| 테이블 | 인터페이스필드 | 매핑 | IF_EXEC_RCV.EXEC_QTY → TB_EXEC_DTL.EXEC_QTY |
| 배치 | 테이블 | 입출력 | BAT_BAL_EOD reads TB_EXEC_DTL, writes TB_BAL_POS |
| API/전문 | 코드그룹 | 참조 | 주문구분코드, 매매구분코드 |
| 품질규칙 | 테이블/컬럼 | 검증 | 체결수량 > 0, 결제금액 대사 |

---

## 02. 메타 관리 대상 및 분류 체계

### 02.1 메타 유형

| 메타 유형 | 관리 단위 | 필수 관리 항목 | 사용 목적 |
| --- | --- | --- | --- |
| 업무 메타 | 업무영역, 엔터티, 업무용어 | 정의, 담당부서, 관련 프로세스, 주요 규칙 | 업무 공통 이해, 분석 기준 |
| 데이터 모델 메타 | 테이블, 컬럼, PK, FK, 인덱스 | 논리명, 물리명, 타입, 길이, NULL, 키, 설명 | DB 설계, 영향도 분석, DDL 생성 |
| 도메인 메타 | 데이터 타입 도메인 | 타입, 길이, 정밀도, 기본값, 검증규칙 | 데이터 표준화 |
| 코드 메타 | 코드그룹, 코드값 | 코드, 코드명, 설명, 유효기간, 사용여부 | 공통코드 관리, 채널 동기화 |
| 인터페이스 메타 | 전문, 필드, 송수신 시스템 | 전문ID, 필드순서, 타입, 필수여부, 매핑테이블 | 연계 표준화, 변경 영향 분석 |
| 배치 메타 | Job, Step, 스케줄, 선후행 | Job ID, 주기, 입력/출력, 재처리 정책 | 일마감/월마감 운영 안정성 |
| 품질 메타 | 품질 규칙, 검증 결과 | 규칙ID, 검증 SQL, 임계치, 조치 담당자 | 데이터 무결성 보장 |
| 보안 메타 | 개인정보, 암호화, 권한 | PII 등급, 마스킹, 암호화, 접근권한 | 개인정보보호, 감사 대응 |
| 운영 메타 | 오류코드, 로그, SLA | 오류유형, 심각도, 알림대상, 복구절차 | 장애 대응, 모니터링 |

### 02.2 메타 상태값

| 상태 | 설명 | 허용 작업 |
| --- | --- | --- |
| 작성중 | 담당자가 신규 메타를 작성 중인 상태 | 수정, 삭제 |
| 검토요청 | 표준/데이터/업무 담당자 검토 요청 상태 | 검토, 반려 |
| 승인 | 정식 표준으로 승인되어 사용 가능한 상태 | 참조, 배포, 변경요청 |
| 반려 | 검토 결과 표준 부적합 또는 중복으로 반려된 상태 | 수정 후 재요청 |
| 폐기예정 | 신규 사용 금지, 기존 시스템만 참조 가능 | 조회, 전환 계획 등록 |
| 폐기 | 사용 종료 | 조회만 허용 |

---

## 03. 업무 도메인 엔터티 맵

| 업무영역 | 주요 엔터티 | 대표 테이블 | 핵심 키 | 설명 | 연관 업무 |
| --- | --- | --- | --- | --- | --- |
| 고객 | 고객기본 | TB_CUST_MST | CUST_NO | 고객 식별, 실명확인, 고객상태, 투자자 구분 | 계좌, KYC, AML, 권한 |
| 고객 | 고객KYC | TB_CUST_KYC | CUST_NO | 투자성향, 위험등급, 고객확인의무, 적합성/적정성 | 상품판매, 주문제한, 컴플라이언스 |
| 고객 | 고객주소/연락처 | TB_CUST_ADDR | CUST_NO+ADDR_TP_CD | 주소, 휴대폰, 이메일, 통지 수단 | 우편, SMS, 알림톡, 전자문서 |
| 계좌 | 계좌기본 | TB_ACCT_MST | ACNO | 위탁/연금/파생/CMA 등 계좌 속성 | 고객, 주문, 잔고, 예수금 |
| 계좌 | 계좌권한 | TB_ACCT_AUTH | ACNO+USER_ID | 대리인, 직원, 온라인 사용자 권한 | 채널, 인증, 감사 |
| 계좌 | 계좌제한 | TB_ACCT_RSTR | ACNO+RSTR_CD | 사고, 압류, 거래정지, 미수동결 등 제한 | 주문, 출금, 대체 |
| 상품/종목 | 종목기본 | TB_ISU_MST | ISU_CD | 주식/ETF/ETN/ELW/채권/파생 공통 종목 | 주문, 시세, 권리 |
| 상품/종목 | 주식종목 | TB_STK_ISU_MST | ISU_CD | 상장주식, 우선주, 관리종목, 투자경고 | 주문, 잔고, 대용 |
| 상품/종목 | 파생종목 | TB_DERIV_ISU_MST | ISU_CD | 선물/옵션 만기, 행사가, 승수, 결제월 | 주문, 증거금, 정산 |
| 상품/종목 | 채권발행 | TB_BOND_ISS_MST | ISU_CD | 발행일, 만기일, 표면금리, 이자지급주기 | 채권매매, 이자, 상환 |
| 시세 | 현재가/호가 | TB_MKT_QUOTE | MKT_DT+ISU_CD | 현재가, 기준가, 상한가, 하한가, 호가단위 | 주문가능금, 평가, HTS/MTS |
| 주문 | 주문원장 | TB_ORD_MST | ORD_DT+ORD_NO | 주문 접수, 정정, 취소, 상태관리 | 채널, 계좌, 체결 |
| 주문 | 주문이력 | TB_ORD_HIST | ORD_DT+ORD_NO+HIST_SEQ | 주문 상태 변경 및 정정/취소 이력 | 감사, 민원, 장애분석 |
| 체결 | 체결내역 | TB_EXEC_DTL | EXEC_DT+EXEC_NO | 거래소 체결 결과, 부분체결, 비용 산정 | 주문, 잔고, 결제 |
| 잔고 | 종목잔고 | TB_BAL_POS | BAS_DT+ACNO+ISU_CD+BAL_TP_CD | 계좌별 상품 보유수량, 평가금액, 매입단가 | 체결, 평가, 권리 |
| 예수금 | 예수금잔고 | TB_CASH_BAL | BAS_DT+ACNO+CURR_CD | 예수금, 주문가능금, 출금가능금, 미수금 | 주문, 결제, 출납 |
| 결제 | 결제예정 | TB_STL_SCHD | STL_DT+ACNO+ISU_CD+STL_SEQ | 매수/매도 결제 예정 금액·수량 | 체결, 예수금, 잔고 |
| 신용공여 | 신용약정 | TB_CRD_AGR | ACNO | 신용거래 한도, 만기, 약정상태 | 계좌, 주문, 리스크 |
| 신용공여 | 신용융자 | TB_CRD_LOAN | LOAN_NO | 융자금, 담보, 이자, 상환, 만기 | 잔고, 예수금, 반대매매 |
| 담보 | 담보평가 | TB_COLL_EVAL | BAS_DT+ACNO | 담보금액, 담보비율, 부족금액 | 신용, 대출, 리스크 |
| 파생 | 파생증거금 | TB_DERIV_MARGIN | BAS_DT+ACNO+CURR_CD | 위탁/유지/추가증거금, 예탁총액 | 파생주문, 정산, 마진콜 |
| 파생 | 파생정산 | TB_DERIV_SETTL_DTL | STTL_DT+ACNO+ISU_CD | 정산가격, 정산차금, 평가손익 | 예수금, 리스크 |
| 채권 | 채권이자스케줄 | TB_BOND_INT_SCHD | ISU_CD+INT_PAY_SEQ | 이자계산기간, 지급일, 만원당 이자 | 권리, 예수금 |
| 권리 | 권리이벤트 | TB_RIGHT_EVT | RIGHT_EVT_NO | 배당, 유/무상증자, 분할, 합병 | 종목, 잔고, 결제 |
| 권리 | 권리배정 | TB_RIGHT_ALOC | RIGHT_EVT_NO+ACNO+ISU_CD | 계좌별 배정수량/금액 | 잔고, 예수금, 세금 |
| 수수료/세금 | 수수료세금규칙 | TB_FEE_TAX_RULE | RULE_ID | 시장/상품/채널/고객등급별 비용 산식 | 주문, 체결, 결제 |
| 채널 | 채널마스터 | TB_CHNL_MST | CHNL_CD | HTS/MTS/API/영업점/ARS 등 채널 관리 | 주문, 인증, 로그 |
| 조직 | 부점/직원 | TB_BR_EMP_MST | BR_CD+EMP_NO | 지점, 영업직원, 승인자, 관리부점 | 고객, 계좌, 감사 |
| 공통 | 공통코드 | TB_CODE_GRP/TB_CODE_DTL | GRP_CD+CD | 업무 코드, 유효값, 배포관리 | 전 업무 |
| 인터페이스 | 전문메타 | TB_IF_MSG_META | IF_ID | 송수신 전문, 필드, 매핑, 버전 | 거래소, FEP, 대외기관 |
| 배치 | 배치메타 | TB_BATCH_JOB_META | JOB_ID | Job, Step, 선후행, 재처리 정책 | 일마감, 월마감, 운영 |
| 감사 | 감사로그 | TB_AUDIT_LOG | LOG_ID | 조회/변경/승인/접속 이력 | 보안, 감사, 컴플라이언스 |

---

## 04. 테이블 표준명 적용 기준

> v0.5.1부터 핵심 기간계 테이블 메타는 기존 `TB_*`, `MT_*` 물리명 중심 목록을 별도 장으로 유지하지 않고, 12자리 고정 길이 코드형 표준 테이블명 체계로 통합 관리한다.  
> 기존 물리명은 레거시 호환 및 전환 관리를 위해 `PHYS_TBL_NM` 또는 `LEGACY_TBL_NM` 속성으로만 보관하며, 신규 표준 식별자는 `STD_TBL_NM`을 기준으로 한다.

> v0.5부터 테이블 메타는 기존 물리테이블명만 관리하지 않고, 테이블명명규칙 v0.1의 **12자리 고정 길이 코드형 표준명**을 함께 관리합니다.  
> 운영 DB의 물리명은 회사 전환 전략에 따라 기존명을 유지할 수 있으나, META 시스템에서는 `STD_TBL_NM`, `PHYS_TBL_NM`, `LEGACY_TBL_NM`을 분리 관리합니다.

### 04.1 표준 테이블명 포맷

```text
SDDBBBOOTVNN
```

| 위치 | 자리수 | 항목 | 설명 | 예시 |
| ---: | ---: | --- | --- | --- |
| 1 | 1 | 시스템 구분 | 기간계, META, 인터페이스, 스테이징, 로그 등 저장소 성격 | `C`, `M`, `I`, `S`, `L` |
| 2~3 | 2 | 업무영역 코드 | 고객, 계좌, 주문, 체결, 잔고, 예수금 등 업무 대분류 | `CU`, `AC`, `OR`, `EX` |
| 4~6 | 3 | 업무객체 코드 | 업무영역 내 세부 관리 객체 | `MST`, `ORD`, `EXC`, `POS` |
| 7~8 | 2 | 세부처리구분 코드 | 기본, 상세, 이력, 잔고, 정산, 평가, 룰, 로그 등 | `BS`, `DT`, `HS`, `BL` |
| 9 | 1 | 테이블 성격 코드 | 마스터, 거래, 상세, 이력, 잔고, 스케줄, 로그 등 | `M`, `T`, `D`, `H`, `B` |
| 10 | 1 | 버전/세대 코드 | 테이블 구조 세대 또는 버전 | `0`, `1`, `2`, `A` |
| 11~12 | 2 | 일련번호 | 동일 분류 내 순번 | `01`~`99` |

### 04.2 테이블명 관리 컬럼

| 컬럼 | 설명 | 적용 기준 |
| --- | --- | --- |
| `STD_TBL_NM` | 12자리 고정 길이 표준 테이블명 | META 표준명, 신규 차세대 테이블명 기준 |
| `PHYS_TBL_NM` | 실제 DB에 생성된 물리 테이블명 | 운영 DB 실제명. 기존 `TB_` 방식 유지 가능 |
| `LEGACY_TBL_NM` | 기존/레거시 테이블명 | 전환·마이그레이션·영향도 분석용 |
| `LOGIC_TBL_NM` | 논리 테이블명 | 업무 사용자가 이해하는 한글명 |
| `TBL_NM_RULE_ID` | 적용된 테이블명 규칙 ID | 예: `TBLNM12` |
| `TBL_NM_VALID_YN` | 표준명 규칙 검증 결과 | 자동 검증 결과 |
| `TBL_NM_VALID_MSG` | 표준명 검증 메시지 | 위반 위치와 사유 |

### 04.3 핵심 테이블 표준명 매핑

| 논리테이블명 | 기존 물리테이블명 | v0.5 표준테이블명 | 자리 해석 |
| --- | --- | --- | --- |
| 고객기본 | `TB_CUST_MST` | `CCUMSTBSM001` | C/CU/MST/BS/M/0/01 |
| 고객KYC정보 | `TB_CUST_KYC` | `CCUKYCBSM001` | C/CU/KYC/BS/M/0/01 |
| 고객주소연락처 | `TB_CUST_ADDR` | `CCUADRDTM001` | C/CU/ADR/DT/M/0/01 |
| 계좌기본 | `TB_ACCT_MST` | `CACMSTBSM001` | C/AC/MST/BS/M/0/01 |
| 계좌제한 | `TB_ACCT_RSTR` | `CACRSTBSM001` | C/AC/RST/BS/M/0/01 |
| 종목기본 | `TB_ISU_MST` | `CISMSTBSM001` | C/IS/MST/BS/M/0/01 |
| 주식종목기본 | `TB_STK_ISU_MST` | `CISSTKBSM001` | C/IS/STK/BS/M/0/01 |
| 해외상품기본 | `TB_FRGN_ISU_MST` | `CISFRNBSM001` | C/IS/FRN/BS/M/0/01 |
| 채권발행기본 | `TB_BOND_ISS_MST` | `CBDISSBSM001` | C/BD/ISS/BS/M/0/01 |
| 파생종목기본 | `TB_DERIV_ISU_MST` | `CDRDRVBSM001` | C/DR/DRV/BS/M/0/01 |
| 종목시세스냅샷 | `TB_MKT_QUOTE` | `CMKQUOSNB001` | C/MK/QUO/SN/B/0/01 |
| 주문원장 | `TB_ORD_MST` | `CORORDBST001` | C/OR/ORD/BS/T/0/01 |
| 주문이력 | `TB_ORD_HIST` | `CORORDHSH001` | C/OR/ORD/HS/H/0/01 |
| 체결내역 | `TB_EXEC_DTL` | `CEXEXCDTT001` | C/EX/EXC/DT/T/0/01 |
| 종목잔고 | `TB_BAL_POS` | `CBAPOSBLB001` | C/BA/POS/BL/B/0/01 |
| 예수금잔고 | `TB_CASH_BAL` | `CCACSHBLB001` | C/CA/CSH/BL/B/0/01 |
| 결제예정 | `TB_STL_SCHD` | `CSTSCHSTS001` | C/ST/SCH/ST/S/0/01 |
| 현금입출금내역 | `TB_CASH_IO_DTL` | `CCACSHDTT001` | C/CA/CSH/DT/T/0/01 |
| 신용약정 | `TB_CRD_AGR` | `CCRAGRBSM001` | C/CR/AGR/BS/M/0/01 |
| 신용융자내역 | `TB_CRD_LOAN` | `CCRLONDTT001` | C/CR/LON/DT/T/0/01 |
| 담보평가내역 | `TB_COLL_EVAL` | `CCLEVLEVB001` | C/CL/EVL/EV/B/0/01 |
| 파생증거금 | `TB_DERIV_MARGIN` | `CDRMRGBLB001` | C/DR/MRG/BL/B/0/01 |
| 파생정산내역 | `TB_DERIV_SETTL_DTL` | `CDRSTLSTT001` | C/DR/STL/ST/T/0/01 |
| 채권이자스케줄 | `TB_BOND_INT_SCHD` | `CBDINTSTS001` | C/BD/INT/ST/S/0/01 |
| 권리이벤트 | `TB_RIGHT_EVT` | `CRTEVTBSE001` | C/RT/EVT/BS/E/0/01 |
| 권리배정내역 | `TB_RIGHT_ALOC` | `CRTALCDTT001` | C/RT/ALC/DT/T/0/01 |
| 수수료세금규칙 | `TB_FEE_TAX_RULE` | `CFEFTRRLR001` | C/FE/FTR/RL/R/0/01 |
| 공통코드그룹 | `TB_CODE_GRP` | `CCMCODCDC001` | C/CM/COD/CD/C/0/01 |
| 공통코드상세 | `TB_CODE_DTL` | `CCMCODDTD001` | C/CM/COD/DT/D/0/01 |
| 인터페이스메타 | `TB_IF_MSG_META` | `MIFMSGIFI001` | M/IF/MSG/IF/I/0/01 |
| 인터페이스필드메타 | `TB_IF_FIELD_META` | `MIFFLDDTD001` | M/IF/FLD/DT/D/0/01 |
| 배치Job메타 | `TB_BATCH_JOB_META` | `MBTJOBBSM001` | M/BT/JOB/BS/M/0/01 |
| 배치실행로그 | `TB_BATCH_RUN_LOG` | `LBTRUNLGL001` | L/BT/RUN/LG/L/0/01 |
| 감사로그 | `TB_AUDIT_LOG` | `LAULOGLGL001` | L/AU/LOG/LG/L/0/01 |
| 메타테이블 | `MT_TABLE` | `MMTTBLBSM001` | M/MT/TBL/BS/M/0/01 |
| 메타컬럼 | `MT_COLUMN` | `MMTCOLBSM001` | M/MT/COL/BS/M/0/01 |
| 메타도메인 | `MT_DOMAIN` | `MMTDOMDMM001` | M/MT/DOM/DM/M/0/01 |
| 메타코드그룹 | `MT_CODE_GRP` | `MMTCODCDC001` | M/MT/COD/CD/C/0/01 |
| 메타코드상세 | `MT_CODE_DTL` | `MMTCODDTD001` | M/MT/COD/DT/D/0/01 |
| 메타품질규칙 | `MT_DQ_RULE` | `MDQRULRLQ001` | M/DQ/RUL/RL/Q/0/01 |
| 메타변경요청 | `MT_CHANGE_REQ` | `MMTCHGRQA001` | M/MT/CHG/RQ/A/0/01 |

### 04.4 테이블명 검증 Rule

| Rule ID | 검증 항목 | 검증 기준 |
| --- | --- | --- |
| `TBL-NM-001` | 길이 검증 | 표준테이블명은 반드시 12자리 |
| `TBL-NM-002` | 문자 검증 | 영문 대문자와 숫자만 허용. `_`, 공백, 특수문자 금지 |
| `TBL-NM-003` | 시스템 구분 검증 | 1번째 자리는 `SYS_DVSN_CD` 코드값에 존재해야 함 |
| `TBL-NM-004` | 업무영역 검증 | 2~3번째 자리는 `BIZ_AREA_CD` 코드값에 존재해야 함 |
| `TBL-NM-005` | 업무객체 검증 | 4~6번째 자리는 해당 업무영역에 허용된 객체 코드여야 함 |
| `TBL-NM-006` | 세부처리구분 검증 | 7~8번째 자리는 `SUB_PROC_CD` 코드값에 존재해야 함 |
| `TBL-NM-007` | 테이블성격 검증 | 9번째 자리는 `TBL_KIND_CD` 코드값에 존재해야 함 |
| `TBL-NM-008` | 버전 검증 | 10번째 자리는 `0~9`, `A~Z` 허용 |
| `TBL-NM-009` | 순번 검증 | 11~12번째 자리는 `01~99` 숫자 |
| `TBL-NM-010` | 중복 검증 | 동일 `STD_TBL_NM` 중복 불가 |
| `TBL-NM-011` | 의미 조합 검증 | 세부처리구분과 테이블성격이 모순되면 반려. 예: `BL` + `M` 조합 지양 |

### 04.5 적용 전략

| 구분 | 적용 방식 |
| --- | --- |
| 신규 차세대 테이블 | `STD_TBL_NM`을 실제 물리명으로 우선 적용 |
| 기존 기간계 테이블 | 기존명을 `PHYS_TBL_NM` 또는 `LEGACY_TBL_NM`으로 유지하고, `STD_TBL_NM`을 별도 매핑 |
| 인터페이스/배치 | 송수신 전문, Job, Step, 품질 Rule과 `STD_TBL_NM` 기준으로 영향도 분석 |
| 전환 기간 | 프로그램에서는 기존 물리명을 사용하되, META 포털과 설계 산출물은 표준명을 병기 |
| 최종 전환 | 신규 업무부터 표준명 우선 적용 후, 레거시 테이블은 단계적 전환 |

## 05. 핵심 테이블 컬럼 메타

> v0.4에서는 각 핵심 테이블을 실제 기간계 설계의 출발점으로 사용할 수 있도록 업무 필수 컬럼, 상태/처리 컬럼, 원천 추적 컬럼, 배치 재처리 컬럼, 개인정보/보안 컬럼, 공통 Audit 컬럼을 보강했습니다.  
> 회사별 표준 약어, DBMS 타입, 파티션 정책, 개인정보 암호화 정책에 따라 물리명과 타입은 조정할 수 있습니다.

### 05.0 공통 Audit/운영 컬럼 적용 원칙

| 구분 | 권장 컬럼 | 적용 대상 | 설계 기준 |
| --- | --- | --- | --- |
| 등록 감사 | `REG_DTTM`, `REG_USER_ID`, `REG_PGM_ID` | Master/Rule/Meta/Transaction | 최초 생성 주체와 프로그램을 추적합니다. 대외 연계 데이터는 시스템 ID를 사용자 ID로 저장할 수 있습니다. |
| 변경 감사 | `CHG_DTTM`, `CHG_USER_ID`, `CHG_PGM_ID` | 변경 가능한 전 테이블 | 최종 변경 정보만 본 테이블에 두고, 상세 변경 이력은 History 또는 Audit Log에 보관합니다. |
| 논리삭제 | `DEL_YN` | Master/Rule/Meta | 기간계 원장은 물리삭제를 지양하고 논리삭제 + 이력 보관을 원칙으로 합니다. |
| 사용상태 | `USE_YN`, `VALID_STRT_DT`, `VALID_END_DT` | 코드/규칙/상품/채널/수수료 | 신규 거래 가능 여부와 과거 데이터 참조 가능 여부를 분리합니다. |
| 원천추적 | `SRC_SYS_ID`, `SRC_TR_ID`, `IF_ID`, `MSG_ID` | Interface/Transaction | 거래소/FEP/채널/대외기관 원천 전문과 기간계 원장의 추적성을 확보합니다. |
| 배치추적 | `PROC_JOB_ID`, `RUN_ID`, `PROC_DTTM`, `PROC_STS_CD` | Batch 산출 테이블 | 재처리, 정합성 검증, 장애 복구를 위해 생성 배치와 실행 ID를 보관합니다. |
| 동시성 | `DATA_VER_NO` | Master/Meta/Rule | 화면 또는 API에서 동시 변경 시 낙관적 잠금 기준으로 사용합니다. |
| 보안/개인정보 | `PII_GRD_CD`, `ENC_YN`, `MSK_YN` | 개인정보 포함 테이블/컬럼 메타 | 암호화/마스킹/권한 통제 정책과 연결합니다. |
| 승인통제 | `APPR_STS_CD`, `APPR_USER_ID`, `APPR_DTTM` | 한도/수수료/코드/메타 변경 | 운영 반영 전 승인 워크플로우를 추적합니다. |
| 보정관리 | `ADJ_YN`, `ADJ_RSN_CD`, `ADJ_USER_ID`, `ADJ_DTTM` | 잔고/예수금/결제/권리 | 수작업 보정 또는 장애 복구 보정의 사유와 책임자를 남깁니다. |



## 05A. 컬럼 메타 Rule 적용 기준

> v0.5부터 컬럼 메타는 단순 컬럼 목록이 아니라, 컬럼명명규칙 v0.1의 **논리명·물리명·Suffix·도메인·PK/FK·NULL·코드·Audit·개인정보·품질검증 Rule**을 함께 관리합니다.

### 05A.1 컬럼 메타 필수 관리 항목

| 구분 | 항목 | 필수 | 설명 |
| --- | --- | :---: | --- |
| 기본 | 업무영역 | Y | 고객, 계좌, 주문, 체결 등 |
| 기본 | 논리테이블명 | Y | 업무적으로 이해 가능한 테이블명 |
| 기본 | 표준테이블명 | Y | 12자리 표준 테이블명. 예: `CORORDBST001` |
| 기본 | 물리테이블명 | Y | 실제 DB 테이블명. 예: `TB_ORD_MST` |
| 기본 | 컬럼순서 | Y | 테이블 내 컬럼 순서 |
| 기본 | 논리컬럼명 | Y | 한글 업무 컬럼명 |
| 기본 | 물리컬럼명 | Y | 영문 컬럼명 |
| 기본 | 컬럼설명 | Y | 업무적 의미, 계산식, 사용 기준 |
| 타입 | 도메인ID | Y | 표준 도메인 참조 |
| 타입 | 데이터타입 | Y | DBMS 타입 |
| 타입 | 길이/정밀도/Scale | Y | VARCHAR2 길이, NUMBER precision/scale 등 |
| 제약 | PK/FK/NULL 여부 | Y | 키와 NULL 허용 기준 |
| 코드 | 코드그룹ID | 조건부 | `_CD` 컬럼은 원칙적으로 필수 |
| 보안 | 개인정보/암호화/마스킹 | 조건부 | 개인정보 컬럼은 필수 관리 |
| 운영 | Audit 적용 여부 | Y | 등록/변경/프로그램/원천추적 컬럼 적용 여부 |
| 품질 | 품질검증 Rule ID | 조건부 | 수량, 금액, 코드, FK, 산식 검증 등 |
| 변경 | 변경요청ID/승인상태 | Y | 컬럼 신설·변경·폐기 이력 관리 |

### 05A.2 컬럼 물리명 표준 Suffix

| Suffix | 의미 | 표준 도메인 | 예시 |
| --- | --- | --- | --- |
| `_NO` | 번호 | ID/NO | `CUST_NO`, `ORD_NO`, `EXEC_NO` |
| `_ID` | 시스템 식별자 | USER_ID/SYS_ID | `USER_ID`, `JOB_ID`, `MSG_ID` |
| `_CD` | 코드 | CODE | `ORD_STS_CD`, `MKT_DVSN_CD` |
| `_NM` | 명칭 | NAME | `CUST_NM`, `ISU_NM` |
| `_DT` | 일자 | DATE8 | `ORD_DT`, `EXEC_DT`, `STL_DT` |
| `_DTTM` | 일시 | DTTM | `RCPT_DTTM`, `REG_DTTM` |
| `_AMT` | 금액 | AMT | `ORD_AMT`, `FEE_AMT` |
| `_QTY` | 수량 | QTY | `ORD_QTY`, `HOLD_QTY` |
| `_UPRC` | 단가 | PRICE | `ORD_UPRC`, `EXEC_UPRC` |
| `_PRC` | 가격 | PRICE | `STTL_PRC`, `SUB_PRC` |
| `_RT` | 비율/율 | RATE | `INT_RT`, `FEE_RT` |
| `_YN` | 여부 | YN | `USE_YN`, `DEL_YN` |
| `_SEQ` | 순번 | SEQ | `HIST_SEQ`, `FIELD_SEQ` |
| `_CNT` | 건수/횟수 | COUNT | `PROC_CNT`, `ERR_CNT` |
| `_MSG` | 메시지 | TEXT | `ERR_MSG`, `RJCT_MSG` |
| `_DESC` | 설명 | TEXT | `RULE_DESC` |
| `_DVSN_CD` | 구분코드 | CODE | `BUY_SELL_DVSN_CD` |
| `_TP_CD` | 유형코드 | CODE | `PRD_TP_CD` |
| `_STS_CD` | 상태코드 | CODE | `ORD_STS_CD` |
| `_RSLT_CD` | 결과코드 | CODE | `PROC_RSLT_CD` |
| `_ERR_CD` | 오류코드 | CODE | `ERR_CD` |

### 05A.3 데이터 타입 및 도메인 Rule

| Rule ID | 규칙 | 권장 기준 |
| --- | --- | --- |
| `COL-TYPE-001` | `_DT` 컬럼은 `DATE8` 도메인 또는 회사 표준 DATE 도메인을 사용 | `CHAR(8)` `YYYYMMDD` |
| `COL-TYPE-002` | `_DTTM` 컬럼은 일시 도메인을 사용 | `TIMESTAMP(6)` |
| `COL-TYPE-003` | `_AMT` 컬럼은 금액 도메인을 사용 | `NUMBER(20,2)` 이상 |
| `COL-TYPE-004` | `_QTY` 컬럼은 수량 도메인을 사용 | `NUMBER(18,6)` 권장 |
| `COL-TYPE-005` | `_RT` 컬럼은 비율 도메인을 사용 | `NUMBER(12,8)` 권장 |
| `COL-TYPE-006` | `_YN` 컬럼은 여부 도메인을 사용 | `CHAR(1)` + `Y/N` |
| `COL-TYPE-007` | `_CD` 컬럼은 코드그룹 길이에 맞춤 | 코드그룹 필수 |
| `COL-TYPE-008` | 설명/메시지 컬럼은 업무상 최대 길이를 산정 | `VARCHAR2(500~4000)` |

### 05A.4 PK/FK/NULL Rule

| Rule ID | 검증 항목 | 기준 |
| --- | --- | --- |
| `COL-KEY-001` | PK NULL 검증 | PK 컬럼은 `NULL` 허용 불가 |
| `COL-KEY-002` | 업무키 검증 | 원장성 테이블은 업무일자 + 업무번호 조합 우선 |
| `COL-KEY-003` | 잔고키 검증 | 잔고는 기준일자 + 계좌 + 종목 + 잔고유형 + 신용구분 등으로 식별 |
| `COL-KEY-004` | 이력키 검증 | 이력 테이블은 원천 PK + 이력순번 또는 변경일시 포함 |
| `COL-KEY-005` | FK 메타 검증 | 물리 FK가 없어도 논리 FK는 META에 등록 |
| `COL-NULL-001` | 금액/수량 NULL 검증 | 계산 대상 금액/수량은 `0` 기본값 원칙 |
| `COL-NULL-002` | 종료일자 기준 | 미종료 상태는 NULL 또는 `99991231` 중 회사 표준 선택 |

### 05A.5 Audit/운영 컬럼 적용 Matrix

| 테이블 유형 | 기본 Audit | 원천추적 | 처리추적 | 삭제여부 | 사용여부 | 데이터버전 |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| Master | Y | 조건부 | 조건부 | Y | Y | Y |
| Transaction | Y | Y | Y | 조건부 | N | 조건부 |
| Balance | Y | 조건부 | Y | N | N | 조건부 |
| Schedule | Y | 조건부 | Y | 조건부 | 조건부 | 조건부 |
| History | Y | 조건부 | 조건부 | N | N | N |
| Code | Y | N | 조건부 | Y | Y | Y |
| Rule | Y | N | 조건부 | Y | Y | Y |
| Interface | Y | Y | Y | 조건부 | 조건부 | 조건부 |
| Batch Log | Y | Y | Y | N | N | N |
| Audit Log | 생성 Audit만 | 조건부 | 조건부 | N | N | N |

### 05A.6 컬럼 품질 검증 Rule

| Rule ID | 검증대상 | 검증내용 |
| --- | --- | --- |
| `COL-META-001` | 물리컬럼명 | 영문 대문자, 숫자, `_`만 허용 |
| `COL-META-002` | 물리컬럼명 | DBMS 예약어 사용 금지 |
| `COL-META-003` | 논리컬럼명 | `값1`, `구분`, `비고1` 등 의미 없는 명칭 금지 |
| `COL-META-004` | Suffix | suffix와 도메인 일치 |
| `COL-META-005` | 코드컬럼 | `_CD` 컬럼은 코드그룹 필수 |
| `COL-META-006` | 여부컬럼 | `_YN` 컬럼은 `YN` 도메인 필수 |
| `COL-META-007` | PK컬럼 | PK 컬럼은 NULL 허용 불가 |
| `COL-META-008` | FK컬럼 | FK 대상 테이블/컬럼 메타 필수 |
| `COL-META-009` | 개인정보 | 개인정보 컬럼은 보안 메타 필수 |
| `COL-META-010` | Audit | 운영 테이블은 기본 Audit 컬럼 필요 |

### 05A.7 컬럼 메타 등록 반려 기준

| 반려 사유 | 예시 |
| --- | --- |
| 동일 의미 기존 표준 컬럼 존재 | 신규 `ACCOUNT_NO` 요청, 기존 `ACNO` 존재 |
| 물리명 표준 위반 | `order_date`, `GUBUN`, `AMOUNT` |
| 도메인 불일치 | `_AMT` 컬럼을 `VARCHAR2`로 신청 |
| 코드그룹 누락 | `ORD_STS_CD`에 코드그룹 미지정 |
| 개인정보 메타 누락 | `MOBILE_NO`에 마스킹여부 미지정 |
| Audit 컬럼 누락 | 운영 Master 테이블에 `REG_DTTM` 없음 |
| 설명 부족 | 컬럼 설명이 “값”, “구분”, “금액”처럼 불명확 |
| 영향도 분석 누락 | 물리컬럼명 변경인데 인터페이스/배치 영향 미분석 |

### 05.1 고객기본 `TB_CUST_MST`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 고객번호 | CUST_NO | VARCHAR2(12) | Y | N | N | CUST_NO | 고객 고유 식별자. 내부 고객번호 |
| 2 | 고객구분코드 | CUST_DVSN_CD | CHAR(1) | N | N | N | CODE | 개인/법인/외국인/재외국민 등 |
| 3 | 고객명 | CUST_NM | VARCHAR2(100) | N | N | N | NAME | 고객 실명 또는 법인명. 마스킹 대상 |
| 4 | 영문고객명 | ENG_CUST_NM | VARCHAR2(200) | N | N | Y | NAME | 해외거래/외국인 고객 영문명 |
| 5 | 실명확인여부 | REAL_NM_CFM_YN | CHAR(1) | N | N | N | YN | 실명확인 완료 여부 |
| 6 | 실명확인일자 | REAL_NM_CFM_DT | CHAR(8) | N | N | Y | DATE8 | 실명확인 수행일 |
| 7 | 고객상태코드 | CUST_STS_CD | CHAR(2) | N | N | N | CODE | 정상/휴면/탈퇴/거래정지 |
| 8 | 고객위험등급코드 | CUST_RISK_GRD_CD | CHAR(2) | N | N | Y | CODE | AML/KYC 위험등급 |
| 9 | 투자자구분코드 | INVR_DVSN_CD | CHAR(2) | N | N | Y | CODE | 일반/전문투자자 등 |
| 10 | 생년월일 | BIRTH_DT | CHAR(8) | N | N | Y | DATE8 | 개인 고객 생년월일. 암호화 또는 별도 개인정보 테이블 분리 검토 |
| 11 | 성별코드 | GENDER_CD | CHAR(1) | N | N | Y | CODE | 성별 구분. 필요한 업무에서만 관리 |
| 12 | 법인등록번호 | CORP_REG_NO | VARCHAR2(20) | N | N | Y | IDENT_NO | 법인 고객 식별번호. 암호화 대상 |
| 13 | 사업자등록번호 | BIZ_REG_NO | VARCHAR2(20) | N | N | Y | IDENT_NO | 사업자 등록 식별번호 |
| 14 | 국적코드 | NAT_CD | CHAR(3) | N | N | Y | COUNTRY_CD | ISO 국가코드 |
| 15 | 거주자여부 | RESD_YN | CHAR(1) | N | N | Y | YN | 거주자/비거주자 구분 |
| 16 | 세법상거주국가코드 | TAX_RESD_NAT_CD | CHAR(3) | N | N | Y | COUNTRY_CD | CRS/FATCA 등 세무 거주지 |
| 17 | 관리부점코드 | MGMT_BR_CD | VARCHAR2(6) | N | Y | N | BR_CD | 담당 지점 또는 관리 부서 |
| 18 | 담당직원번호 | CHRG_EMP_NO | VARCHAR2(20) | N | Y | Y | EMP_NO | 담당 PB/영업직원 |
| 19 | 개인정보등급코드 | PII_GRD_CD | CHAR(1) | N | N | N | CODE | 개인정보 민감도 등급 |
| 20 | 마케팅동의여부 | MKT_AGR_YN | CHAR(1) | N | N | N | YN | 마케팅 수신 동의 여부 |
| 21 | 전자문서동의여부 | ELEC_DOC_AGR_YN | CHAR(1) | N | N | N | YN | 전자문서 교부 동의 여부 |
| 22 | 사용여부 | USE_YN | CHAR(1) | N | N | N | YN | 사용 가능 여부. 신규 거래/조회 노출 기준 |
| 23 | 삭제여부 | DEL_YN | CHAR(1) | N | N | N | YN | 논리삭제 여부. 물리삭제 대신 이력 추적 유지 |
| 24 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 입력 일시 |
| 25 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 입력 사용자 또는 시스템 ID |
| 26 | 최초등록프로그램ID | REG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최초 입력 프로그램/서비스 ID |
| 27 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 28 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |
| 29 | 최종변경프로그램ID | CHG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최종 변경 프로그램/서비스 ID |
| 30 | 데이터버전번호 | DATA_VER_NO | NUMBER(10) | N | N | N | SEQ | 낙관적 잠금 및 변경 충돌 방지용 버전 |

### 05.2 고객KYC정보 `TB_CUST_KYC`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 고객번호 | CUST_NO | VARCHAR2(12) | Y | Y | N | CUST_NO | KYC 대상 고객 |
| 2 | KYC수행일자 | KYC_EXEC_DT | CHAR(8) | N | N | N | DATE8 | 고객확인의무 수행일 |
| 3 | KYC만료일자 | KYC_EXPI_DT | CHAR(8) | N | N | Y | DATE8 | 재확인 필요 만료일 |
| 4 | 투자성향코드 | INV_PREF_CD | CHAR(2) | N | N | Y | CODE | 안정형/중립형/공격형 등 |
| 5 | 투자목적코드 | INV_PURP_CD | CHAR(2) | N | N | Y | CODE | 수익/헤지/연금/단기자금 등 |
| 6 | 소득구간코드 | INCOME_RNG_CD | CHAR(2) | N | N | Y | CODE | 고객 신고 소득구간 |
| 7 | 자산구간코드 | ASSET_RNG_CD | CHAR(2) | N | N | Y | CODE | 고객 신고 자산구간 |
| 8 | 투자경험코드 | INV_EXP_CD | CHAR(2) | N | N | Y | CODE | 주식/파생/채권 등 경험 수준 |
| 9 | 위험감내등급코드 | RISK_TOL_GRD_CD | CHAR(2) | N | N | Y | CODE | 상품 적합성 판단 기준 |
| 10 | 적합성검증결과코드 | SUIT_TEST_RSLT_CD | CHAR(2) | N | N | Y | CODE | 적합/부적합/확인불가 |
| 11 | 적정성확인여부 | APPROP_CFM_YN | CHAR(1) | N | N | N | YN | 부적합 상품 거래 시 확인 여부 |
| 12 | AML위험등급코드 | AML_RISK_GRD_CD | CHAR(2) | N | N | N | CODE | AML 모니터링 위험등급 |
| 13 | 고위험고객여부 | HIGH_RISK_CUST_YN | CHAR(1) | N | N | N | YN | 고위험 고객 여부 |
| 14 | 정보수집출처코드 | INFO_SRC_CD | CHAR(2) | N | N | Y | CODE | 온라인/영업점/대외기관 등 |
| 15 | 사용여부 | USE_YN | CHAR(1) | N | N | N | YN | 사용 가능 여부. 신규 거래/조회 노출 기준 |
| 16 | 삭제여부 | DEL_YN | CHAR(1) | N | N | N | YN | 논리삭제 여부. 물리삭제 대신 이력 추적 유지 |
| 17 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 입력 일시 |
| 18 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 입력 사용자 또는 시스템 ID |
| 19 | 최초등록프로그램ID | REG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최초 입력 프로그램/서비스 ID |
| 20 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 21 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |
| 22 | 최종변경프로그램ID | CHG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최종 변경 프로그램/서비스 ID |
| 23 | 데이터버전번호 | DATA_VER_NO | NUMBER(10) | N | N | N | SEQ | 낙관적 잠금 및 변경 충돌 방지용 버전 |

### 05.3 고객주소연락처 `TB_CUST_ADDR`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 고객번호 | CUST_NO | VARCHAR2(12) | Y | Y | N | CUST_NO | 주소/연락처 대상 고객 |
| 2 | 주소유형코드 | ADDR_TP_CD | CHAR(2) | Y | N | N | CODE | 자택/직장/우편/법인본점 등 |
| 3 | 주소순번 | ADDR_SEQ | NUMBER(5) | Y | N | N | SEQ | 동일 유형 내 순번 |
| 4 | 우편번호 | ZIP_CD | VARCHAR2(10) | N | N | Y | CODE | 우편번호 |
| 5 | 기본주소 | BASE_ADDR | VARCHAR2(300) | N | N | Y | ADDR | 기본 주소. 마스킹 대상 |
| 6 | 상세주소 | DTL_ADDR | VARCHAR2(300) | N | N | Y | ADDR | 상세 주소. 마스킹 대상 |
| 7 | 휴대폰번호 | MOBILE_NO | VARCHAR2(100) | N | N | Y | PHONE | 암호화 저장 권장 |
| 8 | 전화번호 | TEL_NO | VARCHAR2(100) | N | N | Y | PHONE | 자택/직장 전화번호 |
| 9 | 이메일주소 | EMAIL_ADDR | VARCHAR2(200) | N | N | Y | EMAIL | 전자문서/알림 수신 이메일 |
| 10 | 기본연락처여부 | BASE_CNTC_YN | CHAR(1) | N | N | N | YN | 기본 연락처 여부 |
| 11 | 통지가능여부 | NOTI_ABLE_YN | CHAR(1) | N | N | N | YN | 우편/SMS/이메일 통지 가능 여부 |
| 12 | 유효시작일자 | VALID_STRT_DT | CHAR(8) | N | N | N | DATE8 | 연락처 유효 시작일 |
| 13 | 유효종료일자 | VALID_END_DT | CHAR(8) | N | N | N | DATE8 | 연락처 유효 종료일 |
| 14 | 사용여부 | USE_YN | CHAR(1) | N | N | N | YN | 사용 가능 여부. 신규 거래/조회 노출 기준 |
| 15 | 삭제여부 | DEL_YN | CHAR(1) | N | N | N | YN | 논리삭제 여부. 물리삭제 대신 이력 추적 유지 |
| 16 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 입력 일시 |
| 17 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 입력 사용자 또는 시스템 ID |
| 18 | 최초등록프로그램ID | REG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최초 입력 프로그램/서비스 ID |
| 19 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 20 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |
| 21 | 최종변경프로그램ID | CHG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최종 변경 프로그램/서비스 ID |
| 22 | 데이터버전번호 | DATA_VER_NO | NUMBER(10) | N | N | N | SEQ | 낙관적 잠금 및 변경 충돌 방지용 버전 |

### 05.4 계좌기본 `TB_ACCT_MST`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 계좌번호 | ACNO | VARCHAR2(20) | Y | N | N | ACNO | 계좌 고유 식별자 |
| 2 | 고객번호 | CUST_NO | VARCHAR2(12) | N | Y | N | CUST_NO | 계좌 소유 고객 |
| 3 | 종합계좌번호 | COMP_ACNO | VARCHAR2(20) | N | N | Y | ACNO | 종합계좌 또는 대표계좌 |
| 4 | 계좌상품구분코드 | ACCT_PRD_DVSN_CD | CHAR(2) | N | N | N | CODE | 위탁/연금/신용/파생/CMA |
| 5 | 계좌상태코드 | ACCT_STS_CD | CHAR(2) | N | N | N | CODE | 정상/폐쇄/거래정지/휴면 |
| 6 | 개설일자 | OPEN_DT | CHAR(8) | N | N | N | DATE8 | 계좌 개설일 |
| 7 | 폐쇄일자 | CLS_DT | CHAR(8) | N | N | Y | DATE8 | 계좌 폐쇄일 |
| 8 | 관리부점코드 | MGMT_BR_CD | VARCHAR2(6) | N | Y | N | BR_CD | 계좌 관리 부점 |
| 9 | 담당직원번호 | CHRG_EMP_NO | VARCHAR2(20) | N | Y | Y | EMP_NO | 계좌 담당자 |
| 10 | 기본통화코드 | BASE_CURR_CD | CHAR(3) | N | N | N | CURR_CD | KRW/USD 등 |
| 11 | 온라인거래가능여부 | ONLN_TRD_ABLE_YN | CHAR(1) | N | N | N | YN | HTS/MTS/API 거래 가능 여부 |
| 12 | 신용거래가능여부 | CRD_TRD_ABLE_YN | CHAR(1) | N | N | N | YN | 신용 약정 및 주문 가능 여부 |
| 13 | 파생거래가능여부 | DERIV_TRD_ABLE_YN | CHAR(1) | N | N | N | YN | 선물옵션 거래 가능 여부 |
| 14 | 해외거래가능여부 | FRGN_TRD_ABLE_YN | CHAR(1) | N | N | N | YN | 해외주식/해외파생 거래 가능 여부 |
| 15 | 출금제한여부 | WDRW_RSTR_YN | CHAR(1) | N | N | N | YN | 사고/압류 등 출금 제한 |
| 16 | 주문제한여부 | ORD_RSTR_YN | CHAR(1) | N | N | N | YN | 주문 제한 여부 |
| 17 | 부실계좌여부 | BAD_ACCT_YN | CHAR(1) | N | N | N | YN | 미수/연체/사고 계좌 여부 |
| 18 | 미수동결여부 | RCVB_FRZ_YN | CHAR(1) | N | N | N | YN | 미수동결계좌 여부 |
| 19 | 반대매매대상여부 | FORCE_SELL_TGT_YN | CHAR(1) | N | N | N | YN | 강제청산 대상 여부 |
| 20 | 비대면개설여부 | NON_FACE_OPEN_YN | CHAR(1) | N | N | N | YN | 비대면 개설 여부 |
| 21 | 계좌개설채널코드 | OPEN_CHNL_CD | VARCHAR2(10) | N | Y | Y | CHNL_CD | 계좌 개설 채널 |
| 22 | 사용여부 | USE_YN | CHAR(1) | N | N | N | YN | 사용 가능 여부. 신규 거래/조회 노출 기준 |
| 23 | 삭제여부 | DEL_YN | CHAR(1) | N | N | N | YN | 논리삭제 여부. 물리삭제 대신 이력 추적 유지 |
| 24 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 입력 일시 |
| 25 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 입력 사용자 또는 시스템 ID |
| 26 | 최초등록프로그램ID | REG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최초 입력 프로그램/서비스 ID |
| 27 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 28 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |
| 29 | 최종변경프로그램ID | CHG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최종 변경 프로그램/서비스 ID |
| 30 | 데이터버전번호 | DATA_VER_NO | NUMBER(10) | N | N | N | SEQ | 낙관적 잠금 및 변경 충돌 방지용 버전 |

### 05.5 계좌제한 `TB_ACCT_RSTR`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 계좌번호 | ACNO | VARCHAR2(20) | Y | Y | N | ACNO | 제한 대상 계좌 |
| 2 | 제한코드 | RSTR_CD | VARCHAR2(20) | Y | N | N | CODE | 압류/사고/미수동결/주문제한/출금제한 등 |
| 3 | 제한순번 | RSTR_SEQ | NUMBER(5) | Y | N | N | SEQ | 동일 제한코드 내 순번 |
| 4 | 제한상태코드 | RSTR_STS_CD | CHAR(2) | N | N | N | CODE | 등록/해제/보류 |
| 5 | 제한시작일자 | RSTR_STRT_DT | CHAR(8) | N | N | N | DATE8 | 제한 시작일 |
| 6 | 제한종료일자 | RSTR_END_DT | CHAR(8) | N | N | Y | DATE8 | 제한 종료 예정일 |
| 7 | 제한등록사유코드 | RSTR_REG_RSN_CD | VARCHAR2(20) | N | N | Y | CODE | 제한 등록 사유 |
| 8 | 제한등록내용 | RSTR_REG_CONT | VARCHAR2(1000) | N | N | Y | TEXT | 제한 등록 상세 내용 |
| 9 | 해제일자 | RLSE_DT | CHAR(8) | N | N | Y | DATE8 | 제한 해제일 |
| 10 | 해제사유코드 | RLSE_RSN_CD | VARCHAR2(20) | N | N | Y | CODE | 제한 해제 사유 |
| 11 | 승인상태코드 | APPR_STS_CD | CHAR(2) | N | N | N | CODE | 승인대기/승인/반려 |
| 12 | 승인사용자ID | APPR_USER_ID | VARCHAR2(50) | N | N | Y | USER_ID | 제한 등록/해제 승인자 |
| 13 | 승인일시 | APPR_DTTM | TIMESTAMP(6) | N | N | Y | DTTM | 승인 일시 |
| 14 | 사용여부 | USE_YN | CHAR(1) | N | N | N | YN | 사용 가능 여부. 신규 거래/조회 노출 기준 |
| 15 | 삭제여부 | DEL_YN | CHAR(1) | N | N | N | YN | 논리삭제 여부. 물리삭제 대신 이력 추적 유지 |
| 16 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 입력 일시 |
| 17 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 입력 사용자 또는 시스템 ID |
| 18 | 최초등록프로그램ID | REG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최초 입력 프로그램/서비스 ID |
| 19 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 20 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |
| 21 | 최종변경프로그램ID | CHG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최종 변경 프로그램/서비스 ID |
| 22 | 데이터버전번호 | DATA_VER_NO | NUMBER(10) | N | N | N | SEQ | 낙관적 잠금 및 변경 충돌 방지용 버전 |

### 05.6 종목기본 `TB_ISU_MST`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 종목코드 | ISU_CD | VARCHAR2(12) | Y | N | N | ISU_CD | 표준 종목코드/ISIN |
| 2 | 단축종목코드 | SHTN_ISU_CD | VARCHAR2(9) | N | N | Y | ISU_CD | 거래소 단축코드 |
| 3 | 종목명 | ISU_NM | VARCHAR2(200) | N | N | N | NAME | 종목 한글명 |
| 4 | 영문종목명 | ENG_ISU_NM | VARCHAR2(200) | N | N | Y | NAME | 종목 영문명 |
| 5 | 시장구분코드 | MKT_DVSN_CD | CHAR(2) | N | N | N | CODE | KOSPI/KOSDAQ/KONEX/파생/해외 |
| 6 | 상품유형코드 | PRD_TP_CD | CHAR(2) | N | N | N | CODE | 주식/ETF/ETN/채권/선물/옵션 |
| 7 | 거래통화코드 | TRD_CURR_CD | CHAR(3) | N | N | N | CURR_CD | KRW/USD 등 |
| 8 | 상장일자 | LIST_DT | CHAR(8) | N | N | Y | DATE8 | 상장일 |
| 9 | 상장폐지일자 | DELIST_DT | CHAR(8) | N | N | Y | DATE8 | 상장폐지일 |
| 10 | 거래정지여부 | TRD_SPND_YN | CHAR(1) | N | N | N | YN | 거래정지 여부 |
| 11 | 관리종목여부 | MNGR_ISU_YN | CHAR(1) | N | N | N | YN | 관리종목 여부 |
| 12 | 투자경고코드 | INV_WARN_CD | CHAR(2) | N | N | Y | CODE | 투자주의/경고/위험 |
| 13 | 액면가 | PAR_PRC | NUMBER(18,4) | N | N | Y | PRICE | 주식 액면가 또는 채권 액면 기준 |
| 14 | 호가단위코드 | TICK_SIZE_CD | VARCHAR2(20) | N | N | Y | CODE | 가격대별 호가단위 규칙 |
| 15 | 최소주문수량 | MIN_ORD_QTY | NUMBER(18,6) | N | N | N | QTY | 주문 최소 단위 |
| 16 | 거래단위수량 | TRD_UNIT_QTY | NUMBER(18,6) | N | N | N | QTY | 시장 거래 단위 |
| 17 | 가격제한폭비율 | PRC_LMT_RT | NUMBER(12,8) | N | N | Y | RATE | 상하한가 산정 비율 |
| 18 | 대용가능여부 | SUB_ABLE_YN | CHAR(1) | N | N | N | YN | 증거금/담보 대용 가능 여부 |
| 19 | 사용여부 | USE_YN | CHAR(1) | N | N | N | YN | 사용 가능 여부. 신규 거래/조회 노출 기준 |
| 20 | 삭제여부 | DEL_YN | CHAR(1) | N | N | N | YN | 논리삭제 여부. 물리삭제 대신 이력 추적 유지 |
| 21 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 입력 일시 |
| 22 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 입력 사용자 또는 시스템 ID |
| 23 | 최초등록프로그램ID | REG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최초 입력 프로그램/서비스 ID |
| 24 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 25 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |
| 26 | 최종변경프로그램ID | CHG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최종 변경 프로그램/서비스 ID |
| 27 | 데이터버전번호 | DATA_VER_NO | NUMBER(10) | N | N | N | SEQ | 낙관적 잠금 및 변경 충돌 방지용 버전 |

### 05.7 종목시세스냅샷 `TB_MKT_QUOTE`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 시장일자 | MKT_DT | CHAR(8) | Y | N | N | DATE8 | 시세 기준일 |
| 2 | 종목코드 | ISU_CD | VARCHAR2(12) | Y | Y | N | ISU_CD | 시세 대상 종목 |
| 3 | 시장구분코드 | MKT_DVSN_CD | CHAR(2) | N | N | N | CODE | 시장 구분 |
| 4 | 기준가 | BASE_PRC | NUMBER(18,6) | N | N | Y | PRICE | 당일 기준가 |
| 5 | 전일종가 | PRV_CLPR | NUMBER(18,6) | N | N | Y | PRICE | 전일 종가 |
| 6 | 시가 | OPEN_PRC | NUMBER(18,6) | N | N | Y | PRICE | 시가 |
| 7 | 고가 | HIGH_PRC | NUMBER(18,6) | N | N | Y | PRICE | 고가 |
| 8 | 저가 | LOW_PRC | NUMBER(18,6) | N | N | Y | PRICE | 저가 |
| 9 | 현재가 | CUR_PRC | NUMBER(18,6) | N | N | Y | PRICE | 현재가 또는 종가 |
| 10 | 상한가 | UP_LMT_PRC | NUMBER(18,6) | N | N | Y | PRICE | 상한가 |
| 11 | 하한가 | LOW_LMT_PRC | NUMBER(18,6) | N | N | Y | PRICE | 하한가 |
| 12 | 누적거래량 | ACML_TRD_QTY | NUMBER(22,6) | N | N | N | QTY | 누적 거래량 |
| 13 | 누적거래대금 | ACML_TRD_AMT | NUMBER(24,2) | N | N | N | AMT | 누적 거래대금 |
| 14 | 거래정지여부 | TRD_SPND_YN | CHAR(1) | N | N | N | YN | 시세 기준 거래정지 여부 |
| 15 | 시세수신일시 | QUOTE_RCV_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 시세 원천 수신 일시 |
| 16 | 시세원천코드 | QUOTE_SRC_CD | VARCHAR2(20) | N | N | Y | CODE | 거래소/벤더/FEP 등 원천 |
| 17 | 원천시스템ID | SRC_SYS_ID | VARCHAR2(30) | N | N | Y | SYS_ID | 데이터를 발생시킨 원천 시스템 |
| 18 | 원천거래ID | SRC_TR_ID | VARCHAR2(100) | N | N | Y | TR_ID | 원천 거래/전문/요청 식별자 |
| 19 | 처리상태코드 | PROC_STS_CD | CHAR(2) | N | N | N | CODE | 정상/오류/보류/재처리 등 처리 상태 |
| 20 | 처리일시 | PROC_DTTM | TIMESTAMP(6) | N | N | Y | DTTM | 원장 반영 또는 최종 처리 일시 |
| 21 | 처리배치ID | PROC_JOB_ID | VARCHAR2(50) | N | N | Y | JOB_ID | 배치 반영 시 실행 Job ID |
| 22 | 오류코드 | ERR_CD | VARCHAR2(30) | N | N | Y | CODE | 처리 오류 발생 시 표준 오류코드 |
| 23 | 오류메시지 | ERR_MSG | VARCHAR2(1000) | N | N | Y | TEXT | 처리 오류 상세 메시지 |
| 24 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 적재 일시 |
| 25 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 적재 사용자 또는 시스템 ID |
| 26 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 27 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |

### 05.8 주문원장 `TB_ORD_MST`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 주문일자 | ORD_DT | CHAR(8) | Y | N | N | DATE8 | 주문 발생 일자 |
| 2 | 주문번호 | ORD_NO | VARCHAR2(20) | Y | N | N | ORD_NO | 내부 주문 식별 번호 |
| 3 | 원주문번호 | ORG_ORD_NO | VARCHAR2(20) | N | Y | Y | ORD_NO | 정정/취소 대상 주문번호 |
| 4 | 상위주문번호 | PRNT_ORD_NO | VARCHAR2(20) | N | Y | Y | ORD_NO | 알고리즘/분할주문 모주문 번호 |
| 5 | 계좌번호 | ACNO | VARCHAR2(20) | N | Y | N | ACNO | 주문 계좌 |
| 6 | 고객번호 | CUST_NO | VARCHAR2(12) | N | Y | Y | CUST_NO | 계좌 고객. 조회 성능 목적 중복 가능 |
| 7 | 종목코드 | ISU_CD | VARCHAR2(12) | N | Y | N | ISU_CD | 주문 종목 |
| 8 | 시장구분코드 | MKT_DVSN_CD | CHAR(2) | N | N | N | CODE | 주문 시장 |
| 9 | 상품유형코드 | PRD_TP_CD | CHAR(2) | N | N | N | CODE | 주식/ETF/채권/선물/옵션 |
| 10 | 매매구분코드 | BUY_SELL_DVSN_CD | CHAR(1) | N | N | N | CODE | 매도/매수/정정/취소 |
| 11 | 주문구분코드 | ORD_DVSN_CD | CHAR(2) | N | N | N | CODE | 지정가/시장가/조건부/시간외 |
| 12 | 주문조건코드 | ORD_COND_CD | CHAR(2) | N | N | Y | CODE | IOC/FOK/장개시/장마감 등 |
| 13 | 주문상태코드 | ORD_STS_CD | CHAR(2) | N | N | N | CODE | 접수/확인/일부체결/전량체결/거부/취소 |
| 14 | 주문수량 | ORD_QTY | NUMBER(18,6) | N | N | N | QTY | 최초 주문 수량 |
| 15 | 주문단가 | ORD_UPRC | NUMBER(18,6) | N | N | Y | PRICE | 지정가 주문 가격 |
| 16 | 주문금액 | ORD_AMT | NUMBER(20,2) | N | N | N | AMT | 주문수량 × 주문단가 또는 예상금액 |
| 17 | 체결누계수량 | EXEC_ACML_QTY | NUMBER(18,6) | N | N | N | QTY | 누적 체결 수량 |
| 18 | 체결누계금액 | EXEC_ACML_AMT | NUMBER(20,2) | N | N | N | AMT | 누적 체결 금액 |
| 19 | 미체결수량 | UNEXEC_QTY | NUMBER(18,6) | N | N | N | QTY | 주문수량 - 체결누계수량 - 취소수량 |
| 20 | 취소수량 | CNCL_QTY | NUMBER(18,6) | N | N | N | QTY | 취소 처리 수량 |
| 21 | 채널코드 | CHNL_CD | VARCHAR2(10) | N | Y | N | CHNL_CD | HTS/MTS/API/영업점 |
| 22 | 주문매체상세코드 | ORD_MEDIA_DTL_CD | VARCHAR2(20) | N | N | Y | CODE | 모바일OS/API App/영업점 단말 등 |
| 23 | 대외주문번호 | EXCH_ORD_NO | VARCHAR2(30) | N | N | Y | ORD_NO | 거래소/FEP 주문번호 |
| 24 | 접수일시 | RCPT_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 주문 접수 시각 |
| 25 | 거래소전송일시 | EXCH_SEND_DTTM | TIMESTAMP(6) | N | N | Y | DTTM | 거래소 송신 시각 |
| 26 | 거래소확인일시 | EXCH_CFM_DTTM | TIMESTAMP(6) | N | N | Y | DTTM | 거래소/FEP 확인 시각 |
| 27 | 거부코드 | RJCT_CD | VARCHAR2(20) | N | N | Y | CODE | 주문 거부 사유 코드 |
| 28 | 거부메시지 | RJCT_MSG | VARCHAR2(500) | N | N | Y | TEXT | 대고객/운영자 확인용 메시지 |
| 29 | 신용구분코드 | CRD_DVSN_CD | CHAR(2) | N | N | Y | CODE | 현금/자기융자/상환 등 |
| 30 | 대출일자 | LOAN_DT | CHAR(8) | N | N | Y | DATE8 | 신용 상환 주문 대상 융자일 |
| 31 | 매도담보구분코드 | SELL_MGE_DVSN_CD | CHAR(2) | N | N | Y | CODE | 일반매도/상환매도/반대매매 |
| 32 | 증거금율 | MARGIN_RT | NUMBER(12,8) | N | N | Y | RATE | 주문 시 적용 증거금율 |
| 33 | 주문가능금액차감액 | ORD_ABLE_DED_AMT | NUMBER(20,2) | N | N | Y | AMT | 주문 접수 시 주문가능금 차감액 |
| 34 | 영업일자 | BIZ_DT | CHAR(8) | N | N | N | DATE8 | 거래 캘린더 기준 영업일 |
| 35 | 원천시스템ID | SRC_SYS_ID | VARCHAR2(30) | N | N | Y | SYS_ID | 데이터를 발생시킨 원천 시스템 |
| 36 | 원천거래ID | SRC_TR_ID | VARCHAR2(100) | N | N | Y | TR_ID | 원천 거래/전문/요청 식별자 |
| 37 | 처리상태코드 | PROC_STS_CD | CHAR(2) | N | N | N | CODE | 정상/오류/보류/재처리 등 처리 상태 |
| 38 | 처리일시 | PROC_DTTM | TIMESTAMP(6) | N | N | Y | DTTM | 원장 반영 또는 최종 처리 일시 |
| 39 | 처리배치ID | PROC_JOB_ID | VARCHAR2(50) | N | N | Y | JOB_ID | 배치 반영 시 실행 Job ID |
| 40 | 오류코드 | ERR_CD | VARCHAR2(30) | N | N | Y | CODE | 처리 오류 발생 시 표준 오류코드 |
| 41 | 오류메시지 | ERR_MSG | VARCHAR2(1000) | N | N | Y | TEXT | 처리 오류 상세 메시지 |
| 42 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 적재 일시 |
| 43 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 적재 사용자 또는 시스템 ID |
| 44 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 45 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |

### 05.9 주문이력 `TB_ORD_HIST`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 주문일자 | ORD_DT | CHAR(8) | Y | Y | N | DATE8 | 원 주문일자 |
| 2 | 주문번호 | ORD_NO | VARCHAR2(20) | Y | Y | N | ORD_NO | 원 주문번호 |
| 3 | 이력순번 | HIST_SEQ | NUMBER(10) | Y | N | N | SEQ | 주문별 상태 변경 순번 |
| 4 | 이력유형코드 | HIST_TP_CD | VARCHAR2(20) | N | N | N | CODE | 접수/확인/체결/정정/취소/거부/보정 |
| 5 | 변경전주문상태코드 | BEF_ORD_STS_CD | CHAR(2) | N | N | Y | CODE | 변경 전 주문상태 |
| 6 | 변경후주문상태코드 | AFT_ORD_STS_CD | CHAR(2) | N | N | Y | CODE | 변경 후 주문상태 |
| 7 | 변경수량 | CHG_QTY | NUMBER(18,6) | N | N | Y | QTY | 정정/취소/체결에 따른 변경 수량 |
| 8 | 변경단가 | CHG_UPRC | NUMBER(18,6) | N | N | Y | PRICE | 가격 정정 시 변경 단가 |
| 9 | 이벤트발생일시 | EVT_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 상태 변경 이벤트 발생 시각 |
| 10 | 전문ID | IF_ID | VARCHAR2(50) | N | Y | Y | IF_ID | 상태 변경을 유발한 전문 ID |
| 11 | 메시지ID | MSG_ID | VARCHAR2(100) | N | N | Y | MSG_ID | 원천 메시지 식별자 |
| 12 | 이력생성일시 | HIST_CRT_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 이력 레코드 생성 일시 |
| 13 | 이력생성사유코드 | HIST_CRT_RSN_CD | VARCHAR2(20) | N | N | Y | CODE | 정정/취소/상태변경/배치보정 등 사유 |
| 14 | 변경전값내용 | BEF_VAL_CONT | CLOB | N | N | Y | TEXT | 변경 전 주요 값 JSON 또는 전문 원문 |
| 15 | 변경후값내용 | AFT_VAL_CONT | CLOB | N | N | Y | TEXT | 변경 후 주요 값 JSON 또는 전문 원문 |
| 16 | 변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 이력 발생 사용자 또는 시스템 ID |

### 05.10 체결내역 `TB_EXEC_DTL`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 체결일자 | EXEC_DT | CHAR(8) | Y | N | N | DATE8 | 체결 발생 일자 |
| 2 | 체결번호 | EXEC_NO | VARCHAR2(20) | Y | N | N | EXEC_NO | 내부 체결 식별 번호 |
| 3 | 주문일자 | ORD_DT | CHAR(8) | N | Y | N | DATE8 | 원 주문일자 |
| 4 | 주문번호 | ORD_NO | VARCHAR2(20) | N | Y | N | ORD_NO | 원 주문번호 |
| 5 | 계좌번호 | ACNO | VARCHAR2(20) | N | Y | N | ACNO | 체결 계좌 |
| 6 | 고객번호 | CUST_NO | VARCHAR2(12) | N | Y | Y | CUST_NO | 조회 성능 목적 중복 가능 |
| 7 | 종목코드 | ISU_CD | VARCHAR2(12) | N | Y | N | ISU_CD | 체결 종목 |
| 8 | 시장구분코드 | MKT_DVSN_CD | CHAR(2) | N | N | N | CODE | 체결 시장 |
| 9 | 상품유형코드 | PRD_TP_CD | CHAR(2) | N | N | N | CODE | 상품 유형 |
| 10 | 매매구분코드 | BUY_SELL_DVSN_CD | CHAR(1) | N | N | N | CODE | 매도/매수 |
| 11 | 체결수량 | EXEC_QTY | NUMBER(18,6) | N | N | N | QTY | 부분체결 단위 수량 |
| 12 | 체결단가 | EXEC_UPRC | NUMBER(18,6) | N | N | N | PRICE | 체결 가격 |
| 13 | 체결금액 | EXEC_AMT | NUMBER(20,2) | N | N | N | AMT | 체결수량 × 체결단가 |
| 14 | 수수료금액 | FEE_AMT | NUMBER(20,2) | N | N | N | AMT | 체결 기준 수수료 |
| 15 | 세금금액 | TAX_AMT | NUMBER(20,2) | N | N | N | AMT | 거래세 등 세금 |
| 16 | 기타비용금액 | ETC_COST_AMT | NUMBER(20,2) | N | N | N | AMT | 유관기관수수료 등 기타 비용 |
| 17 | 당일결제금액 | TDY_STL_AMT | NUMBER(20,2) | N | N | N | AMT | 비용 반영 후 정산 금액 |
| 18 | 거래소체결번호 | EXCH_EXEC_NO | VARCHAR2(30) | N | N | N | EXEC_NO | 거래소 원천 체결번호 |
| 19 | 체결일시 | EXEC_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 체결 시각 |
| 20 | 결제예정일자 | STL_DT | CHAR(8) | N | N | N | DATE8 | T+N 결제일 |
| 21 | 비용규칙ID | FEE_TAX_RULE_ID | VARCHAR2(30) | N | Y | Y | RULE_ID | 적용 수수료/세금 규칙 |
| 22 | 잔고반영여부 | BAL_APLY_YN | CHAR(1) | N | N | N | YN | 잔고 반영 완료 여부 |
| 23 | 예수금반영여부 | CASH_APLY_YN | CHAR(1) | N | N | N | YN | 예수금 반영 완료 여부 |
| 24 | 결제생성여부 | STL_CRT_YN | CHAR(1) | N | N | N | YN | 결제예정 생성 여부 |
| 25 | 원천시스템ID | SRC_SYS_ID | VARCHAR2(30) | N | N | Y | SYS_ID | 데이터를 발생시킨 원천 시스템 |
| 26 | 원천거래ID | SRC_TR_ID | VARCHAR2(100) | N | N | Y | TR_ID | 원천 거래/전문/요청 식별자 |
| 27 | 처리상태코드 | PROC_STS_CD | CHAR(2) | N | N | N | CODE | 정상/오류/보류/재처리 등 처리 상태 |
| 28 | 처리일시 | PROC_DTTM | TIMESTAMP(6) | N | N | Y | DTTM | 원장 반영 또는 최종 처리 일시 |
| 29 | 처리배치ID | PROC_JOB_ID | VARCHAR2(50) | N | N | Y | JOB_ID | 배치 반영 시 실행 Job ID |
| 30 | 오류코드 | ERR_CD | VARCHAR2(30) | N | N | Y | CODE | 처리 오류 발생 시 표준 오류코드 |
| 31 | 오류메시지 | ERR_MSG | VARCHAR2(1000) | N | N | Y | TEXT | 처리 오류 상세 메시지 |
| 32 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 적재 일시 |
| 33 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 적재 사용자 또는 시스템 ID |
| 34 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 35 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |

### 05.11 종목잔고 `TB_BAL_POS`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 기준일자 | BAS_DT | CHAR(8) | Y | N | N | DATE8 | 잔고 기준일 |
| 2 | 계좌번호 | ACNO | VARCHAR2(20) | Y | Y | N | ACNO | 잔고 계좌 |
| 3 | 종목코드 | ISU_CD | VARCHAR2(12) | Y | Y | N | ISU_CD | 보유 종목 |
| 4 | 잔고유형코드 | BAL_TP_CD | CHAR(2) | Y | N | N | CODE | 일반/신용/대여/담보/권리 |
| 5 | 신용구분코드 | CRD_DVSN_CD | CHAR(2) | Y | N | N | CODE | 현금성/자기융자/예탁담보대출 |
| 6 | 대출일자 | LOAN_DT | CHAR(8) | Y | N | N | DATE8 | 신용 잔고 융자일. 일반잔고는 00000000 가능 |
| 7 | 보유수량 | HOLD_QTY | NUMBER(18,6) | N | N | N | QTY | 현재 보유 수량 |
| 8 | 주문가능수량 | ORD_ABLE_QTY | NUMBER(18,6) | N | N | N | QTY | 매도 주문 가능 수량 |
| 9 | 출고가능수량 | OUT_ABLE_QTY | NUMBER(18,6) | N | N | N | QTY | 대체/출고 가능 수량 |
| 10 | 담보지정수량 | COLL_ASGN_QTY | NUMBER(18,6) | N | N | N | QTY | 담보로 지정된 수량 |
| 11 | 대여수량 | LEND_QTY | NUMBER(18,6) | N | N | N | QTY | 대여 중인 수량 |
| 12 | 권리기준수량 | RIGHT_BASE_QTY | NUMBER(18,6) | N | N | Y | QTY | 권리 산정 기준 수량 |
| 13 | 매입금액 | BUY_AMT | NUMBER(20,2) | N | N | N | AMT | 평균단가 산정 기준 매입 금액 |
| 14 | 매입평균단가 | BUY_AVG_UPRC | NUMBER(18,6) | N | N | Y | PRICE | 매입 평균 단가 |
| 15 | 평가단가 | EVAL_UPRC | NUMBER(18,6) | N | N | Y | PRICE | 평가 적용 단가 |
| 16 | 평가금액 | EVAL_AMT | NUMBER(20,2) | N | N | N | AMT | 보유수량 × 평가가격 |
| 17 | 평가손익금액 | EVAL_PL_AMT | NUMBER(20,2) | N | N | N | AMT | 평가금액 - 매입금액 |
| 18 | 대용가격 | SUB_PRC | NUMBER(18,6) | N | N | Y | PRICE | 대용평가 기준 가격 |
| 19 | 대용평가금액 | SUB_EVAL_AMT | NUMBER(20,2) | N | N | N | AMT | 대용가격 × 대용가능수량 |
| 20 | 담보대출가능수량 | MGE_LOAN_ABLE_QTY | NUMBER(18,6) | N | N | N | QTY | 예탁담보대출 대상 가능 주식 수량 |
| 21 | 권리락반영여부 | RIGHT_ADJ_YN | CHAR(1) | N | N | N | YN | 권리/분할 조정 반영 여부 |
| 22 | 보정여부 | ADJ_YN | CHAR(1) | N | N | N | YN | 수작업 또는 장애 복구 보정 여부 |
| 23 | 보정사유코드 | ADJ_RSN_CD | VARCHAR2(20) | N | N | Y | CODE | 보정 사유 |
| 24 | 원천시스템ID | SRC_SYS_ID | VARCHAR2(30) | N | N | Y | SYS_ID | 데이터를 발생시킨 원천 시스템 |
| 25 | 원천거래ID | SRC_TR_ID | VARCHAR2(100) | N | N | Y | TR_ID | 원천 거래/전문/요청 식별자 |
| 26 | 처리상태코드 | PROC_STS_CD | CHAR(2) | N | N | N | CODE | 정상/오류/보류/재처리 등 처리 상태 |
| 27 | 처리일시 | PROC_DTTM | TIMESTAMP(6) | N | N | Y | DTTM | 원장 반영 또는 최종 처리 일시 |
| 28 | 처리배치ID | PROC_JOB_ID | VARCHAR2(50) | N | N | Y | JOB_ID | 배치 반영 시 실행 Job ID |
| 29 | 오류코드 | ERR_CD | VARCHAR2(30) | N | N | Y | CODE | 처리 오류 발생 시 표준 오류코드 |
| 30 | 오류메시지 | ERR_MSG | VARCHAR2(1000) | N | N | Y | TEXT | 처리 오류 상세 메시지 |
| 31 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 적재 일시 |
| 32 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 적재 사용자 또는 시스템 ID |
| 33 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 34 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |

### 05.12 예수금잔고 `TB_CASH_BAL`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 기준일자 | BAS_DT | CHAR(8) | Y | N | N | DATE8 | 잔고 기준일 |
| 2 | 계좌번호 | ACNO | VARCHAR2(20) | Y | Y | N | ACNO | 예수금 계좌 |
| 3 | 통화코드 | CURR_CD | CHAR(3) | Y | N | N | CURR_CD | KRW/USD 등 |
| 4 | 예수금 | DPST_AMT | NUMBER(20,2) | N | N | N | AMT | 현재 현금 예수금 |
| 5 | 주문가능금액 | ORD_ABLE_AMT | NUMBER(20,2) | N | N | N | AMT | 신규 주문 가능 금액 |
| 6 | 출금가능금액 | WDRW_ABLE_AMT | NUMBER(20,2) | N | N | N | AMT | 출금 가능 금액 |
| 7 | 익일예수금 | D1_DPST_AMT | NUMBER(20,2) | N | N | N | AMT | T+1 예상 예수금 |
| 8 | 이튿날예수금 | D2_DPST_AMT | NUMBER(20,2) | N | N | N | AMT | T+2 예상 예수금 |
| 9 | 미수금액 | RCVB_AMT | NUMBER(20,2) | N | N | N | AMT | 미수 발생 금액 |
| 10 | 연체미수금액 | DMND_RCVB_AMT | NUMBER(20,2) | N | N | N | AMT | 반대매매 대상 연체 미수 |
| 11 | 증거금사용금액 | MARGIN_USE_AMT | NUMBER(20,2) | N | N | N | AMT | 주문 또는 파생 증거금 사용 금액 |
| 12 | 미결제매수금액 | UNSTL_BUY_AMT | NUMBER(20,2) | N | N | N | AMT | 아직 결제되지 않은 매수 금액 |
| 13 | 미결제매도금액 | UNSTL_SELL_AMT | NUMBER(20,2) | N | N | N | AMT | 아직 결제되지 않은 매도 금액 |
| 14 | 매수결제예정금액 | BUY_STL_SCHD_AMT | NUMBER(20,2) | N | N | N | AMT | 매수 결제 예정 금액 |
| 15 | 매도결제예정금액 | SELL_STL_SCHD_AMT | NUMBER(20,2) | N | N | N | AMT | 매도 결제 예정 금액 |
| 16 | 대용평가금액 | SUB_EVAL_AMT | NUMBER(20,2) | N | N | N | AMT | 대용증권 평가 금액 |
| 17 | 담보평가금액 | COLL_EVAL_AMT | NUMBER(20,2) | N | N | N | AMT | 담보 평가 금액 |
| 18 | 환산예수금 | CNV_DPST_AMT | NUMBER(20,2) | N | N | Y | AMT | 기준통화 환산 예수금 |
| 19 | 적용환율 | APLY_EXRT | NUMBER(18,8) | N | N | Y | RATE | 외화 환산 적용 환율 |
| 20 | 보정여부 | ADJ_YN | CHAR(1) | N | N | N | YN | 수작업 또는 장애 복구 보정 여부 |
| 21 | 원천시스템ID | SRC_SYS_ID | VARCHAR2(30) | N | N | Y | SYS_ID | 데이터를 발생시킨 원천 시스템 |
| 22 | 원천거래ID | SRC_TR_ID | VARCHAR2(100) | N | N | Y | TR_ID | 원천 거래/전문/요청 식별자 |
| 23 | 처리상태코드 | PROC_STS_CD | CHAR(2) | N | N | N | CODE | 정상/오류/보류/재처리 등 처리 상태 |
| 24 | 처리일시 | PROC_DTTM | TIMESTAMP(6) | N | N | Y | DTTM | 원장 반영 또는 최종 처리 일시 |
| 25 | 처리배치ID | PROC_JOB_ID | VARCHAR2(50) | N | N | Y | JOB_ID | 배치 반영 시 실행 Job ID |
| 26 | 오류코드 | ERR_CD | VARCHAR2(30) | N | N | Y | CODE | 처리 오류 발생 시 표준 오류코드 |
| 27 | 오류메시지 | ERR_MSG | VARCHAR2(1000) | N | N | Y | TEXT | 처리 오류 상세 메시지 |
| 28 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 적재 일시 |
| 29 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 적재 사용자 또는 시스템 ID |
| 30 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 31 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |

### 05.13 결제예정 `TB_STL_SCHD`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 결제일자 | STL_DT | CHAR(8) | Y | N | N | DATE8 | 실제 결제 예정일 |
| 2 | 계좌번호 | ACNO | VARCHAR2(20) | Y | Y | N | ACNO | 결제 계좌 |
| 3 | 종목코드 | ISU_CD | VARCHAR2(12) | Y | Y | N | ISU_CD | 결제 종목 |
| 4 | 결제순번 | STL_SEQ | NUMBER(5) | Y | N | N | SEQ | 동일 키 내 결제 순번 |
| 5 | 체결일자 | EXEC_DT | CHAR(8) | N | Y | N | DATE8 | 원 체결일 |
| 6 | 체결번호 | EXEC_NO | VARCHAR2(20) | N | Y | N | EXEC_NO | 원 체결번호 |
| 7 | 매매구분코드 | BUY_SELL_DVSN_CD | CHAR(1) | N | N | N | CODE | 매수/매도 |
| 8 | 결제수량 | STL_QTY | NUMBER(18,6) | N | N | N | QTY | 결제 대상 수량 |
| 9 | 결제금액 | STL_AMT | NUMBER(20,2) | N | N | N | AMT | 결제 대상 금액 |
| 10 | 수수료금액 | FEE_AMT | NUMBER(20,2) | N | N | N | AMT | 결제 시 반영 수수료 |
| 11 | 세금금액 | TAX_AMT | NUMBER(20,2) | N | N | N | AMT | 결제 시 반영 세금 |
| 12 | 순결제금액 | NET_STL_AMT | NUMBER(20,2) | N | N | N | AMT | 수수료/세금 반영 순결제금액 |
| 13 | 결제상태코드 | STL_STS_CD | CHAR(2) | N | N | N | CODE | 예정/처리중/완료/오류/보류 |
| 14 | 결제보류여부 | STL_HOLD_YN | CHAR(1) | N | N | N | YN | 사고/권리/대외기관 사유 보류 여부 |
| 15 | 결제보류사유코드 | STL_HOLD_RSN_CD | VARCHAR2(20) | N | N | Y | CODE | 결제 보류 사유 |
| 16 | 잔고반영여부 | BAL_APLY_YN | CHAR(1) | N | N | N | YN | 잔고 반영 여부 |
| 17 | 예수금반영여부 | CASH_APLY_YN | CHAR(1) | N | N | N | YN | 예수금 반영 여부 |
| 18 | 대사결과코드 | RECON_RSLT_CD | CHAR(2) | N | N | Y | CODE | 대외기관/내부 대사 결과 |
| 19 | 원천시스템ID | SRC_SYS_ID | VARCHAR2(30) | N | N | Y | SYS_ID | 데이터를 발생시킨 원천 시스템 |
| 20 | 원천거래ID | SRC_TR_ID | VARCHAR2(100) | N | N | Y | TR_ID | 원천 거래/전문/요청 식별자 |
| 21 | 처리상태코드 | PROC_STS_CD | CHAR(2) | N | N | N | CODE | 정상/오류/보류/재처리 등 처리 상태 |
| 22 | 처리일시 | PROC_DTTM | TIMESTAMP(6) | N | N | Y | DTTM | 원장 반영 또는 최종 처리 일시 |
| 23 | 처리배치ID | PROC_JOB_ID | VARCHAR2(50) | N | N | Y | JOB_ID | 배치 반영 시 실행 Job ID |
| 24 | 오류코드 | ERR_CD | VARCHAR2(30) | N | N | Y | CODE | 처리 오류 발생 시 표준 오류코드 |
| 25 | 오류메시지 | ERR_MSG | VARCHAR2(1000) | N | N | Y | TEXT | 처리 오류 상세 메시지 |
| 26 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 적재 일시 |
| 27 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 적재 사용자 또는 시스템 ID |
| 28 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 29 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |

### 05.14 현금입출금내역 `TB_CASH_IO_DTL`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 거래일자 | TR_DT | CHAR(8) | Y | N | N | DATE8 | 입출금/대체 거래일 |
| 2 | 입출금번호 | IO_NO | VARCHAR2(30) | Y | N | N | IO_NO | 현금 입출금 식별번호 |
| 3 | 계좌번호 | ACNO | VARCHAR2(20) | N | Y | N | ACNO | 입출금 계좌 |
| 4 | 통화코드 | CURR_CD | CHAR(3) | N | N | N | CURR_CD | 입출금 통화 |
| 5 | 입출금구분코드 | IO_DVSN_CD | CHAR(2) | N | N | N | CODE | 입금/출금/대체/환전/수수료 |
| 6 | 거래금액 | TR_AMT | NUMBER(20,2) | N | N | N | AMT | 입출금 거래 금액 |
| 7 | 수수료금액 | FEE_AMT | NUMBER(20,2) | N | N | N | AMT | 입출금 수수료 |
| 8 | 세금금액 | TAX_AMT | NUMBER(20,2) | N | N | N | AMT | 세금 또는 원천징수 |
| 9 | 상대계좌번호 | CNTP_ACNO | VARCHAR2(50) | N | N | Y | ACNO | 대체/이체 상대 계좌 |
| 10 | 상대은행코드 | CNTP_BANK_CD | VARCHAR2(10) | N | N | Y | CODE | 외부 은행 코드 |
| 11 | 거래상태코드 | TR_STS_CD | CHAR(2) | N | N | N | CODE | 접수/완료/취소/거부 |
| 12 | 취소원거래번호 | CNCL_ORG_IO_NO | VARCHAR2(30) | N | Y | Y | IO_NO | 취소 거래의 원 거래번호 |
| 13 | 채널코드 | CHNL_CD | VARCHAR2(10) | N | Y | N | CHNL_CD | 거래 발생 채널 |
| 14 | 거래일시 | TR_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 거래 발생 시각 |
| 15 | 예수금반영여부 | CASH_APLY_YN | CHAR(1) | N | N | N | YN | 예수금 원장 반영 여부 |
| 16 | 원천시스템ID | SRC_SYS_ID | VARCHAR2(30) | N | N | Y | SYS_ID | 데이터를 발생시킨 원천 시스템 |
| 17 | 원천거래ID | SRC_TR_ID | VARCHAR2(100) | N | N | Y | TR_ID | 원천 거래/전문/요청 식별자 |
| 18 | 처리상태코드 | PROC_STS_CD | CHAR(2) | N | N | N | CODE | 정상/오류/보류/재처리 등 처리 상태 |
| 19 | 처리일시 | PROC_DTTM | TIMESTAMP(6) | N | N | Y | DTTM | 원장 반영 또는 최종 처리 일시 |
| 20 | 처리배치ID | PROC_JOB_ID | VARCHAR2(50) | N | N | Y | JOB_ID | 배치 반영 시 실행 Job ID |
| 21 | 오류코드 | ERR_CD | VARCHAR2(30) | N | N | Y | CODE | 처리 오류 발생 시 표준 오류코드 |
| 22 | 오류메시지 | ERR_MSG | VARCHAR2(1000) | N | N | Y | TEXT | 처리 오류 상세 메시지 |
| 23 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 적재 일시 |
| 24 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 적재 사용자 또는 시스템 ID |
| 25 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 26 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |

### 05.15 신용약정 `TB_CRD_AGR`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 계좌번호 | ACNO | VARCHAR2(20) | Y | Y | N | ACNO | 신용 약정 계좌 |
| 2 | 약정번호 | AGR_NO | VARCHAR2(30) | N | N | N | AGR_NO | 신용 약정 식별 번호 |
| 3 | 약정일자 | AGR_DT | CHAR(8) | N | N | N | DATE8 | 약정 체결일 |
| 4 | 약정만기일자 | AGR_EXPI_DT | CHAR(8) | N | N | Y | DATE8 | 약정 만기일 |
| 5 | 약정상태코드 | AGR_STS_CD | CHAR(2) | N | N | N | CODE | 정상/해지/정지/만료 |
| 6 | 신용한도금액 | CRD_LMT_AMT | NUMBER(20,2) | N | N | N | AMT | 계좌별 신용거래 한도 |
| 7 | 사용한도금액 | USE_LMT_AMT | NUMBER(20,2) | N | N | N | AMT | 현재 사용 중인 한도 |
| 8 | 잔여한도금액 | RMN_LMT_AMT | NUMBER(20,2) | N | N | N | AMT | 신규 가능 한도 |
| 9 | 기본담보비율 | BASE_COLL_RT | NUMBER(12,8) | N | N | N | RATE | 신용거래 기본 담보비율 |
| 10 | 유지담보비율 | MAIN_COLL_RT | NUMBER(12,8) | N | N | N | RATE | 담보부족 판단 기준 비율 |
| 11 | 반대매매유예일수 | FORCE_SELL_GRACE_DAYS | NUMBER(3) | N | N | Y | SEQ | 담보부족 후 유예 일수 |
| 12 | 이자율그룹코드 | INT_RT_GRP_CD | VARCHAR2(20) | N | N | Y | CODE | 신용이자율 산정 그룹 |
| 13 | 승인상태코드 | APPR_STS_CD | CHAR(2) | N | N | N | CODE | 승인대기/승인/반려 |
| 14 | 승인사용자ID | APPR_USER_ID | VARCHAR2(50) | N | N | Y | USER_ID | 약정 승인자 |
| 15 | 승인일시 | APPR_DTTM | TIMESTAMP(6) | N | N | Y | DTTM | 약정 승인 일시 |
| 16 | 사용여부 | USE_YN | CHAR(1) | N | N | N | YN | 사용 가능 여부. 신규 거래/조회 노출 기준 |
| 17 | 삭제여부 | DEL_YN | CHAR(1) | N | N | N | YN | 논리삭제 여부. 물리삭제 대신 이력 추적 유지 |
| 18 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 입력 일시 |
| 19 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 입력 사용자 또는 시스템 ID |
| 20 | 최초등록프로그램ID | REG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최초 입력 프로그램/서비스 ID |
| 21 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 22 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |
| 23 | 최종변경프로그램ID | CHG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최종 변경 프로그램/서비스 ID |
| 24 | 데이터버전번호 | DATA_VER_NO | NUMBER(10) | N | N | N | SEQ | 낙관적 잠금 및 변경 충돌 방지용 버전 |

### 05.16 신용융자내역 `TB_CRD_LOAN`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 대출번호 | LOAN_NO | VARCHAR2(30) | Y | N | N | LOAN_NO | 신용융자 식별 번호 |
| 2 | 계좌번호 | ACNO | VARCHAR2(20) | N | Y | N | ACNO | 대출 계좌 |
| 3 | 종목코드 | ISU_CD | VARCHAR2(12) | N | Y | N | ISU_CD | 융자 매수 종목 |
| 4 | 주문일자 | ORD_DT | CHAR(8) | N | Y | Y | DATE8 | 융자 발생 주문일자 |
| 5 | 주문번호 | ORD_NO | VARCHAR2(20) | N | Y | Y | ORD_NO | 융자 발생 주문번호 |
| 6 | 체결일자 | EXEC_DT | CHAR(8) | N | Y | Y | DATE8 | 융자 발생 체결일자 |
| 7 | 체결번호 | EXEC_NO | VARCHAR2(20) | N | Y | Y | EXEC_NO | 융자 발생 체결번호 |
| 8 | 신용구분코드 | CRD_DVSN_CD | CHAR(2) | N | N | N | CODE | 자기융자/유통융자/담보대출 |
| 9 | 대출일자 | LOAN_DT | CHAR(8) | N | N | N | DATE8 | 융자 발생일 |
| 10 | 만기일자 | MTRT_DT | CHAR(8) | N | N | N | DATE8 | 융자 만기일 |
| 11 | 대출수량 | LOAN_QTY | NUMBER(18,6) | N | N | N | QTY | 융자 대상 수량 |
| 12 | 잔여수량 | RMN_QTY | NUMBER(18,6) | N | N | N | QTY | 상환 후 잔여 수량 |
| 13 | 대출금액 | LOAN_AMT | NUMBER(20,2) | N | N | N | AMT | 융자 원금 |
| 14 | 잔여대출금액 | RMN_LOAN_AMT | NUMBER(20,2) | N | N | N | AMT | 상환 후 잔여 원금 |
| 15 | 상환수량 | RPY_QTY | NUMBER(18,6) | N | N | N | QTY | 상환 완료 수량 |
| 16 | 상환금액 | RPY_AMT | NUMBER(20,2) | N | N | N | AMT | 상환 원금 |
| 17 | 이자율 | INT_RT | NUMBER(12,8) | N | N | N | RATE | 연 이자율 |
| 18 | 발생이자금액 | ACCR_INT_AMT | NUMBER(20,2) | N | N | N | AMT | 누적 발생 이자 |
| 19 | 미수이자금액 | RCVB_INT_AMT | NUMBER(20,2) | N | N | N | AMT | 미납 이자 |
| 20 | 대출상태코드 | LOAN_STS_CD | CHAR(2) | N | N | N | CODE | 정상/상환/연체/강제상환 |
| 21 | 반대매매대상여부 | FORCE_SELL_TGT_YN | CHAR(1) | N | N | N | YN | 담보부족 등 강제청산 대상 여부 |
| 22 | 원천시스템ID | SRC_SYS_ID | VARCHAR2(30) | N | N | Y | SYS_ID | 데이터를 발생시킨 원천 시스템 |
| 23 | 원천거래ID | SRC_TR_ID | VARCHAR2(100) | N | N | Y | TR_ID | 원천 거래/전문/요청 식별자 |
| 24 | 처리상태코드 | PROC_STS_CD | CHAR(2) | N | N | N | CODE | 정상/오류/보류/재처리 등 처리 상태 |
| 25 | 처리일시 | PROC_DTTM | TIMESTAMP(6) | N | N | Y | DTTM | 원장 반영 또는 최종 처리 일시 |
| 26 | 처리배치ID | PROC_JOB_ID | VARCHAR2(50) | N | N | Y | JOB_ID | 배치 반영 시 실행 Job ID |
| 27 | 오류코드 | ERR_CD | VARCHAR2(30) | N | N | Y | CODE | 처리 오류 발생 시 표준 오류코드 |
| 28 | 오류메시지 | ERR_MSG | VARCHAR2(1000) | N | N | Y | TEXT | 처리 오류 상세 메시지 |
| 29 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 적재 일시 |
| 30 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 적재 사용자 또는 시스템 ID |
| 31 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 32 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |

### 05.17 담보평가내역 `TB_COLL_EVAL`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 기준일자 | BAS_DT | CHAR(8) | Y | N | N | DATE8 | 담보 평가 기준일 |
| 2 | 계좌번호 | ACNO | VARCHAR2(20) | Y | Y | N | ACNO | 담보 평가 계좌 |
| 3 | 평가순번 | EVAL_SEQ | NUMBER(5) | Y | N | N | SEQ | 일중 재평가 순번 |
| 4 | 예수금평가금액 | CASH_EVAL_AMT | NUMBER(20,2) | N | N | N | AMT | 현금성 담보 평가금액 |
| 5 | 증권평가금액 | SECU_EVAL_AMT | NUMBER(20,2) | N | N | N | AMT | 주식/채권 등 담보증권 평가금액 |
| 6 | 대용평가금액 | SUB_EVAL_AMT | NUMBER(20,2) | N | N | N | AMT | 대용증권 평가금액 |
| 7 | 총담보평가금액 | TOT_COLL_EVAL_AMT | NUMBER(20,2) | N | N | N | AMT | 총 담보 평가금액 |
| 8 | 신용융자금액 | CRD_LOAN_AMT | NUMBER(20,2) | N | N | N | AMT | 신용융자 원금 합계 |
| 9 | 미수금액 | RCVB_AMT | NUMBER(20,2) | N | N | N | AMT | 미수금 합계 |
| 10 | 담보비율 | COLL_RT | NUMBER(12,8) | N | N | N | RATE | 총담보평가금액 / 필요담보금액 |
| 11 | 유지담보비율 | MAIN_COLL_RT | NUMBER(12,8) | N | N | N | RATE | 담보부족 판단 기준 |
| 12 | 담보부족금액 | COLL_SHORT_AMT | NUMBER(20,2) | N | N | N | AMT | 추가 납부 필요 금액 |
| 13 | 반대매매대상여부 | FORCE_SELL_TGT_YN | CHAR(1) | N | N | N | YN | 반대매매 대상 여부 |
| 14 | 평가일시 | EVAL_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 담보 평가 시각 |
| 15 | 원천시스템ID | SRC_SYS_ID | VARCHAR2(30) | N | N | Y | SYS_ID | 데이터를 발생시킨 원천 시스템 |
| 16 | 원천거래ID | SRC_TR_ID | VARCHAR2(100) | N | N | Y | TR_ID | 원천 거래/전문/요청 식별자 |
| 17 | 처리상태코드 | PROC_STS_CD | CHAR(2) | N | N | N | CODE | 정상/오류/보류/재처리 등 처리 상태 |
| 18 | 처리일시 | PROC_DTTM | TIMESTAMP(6) | N | N | Y | DTTM | 원장 반영 또는 최종 처리 일시 |
| 19 | 처리배치ID | PROC_JOB_ID | VARCHAR2(50) | N | N | Y | JOB_ID | 배치 반영 시 실행 Job ID |
| 20 | 오류코드 | ERR_CD | VARCHAR2(30) | N | N | Y | CODE | 처리 오류 발생 시 표준 오류코드 |
| 21 | 오류메시지 | ERR_MSG | VARCHAR2(1000) | N | N | Y | TEXT | 처리 오류 상세 메시지 |
| 22 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 적재 일시 |
| 23 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 적재 사용자 또는 시스템 ID |
| 24 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 25 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |

### 05.18 파생종목기본 `TB_DERIV_ISU_MST`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 종목코드 | ISU_CD | VARCHAR2(12) | Y | Y | N | ISU_CD | 파생상품 표준코드 |
| 2 | 파생상품구분코드 | DERIV_PRD_DVSN_CD | CHAR(2) | N | N | N | CODE | 지수선물/지수옵션/주식선물 등 |
| 3 | 기초자산코드 | UNDL_ISU_CD | VARCHAR2(12) | N | Y | Y | ISU_CD | 기초자산 종목/지수 코드 |
| 4 | 결제월 | STL_MTH | CHAR(6) | N | N | N | YYYYMM | 파생상품 결제월 |
| 5 | 최근월물여부 | NEAR_MTH_YN | CHAR(1) | N | N | N | YN | 가장 가까운 활성 월물 여부 |
| 6 | 만기일자 | EXPI_DT | CHAR(8) | N | N | N | DATE8 | 최종거래일 및 만기일자 |
| 7 | 최종거래일자 | LAST_TRD_DT | CHAR(8) | N | N | N | DATE8 | 최종 거래 가능일 |
| 8 | 행사가격 | EXER_PRC | NUMBER(18,6) | N | N | Y | PRICE | 옵션 행사가격 |
| 9 | 콜풋구분코드 | CALL_PUT_DVSN_CD | CHAR(1) | N | N | Y | CODE | 콜/풋 구분 |
| 10 | 거래승수 | TRD_MULT | NUMBER(18,6) | N | N | N | AMT | 계약당 가치 산정 거래승수 |
| 11 | 호가단위 | TICK_SIZE | NUMBER(18,6) | N | N | N | PRICE | 최소 가격 변동 단위 |
| 12 | 기준가격 | BASE_PRC | NUMBER(18,6) | N | N | Y | PRICE | 당일 기준가격 |
| 13 | 정산가격 | STTL_PRC | NUMBER(18,6) | N | N | Y | PRICE | 최근 정산가격 |
| 14 | 상장일자 | LIST_DT | CHAR(8) | N | N | Y | DATE8 | 상장일 |
| 15 | 거래정지여부 | TRD_SPND_YN | CHAR(1) | N | N | N | YN | 거래정지 여부 |
| 16 | 사용여부 | USE_YN | CHAR(1) | N | N | N | YN | 사용 가능 여부. 신규 거래/조회 노출 기준 |
| 17 | 삭제여부 | DEL_YN | CHAR(1) | N | N | N | YN | 논리삭제 여부. 물리삭제 대신 이력 추적 유지 |
| 18 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 입력 일시 |
| 19 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 입력 사용자 또는 시스템 ID |
| 20 | 최초등록프로그램ID | REG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최초 입력 프로그램/서비스 ID |
| 21 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 22 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |
| 23 | 최종변경프로그램ID | CHG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최종 변경 프로그램/서비스 ID |
| 24 | 데이터버전번호 | DATA_VER_NO | NUMBER(10) | N | N | N | SEQ | 낙관적 잠금 및 변경 충돌 방지용 버전 |

### 05.19 파생증거금 `TB_DERIV_MARGIN`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 기준일자 | BAS_DT | CHAR(8) | Y | N | N | DATE8 | 증거금 산출 기준일 |
| 2 | 계좌번호 | ACNO | VARCHAR2(20) | Y | Y | N | ACNO | 파생상품 계좌 |
| 3 | 통화코드 | CURR_CD | CHAR(3) | Y | N | N | CURR_CD | 증거금 산정 통화 |
| 4 | 예탁총액 | DPST_TOT_AMT | NUMBER(20,2) | N | N | N | AMT | 현금 및 대용 평가금액 합산 |
| 5 | 현금예탁금액 | CASH_DPST_AMT | NUMBER(20,2) | N | N | N | AMT | 현금 예탁금 |
| 6 | 대용예탁금액 | SUB_DPST_AMT | NUMBER(20,2) | N | N | N | AMT | 대용증권 예탁 평가금액 |
| 7 | 위탁증거금액 | CUST_MARGIN_AMT | NUMBER(20,2) | N | N | N | AMT | 신규 주문 및 잔고 유지 증거금 |
| 8 | 유지증거금액 | MAIN_MARGIN_AMT | NUMBER(20,2) | N | N | N | AMT | 마진콜 판단 기준 금액 |
| 9 | 추가증거금액 | ADD_MARGIN_AMT | NUMBER(20,2) | N | N | N | AMT | 추가 납부 필요 금액 |
| 10 | 주문가능금액 | ORD_ABLE_AMT | NUMBER(20,2) | N | N | N | AMT | 파생 신규 주문 가능 금액 |
| 11 | 평가손익금액 | EVAL_PL_AMT | NUMBER(20,2) | N | N | N | AMT | 미결제약정 평가손익 |
| 12 | 정산차금 | STTL_DIFF_AMT | NUMBER(20,2) | N | N | N | AMT | 일일 정산으로 가감되는 금액 |
| 13 | 마진콜여부 | MARGIN_CALL_YN | CHAR(1) | N | N | N | YN | 추가증거금 발생 여부 |
| 14 | 강제청산대상여부 | FORCE_LQDT_TGT_YN | CHAR(1) | N | N | N | YN | 강제청산 대상 여부 |
| 15 | 산출일시 | CALC_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 증거금 산출 시각 |
| 16 | 원천시스템ID | SRC_SYS_ID | VARCHAR2(30) | N | N | Y | SYS_ID | 데이터를 발생시킨 원천 시스템 |
| 17 | 원천거래ID | SRC_TR_ID | VARCHAR2(100) | N | N | Y | TR_ID | 원천 거래/전문/요청 식별자 |
| 18 | 처리상태코드 | PROC_STS_CD | CHAR(2) | N | N | N | CODE | 정상/오류/보류/재처리 등 처리 상태 |
| 19 | 처리일시 | PROC_DTTM | TIMESTAMP(6) | N | N | Y | DTTM | 원장 반영 또는 최종 처리 일시 |
| 20 | 처리배치ID | PROC_JOB_ID | VARCHAR2(50) | N | N | Y | JOB_ID | 배치 반영 시 실행 Job ID |
| 21 | 오류코드 | ERR_CD | VARCHAR2(30) | N | N | Y | CODE | 처리 오류 발생 시 표준 오류코드 |
| 22 | 오류메시지 | ERR_MSG | VARCHAR2(1000) | N | N | Y | TEXT | 처리 오류 상세 메시지 |
| 23 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 적재 일시 |
| 24 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 적재 사용자 또는 시스템 ID |
| 25 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 26 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |

### 05.20 파생정산내역 `TB_DERIV_SETTL_DTL`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 정산일자 | STTL_DT | CHAR(8) | Y | N | N | DATE8 | 파생상품 일일 정산일 |
| 2 | 계좌번호 | ACNO | VARCHAR2(20) | Y | Y | N | ACNO | 정산 계좌 |
| 3 | 종목코드 | ISU_CD | VARCHAR2(12) | Y | Y | N | ISU_CD | 정산 대상 파생 종목 |
| 4 | 매매구분코드 | BUY_SELL_DVSN_CD | CHAR(1) | Y | N | N | CODE | 매수/매도 포지션 |
| 5 | 미결제약정수량 | OPEN_INT_QTY | NUMBER(18,6) | N | N | N | QTY | 정산 기준 미결제약정 수량 |
| 6 | 전일정산가격 | PRV_STTL_PRC | NUMBER(18,6) | N | N | Y | PRICE | 전일 정산가격 |
| 7 | 당일정산가격 | STTL_PRC | NUMBER(18,6) | N | N | N | PRICE | 당일 최종 정산가격 |
| 8 | 거래승수 | TRD_MULT | NUMBER(18,6) | N | N | N | AMT | 계약 승수 |
| 9 | 평가손익금액 | EVAL_PL_AMT | NUMBER(20,2) | N | N | N | AMT | 평가손익 |
| 10 | 정산차금 | STTL_DIFF_AMT | NUMBER(20,2) | N | N | N | AMT | 예수금에 가감되는 정산차액 |
| 11 | 수수료금액 | FEE_AMT | NUMBER(20,2) | N | N | N | AMT | 정산 관련 수수료 |
| 12 | 세금금액 | TAX_AMT | NUMBER(20,2) | N | N | N | AMT | 세금 |
| 13 | 예수금반영여부 | CASH_APLY_YN | CHAR(1) | N | N | N | YN | 예수금 반영 여부 |
| 14 | 정산상태코드 | STTL_STS_CD | CHAR(2) | N | N | N | CODE | 예정/완료/오류/보류 |
| 15 | 원천시스템ID | SRC_SYS_ID | VARCHAR2(30) | N | N | Y | SYS_ID | 데이터를 발생시킨 원천 시스템 |
| 16 | 원천거래ID | SRC_TR_ID | VARCHAR2(100) | N | N | Y | TR_ID | 원천 거래/전문/요청 식별자 |
| 17 | 처리상태코드 | PROC_STS_CD | CHAR(2) | N | N | N | CODE | 정상/오류/보류/재처리 등 처리 상태 |
| 18 | 처리일시 | PROC_DTTM | TIMESTAMP(6) | N | N | Y | DTTM | 원장 반영 또는 최종 처리 일시 |
| 19 | 처리배치ID | PROC_JOB_ID | VARCHAR2(50) | N | N | Y | JOB_ID | 배치 반영 시 실행 Job ID |
| 20 | 오류코드 | ERR_CD | VARCHAR2(30) | N | N | Y | CODE | 처리 오류 발생 시 표준 오류코드 |
| 21 | 오류메시지 | ERR_MSG | VARCHAR2(1000) | N | N | Y | TEXT | 처리 오류 상세 메시지 |
| 22 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 적재 일시 |
| 23 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 적재 사용자 또는 시스템 ID |
| 24 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 25 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |

### 05.21 채권발행기본 `TB_BOND_ISS_MST`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 종목코드 | ISU_CD | VARCHAR2(12) | Y | Y | N | ISU_CD | 채권 표준코드 |
| 2 | 채권종류코드 | BOND_TP_CD | CHAR(2) | N | N | N | CODE | 국채/지방채/금융채/회사채 |
| 3 | 발행기관코드 | ISS_INST_CD | VARCHAR2(20) | N | N | Y | INST_CD | 발행기관 식별 코드 |
| 4 | 발행일자 | ISS_DT | CHAR(8) | N | N | N | DATE8 | 채권 발행일 |
| 5 | 만기일자 | EXPI_DT | CHAR(8) | N | N | N | DATE8 | 원금 상환 만기일 |
| 6 | 표면금리 | CUPN_RT | NUMBER(12,8) | N | N | N | RATE | 연 표면 이자율 |
| 7 | 이자지급유형코드 | INT_PAY_TP_CD | CHAR(1) | N | N | N | CODE | 이표채/할인채/복리채 |
| 8 | 이자지급주기월수 | INT_PAY_MTH_CNT | NUMBER(3) | N | N | Y | SEQ | 3개월/6개월 등 |
| 9 | 액면금액 | FACE_AMT | NUMBER(20,2) | N | N | N | AMT | 권면 기준 금액 |
| 10 | 발행금액 | ISS_AMT | NUMBER(24,2) | N | N | Y | AMT | 총 발행 금액 |
| 11 | 상장여부 | LIST_YN | CHAR(1) | N | N | N | YN | 장내 상장 여부 |
| 12 | 신용등급코드 | CRDT_GRD_CD | VARCHAR2(10) | N | N | Y | CODE | AAA/AA/A/BBB 등 |
| 13 | 상환방법코드 | RDM_MTHD_CD | CHAR(2) | N | N | Y | CODE | 만기일시/분할상환 등 |
| 14 | 과세구분코드 | TAX_DVSN_CD | CHAR(2) | N | N | N | CODE | 과세/비과세/분리과세 등 |
| 15 | 일수계산방식코드 | DAY_CNT_BASIS_CD | VARCHAR2(10) | N | N | Y | CODE | ACT/365, ACT/ACT 등 |
| 16 | 선후순위구분코드 | SENIORITY_CD | CHAR(2) | N | N | Y | CODE | 선순위/후순위/신종자본 등 |
| 17 | 사용여부 | USE_YN | CHAR(1) | N | N | N | YN | 사용 가능 여부. 신규 거래/조회 노출 기준 |
| 18 | 삭제여부 | DEL_YN | CHAR(1) | N | N | N | YN | 논리삭제 여부. 물리삭제 대신 이력 추적 유지 |
| 19 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 입력 일시 |
| 20 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 입력 사용자 또는 시스템 ID |
| 21 | 최초등록프로그램ID | REG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최초 입력 프로그램/서비스 ID |
| 22 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 23 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |
| 24 | 최종변경프로그램ID | CHG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최종 변경 프로그램/서비스 ID |
| 25 | 데이터버전번호 | DATA_VER_NO | NUMBER(10) | N | N | N | SEQ | 낙관적 잠금 및 변경 충돌 방지용 버전 |

### 05.22 채권이자스케줄 `TB_BOND_INT_SCHD`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 종목코드 | ISU_CD | VARCHAR2(12) | Y | Y | N | ISU_CD | 채권 코드 |
| 2 | 이자지급순번 | INT_PAY_SEQ | NUMBER(5) | Y | N | N | SEQ | 회차별 이자지급 순번 |
| 3 | 이자계산시작일자 | INT_STRT_DT | CHAR(8) | N | N | N | DATE8 | 해당 회차 이자 계산 시작일 |
| 4 | 이자계산종료일자 | INT_END_DT | CHAR(8) | N | N | N | DATE8 | 해당 회차 이자 계산 종료일 |
| 5 | 이자지급일자 | INT_PAY_DT | CHAR(8) | N | N | N | DATE8 | 고객 계좌 지급 예정일 |
| 6 | 이자일수 | INT_DAYS | NUMBER(5) | N | N | N | SEQ | 해당 회차 이자 일수 |
| 7 | 표면금리 | CUPN_RT | NUMBER(12,8) | N | N | N | RATE | 회차 적용 표면금리 |
| 8 | 만원당이자가격 | INT_PRC_PER_10K | NUMBER(18,6) | N | N | N | PRICE | 액면 10,000원당 지급 이자 |
| 9 | 세율 | TAX_RT | NUMBER(12,8) | N | N | Y | RATE | 원천징수 세율 |
| 10 | 지급상태코드 | PAY_STS_CD | CHAR(2) | N | N | N | CODE | 예정/확정/지급/취소 |
| 11 | 권리기준일자 | RIGHT_BASE_DT | CHAR(8) | N | N | Y | DATE8 | 이자 권리자 확정 기준일 |
| 12 | 사용여부 | USE_YN | CHAR(1) | N | N | N | YN | 사용 가능 여부. 신규 거래/조회 노출 기준 |
| 13 | 삭제여부 | DEL_YN | CHAR(1) | N | N | N | YN | 논리삭제 여부. 물리삭제 대신 이력 추적 유지 |
| 14 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 입력 일시 |
| 15 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 입력 사용자 또는 시스템 ID |
| 16 | 최초등록프로그램ID | REG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최초 입력 프로그램/서비스 ID |
| 17 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 18 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |
| 19 | 최종변경프로그램ID | CHG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최종 변경 프로그램/서비스 ID |
| 20 | 데이터버전번호 | DATA_VER_NO | NUMBER(10) | N | N | N | SEQ | 낙관적 잠금 및 변경 충돌 방지용 버전 |

### 05.23 권리이벤트 `TB_RIGHT_EVT`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 권리이벤트번호 | RIGHT_EVT_NO | VARCHAR2(30) | Y | N | N | RIGHT_EVT_NO | 권리 이벤트 식별번호 |
| 2 | 종목코드 | ISU_CD | VARCHAR2(12) | N | Y | N | ISU_CD | 권리 대상 종목 |
| 3 | 권리유형코드 | RIGHT_TP_CD | CHAR(2) | N | N | N | CODE | 현금배당/주식배당/유상/무상/분할/합병 |
| 4 | 기준일자 | BAS_DT | CHAR(8) | N | N | N | DATE8 | 권리 기준일 |
| 5 | 락일자 | EX_RIGHT_DT | CHAR(8) | N | N | Y | DATE8 | 권리락/배당락 일자 |
| 6 | 지급예정일자 | PAY_SCHD_DT | CHAR(8) | N | N | Y | DATE8 | 현금/주식 지급 예정일 |
| 7 | 지급확정일자 | PAY_CFM_DT | CHAR(8) | N | N | Y | DATE8 | 지급 확정일 |
| 8 | 배정비율 | ALOC_RT | NUMBER(18,10) | N | N | Y | RATE | 신주/배당주 배정 비율 |
| 9 | 배당금액 | DVD_AMT | NUMBER(20,2) | N | N | Y | AMT | 주당 현금 배당금 |
| 10 | 신주종목코드 | NEW_ISU_CD | VARCHAR2(12) | N | Y | Y | ISU_CD | 신주/합병 후 종목코드 |
| 11 | 권리상태코드 | RIGHT_STS_CD | CHAR(2) | N | N | N | CODE | 접수/확정/배정/지급/취소 |
| 12 | 대외공지번호 | EXT_NOTICE_NO | VARCHAR2(50) | N | N | Y | TEXT | 거래소/예탁원 공지 식별자 |
| 13 | 사용여부 | USE_YN | CHAR(1) | N | N | N | YN | 사용 가능 여부. 신규 거래/조회 노출 기준 |
| 14 | 삭제여부 | DEL_YN | CHAR(1) | N | N | N | YN | 논리삭제 여부. 물리삭제 대신 이력 추적 유지 |
| 15 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 입력 일시 |
| 16 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 입력 사용자 또는 시스템 ID |
| 17 | 최초등록프로그램ID | REG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최초 입력 프로그램/서비스 ID |
| 18 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 19 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |
| 20 | 최종변경프로그램ID | CHG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최종 변경 프로그램/서비스 ID |
| 21 | 데이터버전번호 | DATA_VER_NO | NUMBER(10) | N | N | N | SEQ | 낙관적 잠금 및 변경 충돌 방지용 버전 |

### 05.24 권리배정내역 `TB_RIGHT_ALOC`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 권리이벤트번호 | RIGHT_EVT_NO | VARCHAR2(30) | Y | Y | N | RIGHT_EVT_NO | 권리 이벤트 |
| 2 | 계좌번호 | ACNO | VARCHAR2(20) | Y | Y | N | ACNO | 배정 대상 계좌 |
| 3 | 종목코드 | ISU_CD | VARCHAR2(12) | Y | Y | N | ISU_CD | 기준 종목 |
| 4 | 배정순번 | ALOC_SEQ | NUMBER(5) | Y | N | N | SEQ | 동일 이벤트/계좌 내 순번 |
| 5 | 기준보유수량 | BASE_HOLD_QTY | NUMBER(18,6) | N | N | N | QTY | 권리 기준일 보유수량 |
| 6 | 배정수량 | ALOC_QTY | NUMBER(18,6) | N | N | N | QTY | 배정 주식/청약 가능 수량 |
| 7 | 단수수량 | FRAC_QTY | NUMBER(18,6) | N | N | Y | QTY | 단수주 수량 |
| 8 | 지급금액 | PAY_AMT | NUMBER(20,2) | N | N | Y | AMT | 현금 지급 금액 |
| 9 | 세금금액 | TAX_AMT | NUMBER(20,2) | N | N | Y | AMT | 배당세 등 세금 |
| 10 | 실지급금액 | NET_PAY_AMT | NUMBER(20,2) | N | N | Y | AMT | 세후 지급 금액 |
| 11 | 배정상태코드 | ALOC_STS_CD | CHAR(2) | N | N | N | CODE | 예정/확정/지급/취소 |
| 12 | 잔고반영여부 | BAL_APLY_YN | CHAR(1) | N | N | N | YN | 주식 권리 잔고 반영 여부 |
| 13 | 예수금반영여부 | CASH_APLY_YN | CHAR(1) | N | N | N | YN | 현금 권리 예수금 반영 여부 |
| 14 | 원천시스템ID | SRC_SYS_ID | VARCHAR2(30) | N | N | Y | SYS_ID | 데이터를 발생시킨 원천 시스템 |
| 15 | 원천거래ID | SRC_TR_ID | VARCHAR2(100) | N | N | Y | TR_ID | 원천 거래/전문/요청 식별자 |
| 16 | 처리상태코드 | PROC_STS_CD | CHAR(2) | N | N | N | CODE | 정상/오류/보류/재처리 등 처리 상태 |
| 17 | 처리일시 | PROC_DTTM | TIMESTAMP(6) | N | N | Y | DTTM | 원장 반영 또는 최종 처리 일시 |
| 18 | 처리배치ID | PROC_JOB_ID | VARCHAR2(50) | N | N | Y | JOB_ID | 배치 반영 시 실행 Job ID |
| 19 | 오류코드 | ERR_CD | VARCHAR2(30) | N | N | Y | CODE | 처리 오류 발생 시 표준 오류코드 |
| 20 | 오류메시지 | ERR_MSG | VARCHAR2(1000) | N | N | Y | TEXT | 처리 오류 상세 메시지 |
| 21 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 적재 일시 |
| 22 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 적재 사용자 또는 시스템 ID |
| 23 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 24 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |

### 05.25 수수료세금규칙 `TB_FEE_TAX_RULE`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 규칙ID | RULE_ID | VARCHAR2(30) | Y | N | N | RULE_ID | 수수료/세금 규칙 식별자 |
| 2 | 규칙명 | RULE_NM | VARCHAR2(200) | N | N | N | NAME | 규칙명 |
| 3 | 시장구분코드 | MKT_DVSN_CD | CHAR(2) | N | N | Y | CODE | 적용 시장 |
| 4 | 상품유형코드 | PRD_TP_CD | CHAR(2) | N | N | Y | CODE | 적용 상품 유형 |
| 5 | 채널코드 | CHNL_CD | VARCHAR2(10) | N | Y | Y | CHNL_CD | 적용 채널 |
| 6 | 고객등급코드 | CUST_GRD_CD | CHAR(2) | N | N | Y | CODE | 고객 등급별 우대 |
| 7 | 매매구분코드 | BUY_SELL_DVSN_CD | CHAR(1) | N | N | Y | CODE | 매수/매도별 적용 |
| 8 | 수수료율 | FEE_RT | NUMBER(12,8) | N | N | Y | RATE | 정률 수수료 |
| 9 | 정액수수료 | FIX_FEE_AMT | NUMBER(20,2) | N | N | Y | AMT | 정액 수수료 |
| 10 | 최소수수료 | MIN_FEE_AMT | NUMBER(20,2) | N | N | Y | AMT | 최소 부과 수수료 |
| 11 | 최대수수료 | MAX_FEE_AMT | NUMBER(20,2) | N | N | Y | AMT | 최대 부과 수수료 |
| 12 | 세율 | TAX_RT | NUMBER(12,8) | N | N | Y | RATE | 거래세/원천세 등 |
| 13 | 계산방식코드 | CALC_MTHD_CD | VARCHAR2(20) | N | N | N | CODE | 정률/정액/구간/혼합 |
| 14 | 절사방식코드 | ROUND_MTHD_CD | CHAR(2) | N | N | N | CODE | 반올림/절상/절사 |
| 15 | 유효시작일자 | VALID_STRT_DT | CHAR(8) | N | N | N | DATE8 | 규칙 적용 시작일 |
| 16 | 유효종료일자 | VALID_END_DT | CHAR(8) | N | N | N | DATE8 | 규칙 적용 종료일 |
| 17 | 승인상태코드 | APPR_STS_CD | CHAR(2) | N | N | N | CODE | 승인대기/승인/반려 |
| 18 | 사용여부 | USE_YN | CHAR(1) | N | N | N | YN | 사용 가능 여부. 신규 거래/조회 노출 기준 |
| 19 | 삭제여부 | DEL_YN | CHAR(1) | N | N | N | YN | 논리삭제 여부. 물리삭제 대신 이력 추적 유지 |
| 20 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 입력 일시 |
| 21 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 입력 사용자 또는 시스템 ID |
| 22 | 최초등록프로그램ID | REG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최초 입력 프로그램/서비스 ID |
| 23 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 24 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |
| 25 | 최종변경프로그램ID | CHG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최종 변경 프로그램/서비스 ID |
| 26 | 데이터버전번호 | DATA_VER_NO | NUMBER(10) | N | N | N | SEQ | 낙관적 잠금 및 변경 충돌 방지용 버전 |

### 05.26 공통코드그룹 `TB_CODE_GRP`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 코드그룹코드 | GRP_CD | VARCHAR2(50) | Y | N | N | CODE | 코드 그룹 식별자 |
| 2 | 코드그룹명 | GRP_NM | VARCHAR2(200) | N | N | N | NAME | 코드 그룹명 |
| 3 | 업무영역코드 | BIZ_DOMAIN_CD | VARCHAR2(30) | N | Y | N | CODE | 소관 업무영역 |
| 4 | 코드길이 | CD_LEN | NUMBER(5) | N | N | Y | SEQ | 상세 코드 권장 길이 |
| 5 | 코드유형코드 | CD_TP_CD | CHAR(2) | N | N | N | CODE | 공통/업무/대외/시스템 |
| 6 | 배포대상시스템 | DEPLOY_TGT_SYS | VARCHAR2(500) | N | N | Y | TEXT | 코드 배포 대상 시스템 목록 |
| 7 | 담당자ID | OWN_USER_ID | VARCHAR2(50) | N | N | Y | USER_ID | 코드그룹 담당자 |
| 8 | 승인필요여부 | APPR_REQ_YN | CHAR(1) | N | N | N | YN | 변경 시 승인 필요 여부 |
| 9 | 사용여부 | USE_YN | CHAR(1) | N | N | N | YN | 사용 가능 여부. 신규 거래/조회 노출 기준 |
| 10 | 삭제여부 | DEL_YN | CHAR(1) | N | N | N | YN | 논리삭제 여부. 물리삭제 대신 이력 추적 유지 |
| 11 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 입력 일시 |
| 12 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 입력 사용자 또는 시스템 ID |
| 13 | 최초등록프로그램ID | REG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최초 입력 프로그램/서비스 ID |
| 14 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 15 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |
| 16 | 최종변경프로그램ID | CHG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최종 변경 프로그램/서비스 ID |
| 17 | 데이터버전번호 | DATA_VER_NO | NUMBER(10) | N | N | N | SEQ | 낙관적 잠금 및 변경 충돌 방지용 버전 |

### 05.27 공통코드상세 `TB_CODE_DTL`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 코드그룹코드 | GRP_CD | VARCHAR2(50) | Y | Y | N | CODE | 코드 그룹 |
| 2 | 코드 | CD | VARCHAR2(50) | Y | N | N | CODE | 상세 코드값 |
| 3 | 코드명 | CD_NM | VARCHAR2(200) | N | N | N | NAME | 코드 한글명 |
| 4 | 영문코드명 | ENG_CD_NM | VARCHAR2(200) | N | N | Y | NAME | 코드 영문명 |
| 5 | 코드설명 | CD_DESC | VARCHAR2(1000) | N | N | Y | TEXT | 코드 의미와 사용 기준 |
| 6 | 정렬순서 | SORT_SEQ | NUMBER(5) | N | N | N | SEQ | 화면 표시 순서 |
| 7 | 상위코드 | UP_CD | VARCHAR2(50) | N | N | Y | CODE | 계층형 코드의 상위 코드 |
| 8 | 대외매핑코드 | EXT_MAP_CD | VARCHAR2(100) | N | N | Y | CODE | 거래소/대외기관 코드 매핑 |
| 9 | 유효시작일자 | VALID_STRT_DT | CHAR(8) | N | N | N | DATE8 | 코드 유효 시작일 |
| 10 | 유효종료일자 | VALID_END_DT | CHAR(8) | N | N | N | DATE8 | 코드 유효 종료일 |
| 11 | 기본값여부 | DFLT_YN | CHAR(1) | N | N | N | YN | 기본 선택값 여부 |
| 12 | 사용여부 | USE_YN | CHAR(1) | N | N | N | YN | 사용 가능 여부. 신규 거래/조회 노출 기준 |
| 13 | 삭제여부 | DEL_YN | CHAR(1) | N | N | N | YN | 논리삭제 여부. 물리삭제 대신 이력 추적 유지 |
| 14 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 입력 일시 |
| 15 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 입력 사용자 또는 시스템 ID |
| 16 | 최초등록프로그램ID | REG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최초 입력 프로그램/서비스 ID |
| 17 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 18 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |
| 19 | 최종변경프로그램ID | CHG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최종 변경 프로그램/서비스 ID |
| 20 | 데이터버전번호 | DATA_VER_NO | NUMBER(10) | N | N | N | SEQ | 낙관적 잠금 및 변경 충돌 방지용 버전 |

### 05.28 인터페이스메타 `TB_IF_MSG_META`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 인터페이스ID | IF_ID | VARCHAR2(50) | Y | N | N | IF_ID | 전문/인터페이스 식별자 |
| 2 | 인터페이스명 | IF_NM | VARCHAR2(200) | N | N | N | NAME | 인터페이스명 |
| 3 | 인터페이스유형코드 | IF_TP_CD | CHAR(2) | N | N | N | CODE | 실시간/배치/API/File/MQ |
| 4 | 송신시스템ID | SEND_SYS_ID | VARCHAR2(30) | N | N | N | SYS_ID | 송신 시스템 |
| 5 | 수신시스템ID | RECV_SYS_ID | VARCHAR2(30) | N | N | N | SYS_ID | 수신 시스템 |
| 6 | 전문버전 | MSG_VER | VARCHAR2(20) | N | N | N | VER | 전문 버전 |
| 7 | 전문포맷코드 | MSG_FMT_CD | CHAR(2) | N | N | N | CODE | JSON/XML/Fixed/Delimited |
| 8 | 송수신방식코드 | TRNS_MTHD_CD | CHAR(2) | N | N | N | CODE | TCP/HTTP/MQ/SFTP |
| 9 | 처리주기코드 | PROC_CYCLE_CD | CHAR(2) | N | N | Y | CODE | 실시간/일/월/수시 |
| 10 | 재처리가능여부 | REPROC_ABLE_YN | CHAR(1) | N | N | N | YN | 재처리 가능 여부 |
| 11 | 중복체크키 | DUP_CHK_KEY | VARCHAR2(500) | N | N | Y | TEXT | 중복 수신 방지 키 정의 |
| 12 | 타임아웃초수 | TIMEOUT_SEC | NUMBER(6) | N | N | Y | SEQ | 응답 타임아웃 기준 |
| 13 | 상태코드 | IF_STS_CD | CHAR(2) | N | N | N | CODE | 정상/중지/폐기/테스트 |
| 14 | 담당자ID | OWN_USER_ID | VARCHAR2(50) | N | N | Y | USER_ID | 인터페이스 담당자 |
| 15 | 사용여부 | USE_YN | CHAR(1) | N | N | N | YN | 사용 가능 여부. 신규 거래/조회 노출 기준 |
| 16 | 삭제여부 | DEL_YN | CHAR(1) | N | N | N | YN | 논리삭제 여부. 물리삭제 대신 이력 추적 유지 |
| 17 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 입력 일시 |
| 18 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 입력 사용자 또는 시스템 ID |
| 19 | 최초등록프로그램ID | REG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최초 입력 프로그램/서비스 ID |
| 20 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 21 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |
| 22 | 최종변경프로그램ID | CHG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최종 변경 프로그램/서비스 ID |
| 23 | 데이터버전번호 | DATA_VER_NO | NUMBER(10) | N | N | N | SEQ | 낙관적 잠금 및 변경 충돌 방지용 버전 |

### 05.29 인터페이스필드메타 `TB_IF_FIELD_META`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 인터페이스ID | IF_ID | VARCHAR2(50) | Y | Y | N | IF_ID | 전문 ID |
| 2 | 필드순번 | FIELD_SEQ | NUMBER(5) | Y | N | N | SEQ | 전문 내 필드 순서 |
| 3 | 필드명 | FIELD_NM | VARCHAR2(100) | N | N | N | NAME | 논리 필드명 |
| 4 | 물리필드명 | PHY_FIELD_NM | VARCHAR2(100) | N | N | N | NAME | 전문 물리 필드명 |
| 5 | 데이터타입 | DATA_TP | VARCHAR2(30) | N | N | N | TYPE | String/Number/Date 등 |
| 6 | 필드길이 | FIELD_LEN | NUMBER(5) | N | N | Y | SEQ | Fixed 전문 길이 또는 최대 길이 |
| 7 | 소수자리수 | SCALE_LEN | NUMBER(5) | N | N | Y | SEQ | 숫자 소수 자리수 |
| 8 | 필수여부 | REQ_YN | CHAR(1) | N | N | N | YN | 필수 필드 여부 |
| 9 | 반복여부 | REPEAT_YN | CHAR(1) | N | N | N | YN | 반복 그룹 여부 |
| 10 | 코드그룹코드 | GRP_CD | VARCHAR2(50) | N | Y | Y | CODE | 코드 필드인 경우 코드그룹 |
| 11 | 매핑테이블명 | MAP_TABLE_NM | VARCHAR2(100) | N | Y | Y | TABLE_NM | 기간계 매핑 테이블 |
| 12 | 매핑컬럼명 | MAP_COLUMN_NM | VARCHAR2(100) | N | Y | Y | COLUMN_NM | 기간계 매핑 컬럼 |
| 13 | 검증규칙내용 | VALID_RULE_CONT | VARCHAR2(1000) | N | N | Y | TEXT | 필드 유효성 검증 규칙 |
| 14 | 마스킹여부 | MSK_YN | CHAR(1) | N | N | N | YN | 로그/화면 마스킹 필요 여부 |
| 15 | 사용여부 | USE_YN | CHAR(1) | N | N | N | YN | 사용 가능 여부. 신규 거래/조회 노출 기준 |
| 16 | 삭제여부 | DEL_YN | CHAR(1) | N | N | N | YN | 논리삭제 여부. 물리삭제 대신 이력 추적 유지 |
| 17 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 입력 일시 |
| 18 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 입력 사용자 또는 시스템 ID |
| 19 | 최초등록프로그램ID | REG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최초 입력 프로그램/서비스 ID |
| 20 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 21 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |
| 22 | 최종변경프로그램ID | CHG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최종 변경 프로그램/서비스 ID |
| 23 | 데이터버전번호 | DATA_VER_NO | NUMBER(10) | N | N | N | SEQ | 낙관적 잠금 및 변경 충돌 방지용 버전 |

### 05.30 배치Job메타 `TB_BATCH_JOB_META`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | JobID | JOB_ID | VARCHAR2(50) | Y | N | N | JOB_ID | 배치 Job 식별자 |
| 2 | Job명 | JOB_NM | VARCHAR2(200) | N | N | N | NAME | 배치 Job명 |
| 3 | 업무영역코드 | BIZ_DOMAIN_CD | VARCHAR2(30) | N | Y | N | CODE | 소관 업무영역 |
| 4 | Job유형코드 | JOB_TP_CD | CHAR(2) | N | N | N | CODE | 일마감/월마감/수시/재처리 |
| 5 | 스케줄표현식 | SCHED_EXPR | VARCHAR2(200) | N | N | Y | TEXT | Cron 또는 스케줄러 표현식 |
| 6 | 선행JobID목록 | PRE_JOB_IDS | VARCHAR2(1000) | N | N | Y | TEXT | 선행 배치 목록 |
| 7 | 후행JobID목록 | POST_JOB_IDS | VARCHAR2(1000) | N | N | Y | TEXT | 후행 배치 목록 |
| 8 | 입력테이블목록 | IN_TABLE_LIST | VARCHAR2(1000) | N | N | Y | TEXT | 주요 입력 테이블 |
| 9 | 출력테이블목록 | OUT_TABLE_LIST | VARCHAR2(1000) | N | N | Y | TEXT | 주요 출력 테이블 |
| 10 | 재처리가능여부 | REPROC_ABLE_YN | CHAR(1) | N | N | N | YN | 재처리 가능 여부 |
| 11 | 멱등성보장여부 | IDEMP_YN | CHAR(1) | N | N | N | YN | 동일 기준 재수행 시 중복 반영 방지 여부 |
| 12 | 허용지연분 | ALLOW_DELAY_MIN | NUMBER(5) | N | N | Y | SEQ | SLA 허용 지연 시간 |
| 13 | 오류알림대상 | ERR_NOTI_TGT | VARCHAR2(1000) | N | N | Y | TEXT | 오류 알림 대상 |
| 14 | 담당자ID | OWN_USER_ID | VARCHAR2(50) | N | N | Y | USER_ID | 운영 담당자 |
| 15 | 사용여부 | USE_YN | CHAR(1) | N | N | N | YN | 사용 가능 여부. 신규 거래/조회 노출 기준 |
| 16 | 삭제여부 | DEL_YN | CHAR(1) | N | N | N | YN | 논리삭제 여부. 물리삭제 대신 이력 추적 유지 |
| 17 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 입력 일시 |
| 18 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 입력 사용자 또는 시스템 ID |
| 19 | 최초등록프로그램ID | REG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최초 입력 프로그램/서비스 ID |
| 20 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 21 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |
| 22 | 최종변경프로그램ID | CHG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최종 변경 프로그램/서비스 ID |
| 23 | 데이터버전번호 | DATA_VER_NO | NUMBER(10) | N | N | N | SEQ | 낙관적 잠금 및 변경 충돌 방지용 버전 |

### 05.31 배치실행로그 `TB_BATCH_RUN_LOG`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 실행ID | RUN_ID | VARCHAR2(50) | Y | N | N | RUN_ID | 배치 실행 식별자 |
| 2 | JobID | JOB_ID | VARCHAR2(50) | N | Y | N | JOB_ID | 배치 Job ID |
| 3 | 기준일자 | BAS_DT | CHAR(8) | N | N | Y | DATE8 | 배치 처리 기준일 |
| 4 | 실행유형코드 | RUN_TP_CD | CHAR(2) | N | N | N | CODE | 정기/수동/재처리 |
| 5 | 시작일시 | START_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 배치 시작 일시 |
| 6 | 종료일시 | END_DTTM | TIMESTAMP(6) | N | N | Y | DTTM | 배치 종료 일시 |
| 7 | 실행상태코드 | RUN_STS_CD | CHAR(2) | N | N | N | CODE | 실행중/성공/실패/중단 |
| 8 | 입력건수 | IN_CNT | NUMBER(18) | N | N | N | CNT | 입력 처리 건수 |
| 9 | 성공건수 | SUCC_CNT | NUMBER(18) | N | N | N | CNT | 성공 처리 건수 |
| 10 | 오류건수 | ERR_CNT | NUMBER(18) | N | N | N | CNT | 오류 처리 건수 |
| 11 | 스킵건수 | SKIP_CNT | NUMBER(18) | N | N | N | CNT | 스킵 건수 |
| 12 | 오류코드 | ERR_CD | VARCHAR2(30) | N | N | Y | CODE | 대표 오류코드 |
| 13 | 오류메시지 | ERR_MSG | VARCHAR2(1000) | N | N | Y | TEXT | 대표 오류 메시지 |
| 14 | 재처리원실행ID | REPROC_ORG_RUN_ID | VARCHAR2(50) | N | Y | Y | RUN_ID | 재처리의 원 실행 ID |
| 15 | 실행서버명 | RUN_SVR_NM | VARCHAR2(100) | N | N | Y | TEXT | 실행 서버/컨테이너명 |
| 16 | 원천시스템ID | SRC_SYS_ID | VARCHAR2(30) | N | N | Y | SYS_ID | 데이터를 발생시킨 원천 시스템 |
| 17 | 원천거래ID | SRC_TR_ID | VARCHAR2(100) | N | N | Y | TR_ID | 원천 거래/전문/요청 식별자 |
| 18 | 처리상태코드 | PROC_STS_CD | CHAR(2) | N | N | N | CODE | 정상/오류/보류/재처리 등 처리 상태 |
| 19 | 처리일시 | PROC_DTTM | TIMESTAMP(6) | N | N | Y | DTTM | 원장 반영 또는 최종 처리 일시 |
| 20 | 처리배치ID | PROC_JOB_ID | VARCHAR2(50) | N | N | Y | JOB_ID | 배치 반영 시 실행 Job ID |
| 21 | 오류코드 | ERR_CD | VARCHAR2(30) | N | N | Y | CODE | 처리 오류 발생 시 표준 오류코드 |
| 22 | 오류메시지 | ERR_MSG | VARCHAR2(1000) | N | N | Y | TEXT | 처리 오류 상세 메시지 |
| 23 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 적재 일시 |
| 24 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 적재 사용자 또는 시스템 ID |
| 25 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 26 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |

### 05.32 감사로그 `TB_AUDIT_LOG`

> 감사로그는 불변 저장을 원칙으로 하며, 정정이 필요한 경우 별도 보정 로그를 생성합니다.

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 로그ID | LOG_ID | VARCHAR2(50) | Y | N | N | LOG_ID | 감사 로그 식별자 |
| 2 | 로그일시 | LOG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 행위 발생 일시 |
| 3 | 사용자ID | USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 행위 사용자 |
| 4 | 사용자IP주소 | USER_IP_ADDR | VARCHAR2(100) | N | N | Y | IP | 접속 IP |
| 5 | 프로그램ID | PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 화면/서비스/배치 ID |
| 6 | 메뉴ID | MENU_ID | VARCHAR2(50) | N | N | Y | MENU_ID | 메뉴 ID |
| 7 | 행위유형코드 | ACT_TP_CD | CHAR(2) | N | N | N | CODE | 조회/등록/변경/삭제/승인/다운로드 |
| 8 | 대상테이블명 | TGT_TABLE_NM | VARCHAR2(100) | N | Y | Y | TABLE_NM | 행위 대상 테이블 |
| 9 | 대상키값 | TGT_KEY_VAL | VARCHAR2(1000) | N | N | Y | TEXT | 대상 레코드 키 값 |
| 10 | 변경전값내용 | BEF_VAL_CONT | CLOB | N | N | Y | TEXT | 변경 전 값 |
| 11 | 변경후값내용 | AFT_VAL_CONT | CLOB | N | N | Y | TEXT | 변경 후 값 |
| 12 | 개인정보조회여부 | PII_READ_YN | CHAR(1) | N | N | N | YN | 개인정보 조회 여부 |
| 13 | 마스킹해제여부 | MSK_RLSE_YN | CHAR(1) | N | N | N | YN | 마스킹 해제 조회 여부 |
| 14 | 처리결과코드 | PROC_RSLT_CD | CHAR(2) | N | N | N | CODE | 성공/실패/권한거부 |
| 15 | 세션ID | SESSION_ID | VARCHAR2(100) | N | N | Y | SESSION_ID | 사용자 세션 ID |

### 05.33 메타테이블 `MT_TABLE`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 테이블ID | TABLE_ID | VARCHAR2(50) | Y | N | N | TABLE_ID | 메타 테이블 식별자 |
| 2 | 업무영역코드 | BIZ_DOMAIN_CD | VARCHAR2(30) | N | Y | N | CODE | 업무 영역 |
| 3 | 논리테이블명 | LGC_TABLE_NM | VARCHAR2(200) | N | N | N | NAME | 논리 테이블명 |
| 4 | 물리테이블명 | PHY_TABLE_NM | VARCHAR2(100) | N | N | N | TABLE_NM | 물리 테이블명 |
| 5 | 테이블유형코드 | TABLE_TP_CD | CHAR(2) | N | N | N | CODE | Master/Transaction/Balance/History/Log/Meta |
| 6 | 소유시스템ID | OWN_SYS_ID | VARCHAR2(30) | N | N | N | SYS_ID | 테이블 소유 시스템 |
| 7 | 소유부서코드 | OWN_DEPT_CD | VARCHAR2(20) | N | N | Y | DEPT_CD | 업무 소유 부서 |
| 8 | 담당자ID | OWN_USER_ID | VARCHAR2(50) | N | N | Y | USER_ID | 데이터 담당자 |
| 9 | 주요키내용 | PK_CONT | VARCHAR2(1000) | N | N | Y | TEXT | PK 컬럼 목록 |
| 10 | 파티션기준컬럼명 | PART_COL_NM | VARCHAR2(100) | N | Y | Y | COLUMN_NM | 파티션 기준 컬럼 |
| 11 | 보관주기내용 | RETENTION_CONT | VARCHAR2(500) | N | N | Y | TEXT | 보관 기간 및 법정 근거 |
| 12 | 개인정보포함여부 | PII_INCL_YN | CHAR(1) | N | N | N | YN | 개인정보 포함 여부 |
| 13 | DDL생성대상여부 | DDL_GEN_TGT_YN | CHAR(1) | N | N | N | YN | DDL 자동생성 대상 여부 |
| 14 | 승인상태코드 | APPR_STS_CD | CHAR(2) | N | N | N | CODE | 작성/검토/승인/폐기 |
| 15 | 사용여부 | USE_YN | CHAR(1) | N | N | N | YN | 사용 가능 여부. 신규 거래/조회 노출 기준 |
| 16 | 삭제여부 | DEL_YN | CHAR(1) | N | N | N | YN | 논리삭제 여부. 물리삭제 대신 이력 추적 유지 |
| 17 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 입력 일시 |
| 18 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 입력 사용자 또는 시스템 ID |
| 19 | 최초등록프로그램ID | REG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최초 입력 프로그램/서비스 ID |
| 20 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 21 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |
| 22 | 최종변경프로그램ID | CHG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최종 변경 프로그램/서비스 ID |
| 23 | 데이터버전번호 | DATA_VER_NO | NUMBER(10) | N | N | N | SEQ | 낙관적 잠금 및 변경 충돌 방지용 버전 |

### 05.34 메타컬럼 `MT_COLUMN`

| 순서 | 논리컬럼명 | 물리컬럼명 | 데이터타입 | PK | FK | NULL | 도메인 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | :---: | --- | --- |
| 1 | 컬럼ID | COLUMN_ID | VARCHAR2(50) | Y | N | N | COLUMN_ID | 메타 컬럼 식별자 |
| 2 | 테이블ID | TABLE_ID | VARCHAR2(50) | N | Y | N | TABLE_ID | 소속 테이블 ID |
| 3 | 컬럼순번 | COLUMN_SEQ | NUMBER(5) | N | N | N | SEQ | 테이블 내 컬럼 순서 |
| 4 | 논리컬럼명 | LGC_COLUMN_NM | VARCHAR2(200) | N | N | N | NAME | 논리 컬럼명 |
| 5 | 물리컬럼명 | PHY_COLUMN_NM | VARCHAR2(100) | N | N | N | COLUMN_NM | 물리 컬럼명 |
| 6 | 도메인ID | DOMAIN_ID | VARCHAR2(50) | N | Y | Y | DOMAIN_ID | 표준 도메인 ID |
| 7 | 데이터타입 | DATA_TP | VARCHAR2(30) | N | N | N | TYPE | DBMS 데이터 타입 |
| 8 | 데이터길이 | DATA_LEN | NUMBER(10) | N | N | Y | SEQ | 데이터 길이 |
| 9 | 소수자리수 | SCALE_LEN | NUMBER(10) | N | N | Y | SEQ | 숫자 소수 자리수 |
| 10 | PK여부 | PK_YN | CHAR(1) | N | N | N | YN | PK 포함 여부 |
| 11 | FK여부 | FK_YN | CHAR(1) | N | N | N | YN | FK 포함 여부 |
| 12 | NULL허용여부 | NULL_ABLE_YN | CHAR(1) | N | N | N | YN | NULL 허용 여부 |
| 13 | 기본값내용 | DFLT_VAL_CONT | VARCHAR2(500) | N | N | Y | TEXT | 컬럼 기본값 |
| 14 | 코드그룹코드 | GRP_CD | VARCHAR2(50) | N | Y | Y | CODE | 코드 컬럼의 코드그룹 |
| 15 | 개인정보등급코드 | PII_GRD_CD | CHAR(1) | N | N | Y | CODE | 개인정보 등급 |
| 16 | 암호화여부 | ENC_YN | CHAR(1) | N | N | N | YN | 저장 암호화 여부 |
| 17 | 마스킹여부 | MSK_YN | CHAR(1) | N | N | N | YN | 조회 마스킹 여부 |
| 18 | 검증규칙내용 | VALID_RULE_CONT | VARCHAR2(1000) | N | N | Y | TEXT | 컬럼 유효성 검증 규칙 |
| 19 | 컬럼설명 | COLUMN_DESC | VARCHAR2(1000) | N | N | Y | TEXT | 업무 설명 |
| 20 | 승인상태코드 | APPR_STS_CD | CHAR(2) | N | N | N | CODE | 작성/검토/승인/폐기 |
| 21 | 사용여부 | USE_YN | CHAR(1) | N | N | N | YN | 사용 가능 여부. 신규 거래/조회 노출 기준 |
| 22 | 삭제여부 | DEL_YN | CHAR(1) | N | N | N | YN | 논리삭제 여부. 물리삭제 대신 이력 추적 유지 |
| 23 | 최초등록일시 | REG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최초 입력 일시 |
| 24 | 최초등록사용자ID | REG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최초 입력 사용자 또는 시스템 ID |
| 25 | 최초등록프로그램ID | REG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최초 입력 프로그램/서비스 ID |
| 26 | 최종변경일시 | CHG_DTTM | TIMESTAMP(6) | N | N | N | DTTM | 최종 변경 일시 |
| 27 | 최종변경사용자ID | CHG_USER_ID | VARCHAR2(50) | N | N | N | USER_ID | 최종 변경 사용자 또는 시스템 ID |
| 28 | 최종변경프로그램ID | CHG_PGM_ID | VARCHAR2(50) | N | N | Y | PGM_ID | 최종 변경 프로그램/서비스 ID |
| 29 | 데이터버전번호 | DATA_VER_NO | NUMBER(10) | N | N | N | SEQ | 낙관적 잠금 및 변경 충돌 방지용 버전 |

## 06. 코드/도메인 값 메타

### 06.1 공통 코드그룹

| GRP_CD | 그룹명 | 코드길이 | 담당영역 | 설명 |
| --- | --- | :---: | --- | --- |
| YN | 여부 | 1 | 공통 | Y/N 여부 값 |
| CUST_DVSN_CD | 고객구분코드 | 1 | 고객 | 개인/법인/외국인/재외국민 |
| CUST_STS_CD | 고객상태코드 | 2 | 고객 | 정상/휴면/탈퇴/거래정지 |
| ACCT_PRD_DVSN_CD | 계좌상품구분코드 | 2 | 계좌 | 위탁/연금/신용/파생/CMA |
| ACCT_STS_CD | 계좌상태코드 | 2 | 계좌 | 정상/폐쇄/거래정지/휴면 |
| MKT_DVSN_CD | 시장구분코드 | 2 | 상품 | KOSPI/KOSDAQ/KONEX/파생/해외 |
| PRD_TP_CD | 상품유형코드 | 2 | 상품 | 주식/ETF/채권/선물/옵션/펀드 |
| BUY_SELL_DVSN_CD | 매매구분코드 | 1 | 주문 | 매도/매수/정정/취소 |
| ORD_DVSN_CD | 주문구분코드 | 2 | 주문 | 지정가/시장가/시간외/조건부 |
| ORD_STS_CD | 주문상태코드 | 2 | 주문 | 접수/확인/일부체결/전량체결/거부 |
| STL_STS_CD | 결제상태코드 | 2 | 결제 | 예정/처리중/완료/오류/보류 |
| CRD_DVSN_CD | 신용구분코드 | 2 | 신용 | 현금성/자기융자/유통융자/담보대출 |
| SELL_MGE_DVSN_CD | 매도담보구분코드 | 2 | 신용 | 일반매도/상환매도/반대매매 |
| DERIV_PRD_DVSN_CD | 파생상품구분코드 | 2 | 파생 | 지수선물/지수옵션/주식선물/주식옵션 |
| BOND_TP_CD | 채권종류코드 | 2 | 채권 | 국채/지방채/금융채/회사채 |
| INT_PAY_TP_CD | 이자지급유형코드 | 1 | 채권 | 이표채/할인채/복리채 |
| RIGHT_TP_CD | 권리유형코드 | 2 | 권리 | 현금배당/주식배당/유상증자/무상증자/분할 |
| CHNL_CD | 채널코드 | 3~10 | 채널 | HTS/MTS/API/영업점/ARS |
| IF_STS_CD | 인터페이스상태코드 | 2 | 인터페이스 | 정상/중지/폐기/테스트 |
| JOB_STS_CD | 배치상태코드 | 2 | 배치 | 대기/실행중/성공/실패/재처리 |

### 06.2 주요 코드 상세

| GRP_CD | CD | 코드명 | 설명 | 유효시작일 | 유효종료일 | 사용여부 |
| --- | --- | --- | --- | :---: | :---: | :---: |
| YN | Y | 예 | 참/사용/가능 | 20200101 | 99991231 | Y |
| YN | N | 아니오 | 거짓/미사용/불가 | 20200101 | 99991231 | Y |
| CUST_DVSN_CD | 1 | 개인 | 내국인 개인 고객 | 20200101 | 99991231 | Y |
| CUST_DVSN_CD | 2 | 법인 | 법인 고객 | 20200101 | 99991231 | Y |
| CUST_DVSN_CD | 3 | 외국인 | 외국인 개인/법인 | 20200101 | 99991231 | Y |
| CUST_DVSN_CD | 4 | 재외국민 | 해외 거주 국내 국적자 | 20200101 | 99991231 | Y |
| CUST_STS_CD | 01 | 정상 | 거래 가능 고객 | 20200101 | 99991231 | Y |
| CUST_STS_CD | 02 | 휴면 | 장기 미거래 또는 휴면 고객 | 20200101 | 99991231 | Y |
| CUST_STS_CD | 03 | 탈퇴 | 거래 종료 고객 | 20200101 | 99991231 | Y |
| CUST_STS_CD | 09 | 거래정지 | 법적/내부통제 사유 거래 제한 | 20200101 | 99991231 | Y |
| ACCT_PRD_DVSN_CD | 01 | 위탁 | 국내/해외 위탁매매 계좌 | 20200101 | 99991231 | Y |
| ACCT_PRD_DVSN_CD | 02 | 연금 | IRP/연금저축 계좌 | 20200101 | 99991231 | Y |
| ACCT_PRD_DVSN_CD | 03 | 신용 | 신용거래 약정 계좌 | 20200101 | 99991231 | Y |
| ACCT_PRD_DVSN_CD | 04 | 국내파생 | 선물옵션 전용 계좌 | 20200101 | 99991231 | Y |
| ACCT_PRD_DVSN_CD | 05 | CMA | RP/MMF 자동매수 연계 계좌 | 20200101 | 99991231 | Y |
| ACCT_STS_CD | 01 | 정상 | 정상 사용 가능 계좌 | 20200101 | 99991231 | Y |
| ACCT_STS_CD | 02 | 폐쇄 | 폐쇄 처리 계좌 | 20200101 | 99991231 | Y |
| ACCT_STS_CD | 03 | 휴면 | 장기 미사용 휴면 계좌 | 20200101 | 99991231 | Y |
| ACCT_STS_CD | 09 | 거래정지 | 사고/압류/제재 등 제한 계좌 | 20200101 | 99991231 | Y |
| MKT_DVSN_CD | 01 | KOSPI | 유가증권시장 | 20200101 | 99991231 | Y |
| MKT_DVSN_CD | 02 | KOSDAQ | 코스닥시장 | 20200101 | 99991231 | Y |
| MKT_DVSN_CD | 03 | KONEX | 코넥스시장 | 20200101 | 99991231 | Y |
| MKT_DVSN_CD | 04 | KRX_DERIV | 국내 파생상품시장 | 20200101 | 99991231 | Y |
| MKT_DVSN_CD | 05 | OTC_BOND | 장외채권시장 | 20200101 | 99991231 | Y |
| MKT_DVSN_CD | 90 | FRGN | 해외시장 | 20200101 | 99991231 | Y |
| PRD_TP_CD | 01 | 주식 | 보통주/우선주 | 20200101 | 99991231 | Y |
| PRD_TP_CD | 02 | ETF | 상장지수펀드 | 20200101 | 99991231 | Y |
| PRD_TP_CD | 03 | ETN | 상장지수증권 | 20200101 | 99991231 | Y |
| PRD_TP_CD | 04 | 채권 | 장내/장외 채권 | 20200101 | 99991231 | Y |
| PRD_TP_CD | 05 | 선물 | 지수/주식/통화/상품 선물 | 20200101 | 99991231 | Y |
| PRD_TP_CD | 06 | 옵션 | 지수/주식 옵션 | 20200101 | 99991231 | Y |
| BUY_SELL_DVSN_CD | 1 | 매도 | Sell | 20200101 | 99991231 | Y |
| BUY_SELL_DVSN_CD | 2 | 매수 | Buy | 20200101 | 99991231 | Y |
| BUY_SELL_DVSN_CD | 3 | 정정 | Modify | 20200101 | 99991231 | Y |
| BUY_SELL_DVSN_CD | 4 | 취소 | Cancel | 20200101 | 99991231 | Y |
| ORD_DVSN_CD | 00 | 지정가 | 가격 지정 주문 | 20200101 | 99991231 | Y |
| ORD_DVSN_CD | 01 | 시장가 | 가격 미지정 시장가 주문 | 20200101 | 99991231 | Y |
| ORD_DVSN_CD | 02 | 조건부지정가 | 장중 지정가, 미체결 시 시장가 전환 | 20200101 | 99991231 | Y |
| ORD_DVSN_CD | 03 | 최유리지정가 | 최유리 호가 기준 주문 | 20200101 | 99991231 | Y |
| ORD_DVSN_CD | 04 | 최우선지정가 | 최우선 호가 기준 주문 | 20200101 | 99991231 | Y |
| ORD_DVSN_CD | 05 | 시간외종가 | 장전/장후 시간외 종가 | 20200101 | 99991231 | Y |
| ORD_DVSN_CD | 06 | 시간외단일가 | 장후 시간외 단일가 | 20200101 | 99991231 | Y |
| ORD_STS_CD | 01 | 접수 | 내부 주문 접수 완료 | 20200101 | 99991231 | Y |
| ORD_STS_CD | 02 | 확인 | 거래소/FEP 접수 확인 | 20200101 | 99991231 | Y |
| ORD_STS_CD | 03 | 일부체결 | 일부 수량 체결 | 20200101 | 99991231 | Y |
| ORD_STS_CD | 04 | 전량체결 | 주문 수량 전량 체결 | 20200101 | 99991231 | Y |
| ORD_STS_CD | 05 | 전량취소 | 주문 전량 취소 | 20200101 | 99991231 | Y |
| ORD_STS_CD | 06 | 거부 | 주문 접수 또는 거래소 거부 | 20200101 | 99991231 | Y |
| ORD_STS_CD | 08 | 반대매매수행 | 시스템 강제청산 주문 | 20200101 | 99991231 | Y |
| STL_STS_CD | 01 | 예정 | 결제 예정 상태 | 20200101 | 99991231 | Y |
| STL_STS_CD | 02 | 처리중 | 결제 처리 중 | 20200101 | 99991231 | Y |
| STL_STS_CD | 03 | 완료 | 결제 완료 | 20200101 | 99991231 | Y |
| STL_STS_CD | 04 | 오류 | 결제 오류 | 20200101 | 99991231 | Y |
| STL_STS_CD | 05 | 보류 | 법적/업무 사유 보류 | 20200101 | 99991231 | Y |
| CRD_DVSN_CD | 00 | 현금성 | 일반 현금 또는 대용 잔고 | 20200101 | 99991231 | Y |
| CRD_DVSN_CD | 01 | 자기융자 | 증권사 자금 신용융자 | 20200101 | 99991231 | Y |
| CRD_DVSN_CD | 02 | 유통융자 | 유통금융 신용융자 | 20200101 | 99991231 | Y |
| CRD_DVSN_CD | 03 | 예탁담보대출 | 보유증권 담보대출 | 20200101 | 99991231 | Y |
| SELL_MGE_DVSN_CD | 01 | 일반매도 | 보유 현금 주식 매도 | 20200101 | 99991231 | Y |
| SELL_MGE_DVSN_CD | 02 | 신용상환매도 | 융자금 상환 목적 매도 | 20200101 | 99991231 | Y |
| SELL_MGE_DVSN_CD | 09 | 반대매매 | 담보부족/미수 강제청산 매도 | 20200101 | 99991231 | Y |
| DERIV_PRD_DVSN_CD | 11 | 지수선물 | KOSPI200 등 지수 선물 | 20200101 | 99991231 | Y |
| DERIV_PRD_DVSN_CD | 12 | 지수옵션 | KOSPI200 등 지수 옵션 | 20200101 | 99991231 | Y |
| DERIV_PRD_DVSN_CD | 21 | 주식선물 | 개별주식 선물 | 20200101 | 99991231 | Y |
| DERIV_PRD_DVSN_CD | 22 | 주식옵션 | 개별주식 옵션 | 20200101 | 99991231 | Y |
| BOND_TP_CD | 01 | 국채 | 정부 발행 채권 | 20200101 | 99991231 | Y |
| BOND_TP_CD | 02 | 지방채 | 지자체 발행 채권 | 20200101 | 99991231 | Y |
| BOND_TP_CD | 03 | 금융채 | 은행/금융기관 발행 채권 | 20200101 | 99991231 | Y |
| BOND_TP_CD | 04 | 회사채 | 일반 기업 발행 채권 | 20200101 | 99991231 | Y |
| INT_PAY_TP_CD | 1 | 이표채 | 주기적 이자 지급 | 20200101 | 99991231 | Y |
| INT_PAY_TP_CD | 2 | 할인채 | 할인 발행, 만기 원금 상환 | 20200101 | 99991231 | Y |
| INT_PAY_TP_CD | 3 | 복리채 | 이자 복리 축적 후 만기 지급 | 20200101 | 99991231 | Y |

---

## 07. 표준 데이터 타입 및 도메인

| 도메인 | 권장 DB 타입 | 길이/Scale | 예시 컬럼 | 검증 규칙 | 비고 |
| --- | --- | --- | --- | --- | --- |
| ACNO | VARCHAR2 | 20 | ACNO | 숫자/하이픈 제거 후 표준길이 검증 | 표시 포맷과 저장값 분리 권장 |
| CUST_NO | VARCHAR2 | 12~20 | CUST_NO | 중복 불가, 고객마스터 존재 | 내부 고객 식별자 |
| ISU_CD | VARCHAR2 | 12 | ISU_CD | 시장별 코드체계 검증 | ISIN/단축코드 병행 관리 |
| ORD_NO | VARCHAR2 | 20~30 | ORD_NO | 주문일+채널+순번 등 유일성 | 대외 주문번호와 내부 주문번호 분리 |
| EXEC_NO | VARCHAR2 | 20~30 | EXEC_NO | 체결일 기준 유일성 | 거래소 체결번호 별도 관리 |
| DATE8 | CHAR | 8 | ORD_DT, BAS_DT | YYYYMMDD, 유효 달력일 | DB DATE형 사용 시 표시 포맷만 표준화 |
| DTTM | TIMESTAMP | 6 | RCPT_DTTM | KST/UTC 기준 명시 | 대외 로그는 timezone 고려 |
| AMT | NUMBER | 20,2 | EXEC_AMT | 금액 음수 허용 여부 업무별 지정 | 외화/채권 이자 고려 |
| QTY | NUMBER | 18,6 | ORD_QTY | 음수 불가, 소수 가능 여부 상품별 검증 | 해외주식/채권/펀드 고려 |
| PRICE | NUMBER | 18,6 | ORD_UPRC | 호가단위 검증 | 상품별 tick size 연계 |
| RATE | NUMBER | 12,8 | FEE_RT | 0 이상, 상한값 업무별 지정 | 세율/수수료율/표면금리 |
| YN | CHAR | 1 | USE_YN | Y 또는 N | Boolean 대체 도메인 |
| CODE | VARCHAR2 | 20~30 | MKT_DVSN_CD | TB_CODE_DTL 유효값 참조 | 코드그룹 필수 |
| NAME | VARCHAR2 | 100~200 | CUST_NM, ISU_NM | 금칙문자/길이 검증 | 다국어명 별도 컬럼 가능 |
| TEXT | VARCHAR2/CLOB | 500~4000 | RJCT_MSG | 길이 제한, 제어문자 제거 | 메시지/설명 |
| USER_ID | VARCHAR2 | 20~50 | REG_USER_ID | 사용자마스터 존재 검증 | 감사로그 연계 |
| BR_CD | VARCHAR2 | 6~10 | MGMT_BR_CD | 조직마스터 유효값 | 부점코드 |
| JOB_ID | VARCHAR2 | 50 | CRT_JOB_ID | 배치메타 존재 검증 | 운영 추적 |
| IF_ID | VARCHAR2 | 50 | IF_ID | 인터페이스메타 존재 검증 | 전문/연계 추적 |

---

## 08. 명명 규칙 및 표준 약어

### 08.0 v0.5 명명 규칙 통합 적용 원칙

| 구분 | v0.5 기준 |
| --- | --- |
| 테이블명 | 12자리 고정 길이 코드형 표준명 `SDDBBBOOTVNN`을 `STD_TBL_NM`으로 관리 |
| 실제 물리명 | 기존 운영 DB명은 `PHYS_TBL_NM`으로 관리하여 레거시 호환 유지 |
| 레거시명 | 이행/영향도 분석을 위해 `LEGACY_TBL_NM` 별도 관리 |
| 컬럼명 | 영문 대문자 + `_` 기반의 의미형 물리명 사용 |
| 컬럼 Suffix | `_NO`, `_ID`, `_CD`, `_DT`, `_DTTM`, `_AMT`, `_QTY`, `_UPRC`, `_RT`, `_YN` 등 표준 Suffix 적용 |
| 도메인 | 컬럼 suffix와 데이터 도메인이 일치해야 함 |
| 검증 | 테이블명 Rule과 컬럼명 Rule은 META 등록 시 자동 검증 대상 |
| 변경관리 | 테이블명/컬럼명/도메인/코드 변경은 변경요청 및 승인 이력 관리 |



### 08.1 테이블 명명 규칙

| 분류 | 표준 | 예시 | 설명 |
| --- | --- | --- | --- |
| 업무 테이블 Prefix | TB_ | TB_ORD_MST | 업무 데이터 테이블 |
| 메타 테이블 Prefix | MT_ | MT_TABLE | META 시스템 자체 테이블 |
| 임시 테이블 Prefix | TMP_ | TMP_ORD_RECON | 임시/작업 테이블 |
| 스테이징 Prefix | STG_ | STG_KRX_EXEC | 외부 수신 원천 적재 테이블 |
| 백업 Prefix | BAK_ | BAK_CASH_BAL_20260610 | 작업 전 백업 테이블 |
| 테이블 업무영역 | CUST/ACCT/ISU/ORD/EXEC/BAL/CASH/STL/CRD | TB_ACCT_MST | 물리명 중간에 업무영역 배치 |
| 테이블 유형 Suffix | MST/DTL/HIST/BAL/RULE/LOG/SCHD | TB_ORD_HIST | 마스터/상세/이력/잔고/규칙/로그/스케줄 |

### 08.2 컬럼 명명 규칙

| 분류 | 표준 | 예시 | 설명 |
| --- | --- | --- | --- |
| 코드 | _CD | MKT_DVSN_CD | 코드형 컬럼 |
| 명칭 | _NM | CUST_NM | 명칭형 컬럼 |
| 일자 | _DT | ORD_DT | YYYYMMDD 문자형 또는 DATE형 |
| 일시 | _DTTM | RCPT_DTTM | Timestamp/Datetime |
| 금액 | _AMT | EXEC_AMT | 금액 |
| 수량 | _QTY | ORD_QTY | 수량 |
| 단가 | _UPRC | ORD_UPRC | Unit Price |
| 가격 | _PRC | STTL_PRC | 기준가/정산가격 등 |
| 비율 | _RT | FEE_RT | Rate/Ratio |
| 여부 | _YN | USE_YN | Y/N |
| 순번 | _SEQ | HIST_SEQ | 복합키 내 순번 |
| 번호 | _NO | ORD_NO | 업무 식별 번호 |
| ID | _ID | USER_ID | 시스템 식별자 |
| 설명 | _DESC | RULE_DESC | 설명문 |
| 메시지 | _MSG | RJCT_MSG | 오류/거부 메시지 |

### 08.3 표준 약어

| 한글 | 표준 약어 | 영문 의미 | 예시 |
| --- | --- | --- | --- |
| 고객 | CUST | Customer | CUST_NO |
| 계좌 | ACCT/ACNO | Account | ACNO |
| 종목 | ISU | Issue | ISU_CD |
| 주문 | ORD | Order | ORD_NO |
| 체결 | EXEC | Execution | EXEC_QTY |
| 결제 | STL | Settlement | STL_DT |
| 잔고 | BAL | Balance | TB_BAL_POS |
| 예수금 | DPST | Deposit | DPST_AMT |
| 기준 | BAS | Base | BAS_DT |
| 구분 | DVSN | Division | BUY_SELL_DVSN_CD |
| 상태 | STS | Status | ORD_STS_CD |
| 가능 | ABLE | Able | ORD_ABLE_AMT |
| 등록 | REG | Register | REG_DTTM |
| 변경 | CHG | Change | CHG_DTTM |
| 삭제 | DEL | Delete | DEL_YN |
| 수수료 | FEE | Fee | FEE_AMT |
| 세금 | TAX | Tax | TAX_AMT |
| 담보 | COLL/MGE | Collateral/Margin | COLL_EVAL_AMT, MGE_LOAN_ABLE_QTY |
| 신용 | CRD | Credit | CRD_LOAN |
| 파생 | DERIV | Derivatives | DERIV_MARGIN |
| 채권 | BOND | Bond | BOND_TP_CD |

---

## 09. 업무별 처리 기준

### 09.1 국내주식 주문·체결·결제 흐름

| 단계 | 처리 내용 | 주요 테이블 | 핵심 검증 |
| --- | --- | --- | --- |
| 주문접수 | 채널 주문을 접수하고 계좌/종목/주문가능금액 검증 | TB_ORD_MST, TB_CASH_BAL, TB_BAL_POS | 계좌상태 정상, 주문제한 없음, 종목 거래가능, 호가단위 적합 |
| 주문전송 | 주문을 FEP/거래소로 송신 | TB_ORD_MST, TB_ORD_HIST | 중복주문 방지, 대외주문번호 매핑 |
| 체결수신 | 거래소 체결을 수신하고 주문에 매핑 | TB_EXEC_DTL, TB_ORD_MST | 체결 중복 방지, 원주문 존재, 체결수량 누계 검증 |
| 비용계산 | 수수료/세금 산정 | TB_FEE_TAX_RULE, TB_EXEC_DTL | 시장/상품/채널별 규칙 적용 |
| 결제예정생성 | 체결 기준 T+N 결제 예정 생성 | TB_STL_SCHD | 매수/매도 결제일, 금액 부호, 비용 반영 |
| 잔고/예수금반영 | 일중 또는 일마감 기준 잔고/예수금 갱신 | TB_BAL_POS, TB_CASH_BAL | 잔고 음수 방지, D1/D2 예수금 대사 |
| 일마감 | 거래일 최종 잔고, 예수금, 결제 예정 확정 | TB_BATCH_RUN_LOG | 주문/체결/결제/잔고 대사 |

### 09.2 신용공여 처리 기준

| 구분 | 처리 기준 | 관리 테이블 | 비고 |
| --- | --- | --- | --- |
| 약정 | 고객/계좌별 신용거래 약정, 한도, 만기, 등급 관리 | TB_CRD_AGR | KYC, 투자자구분, 사고계좌 여부 확인 |
| 융자매수 | 매수 체결 후 융자 원장 생성 | TB_CRD_LOAN, TB_BAL_POS | 대출일자 기준으로 잔고 분리 |
| 담보평가 | 현금, 주식, 대용가격, 평가비율 기반 담보 평가 | TB_COLL_EVAL, TB_STK_SUB_PRC | 종목별 대용비율 적용 |
| 이자계산 | 대출일수와 이자율 기준 발생이자 산정 | TB_CRD_LOAN | 일할 계산, 연체 가산 가능 |
| 상환 | 매도상환 또는 현금상환 처리 | TB_CRD_LOAN, TB_CASH_BAL | 상환 순서 기준 필요 |
| 반대매매 | 담보부족/미수/연체 발생 시 강제청산 주문 생성 | TB_ORD_MST, TB_CRD_LOAN | 사전통지, 보류/예외 승인 관리 필요 |

### 09.3 파생상품 처리 기준

| 구분 | 처리 기준 | 관리 테이블 | 비고 |
| --- | --- | --- | --- |
| 종목관리 | 결제월, 만기일, 행사가격, 승수 관리 | TB_DERIV_ISU_MST | 만기 도래 시 최근월물 갱신 |
| 주문증거금 | 신규 주문 가능 여부 판단 | TB_DERIV_MARGIN | 위탁증거금, 주문가능금액 검증 |
| 미결제약정 | 체결 후 포지션 집계 | TB_DERIV_POS_BAL | 매수/매도, 롱/숏, 계약수 관리 |
| 일일정산 | 정산가격 기준 평가손익 및 정산차금 계산 | TB_DERIV_SETTL_DTL | 예수금 반영, 정산차금 대사 |
| 마진콜 | 유지증거금 미달 여부 판단 | TB_DERIV_MARGIN | 추가증거금, 강제청산 대상 관리 |
| 만기결제 | 최종거래일/만기일 청산 처리 | TB_DERIV_SETTL_DTL | 현금결제/실물인수도 여부 구분 |

### 09.4 채권 처리 기준

| 구분 | 처리 기준 | 관리 테이블 | 비고 |
| --- | --- | --- | --- |
| 발행정보 | 발행일, 만기일, 표면금리, 이자주기 관리 | TB_BOND_ISS_MST | 발행기관, 신용등급 포함 |
| 매매 | 장내/장외 채권 매매 체결 | TB_ORD_MST, TB_EXEC_DTL | 수량 단위와 가격 단위 주식과 상이 |
| 경과이자 | 매매일 기준 경과이자 산정 | TB_BOND_INT_SCHD | 세금 및 결제금액 반영 |
| 이자지급 | 이자지급일 권리자 확정 및 예수금 입금 | TB_RIGHT_EVT, TB_RIGHT_ALOC | 원천징수 처리 필요 |
| 만기상환 | 만기일 원금 상환 | TB_STL_SCHD, TB_CASH_BAL | 상환금액, 세금, 수수료 반영 |

---

## 10. 인터페이스 및 전문 메타

### 10.1 인터페이스 메타

| 구분 | IF_ID | 논리명 | 송신시스템 | 수신시스템 | 방식 | 주기 | 주요키/전문키 | 주요 데이터 | 오류처리 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 실시간 | IF_ORD_RQST | 주문접수요청 | HTS/MTS/API | 주문계 | REST/TCP | 실시간 | ORD_NO | 계좌, 종목, 주문수량/가격 | 거부코드 반환, 주문이력 기록 |
| 실시간 | IF_ORD_RSPN | 주문접수응답 | 주문계 | 채널계 | TCP/MQ | 실시간 | ORD_NO | 주문상태, 메시지코드 | 응답누락 재조회 |
| 실시간 | IF_EXEC_RCV | 체결수신 | 거래소/FEP | 체결계 | TCP/MQ | 실시간 | EXEC_NO | 체결수량/단가, 거래소번호 | 중복체결 방지, 재처리 큐 |
| 실시간 | IF_QUOTE_RCV | 시세수신 | 시세계/FEP | 상품/주문계 | TCP/MQ | 실시간 | ISU_CD | 현재가, 호가, 거래정지 | 최종시세 보정, 순번 검증 |
| 실시간 | IF_CASH_IO | 입출금처리 | 출납계 | 예수금계 | MQ/API | 실시간 | IO_NO | 입출금금액, 계좌, 통화 | 원거래 조회 후 재처리 |
| 배치 | IF_KRX_ISU_FILE | 종목마스터파일 | 거래소 | 상품계 | File | 일 1회 | ISU_CD | 종목명, 시장, 상장상태 | 변경분 이력 적재 |
| 배치 | IF_KSD_RIGHT | 권리정보수신 | 예탁결제원 | 권리계 | File/API | 이벤트별 | RIGHT_EVT_NO | 배당/증자/분할 정보 | 승인 후 반영 |
| 배치 | IF_BOND_MASTER | 채권마스터수신 | 정보벤더 | 상품계 | File/API | 일 1회 | ISU_CD | 채권 발행/이자 정보 | 원천-내부 대사 |
| 관리 | IF_CODE_DEPLOY | 공통코드배포 | META | 전 시스템 | MQ/File | 변경시 | GRP_CD+CD | 코드 유효값 | 버전관리, 영향도 검토 |
| 관리 | IF_META_SYNC | 메타동기화 | META | DW/운영포털 | API/File | 변경시 | TABLE_ID | 테이블/컬럼/코드 메타 | 승인본만 배포 |

### 10.2 전문 필드 메타 예시 `IF_EXEC_RCV`

| 필드순서 | 전문필드명 | 논리명 | 데이터타입 | 길이 | 필수 | 매핑테이블 | 매핑컬럼 | 설명 |
| :---: | --- | --- | --- | :---: | :---: | --- | --- | --- |
| 1 | MSG_TP | 메시지유형 | CHAR | 4 | Y | - | - | 체결수신 전문 유형 |
| 2 | EXCH_EXEC_NO | 거래소체결번호 | VARCHAR | 30 | Y | TB_EXEC_DTL | EXCH_EXEC_NO | 거래소 원천 체결번호 |
| 3 | EXCH_ORD_NO | 거래소주문번호 | VARCHAR | 30 | Y | TB_ORD_MST | EXCH_ORD_NO | 원 주문 매핑 키 |
| 4 | ISU_CD | 종목코드 | VARCHAR | 12 | Y | TB_EXEC_DTL | ISU_CD | 체결 종목 |
| 5 | BUY_SELL_DVSN_CD | 매매구분코드 | CHAR | 1 | Y | TB_EXEC_DTL | BUY_SELL_DVSN_CD | 매도/매수 |
| 6 | EXEC_QTY | 체결수량 | NUMBER | 18,6 | Y | TB_EXEC_DTL | EXEC_QTY | 체결 수량 |
| 7 | EXEC_UPRC | 체결단가 | NUMBER | 18,6 | Y | TB_EXEC_DTL | EXEC_UPRC | 체결 단가 |
| 8 | EXEC_DTTM | 체결일시 | TIMESTAMP | 6 | Y | TB_EXEC_DTL | EXEC_DTTM | 체결 시각 |
| 9 | TRD_NO | 거래번호 | VARCHAR | 30 | N | TB_EXEC_DTL | TRD_NO | 거래소 거래 식별자 |

---

## 11. 배치/스케줄 메타

### 11.1 주요 배치 Job

| JOB_ID | Job명 | 주기 | 선행 Job | 입력 | 출력 | 재처리 가능 | 오류 처리 | 설명 |
| --- | --- | --- | --- | --- | --- | :---: | --- | --- |
| BAT_ISU_SYNC | 종목마스터동기화 | 영업일 06:00 | - | 거래소/정보벤더 파일 | TB_ISU_MST | Y | 변경분 롤백 가능 | 종목 신규/변경/상폐 반영 |
| BAT_QUOTE_BASE | 기준가생성 | 영업일 07:00 | BAT_ISU_SYNC | 전일시세 | TB_MKT_QUOTE | Y | 전일 데이터 재적재 | 기준가, 상하한가, 호가단위 생성 |
| BAT_ORD_RECON | 주문대사 | 장종료 후 | - | TB_ORD_MST, FEP 로그 | 대사리포트 | Y | 미매칭 수동 확인 | 주문 접수/거래소 수신 대사 |
| BAT_EXEC_RECON | 체결대사 | 장종료 후 | BAT_ORD_RECON | TB_EXEC_DTL, 거래소 체결 | 대사리포트 | Y | 중복/누락 재처리 | 체결 원장 대사 |
| BAT_STL_SCHD | 결제예정생성 | 장종료 후 | BAT_EXEC_RECON | TB_EXEC_DTL | TB_STL_SCHD | Y | 기존 예정 삭제 후 재생성 | T+N 결제 예정 생성 |
| BAT_BAL_EOD | 일마감 잔고생성 | 일 1회 | BAT_STL_SCHD | 체결/결제/전일잔고 | TB_BAL_POS | Y | 스냅샷 보관 후 재수행 | 계좌별 종목 잔고 생성 |
| BAT_CASH_EOD | 일마감 예수금생성 | 일 1회 | BAT_STL_SCHD | 예수금/결제/출납 | TB_CASH_BAL | Y | 차이 검증 리포트 | D0/D1/D2 예수금 생성 |
| BAT_CRD_INT | 신용이자계산 | 일 1회 | BAT_BAL_EOD | TB_CRD_LOAN | TB_CRD_LOAN | Y | 이자 재계산 가능 | 융자 발생이자 산정 |
| BAT_COLL_EVAL | 담보평가 | 일 1회 | BAT_BAL_EOD | 잔고/대용가격 | TB_COLL_EVAL | Y | 부족계좌 재산정 | 담보비율 및 부족금액 산정 |
| BAT_FORCE_SELL | 반대매매대상생성 | 영업일 08:00 | BAT_COLL_EVAL | TB_COLL_EVAL | TB_ORD_MST 후보 | 제한적 | 승인 후 주문생성 | 미수/담보부족 강제청산 대상 |
| BAT_DERIV_EOD | 파생일일정산 | 일 1회 | 장종료 | 정산가격/포지션 | TB_DERIV_SETTL_DTL | Y | 정산차금 대사 | 정산가격 기준 평가손익 및 증거금 반영 |
| BAT_BOND_INT | 채권이자계산 | 일 1회 | BAT_BAL_EOD | 채권스케줄/잔고 | 권리/예수금 | Y | 지급대상 재확정 | 이표채 이자 지급 및 세금 반영 |
| BAT_RIGHT_APPLY | 권리배정반영 | 이벤트별 | 권리승인 | TB_RIGHT_EVT | TB_RIGHT_ALOC | 제한적 | 승인 후 rollback | 배당/증자/분할 권리 반영 |
| BAT_CODE_DEPLOY | 공통코드배포 | 변경시 | 승인완료 | MT_CODE_DTL | 각 시스템 코드캐시 | Y | 이전 버전 재배포 | 공통코드 동기화 |
| BAT_META_EXPORT | 메타배포 | 변경시 | 승인완료 | MT_* | DW/운영포털 | Y | 승인본만 재배포 | 테이블/컬럼/코드/전문 메타 배포 |

### 11.2 배치 실행 로그 필수 항목

| 항목 | 설명 |
| --- | --- |
| RUN_ID | 배치 실행 단위 고유 ID |
| JOB_ID | 배치 Job ID |
| JOB_STS_CD | 대기/실행중/성공/실패/재처리 |
| START_DTTM / END_DTTM | 시작/종료 시각 |
| INPUT_CNT / PROC_CNT / ERR_CNT | 입력/처리/오류 건수 |
| ERR_CD / ERR_MSG | 오류 코드 및 메시지 |
| RESTART_ABLE_YN | 재시작 가능 여부 |
| LAST_SUCCESS_RUN_ID | 직전 성공 실행 ID |
| OPERATOR_ID | 수동 조치 담당자 |

---

## 12. 데이터 품질 및 검증 규칙

### 12.1 공통 품질 규칙

| RULE_ID | 규칙명 | 대상 | 검증 내용 | 심각도 | 조치 기준 |
| --- | --- | --- | --- | --- | --- |
| DQ_COMMON_001 | PK 중복 검증 | 모든 원장/마스터 | PK 기준 중복 건수 0건 | Critical | 배치 중단, 원인 분석 |
| DQ_COMMON_002 | 필수값 검증 | NOT NULL 컬럼 | NULL 건수 0건 | Critical | 적재 실패 처리 |
| DQ_COMMON_003 | 코드 유효값 검증 | 코드 컬럼 | TB_CODE_DTL 사용 가능 코드만 허용 | High | 오류 리포트 및 보정 |
| DQ_COMMON_004 | 날짜 유효성 검증 | DATE8 컬럼 | YYYYMMDD 및 실제 달력일 검증 | High | 오류 격리 |
| DQ_COMMON_005 | 금액/수량 음수 검증 | AMT/QTY 컬럼 | 업무상 음수 허용 여부에 따라 검증 | Medium | 업무별 예외 승인 |
| DQ_COMMON_006 | 참조무결성 검증 | FK 컬럼 | 참조 마스터 존재 여부 | High | 원천 누락 확인 |

### 12.2 업무별 품질 규칙

| RULE_ID | 업무 | 규칙명 | 대상 | 검증 SQL 개념 | 조치 |
| --- | --- | --- | --- | --- | --- |
| DQ_ORD_001 | 주문 | 주문수량 양수 검증 | TB_ORD_MST | ORD_QTY > 0 | 주문 거부 또는 보정 |
| DQ_ORD_002 | 주문 | 주문상태-체결수량 정합성 | TB_ORD_MST | 전량체결이면 ORD_QTY = EXEC_ACML_QTY | 주문/체결 대사 |
| DQ_EXEC_001 | 체결 | 체결 중복 검증 | TB_EXEC_DTL | EXCH_EXEC_NO 중복 없음 | 중복 수신 제거 |
| DQ_EXEC_002 | 체결 | 체결금액 검증 | TB_EXEC_DTL | EXEC_AMT = EXEC_QTY × EXEC_UPRC 허용오차 이내 | 비용 전 금액 재계산 |
| DQ_STL_001 | 결제 | 체결-결제예정 대사 | TB_EXEC_DTL/TB_STL_SCHD | 체결별 결제예정 1건 이상 | 누락 생성 |
| DQ_BAL_001 | 잔고 | 잔고 음수 검증 | TB_BAL_POS | HOLD_QTY >= 0 | 업무 예외 확인 |
| DQ_CASH_001 | 예수금 | D2 예수금 검증 | TB_CASH_BAL | D2 = 현재 + 결제예정 반영 | 예수금 재계산 |
| DQ_CRD_001 | 신용 | 만기일 검증 | TB_CRD_LOAN | MTRT_DT >= LOAN_DT | 약정/융자 오류 확인 |
| DQ_COLL_001 | 담보 | 담보비율 검증 | TB_COLL_EVAL | 담보금액 / 융자금액 산식 검증 | 반대매매 대상 재산정 |
| DQ_DERIV_001 | 파생 | 정산차금 검증 | TB_DERIV_SETTL_DTL | 전일정산가 대비 손익 계산 | 정산 재처리 |
| DQ_BOND_001 | 채권 | 이자스케줄 연속성 | TB_BOND_INT_SCHD | 이전 종료일과 다음 시작일 정합성 | 스케줄 보정 |
| DQ_RIGHT_001 | 권리 | 권리배정 대상 검증 | TB_RIGHT_ALOC | 기준일 잔고 존재 | 권리 대상 재확정 |

### 12.3 대사 기준

| 대사명 | 원천 | 대상 | 기준 | 허용 오차 |
| --- | --- | --- | --- | --- |
| 주문 대사 | FEP/거래소 주문로그 | TB_ORD_MST | 주문번호, 대외주문번호, 상태 | 0건 불일치 |
| 체결 대사 | 거래소 체결파일 | TB_EXEC_DTL | 체결번호, 수량, 단가, 금액 | 금액 1원 이내 정책 가능 |
| 결제 대사 | 체결내역 | TB_STL_SCHD | 결제일, 종목, 금액, 수량 | 0건 누락 |
| 잔고 대사 | 전일잔고+당일체결 | TB_BAL_POS | 수량, 매입금액 | 업무별 허용오차 |
| 예수금 대사 | 전일예수금+출납+결제 | TB_CASH_BAL | 통화별 금액 | 1원 단위 |
| 파생 정산 대사 | 거래소 정산가/포지션 | TB_DERIV_SETTL_DTL | 정산차금, 증거금 | 1원 단위 |
| 채권 이자 대사 | 채권스케줄/잔고 | 권리/예수금 | 지급대상, 세전/세후금액 | 세금 반올림 기준 |

---

## 13. 보안, 개인정보, 권한 메타

### 13.1 개인정보 분류

| 등급 | 분류 | 예시 컬럼 | 처리 기준 |
| --- | --- | --- | --- |
| P1 | 고유식별/민감 | 주민등록번호, 외국인등록번호, 여권번호 | 암호화, 접근통제, 조회로그 필수 |
| P2 | 개인식별 | 고객명, 휴대폰, 이메일, 주소 | 마스킹, 업무권한 기반 조회 |
| P3 | 금융거래 | 계좌번호, 주문, 체결, 잔고, 예수금 | 접근권한, 감사로그, 목적 외 조회 제한 |
| P4 | 내부운영 | 직원번호, 부점코드, 처리자ID | 권한 관리, 변경 이력 |
| N | 비개인정보 | 종목코드, 시장코드, 공통코드 | 일반 조회 가능 |

### 13.2 컬럼 보안 메타

| 항목 | 설명 | 예시 |
| --- | --- | --- |
| PII_CLSS_CD | 개인정보 분류 코드 | P1/P2/P3/P4/N |
| ENC_YN | 저장 암호화 여부 | 주민등록번호 Y |
| MSK_YN | 화면/조회 마스킹 여부 | 고객명, 휴대폰 Y |
| MASK_RULE_CD | 마스킹 규칙 | 이름 가운데 글자, 휴대폰 중간 4자리 |
| ACCESS_ROLE_CD | 접근 가능 역할 | 상담직원, 준법감시, 운영자 |
| AUDIT_LOG_YN | 조회 로그 적재 여부 | P1/P2/P3 컬럼 Y |
| EXPORT_RSTR_YN | 다운로드 제한 여부 | 개인정보 포함 테이블 Y |

### 13.3 권한 관리 기준

| 권한 유형 | 설명 | 통제 기준 |
| --- | --- | --- |
| 업무권한 | 고객/계좌/주문/잔고 등 업무 화면 접근 | 직무, 부점, 담당고객 범위 적용 |
| 데이터권한 | 테이블/컬럼 단위 조회 가능 여부 | 개인정보 등급 기반 통제 |
| 변경권한 | 메타/코드/규칙 변경 가능 여부 | 작성자-검토자-승인자 분리 |
| 운영권한 | 배치 재수행, 인터페이스 재처리 | 운영자 승인 및 로그 필수 |
| 다운로드권한 | 대량 조회/엑셀 다운로드 | 사유 입력, 승인, 이력 보관 |

---

## 14. 변경관리 및 영향도 분석

### 14.1 변경 요청 유형

| 변경 유형 | 예시 | 필수 검토자 | 배포 기준 |
| --- | --- | --- | --- |
| 표준단어 변경 | 약어 변경, 금칙어 지정 | 데이터표준 담당 | 영향 컬럼 전체 검토 후 배포 |
| 테이블 신규 | 신규 업무 원장 추가 | 데이터아키텍트, DBA, 업무담당 | DDL 승인 후 적용 |
| 컬럼 추가 | 주문원장에 신규 상태 컬럼 추가 | 업무담당, 개발담당, DBA | 하위 호환성 확인 후 적용 |
| 컬럼 타입 변경 | 금액 자리수 확장 | DBA, 인터페이스 담당 | 영향 SQL/전문/배치 확인 필수 |
| 코드 추가 | 신규 주문구분코드 추가 | 업무담당, 채널/기간계 담당 | 채널 캐시/기간계 배포 동시 수행 |
| 코드 폐기 | 사용 중지 코드 폐기 | 업무담당, 운영담당 | 기존 데이터 영향 분석 필요 |
| 전문 변경 | 필드 추가/길이 변경 | 송수신 시스템 담당 | 버전 관리, 병행 기간 운영 |
| 배치 변경 | 선후행 변경, 스케줄 변경 | 운영담당, 업무담당 | 모의 마감 검증 후 반영 |

### 14.2 영향도 분석 매트릭스

| 변경 대상 | 영향 분석 대상 | 확인 내용 |
| --- | --- | --- |
| 테이블 | 컬럼, 인덱스, FK, 배치, 화면, API, DW | 참조 SQL, 적재 로직, 조회 화면 영향 |
| 컬럼 | 인터페이스 필드, 코드, 도메인, 품질규칙 | 타입/길이/NULL/코드 유효값 영향 |
| 코드 | 화면 콤보, 주문검증, 배치, 통계 | 신규 코드 허용 여부, 폐기 코드 사용 여부 |
| 인터페이스 | 송수신 시스템, 전문버전, 매핑 테이블 | 필드 순서/길이 변경에 따른 파싱 영향 |
| 배치 | 선후행, 입력/출력 테이블, 재처리 | 일마감 시간, 실패 시 복구 영향 |
| 품질규칙 | 배치 중단 여부, 예외 승인 | 임계치 변경에 따른 운영 영향 |

### 14.3 승인 워크플로우

| 단계 | 담당 | 산출물 | 상태 |
| --- | --- | --- | --- |
| 1. 변경요청 | 요청부서 | 변경요청서, 사유, 희망일 | 작성중 |
| 2. 표준검토 | 데이터표준 담당 | 명명규칙, 도메인, 코드 검토 결과 | 검토요청 |
| 3. 업무검토 | 업무 담당 | 업무 영향, 규정 영향, 고객 영향 | 검토중 |
| 4. 기술검토 | DBA/개발/운영 | DDL, 인터페이스, 배치 영향 | 검토중 |
| 5. 승인 | 데이터설계총괄/업무책임자 | 승인 의견, 적용 일정 | 승인 |
| 6. 배포 | 운영 담당 | 배포 로그, 검증 결과 | 배포완료 |
| 7. 사후점검 | 운영/품질 담당 | 오류 여부, 대사 결과 | 종료 |

---

## 15. 운영 모니터링 및 장애 대응

### 15.1 모니터링 대상

| 대상 | 지표 | 임계치 예시 | 알림 대상 |
| --- | --- | --- | --- |
| 주문 인터페이스 | 응답 지연, 거부율, 미응답 건수 | 1초 초과, 거부율 급증 | 주문계 운영, 채널 담당 |
| 체결 수신 | 체결 누락, 중복, 순번 오류 | 누락 1건 이상 | 체결계 운영, FEP 담당 |
| 시세 수신 | 시세 지연, 결측 종목 | 3초 이상 지연 | 시세계 운영 |
| 일마감 배치 | Job 실패, 처리시간 초과 | SLA 초과 | 배치 운영, 업무 담당 |
| 예수금/잔고 | 대사 불일치 | 금액/수량 불일치 1건 이상 | 원장 운영, DBA |
| 파생 정산 | 정산차금 불일치 | 1원 이상 정책별 | 파생 운영 |
| 코드 배포 | 배포 실패, 버전 불일치 | 시스템별 버전 상이 | 메타 운영 |
| 개인정보 조회 | 대량 조회, 비정상 시간 조회 | 임계치 초과 | 보안/감사 담당 |

### 15.2 장애 대응 기준

| 장애 유형 | 예시 | 1차 조치 | 2차 조치 |
| --- | --- | --- | --- |
| 인터페이스 장애 | 거래소 체결 수신 지연 | 수신 큐/세션 상태 확인, 재연결 | 원천 파일 대체 수신, 수동 대사 |
| 배치 실패 | 잔고 생성 오류 | 실패 Step 재수행, 입력 데이터 확인 | 전일 스냅샷 복구 후 재마감 |
| 데이터 불일치 | 예수금 대사 차이 | 차이 리포트 확인, 원거래 추적 | 보정전표 또는 원장 재생성 |
| 코드 배포 오류 | 채널 코드 미반영 | 코드 캐시 갱신, 배포 로그 확인 | 이전 버전 롤백 |
| 개인정보 오남용 | 대량 고객조회 | 계정 잠금, 로그 보존 | 보안부서 조사, 감사 보고 |

---

## 16. 표준 DDL 예시

### 16.1 주문원장 DDL 예시

```sql
CREATE TABLE TB_ORD_MST (
    ORD_DT              CHAR(8)        NOT NULL,
    ORD_NO              VARCHAR2(20)   NOT NULL,
    ORG_ORD_NO          VARCHAR2(20),
    ACNO                VARCHAR2(20)   NOT NULL,
    ISU_CD              VARCHAR2(12)   NOT NULL,
    MKT_DVSN_CD         CHAR(2)        NOT NULL,
    PRD_TP_CD           CHAR(2)        NOT NULL,
    BUY_SELL_DVSN_CD    CHAR(1)        NOT NULL,
    ORD_DVSN_CD         CHAR(2)        NOT NULL,
    ORD_STS_CD          CHAR(2)        NOT NULL,
    ORD_QTY             NUMBER(18,6)   NOT NULL,
    ORD_UPRC            NUMBER(18,6),
    ORD_AMT             NUMBER(20,2)   DEFAULT 0 NOT NULL,
    EXEC_ACML_QTY       NUMBER(18,6)   DEFAULT 0 NOT NULL,
    UNEXEC_QTY          NUMBER(18,6)   DEFAULT 0 NOT NULL,
    CNCL_QTY            NUMBER(18,6)   DEFAULT 0 NOT NULL,
    CHNL_CD             VARCHAR2(10)   NOT NULL,
    EXCH_ORD_NO         VARCHAR2(30),
    RCPT_DTTM           TIMESTAMP(6)   NOT NULL,
    EXCH_SEND_DTTM      TIMESTAMP(6),
    RJCT_CD             VARCHAR2(20),
    RJCT_MSG            VARCHAR2(500),
    CRD_DVSN_CD         CHAR(2),
    LOAN_DT             CHAR(8),
    SELL_MGE_DVSN_CD    CHAR(2),
    REG_USER_ID         VARCHAR2(50)   NOT NULL,
    REG_DTTM            TIMESTAMP(6)   DEFAULT SYSTIMESTAMP NOT NULL,
    CHG_USER_ID         VARCHAR2(50),
    CHG_DTTM            TIMESTAMP(6),
    CONSTRAINT PK_TB_ORD_MST PRIMARY KEY (ORD_DT, ORD_NO)
)
PARTITION BY RANGE (ORD_DT) (
    PARTITION P_MAX VALUES LESS THAN (MAXVALUE)
);

CREATE INDEX IX_TB_ORD_MST_01 ON TB_ORD_MST (ACNO, ORD_DT);
CREATE INDEX IX_TB_ORD_MST_02 ON TB_ORD_MST (ISU_CD, ORD_DT);
CREATE INDEX IX_TB_ORD_MST_03 ON TB_ORD_MST (EXCH_ORD_NO);
```

### 16.2 메타 컬럼 DDL 예시

```sql
CREATE TABLE MT_COLUMN (
    COLUMN_ID           VARCHAR2(50)    NOT NULL,
    TABLE_ID            VARCHAR2(50)    NOT NULL,
    COLUMN_SEQ          NUMBER(5)       NOT NULL,
    LOGICAL_COLUMN_NM   VARCHAR2(200)   NOT NULL,
    PHYSICAL_COLUMN_NM  VARCHAR2(100)   NOT NULL,
    DOMAIN_ID           VARCHAR2(50),
    DATA_TYPE_NM        VARCHAR2(50)    NOT NULL,
    DATA_LEN            NUMBER(10),
    DATA_PRECISION      NUMBER(10),
    DATA_SCALE          NUMBER(10),
    PK_YN               CHAR(1)         DEFAULT 'N' NOT NULL,
    FK_YN               CHAR(1)         DEFAULT 'N' NOT NULL,
    NULL_ABLE_YN        CHAR(1)         DEFAULT 'Y' NOT NULL,
    DEFAULT_VAL         VARCHAR2(200),
    CODE_GRP_CD         VARCHAR2(50),
    PII_CLSS_CD         CHAR(2)         DEFAULT 'N' NOT NULL,
    ENC_YN              CHAR(1)         DEFAULT 'N' NOT NULL,
    MSK_YN              CHAR(1)         DEFAULT 'N' NOT NULL,
    COLUMN_DESC         VARCHAR2(1000),
    USE_YN              CHAR(1)         DEFAULT 'Y' NOT NULL,
    REG_USER_ID         VARCHAR2(50)    NOT NULL,
    REG_DTTM            TIMESTAMP(6)    DEFAULT SYSTIMESTAMP NOT NULL,
    CHG_USER_ID         VARCHAR2(50),
    CHG_DTTM            TIMESTAMP(6),
    CONSTRAINT PK_MT_COLUMN PRIMARY KEY (COLUMN_ID),
    CONSTRAINT UK_MT_COLUMN_01 UNIQUE (TABLE_ID, PHYSICAL_COLUMN_NM)
);
```

---

## 17. 프로젝트 적용 체크리스트

### 17.1 설계 단계 체크리스트

| 점검항목 | 확인 여부 | 비고 |
| --- | :---: | --- |
| 업무영역/엔터티/테이블 간 매핑이 명확한가 | □ | Entity Map 확인 |
| 모든 테이블에 논리명/물리명/유형/PK/보관주기가 정의되었는가 | □ | Table Meta 확인 |
| 모든 컬럼에 도메인, 타입, NULL, 키, 설명이 정의되었는가 | □ | Column Meta 확인 |
| 코드 컬럼이 코드그룹과 연결되어 있는가 | □ | Code Meta 확인 |
| 금액/수량/가격/비율 컬럼의 정밀도가 충분한가 | □ | Data Type Domain 확인 |
| 개인정보 컬럼의 등급, 암호화, 마스킹 기준이 정의되었는가 | □ | Security Meta 확인 |
| 주문/체결/결제/잔고/예수금 간 대사 기준이 정의되었는가 | □ | DQ Rule 확인 |
| 배치 선후행과 재처리 기준이 정의되었는가 | □ | Batch Meta 확인 |
| 인터페이스 전문 필드와 내부 컬럼 매핑이 정의되었는가 | □ | Interface Field Meta 확인 |
| 변경 영향도 분석 대상이 등록되었는가 | □ | Change Management 확인 |

### 17.2 운영 전환 체크리스트

| 점검항목 | 확인 여부 | 비고 |
| --- | :---: | --- |
| 초기 코드 데이터가 승인본 기준으로 적재되었는가 | □ | 코드 배포 로그 확인 |
| 종목/계좌/고객 마스터 초기 적재 대사가 완료되었는가 | □ | 원천-대상 건수 대사 |
| 주문/체결/결제 테스트 시나리오가 통과되었는가 | □ | 정상/정정/취소/거부/부분체결 |
| 신용/파생/채권 업무별 예외 케이스가 검증되었는가 | □ | 담보부족, 마진콜, 이자지급 등 |
| 일마감/월마감 배치가 SLA 내 완료되는가 | □ | 성능 테스트 필요 |
| 장애 재처리 및 롤백 절차가 검증되었는가 | □ | 배치 재수행, 전문 재처리 |
| 개인정보 조회/다운로드 로그가 정상 적재되는가 | □ | 감사로그 확인 |
| 운영자 권한과 승인 절차가 분리되어 있는가 | □ | 권한 매트릭스 확인 |
| 모니터링 알림이 담당자에게 정상 발송되는가 | □ | SMS/메일/메신저 |
| 변경관리 프로세스가 운영 포털에 반영되었는가 | □ | 승인 워크플로우 확인 |

---

## 부록 A. 기간계 META 시스템에서 특히 중요한 설계 원칙

1. **원장성 데이터는 삭제보다 정정/취소/이력 보관을 원칙으로 한다.**  
   주문, 체결, 결제, 잔고, 예수금은 민원·감사·대사 관점에서 원거래 추적이 가능해야 합니다.

2. **마스터, 원장, 잔고, 스케줄, 로그의 성격을 명확히 분리한다.**  
   마스터는 상태의 기준, 원장은 거래의 발생, 잔고는 특정 시점의 결과, 스케줄은 예정, 로그는 행위 기록입니다.

3. **코드값은 프로그램 상수로 흩어지지 않도록 공통코드와 META에서 관리한다.**  
   주문구분, 계좌상태, 상품유형, 결제상태 같은 코드는 채널·기간계·DW가 동일 버전을 사용해야 합니다.

4. **인터페이스 변경은 테이블 변경보다 더 위험할 수 있다.**  
   필드 길이, 순서, 필수 여부가 변경되면 송수신 시스템이 동시에 영향을 받으므로 버전관리와 병행운영이 필요합니다.

5. **배치 재처리 가능성을 설계에 포함한다.**  
   일마감 실패 시 어느 Step부터 재수행할 수 있는지, 기존 결과를 삭제 후 재생성할지, 차분 보정할지 정의해야 합니다.

6. **개인정보 컬럼은 메타 단계에서부터 분류한다.**  
   개발 완료 후 마스킹을 덧붙이는 방식은 누락 위험이 크므로 컬럼 메타에 개인정보 등급, 암호화, 마스킹, 로그 여부를 포함해야 합니다.

7. **데이터 품질 규칙은 운영 배치와 연결되어야 한다.**  
   품질 규칙이 문서에만 있으면 효과가 낮습니다. 검증 SQL, 임계치, 실패 시 배치 중단 여부까지 메타화해야 합니다.

---

## 부록 B. 향후 추가 권장 영역

| 영역 | 추가 필요 내용 |
| --- | --- |
| 해외주식 | 현지시장, 환전, 현지결제일, 보관기관, 소수점거래, 배당세 |
| 금융상품 | 펀드, ELS/DLS, RP, 발행어음, 랩/신탁 상품 원장 |
| 세무 | 양도세, 배당세, 거래세, 금융투자소득세 대응 구조 |
| AML/FDS | 이상거래 탐지, 고객위험평가, 의심거래보고 연계 |
| SOR/ATS | 복수 시장 주문라우팅, 최선집행, 시장별 체결 대사 |
| DW/데이터허브 | 기간계 원장과 분석계 적재 매핑, CDC, 데이터 카탈로그 |
| API | OpenAPI 전문, rate limit, 인증토큰, 고객동의, API 감사로그 |
| 테스트데이터 | 개인정보 비식별 테스트 데이터 생성 기준 |


## 18. v0.5 표준명/컬럼 Rule 적용 체크리스트

| 점검 항목 | 완료 |
| --- | :---: |
| 모든 핵심 테이블에 `STD_TBL_NM`이 부여되었는가? |  |
| `STD_TBL_NM`이 12자리 고정 길이 포맷 `SDDBBBOOTVNN`을 만족하는가? |  |
| 기존 물리명과 표준테이블명 간 매핑이 `PHYS_TBL_NM`, `LEGACY_TBL_NM`으로 관리되는가? |  |
| 테이블명 시스템구분/업무영역/업무객체/처리구분/성격 코드가 코드 메타에 등록되었는가? |  |
| 컬럼 물리명이 표준 Suffix 규칙을 따르는가? |  |
| 컬럼 Suffix와 도메인/데이터타입이 일치하는가? |  |
| `_CD` 컬럼에 코드그룹이 연결되었는가? |  |
| `_YN` 컬럼이 `YN` 도메인과 `Y/N` 유효값을 사용하는가? |  |
| PK 컬럼은 모두 NOT NULL인가? |  |
| 논리 FK가 META에 등록되었는가? |  |
| 운영 테이블에 Audit 컬럼이 포함되었는가? |  |
| 원장/인터페이스/배치 테이블에 원천추적 및 처리추적 컬럼이 포함되었는가? |  |
| 개인정보 컬럼에 PII 등급, 암호화, 마스킹 속성이 등록되었는가? |  |
| 품질 검증 Rule이 필요한 컬럼에 Rule ID가 매핑되었는가? |  |
| 테이블/컬럼 변경 시 영향도 분석 대상이 식별되는가? |  |
| 변경요청, 승인상태, 적용일자, 폐기예정일자가 관리되는가? |  |

---

## 19. v0.5 META 관리 대상 추가 테이블

| 논리테이블명 | 표준테이블명 | 기존/권장 물리명 | 주요키 | 설명 |
| --- | --- | --- | --- | --- |
| 테이블명규칙 | `MMTTNRRLM001` | `MT_TBL_NM_RULE` | `RULE_ID+POS_NO` | 12자리 테이블명 포맷의 위치별 규칙 관리 |
| 테이블명코드 | `MMTTNCCDC001` | `MT_TBL_NM_CODE` | `CODE_GRP_CD+CD` | 시스템구분, 업무영역, 업무객체, 처리구분, 성격 코드 관리 |
| 테이블명검증결과 | `MDQTNRRST001` | `MT_TBL_NM_VALID_RST` | `VALID_ID` | 테이블명 표준 검증 결과 |
| 컬럼명규칙 | `MMTCNRRLM001` | `MT_COL_NM_RULE` | `RULE_ID` | 컬럼명, suffix, 도메인 검증 규칙 관리 |
| 컬럼명검증결과 | `MDQCNRRST001` | `MT_COL_NM_VALID_RST` | `VALID_ID` | 컬럼명 및 도메인 검증 결과 |
| 표준명매핑 | `MMTNMMPM001` | `MT_STD_NAME_MAP` | `MAP_ID` | 표준테이블명, 물리명, 레거시명 매핑 |

