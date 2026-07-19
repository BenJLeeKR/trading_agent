# 증권시스템 DB 물리설계 및 아키텍처 가이드 v0.1

> 본 문서는 `증권_META시스템_메타정보_사전_v0.5`, `증권시스템_테이블명명규칙_v0.2`, `증권시스템_컬럼명명규칙_v0.2`를 바탕으로, 실제 DBMS(Oracle, PostgreSQL 등) 환경에 데이터베이스를 구축하고 운영하기 위한 **물리적 설계(Physical Design), 성능(Tuning), 파티셔닝(Partitioning), 보안(Security)에 대한 종합 가이드라인**입니다.

---

## 작업 이력

| 버전 (Version) | 변경일자 (Date) | 작성자 (Author) | 변경 내용 (Description) | 승인자 (Approver) |
| :---: | :---: | :--- | :--- | :--- |
| v0.1 | 2026-06-21 | 시스템 | DB 물리설계, 오브젝트 명명, 스토리지, 파티셔닝, SQL 튜닝, 권한 가이드 최초 제정 | 데이터아키텍트 |

---

## 목차

- [1. DB 물리 오브젝트 명명 및 설계 규칙](#1-db-물리-오브젝트-명명-및-설계-규칙)
- [2. 스토리지 및 테이블스페이스 할당 규칙](#2-스토리지-및-테이블스페이스-할당-규칙)
- [3. 대용량 데이터 파티셔닝(Partitioning) 정책](#3-대용량-데이터-파티셔닝partitioning-정책)
- [4. 데이터 라이프사이클 관리 (ILM) 및 아카이빙](#4-데이터-라이프사이클-관리-ilm-및-아카이빙)
- [5. 표준 SQL 작성 및 성능 튜닝 가이드](#5-표준-sql-작성-및-성능-튜닝-가이드)
- [6. DB 보안, 권한 및 접근통제 규칙](#6-db-보안-권한-및-접근통제-규칙)

---

## 1. DB 물리 오브젝트 명명 및 설계 규칙

테이블(`STD_TBL_NM`)과 컬럼을 제외한 기타 데이터베이스 물리 오브젝트의 명명 규칙과 설계 제약사항을 정의합니다.

### 1.1 제약조건 (Constraint) 명명 규칙

제약조건은 시스템이 임의로 생성하는 이름(`SYS_C00...`)을 방지하고 명시적으로 이름을 부여해야 합니다. 기준 테이블명은 12자리 표준명(`STD_TBL_NM`)을 사용합니다.

| 제약조건 유형 | Prefix | 명명 규칙 포맷 | 예시 (`CORORDBST001` 기준) |
| --- | --- | --- | --- |
| **Primary Key** | `PK_` | `PK_` + `STD_TBL_NM` | `PK_CORORDBST001` |
| **Foreign Key** | `FK_` | `FK_` + `STD_TBL_NM` + `_` + 순번(2자리) | `FK_CORORDBST001_01` |
| **Unique Key** | `UK_` | `UK_` + `STD_TBL_NM` + `_` + 순번(2자리) | `UK_CORORDBST001_01` |
| **Check** | `CK_` | `CK_` + `STD_TBL_NM` + `_` + 컬럼명 | `CK_CORORDBST001_USE_YN` |

### 1.2 인덱스 (Index) 명명 및 설계 규칙

| 구분 | Prefix | 명명 규칙 포맷 | 예시 |
| --- | --- | --- | --- |
| **일반 인덱스** | `IX_` | `IX_` + `STD_TBL_NM` + `_` + 순번(2자리) | `IX_CORORDBST001_01` |
| **고유 인덱스** | `UX_` | `UK_` 제약조건 생성 시 자동 생성명 사용 권장 | `UK_CORORDBST001_01` |

* **인덱스 설계 제약 (Design Constraints):**
  1. **개수 제한:** 트랜잭션 빈도가 높은 원장성 테이블(주문, 체결 등)은 인덱스 개수를 최대 5개 이하로 제한하여 `INSERT`/`UPDATE` 성능 저하를 방지합니다.
  2. **컬럼 순서:** 결합 인덱스(Composite Index) 생성 시 컬럼 순서는 **① 등치 조건(`=`) ② 분포도(Selectivity)가 좋은 컬럼 ③ 범위 조건(`BETWEEN`, `LIKE`, `>`, `<`)** 순으로 배치합니다.
  3. **FK 인덱스:** Foreign Key로 설정된 컬럼은 테이블 Lock(TM Lock) 경합 방지를 위해 반드시 인덱스를 생성해야 합니다.

### 1.3 뷰(View) 및 기타 오브젝트 명명 규칙

| 오브젝트 | Prefix | 명명 규칙 포맷 | 예시 | 설명 |
| --- | --- | --- | --- | --- |
| **View** | `VW_` | `VW_` + 업무영역(2) + 논리적의미(영문) | `VW_OR_ORD_STATUS` | 복합 조인 뷰 |
| **Sequence** | `SQ_` | `SQ_` + `STD_TBL_NM` + `_` + 컬럼명 | `SQ_LAULOGLGL001_LOG_ID` | 채번용 시퀀스 |
| **Synonym** | `SN_` | `SN_` + `STD_TBL_NM` | `SN_CORORDBST001` | 타 스키마 참조용 |
| **Procedure** | `SP_` | `SP_` + 업무영역(2) + 처리명 | `SP_EX_CALC_FEE` | 스토어드 프로시저 |
| **Function** | `FN_` | `FN_` + 업무영역(2) + 반환값 | `FN_CU_GET_PII_MSK` | 스칼라 함수 |

---

## 2. 스토리지 및 테이블스페이스 할당 규칙

증권 시스템의 방대한 트랜잭션과 데이터 용량을 감당하기 위해 스토리지 영역을 업무와 I/O 특성에 따라 물리적으로 철저히 분리합니다.

### 2.1 테이블스페이스 (Tablespace) 분리 정책

| 테이블스페이스 명칭 | 저장 대상 | 목적 및 특징 |
| --- | --- | --- |
| `TS_DAT_CORE` | 계정계 핵심 원장 데이터 (주문, 체결, 잔고) | 초고속 I/O 보장 (SSD/NVMe 전용 영역) |
| `TS_IDX_CORE` | 핵심 원장 인덱스 | 데이터 파일과 디스크 채널 분리로 경합 최소화 |
| `TS_DAT_META` | 메타 및 공통코드 데이터 | 읽기 위주의 작은 데이터 블록 보관 |
| `TS_DAT_LOB` | `CLOB`, `BLOB` (원문, 대용량 로그) | Row Chaining 방지를 위한 LOB 전용 공간 |
| `TS_DAT_ARCH` | 1년 이상 경과된 과거 파티션 데이터 | 저비용 대용량 스토리지 (SATA/NL-SAS) |

### 2.2 물리 블록(Block) 및 동시성(Concurrency) 파라미터 튜닝

증권사 특유의 장 개시 직후(09:00) 호가 폭증 현상을 견디기 위해, 블록 내 트랜잭션 슬롯 경합(ITL Waits)을 방지하는 파라미터를 강제합니다.

1. **INITRANS 설정:**
   * 일반 마스터 테이블: `INITRANS 2` (Default)
   * **초고도 트랜잭션 테이블 (주문 `CORORDBST001`, 예수금 `CCACSHBLB001` 등):** `INITRANS 10 ~ 20` 할당 필수.
2. **PCTFREE 설정:**
   * UPDATE가 빈번한 테이블 (주문 원장, 예수금 잔고): `PCTFREE 20 ~ 30` (Row Migration 방지)
   * INSERT Only 테이블 (감사로그, 체결내역): `PCTFREE 10` 이하 (공간 효율 극대화)

---

## 3. 대용량 데이터 파티셔닝(Partitioning) 정책

기간계 원장 테이블은 1년만 운영해도 수십억 건에 달하므로 파티셔닝은 선택이 아닌 필수입니다.

### 3.1 파티션 적용 기준
* **정량적 기준:** 월간 데이터 발생량이 1,000만 건 이상이거나, 테이블 용량이 10GB를 초과할 것으로 예상되는 테이블.
* **적용 대상:** 주문원장, 체결내역, 일마감잔고스냅샷, 예수금이력, 감사로그 등.

### 3.2 파티션 방식 및 설계 가이드

| 파티션 방식 | 적용 대상 | 분할 기준 (Partition Key) | 비고 |
| --- | --- | --- | --- |
| **Range Partition** | 시계열 발생 트랜잭션 (주문, 체결, 로그) | `ORD_DT`, `EXEC_DT`, `BAS_DT` | 월 단위(Monthly) 또는 일 단위(Daily) 분할 |
| **List Partition** | 거대 마스터, 특정 범주별 고립 필요 시 | `MKT_DVSN_CD` (국내/해외 구분) | 파생/해외 등 시장별 격리가 필요할 때 사용 |
| **Composite (Range-List)** | 장기 보관 & 다중 국가 거래 내역 | `LOCAL_STL_DT` + `NAT_CD` | 해외결제예정(`CSTFRNSCH001`) 등에 적합 |

### 3.3 파티션 인덱스 (Partitioned Index) 규칙
* **Local Index 원칙:** 파티션 테이블에 생성되는 모든 인덱스는 파티션 키를 포함하는 **Local Index** 생성을 원칙으로 합니다.
* **사유:** Global Index를 사용할 경우, 오래된 파티션을 아카이빙/삭제(`DROP PARTITION`)할 때 전체 인덱스가 `UNUSABLE` 상태가 되어 장애를 유발할 수 있습니다.
* **PK 파티셔닝:** Primary Key 제약조건 역시 파티션 키(`_DT`)를 반드시 포함하여 Local Index화 될 수 있도록 설계합니다. (예: PK가 `ORD_NO` 단일 컬럼이 아닌 `ORD_DT + ORD_NO`로 구성된 이유).

---

## 4. 데이터 라이프사이클 관리 (ILM) 및 아카이빙

보관주기가 '10년 이상'인 데이터라도 모든 데이터를 고비용 고성능 디스크(Online)에 둘 수는 없습니다. 발생 시점에 따라 3단계 (Hot -> Warm -> Cold) ILM(Information Lifecycle Management) 정책을 적용합니다.

### 4.1 보관 단계별 아카이빙 규칙

| 단계 | 데이터 발생 시기 | 저장소 위치 (Tier) | 접근 특성 | 데이터 처리 |
| --- | --- | --- | --- | --- |
| **Online (Hot)** | 현재 ~ 6개월 전 | SSD / TS_DAT_CORE | 실시간 트랜잭션, HTS 조회 | 원본 테이블 파티션 유지 |
| **Nearline (Warm)** | 6개월 ~ 3년 전 | SAS / TS_DAT_ARCH | 영업점 과거내역 조회 (지연허용) | 압축 활성화 (Advanced Compression) |
| **Offline (Cold)** | 3년 전 ~ 10년 | Object Storage / Tape | 금감원/컴플라이언스 감사용 | DW/Data Lake로 이관 후 OLTP 원장에서는 `DROP PARTITION` |

### 4.2 삭제(Purge) 메커니즘
* 논리삭제(`DEL_YN = 'Y'`) 처리된 마스터 데이터나 보관주기가 끝난 로그 파티션은 애플리케이션에서 `DELETE` 문으로 지우지 않습니다.
* DBA가 관리하는 **월 1회 정기 Purge 배치 Job**을 통해 파티션 `DROP` 또는 `TRUNCATE` 방식을 사용하여 시스템 부하(Undo/Redo 발생) 없이 제거합니다.

---

## 5. 표준 SQL 작성 및 성능 튜닝 가이드

개발자가 작성하는 SQL 퀄리티는 DB 서버의 CPU와 메모리(Shared Pool) 상태를 결정합니다. 다음 가이드를 절대적으로 준수해야 합니다.

### 5.1 바인드 변수 (Bind Variable) 사용 의무화
* 1초에 수천 건이 들어오는 호가/주문 처리 로직에서 SQL 리터럴(Literal) 텍스트를 문자열 결합 방식(String Concatenation)으로 사용하면 **Hard Parsing**이 발생하여 DB가 즉시 다운됩니다.
* ❌ **금지:** `SELECT * FROM CORORDBST001 WHERE ORD_NO = '` + orderNo + `'`
* ⭕ **필수:** `SELECT * FROM CORORDBST001 WHERE ORD_NO = :1` (또는 `?`, `#{orderNo}`)

### 5.2 대용량 배치 처리 (Bulk Processing)
* 일마감 결제, 이자 산정 배치 등 대량의 레코드를 `INSERT`, `UPDATE` 할 때는 단건 루프(Cursor For Loop)를 금지합니다.
* 반드시 **Array Processing** (Oracle의 `FORALL`, PostgreSQL의 `executemany`) 또는 `INSERT /*+ APPEND */ INTO ... SELECT` 문을 사용하여 I/O Context Switching을 최소화합니다.

### 5.3 ANSI 표준 조인 (ANSI JOIN) 권장
* 쿼리의 가독성과 이기종 RDBMS(PostgreSQL 등)로의 전환 확장성을 위해 Oracle 종속적인 조인 문법 `(+)`의 신규 작성을 금지합니다.
* 표준 `INNER JOIN`, `LEFT OUTER JOIN` 구문을 명시적으로 사용합니다.

### 5.4 기타 코딩 금지 사항
1. `SELECT *` 금지: 필요한 컬럼(물리명)만 명시하여 네트워크 대역폭과 메모리 낭비를 줄입니다.
2. 묵시적 형변환 금지: `WHERE ORD_DT = 20260621` (숫자 비교)처럼 비교하면 인덱스를 타지 않고 Table Full Scan이 일어납니다. 반드시 동일 타입으로 명시적 캐스팅을 해야 합니다.

---

## 6. DB 보안, 권한 및 접근통제 규칙

DB 내에 개인정보(PII)와 금융거래정보가 존재하므로, 스키마 레벨에서의 강력한 역할 기반 접근 통제(RBAC) 체계를 구성합니다.

### 6.1 스키마(Schema) 분리 원칙
물리적 DB 안에서 소유권자와 사용자를 철저히 분리합니다.
1. **OWNER 스키마 (예: `COR_OWN`)**: 테이블, 인덱스 등 물리 오브젝트를 생성하고 소유합니다. (외부 접속 엄격 차단)
2. **APP 스키마 (예: `COR_APP`)**: 애플리케이션(WAS)이 DB에 연결할 때 사용하는 계정입니다. DDL(생성/삭제) 권한이 없으며, 오직 `SELECT`, `INSERT`, `UPDATE`, `DELETE` 권한만 부여받습니다. Synonym을 통해 OWNER 객체에 접근합니다.
3. **READ ONLY 스키마 (예: `COR_READ`)**: 데이터 추출, 분석가 연계용 계정으로 `SELECT` 권한만 가집니다.

### 6.2 데이터 암호화 (Encryption) 물리 적용
* 메타정보 사전에 명시된 `ENC_YN = 'Y'` 대상 컬럼(주민등록번호, 여권번호, 연락처 등)은 TDE (Transparent Data Encryption) 방식 또는 API 솔루션 방식을 통해 물리 파일에 기록될 때 반드시 암호화되도록 구성합니다.
* 인덱스 제약: 암호화된 컬럼은 범위 검색(`LIKE`, `BETWEEN`)이 불가능해지므로, 물리 설계 시 해당 컬럼을 검색 조건으로 쓰는 SQL이 없도록 아키텍처를 강제해야 합니다.

### 6.3 Audit (감사) 체계
* **시스템 감사:** DBA 계정(SYS, SYSTEM)으로 접속하여 수행되는 모든 DDL 작업과 권한 변경 내역은 데이터베이스 자체 Audit Trail 기능(Oracle Unified Auditing 등)을 통해 OS 파일로 분리 기록되며, 위변조가 불가능하도록 보관해야 합니다.
