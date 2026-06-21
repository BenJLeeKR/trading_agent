# 증권 AI 에이전트 아키텍처 및 프롬프트 파이프라인 설계서 (v1.2)

> 본 문서는 증권사 기간계 핵심 업무의 코딩 자동화를 목표로 작성되었습니다.  
> AI 에이전트가 `12자리 고정 길이 표준테이블명(STD_TBL_NM)`, `LOGIC_TBL_NM`, `PHYS_TBL_NM`, `LEGACY_TBL_NM`, 컬럼 메타, 도메인, PK/FK, 코드, Audit, 개인정보/보안 규칙을 오차 없이 활용하여 무결성 높은 백엔드 코드와 SQL을 생성하도록 설계한 **하이브리드 RAG 및 다중 에이전트 프롬프트 파이프라인(Agentic Workflow) 아키텍처 가이드**입니다.

---

## 작업 이력

| 버전 | 변경일자 | 작성자 | 변경 내용 | 승인자 |
| :---: | :---: | :--- | :--- | :--- |
| v1.1 | 2026-06-21 | 시스템 | 증권 AI 에이전트 RAG 및 프롬프트 파이프라인 설계 | 아키텍처총괄 |
| v1.2 | 2026-06-21 | ChatGPT | META 시스템 v0.5.2 및 명명규칙 v0.2 기준 반영. `STD_TBL_NM`/`PHYS_TBL_NM`/`LOGIC_TBL_NM` 용어 정합화, RAG 스키마 보강, SQL 주석 표준 변경, Reviewer/Linter 검증 Rule 확대 | 데이터설계총괄 |

---

## 목차

- [1. 아키텍처 도입 배경 및 핵심 과제](#1-아키텍처-도입-배경-및-핵심-과제)
- [2. 핵심 용어 및 META 명명규칙 정합성 기준](#2-핵심-용어-및-meta-명명규칙-정합성-기준)
- [3. 하이브리드 RAG 상세 설계 및 데이터 모델](#3-하이브리드-rag-상세-설계-및-데이터-모델)
- [4. Retrieval Algorithm 검색 및 주입 로직](#4-retrieval-algorithm-검색-및-주입-로직)
- [5. 다중 에이전트 프롬프트 파이프라인](#5-다중-에이전트-프롬프트-파이프라인)
- [6. SQL 및 코드 생성 표준](#6-sql-및-코드-생성-표준)
- [7. Reviewer & Linter 검증 기준](#7-reviewer--linter-검증-기준)
- [8. 운영 및 디버깅 가이드](#8-운영-및-디버깅-가이드)
- [9. 프롬프트 템플릿](#9-프롬프트-템플릿)
- [10. CI/CD 및 정적 분석 연계](#10-cicd-및-정적-분석-연계)
- [11. 적용 체크리스트](#11-적용-체크리스트)

---

## 1. 아키텍처 도입 배경 및 핵심 과제

### 1.1 왜 하이브리드 파이프라인인가?

증권 기간계 META 시스템은 데이터 거버넌스를 위해 `CORORDBST001`, `CEXEXCDTT001`, `MMTCOLBSM001` 같은 **12자리 고정 길이 코드형 표준테이블명**을 사용한다. 이 표준명은 시스템적 통제와 영향도 분석에는 유리하지만, LLM에게는 자연어 의미 추론이 어려운 코드형 식별자다.

예를 들어 `CORORDBST001`은 다음 의미를 가진다.

```text
C / OR / ORD / BS / T / 0 / 01
Core / 주문 / 주문 / 기본 / Transaction / v0 / 01
```

사람은 “주문원장”이라고 말하지만, AI가 SQL을 생성할 때는 반드시 `STD_TBL_NM`인 `CORORDBST001`을 사용해야 한다. 따라서 단순 LLM 프롬프트만으로는 다음 위험이 있다.

| 위험 | 설명 |
| --- | --- |
| 테이블명 환각 | 존재하지 않는 12자리 표준명을 임의 생성 |
| Legacy명 혼용 | `TB_ORD_MST` 같은 기존 물리명을 FROM/JOIN에 직접 사용 |
| 컬럼명 환각 | 실제 컬럼 메타에 없는 컬럼을 생성 |
| 조인 오류 | PK/FK 또는 논리 관계와 맞지 않는 조인 생성 |
| PII 노출 | 개인정보 컬럼을 마스킹/권한 확인 없이 SELECT |
| 원장 무결성 훼손 | 주문/체결/결제 원장을 UPDATE/DELETE하는 코드 생성 |

### 1.2 해결 방향

개발자는 업무 자연어로 요청하고, AI 파이프라인은 내부적으로 다음 변환을 수행한다.

```text
사용자 자연어
→ 업무 도메인/논리테이블명 추출
→ META/RAG 기반 STD_TBL_NM 확정
→ 컬럼/PK/FK/도메인/코드/PII/Audit 메타 주입
→ SQL/코드 생성
→ Reviewer/Linter 검증
→ 위반 시 재생성 또는 Halt
```

핵심 원칙은 다음과 같다.

1. AI는 절대로 12자리 표준테이블명을 임의 생성하지 않는다.
2. SQL의 FROM/JOIN 기준명은 RAG가 제공한 `STD_TBL_NM`만 사용한다.
3. 기존 `TB_*`, `MT_*`, `STG_*` 명칭은 `PHYS_TBL_NM` 또는 `LEGACY_TBL_NM`으로만 병기한다.
4. SQL 주석에는 `LOGIC_TBL_NM`과 `PHYS_TBL_NM`을 함께 병기한다.
5. 컬럼은 `STD_TBL_NM + PHYS_COL_NM` 기준으로 존재성을 검증한다.

---

## 2. 핵심 용어 및 META 명명규칙 정합성 기준

### 2.1 테이블명 관련 용어

| 용어 | 의미 | 예시 | AI 사용 기준 |
| --- | --- | --- | --- |
| `STD_TBL_NM` | 12자리 고정 길이 표준테이블명. 공식 테이블 식별자 | `CORORDBST001` | FROM/JOIN에 사용 |
| `LOGIC_TBL_NM` | 업무적으로 이해 가능한 논리테이블명 | 주문원장 | 사용자 입력, 주석, 로그에 사용 |
| `PHYS_TBL_NM` | 실제 DB 물리 테이블명 | `TB_ORD_MST` | 기존 DB 연계 또는 주석에 사용 |
| `LEGACY_TBL_NM` | 기존/구 시스템 테이블명 | `ORD_MST`, `TO1100` | 전환/이행/영향도 분석에 사용 |
| `TBL_NM_RULE_ID` | 테이블명 규칙 ID | `TBLNM12` | 검증 Rule 참조 |

### 2.2 컬럼명 관련 용어

| 용어 | 의미 | 예시 | AI 사용 기준 |
| --- | --- | --- | --- |
| `LOGIC_COL_NM` | 논리컬럼명 | 주문수량 | 자연어 설명/주석 |
| `PHYS_COL_NM` | 물리컬럼명 | `ORD_QTY` | SELECT/WHERE/JOIN/INSERT/UPDATE에 사용 |
| `DOMAIN_ID` | 표준 도메인 | `QTY`, `AMT`, `DATE8` | 타입 및 검증 기준 |
| `CODE_GRP_CD` | 코드그룹 | `ORD_STS_CD` | 코드 유효값 검증 |
| `PII_YN` | 개인정보 여부 | `Y/N` | 마스킹/권한 검증 |
| `PK_YN`, `FK_YN` | 키 여부 | `Y/N` | 조인/조건 생성 기준 |

### 2.3 금지 표현 및 권장 표현

| 금지 또는 지양 표현 | 권장 표현 | 사유 |
| --- | --- | --- |
| 12자리 물리명 | 12자리 표준테이블명 | `STD_TBL_NM`은 공식 표준명이지 항상 실제 DB 물리명은 아님 |
| 암호화 표준명 | 코드형/부호화 표준테이블명 | 보안 암호화가 아니라 위치 기반 코드화 |
| 논리명(`PHYS_TBL_NM`) | 논리명(`LOGIC_TBL_NM`) 또는 물리명(`PHYS_TBL_NM`) | 용어 혼동 방지 |
| 물리명으로 치환 | 표준테이블명으로 변환 | META 규칙과 정합화 |
| `TB_*`를 표준 테이블명으로 사용 | `TB_*`는 `PHYS_TBL_NM` 또는 `LEGACY_TBL_NM`으로만 사용 | 12자리 표준명 체계 준수 |

---

## 3. 하이브리드 RAG 상세 설계 및 데이터 모델

증권 시스템의 복잡한 규칙과 스키마를 에이전트가 정확히 인식하려면 텍스트형 Rule 검색과 정형 메타 검색을 병행해야 한다.

### 3.1 Data Ingestion 전략

| 저장소 | 저장 대상 | 목적 |
| --- | --- | --- |
| Vector Store | 테이블 명명규칙, 컬럼 명명규칙, DB 물리설계 가이드, SQL 작성 가이드, 원장 처리 기준, 개인정보/마스킹 기준 | 의미 기반 Rule 검색 |
| Structured Metadata DB | 테이블 메타, 컬럼 메타, PK/FK, 코드그룹, 도메인, 인터페이스 매핑, 배치 입출력, 품질 Rule | 정확도 기반 매핑 및 검증 |
| Knowledge Graph | 테이블-컬럼, 테이블-테이블 관계, 배치-테이블 관계, 전문필드-컬럼 매핑, 품질Rule-컬럼 관계 | 영향도 분석 및 조인 경로 추론 |
| Runtime Cache | 자주 사용하는 테이블/컬럼/코드 메타 | 코드 생성/로그 병기 성능 개선 |

### 3.2 Structured Metadata Canonical Schema

AI 에이전트에 주입되는 메타는 최소한 아래 구조를 가져야 한다.

```json
{
  "LOGIC_TBL_NM": "주문원장",
  "STD_TBL_NM": "CORORDBST001",
  "PHYS_TBL_NM": "TB_ORD_MST",
  "LEGACY_TBL_NM": "TB_ORD_MST",
  "TBL_KIND_CD": "T",
  "TBL_KIND_NM": "Transaction",
  "BIZ_AREA_CD": "OR",
  "BIZ_AREA_NM": "주문",
  "PRIMARY_KEYS": ["ORD_DT", "ORD_NO"],
  "UNIQUE_KEYS": [],
  "PARTITION_KEYS": ["ORD_DT"],
  "COLUMNS": [
    {
      "LOGIC_COL_NM": "주문일자",
      "PHYS_COL_NM": "ORD_DT",
      "DOMAIN_ID": "DATE8",
      "DATA_TYPE": "CHAR(8)",
      "PK_YN": "Y",
      "FK_YN": "N",
      "NULL_YN": "N",
      "CODE_GRP_CD": null,
      "PII_YN": "N",
      "COL_DESC": "주문 발생 업무일자"
    },
    {
      "LOGIC_COL_NM": "주문번호",
      "PHYS_COL_NM": "ORD_NO",
      "DOMAIN_ID": "ORD_NO",
      "DATA_TYPE": "VARCHAR2(30)",
      "PK_YN": "Y",
      "FK_YN": "N",
      "NULL_YN": "N",
      "CODE_GRP_CD": null,
      "PII_YN": "N",
      "COL_DESC": "주문 식별 번호"
    },
    {
      "LOGIC_COL_NM": "계좌번호",
      "PHYS_COL_NM": "ACNO",
      "DOMAIN_ID": "ACNO",
      "DATA_TYPE": "VARCHAR2(20)",
      "PK_YN": "N",
      "FK_YN": "Y",
      "NULL_YN": "N",
      "CODE_GRP_CD": null,
      "PII_YN": "Y",
      "MSK_YN": "Y",
      "COL_DESC": "주문 계좌번호"
    }
  ],
  "RELATIONS": [
    {
      "REL_TP_CD": "FK",
      "FROM_STD_TBL_NM": "CORORDBST001",
      "FROM_COLS": ["ORD_DT", "ORD_NO"],
      "TO_STD_TBL_NM": "CEXEXCDTT001",
      "TO_COLS": ["ORD_DT", "ORD_NO"],
      "REL_DESC": "주문원장과 체결내역의 원주문 관계"
    }
  ],
  "QUALITY_RULES": [
    {
      "RULE_ID": "DQ-ORD-001",
      "RULE_DESC": "주문수량은 0보다 커야 한다.",
      "TARGET_COLS": ["ORD_QTY"]
    }
  ]
}
```

### 3.3 RAG 저장소별 역할 분리

| 요청 유형 | 우선 저장소 | 설명 |
| --- | --- | --- |
| “주문원장 컬럼 알려줘” | Structured Metadata DB | 정확한 테이블/컬럼 메타 필요 |
| “주문 체결 조인 SQL 작성” | Structured Metadata DB + Knowledge Graph | 테이블 매핑, PK/FK, 조인 관계 필요 |
| “원장 UPDATE 해도 돼?” | Vector Store + Rule DB | 업무 Rule, 원장 불변성 기준 필요 |
| “개인정보 컬럼 SELECT 가능?” | Structured Metadata DB + Security Rule | PII/마스킹/권한 메타 필요 |
| “이 컬럼 변경 영향도 알려줘” | Knowledge Graph | API/전문/배치/품질Rule 연계 필요 |

---

## 4. Retrieval Algorithm 검색 및 주입 로직

### 4.1 기본 검색 흐름

사용자의 프롬프트가 입력되면 두 갈래 검색이 병렬 실행된다.

| 경로 | 역할 | 산출물 |
| --- | --- | --- |
| 경로 A: Semantic Rule Search | 자연어에서 개발/업무 규칙을 검색 | SQL 작성 Rule, 원장 처리 Rule, 개인정보 Rule |
| 경로 B: Structured Metadata Search | 논리명/동의어/업무영역을 기준으로 테이블·컬럼 메타 검색 | `STD_TBL_NM`, 컬럼, PK/FK, 코드, 도메인 |
| 경로 C: Knowledge Graph Traversal | 조인 후보, 배치 입출력, 전문 매핑, 영향도 관계 검색 | 조인 경로, 영향도 그래프 |

### 4.2 논리명 Exact Match만으로는 부족한 이유

사용자는 논리테이블명을 정확히 말하지 않을 수 있다.

| 사용자 표현 | 후보 논리테이블명 |
| --- | --- |
| 주문 테이블 | 주문원장 |
| 원주문 | 주문원장 |
| 체결 테이블 | 체결내역 |
| 주식잔고 | 종목잔고 |
| 현금잔고 | 예수금잔고 |
| 결제내역 | 결제예정, 결제완료 |
| 고객정보 | 고객기본, 고객KYC, 고객주소연락처 |

따라서 Retrieval은 다음 순서로 수행한다.

1. 업무 도메인 추출
2. 테이블 논리명 후보 검색
3. 동의어/별칭/업무객체 코드 검색
4. Structured DB에서 `STD_TBL_NM` 후보 조회
5. 요청 컬럼/조건/조인 목적과 후보 테이블의 컬럼 존재성 비교
6. 후보가 1개이면 확정
7. 후보가 2개 이상이고 의미 차이가 크면 clarification 또는 Halt
8. 확정된 메타만 Code Generator에 전달

### 4.3 매핑 실패 기준

아래 경우에는 AI가 임의 추론하지 않고 중단한다.

| 상황 | 처리 |
| --- | --- |
| 논리명 후보 없음 | Halt |
| `STD_TBL_NM` 매핑 없음 | Halt |
| 동일 논리명 후보가 2개 이상 | Clarification 또는 Halt |
| 요청 컬럼이 후보 테이블에 없음 | Halt 또는 대체 컬럼 후보 제시 |
| 조인 관계가 META에 없음 | 임의 조인 금지, 관계 후보 제시 |
| PII 컬럼인데 권한/마스킹 정보 없음 | Halt |
| 코드값 유효성 확인 불가 | 코드그룹 후보 제시 후 Halt |

---

## 5. 다중 에이전트 프롬프트 파이프라인

### Step 1: 의도 추출 에이전트 — Intent Analyzer

| 항목 | 내용 |
| --- | --- |
| 역할 | 개발자의 요구사항에서 업무 도메인, 논리테이블명 후보, 조건 컬럼, 출력 컬럼, 처리 유형을 추출 |
| 입력 | 자연어 개발 요청 |
| 출력 | 구조화된 Intent JSON |
| 금지 | 12자리 표준명 임의 생성 |

예시 입력:

```text
알테오젠 당일 매수 체결된 내역과 원주문 상태를 조인해서 가져오는 쿼리 짜줘.
```

예시 출력:

```json
{
  "intent_type": "SELECT_SQL",
  "biz_domains": ["주문", "체결"],
  "logical_table_candidates": ["체결내역", "주문원장"],
  "conditions": [
    {"logical_col_nm": "종목명", "operator": "=", "value_type": "bind"},
    {"logical_col_nm": "매매구분", "operator": "=", "value_type": "bind"},
    {"logical_col_nm": "체결일자", "operator": "=", "value_type": "bind"}
  ],
  "requested_outputs": ["체결일자", "체결번호", "주문번호", "체결수량", "체결단가", "주문상태코드"]
}
```

### Step 2: 메타 번역 에이전트 — Meta Translator

| 항목 | 내용 |
| --- | --- |
| 역할 | 논리 엔터티와 요청 컬럼을 RAG/Structured DB에 질의하여 `STD_TBL_NM`, 컬럼, PK/FK, 코드, 도메인 메타 확보 |
| 입력 | Intent JSON |
| 출력 | Meta Context JSON |
| 금지 | 매핑되지 않은 표준테이블명 또는 컬럼명 생성 |

시스템 프롬프트 핵심 지시:

```text
당신은 증권 META 시스템 관리자입니다.
논리테이블명과 논리컬럼명을 RAG Knowledge Base에서 검색하여
반드시 존재하는 STD_TBL_NM과 PHYS_COL_NM만 반환하십시오.

매핑되는 테이블 또는 컬럼이 없다면 절대로 임의 생성하지 말고
Halt 상태와 사유를 반환하십시오.
```

### Step 3: 코드 생성 에이전트 — Code Generator

| 항목 | 내용 |
| --- | --- |
| 역할 | 확정된 Meta Context와 개발 Rule을 바탕으로 SQL/백엔드 코드 생성 |
| 입력 | Meta Context JSON, Rule Context |
| 출력 | SQL, Repository/Mapper/Service 코드 |
| 금지 | Legacy 테이블명을 FROM/JOIN에 직접 사용, 리터럴 직접 삽입, 존재하지 않는 컬럼 생성 |

절대 규칙:

1. FROM/JOIN에는 RAG가 제공한 `STD_TBL_NM`만 사용한다.
2. 테이블 Alias 선언 직후 `LOGIC_TBL_NM`과 `PHYS_TBL_NM`을 주석으로 병기한다.
3. SELECT/WHERE/JOIN에는 해당 `STD_TBL_NM`의 컬럼 메타에 존재하는 `PHYS_COL_NM`만 사용한다.
4. 조건값은 반드시 바인드 변수로 처리한다.
5. 조인은 META의 PK/FK 또는 논리 관계를 우선 사용한다.
6. PII 컬럼은 권한/마스킹 Rule 없이 직접 SELECT하지 않는다.
7. 원장성 테이블에 대한 UPDATE/DELETE는 명시 승인 Rule 없이는 생성하지 않는다.

### Step 4: 품질 검증 에이전트 — Reviewer & Linter

| 항목 | 내용 |
| --- | --- |
| 역할 | 생성된 코드가 META 표준, DB 설계 Rule, 보안 Rule, 원장 처리 Rule을 위반하지 않았는지 검증 |
| 입력 | 생성 코드, Meta Context, Rule Context |
| 출력 | PASS/FAIL, 위반 Rule, 수정 지시 |
| 실패 시 | Step 3으로 Refine 요청 또는 Halt |

### Step 5: 설명 생성 에이전트 — Explanation Generator

운영자와 개발자가 생성 SQL의 의미를 이해할 수 있도록 설명을 생성한다.

| 설명 항목 | 예시 |
| --- | --- |
| 사용 테이블 | `CORORDBST001` = 주문원장, `CEXEXCDTT001` = 체결내역 |
| 조인 기준 | `ORD_DT + ORD_NO` |
| 바인드 변수 | `:ORD_DT`, `:ISU_CD`, `:BUY_SELL_DVSN_CD` |
| PII 처리 | 계좌번호는 마스킹 또는 권한 필요 |
| 주의사항 | 원장성 테이블이므로 조회 전용 SQL |

---

## 6. SQL 및 코드 생성 표준

### 6.1 SQL 테이블명 사용 기준

| 위치 | 사용 기준 |
| --- | --- |
| FROM | `STD_TBL_NM` |
| JOIN | `STD_TBL_NM` |
| 주석 | `LOGIC_TBL_NM`, `PHYS_TBL_NM` 병기 |
| SELECT 컬럼 | `PHYS_COL_NM` |
| WHERE 컬럼 | `PHYS_COL_NM` |
| 바인드 변수 | 업무 의미 기반 이름 사용. 예: `:ORD_DT`, `:ISU_CD` |
| Legacy명 | FROM/JOIN 직접 사용 금지. 주석 또는 로그 병기만 허용 |

### 6.2 권장 SQL 예시

```sql
SELECT
    E.EXEC_DT,
    E.EXEC_NO,
    E.ORD_DT,
    E.ORD_NO,
    E.ISU_CD,
    E.EXEC_QTY,
    E.EXEC_UPRC,
    O.ORD_STS_CD
FROM CEXEXCDTT001 E /* LOGIC_TBL_NM: 체결내역, PHYS_TBL_NM: TB_EXEC_DTL */
JOIN CORORDBST001 O /* LOGIC_TBL_NM: 주문원장, PHYS_TBL_NM: TB_ORD_MST */
  ON O.ORD_DT = E.ORD_DT
 AND O.ORD_NO = E.ORD_NO
WHERE E.EXEC_DT = :EXEC_DT
  AND E.ISU_CD = :ISU_CD
  AND E.BUY_SELL_DVSN_CD = :BUY_SELL_DVSN_CD;
```

### 6.3 금지 SQL 예시

```sql
-- 금지: Legacy 물리명을 FROM/JOIN에 직접 사용
SELECT *
FROM TB_ORD_MST O
JOIN TB_EXEC_DTL E
  ON O.ORD_NO = E.ORD_NO;
```

```sql
-- 금지: RAG에 없는 12자리 테이블명을 임의 생성
SELECT *
FROM CORORDMST001;
```

```sql
-- 금지: 리터럴 직접 사용
SELECT *
FROM CORORDBST001
WHERE ISU_CD = '196170';
```

```sql
-- 금지: 원장성 테이블 직접 DELETE
DELETE FROM CORORDBST001
WHERE ORD_DT = :ORD_DT;
```

---

## 7. Reviewer & Linter 검증 기준

### 7.1 테이블명 검증

| Rule ID | 검증내용 | 실패 처리 |
| --- | --- | --- |
| `AI-TBL-001` | FROM/JOIN의 테이블명이 `^[A-Z0-9]{12}$` 형식인지 확인 | FAIL |
| `AI-TBL-002` | FROM/JOIN의 `STD_TBL_NM`이 META에 존재하는지 확인 | FAIL |
| `AI-TBL-003` | `TB_*`, `MT_*`, `STG_*`가 FROM/JOIN에 직접 사용되었는지 확인 | FAIL |
| `AI-TBL-004` | SQL 주석에 `LOGIC_TBL_NM`, `PHYS_TBL_NM`이 병기되었는지 확인 | WARN 또는 FAIL |
| `AI-TBL-005` | Alias가 중복되거나 의미 없이 부여되었는지 확인 | WARN |

### 7.2 컬럼 검증

| Rule ID | 검증내용 | 실패 처리 |
| --- | --- | --- |
| `AI-COL-001` | SELECT/WHERE/JOIN 컬럼이 해당 `STD_TBL_NM`의 컬럼 메타에 존재하는지 확인 | FAIL |
| `AI-COL-002` | 컬럼 Suffix와 도메인이 일치하는지 확인 | FAIL |
| `AI-COL-003` | `_CD` 컬럼 조건값이 코드그룹에 존재하는지 확인 | WARN 또는 FAIL |
| `AI-COL-004` | `_DT`, `_DTTM` 컬럼 조건 형식이 도메인 기준과 맞는지 확인 | FAIL |
| `AI-COL-005` | 금액/수량/율 컬럼 계산 시 precision/scale 손실 가능성 확인 | WARN |

### 7.3 조인 검증

| Rule ID | 검증내용 | 실패 처리 |
| --- | --- | --- |
| `AI-JOIN-001` | ANSI JOIN 사용 여부 확인 | FAIL |
| `AI-JOIN-002` | 조인 컬럼이 PK/FK 또는 META 논리 관계에 존재하는지 확인 | FAIL |
| `AI-JOIN-003` | 조인 누락으로 카테시안 곱이 발생하는지 확인 | FAIL |
| `AI-JOIN-004` | 동일 업무일자 기준 조인 누락 여부 확인. 예: `ORD_DT`, `EXEC_DT`, `BAS_DT` | WARN 또는 FAIL |

### 7.4 보안/개인정보 검증

| Rule ID | 검증내용 | 실패 처리 |
| --- | --- | --- |
| `AI-SEC-001` | PII 컬럼 SELECT 여부 확인 | WARN |
| `AI-SEC-002` | PII 컬럼에 마스킹 Rule 적용 여부 확인 | FAIL |
| `AI-SEC-003` | 계좌번호, 고객번호 등 금융거래정보 조회 시 권한 조건 존재 여부 확인 | FAIL |
| `AI-SEC-004` | 로그에 개인정보 원문 출력 여부 확인 | FAIL |

### 7.5 원장/거래 무결성 검증

| Rule ID | 검증내용 | 실패 처리 |
| --- | --- | --- |
| `AI-LEDGER-001` | 주문/체결/결제/입출금 원장 직접 UPDATE 여부 | FAIL |
| `AI-LEDGER-002` | 주문/체결/결제/입출금 원장 직접 DELETE 여부 | FAIL |
| `AI-LEDGER-003` | 상태 변경 시 이력 테이블 또는 Audit 처리 여부 | FAIL |
| `AI-LEDGER-004` | 보정 처리 시 `ADJ_YN`, `ADJ_RSN_CD`, `ADJ_USER_ID`, `ADJ_DTTM` 관리 여부 | FAIL |

### 7.6 바인드 변수 및 SQL 안전성 검증

| Rule ID | 검증내용 | 실패 처리 |
| --- | --- | --- |
| `AI-SQL-001` | WHERE 조건값에 리터럴 직접 사용 여부 | FAIL |
| `AI-SQL-002` | LIKE 조건에 사용자 입력 직접 연결 여부 | FAIL |
| `AI-SQL-003` | 동적 SQL 생성 시 화이트리스트 기반 컬럼/정렬 조건 사용 여부 | FAIL |
| `AI-SQL-004` | SELECT `*` 사용 여부 | WARN 또는 FAIL |
| `AI-SQL-005` | 대량 조회 SQL에 페이징 또는 기간 조건 존재 여부 | WARN 또는 FAIL |

---

## 8. 운영 및 디버깅 가이드

### 8.1 에러 로깅 표준

AI가 생성하는 백엔드 애플리케이션의 에러 핸들러는 테이블 식별자를 다음 세 가지로 함께 남겨야 한다.

```text
STD_TBL_NM=CORORDBST001
LOGIC_TBL_NM=주문원장
PHYS_TBL_NM=TB_ORD_MST
```

권장 로그 예시:

```text
SQL_ERROR table=CORORDBST001 logic=주문원장 phys=TB_ORD_MST column=ORD_STS_CD message=invalid identifier
```

### 8.2 로그 금지 사항

| 금지 항목 | 설명 |
| --- | --- |
| 개인정보 원문 출력 | 고객명, 주민번호, 전화번호, 계좌번호 원문 출력 금지 |
| 바인드 변수 값 전체 출력 | 운영 로그에는 민감 파라미터 마스킹 필요 |
| `STD_TBL_NM`만 단독 출력 | 운영자 가독성 저하 |
| Legacy명만 출력 | 표준명 기반 추적성 저하 |

### 8.3 런타임 캐시

운영 로그와 예외 메시지 가독성을 위해 애플리케이션은 아래 캐시를 사용할 수 있다.

| 캐시 | Key | Value |
| --- | --- | --- |
| 테이블명 캐시 | `STD_TBL_NM` | `LOGIC_TBL_NM`, `PHYS_TBL_NM`, `TBL_KIND_CD` |
| 컬럼명 캐시 | `STD_TBL_NM + PHYS_COL_NM` | `LOGIC_COL_NM`, `DOMAIN_ID`, `PII_YN` |
| 코드 캐시 | `CODE_GRP_CD + CD` | `CD_NM`, `USE_YN`, `VALID_STRT_DT`, `VALID_END_DT` |

---

## 9. 프롬프트 템플릿

### 9.1 Intent Analyzer 시스템 프롬프트

```text
당신은 증권 업무 분석가입니다.
사용자의 개발 요청에서 업무 도메인, 논리테이블명 후보, 논리컬럼명 후보, 조회/변경/등록/삭제 의도를 추출하십시오.

절대 12자리 STD_TBL_NM을 임의 생성하지 마십시오.
불확실한 테이블명은 candidates 배열에 넣고 confidence를 낮게 표시하십시오.
출력은 JSON으로만 반환하십시오.
```

### 9.2 Meta Translator 시스템 프롬프트

```text
당신은 증권 META 시스템 관리자입니다.

입력된 논리테이블명 후보와 논리컬럼명 후보를 기준으로
Structured Metadata DB와 Knowledge Graph를 조회하십시오.

반환 가능한 항목은 META에 존재하는 다음 항목으로 제한됩니다.
- STD_TBL_NM
- LOGIC_TBL_NM
- PHYS_TBL_NM
- LEGACY_TBL_NM
- PRIMARY_KEYS
- COLUMNS.PHYS_COL_NM
- COLUMNS.DOMAIN_ID
- COLUMNS.DATA_TYPE
- COLUMNS.PK_YN
- COLUMNS.FK_YN
- COLUMNS.NULL_YN
- COLUMNS.CODE_GRP_CD
- COLUMNS.PII_YN
- RELATIONS

매핑되는 테이블 또는 컬럼이 없다면 절대로 임의 생성하지 말고 Halt를 반환하십시오.
```

### 9.3 Code Generator 시스템 프롬프트

```text
당신은 증권 기간계 수석 백엔드 개발자입니다.

다음 절대 규칙을 준수하십시오.

1. FROM/JOIN에는 RAG에서 제공한 STD_TBL_NM만 사용하십시오.
2. TB_*, MT_*, STG_* 등 Legacy/물리명은 FROM/JOIN에 직접 사용하지 마십시오.
3. 테이블 Alias 선언 직후 다음 형식의 주석을 병기하십시오.
   /* LOGIC_TBL_NM: 주문원장, PHYS_TBL_NM: TB_ORD_MST */
4. SELECT/WHERE/JOIN에는 해당 STD_TBL_NM의 컬럼 메타에 존재하는 PHYS_COL_NM만 사용하십시오.
5. 조건값은 리터럴이 아니라 바인드 변수로 작성하십시오.
6. 조인은 META의 PK/FK 또는 논리 관계를 기준으로 작성하십시오.
7. PII_YN=Y인 컬럼은 마스킹 또는 권한 Rule 없이는 직접 조회하지 마십시오.
8. 주문/체결/결제/입출금 등 원장성 테이블은 명시 승인 없이 UPDATE/DELETE하지 마십시오.
```

### 9.4 Reviewer 시스템 프롬프트

```text
당신은 증권 시스템 코드 Reviewer이자 META Linter입니다.

생성된 SQL/코드가 다음 규칙을 준수하는지 검증하십시오.

- FROM/JOIN 테이블명이 META에 존재하는 STD_TBL_NM인가?
- Legacy 물리명이 FROM/JOIN에 직접 사용되지 않았는가?
- 모든 컬럼이 해당 STD_TBL_NM의 컬럼 메타에 존재하는가?
- 조인 조건이 PK/FK 또는 META 관계에 부합하는가?
- 리터럴이 아니라 바인드 변수를 사용했는가?
- PII 컬럼에 마스킹/권한 Rule이 적용되었는가?
- 원장성 테이블에 대한 UPDATE/DELETE가 없는가?
- SQL 주석에 LOGIC_TBL_NM과 PHYS_TBL_NM이 병기되었는가?

위반 사항이 있으면 PASS하지 말고 FAIL과 수정 지시를 반환하십시오.
```

---

## 10. CI/CD 및 정적 분석 연계

### 10.1 정적 분석 항목

| 항목 | 검증 방식 |
| --- | --- |
| 12자리 표준명 형식 | SQL AST 또는 정규식으로 FROM/JOIN 대상 검출 |
| META 존재성 | 검출된 `STD_TBL_NM`을 META DB에 조회 |
| Legacy 직접 사용 | `FROM TB_`, `JOIN TB_`, `FROM MT_`, `JOIN MT_` 패턴 차단 |
| 컬럼 존재성 | `STD_TBL_NM + PHYS_COL_NM`을 META DB에 조회 |
| SQL 주석 | Alias 인근에 `LOGIC_TBL_NM`, `PHYS_TBL_NM` 포함 여부 확인 |
| 바인드 변수 | WHERE 조건 리터럴 패턴 차단 |
| PII | PII 컬럼 조회 시 마스킹 함수 또는 권한 조건 확인 |
| 원장 변경 | 원장성 테이블 대상 UPDATE/DELETE 차단 |

### 10.2 빌드 반려 기준

| 기준 | 처리 |
| --- | --- |
| 존재하지 않는 `STD_TBL_NM` | Build Fail |
| 존재하지 않는 컬럼 사용 | Build Fail |
| Legacy 테이블명 직접 사용 | Build Fail |
| PII 컬럼 무마스킹 조회 | Build Fail |
| 원장성 테이블 직접 DELETE | Build Fail |
| 바인드 변수 미사용 | Build Fail |
| SQL 주석 누락 | Warning 또는 Fail. 운영 정책에 따라 결정 |

---

## 11. 적용 체크리스트

| 점검 항목 | 완료 |
| --- | :---: |
| `STD_TBL_NM`을 표준테이블명으로 정의했는가? |  |
| `STD_TBL_NM`, `LOGIC_TBL_NM`, `PHYS_TBL_NM`, `LEGACY_TBL_NM`을 구분했는가? |  |
| AI가 12자리 표준명을 임의 생성하지 못하도록 Halt Rule을 정의했는가? |  |
| RAG 스키마에 컬럼 메타, 도메인, PK/FK, 코드, PII 속성을 포함했는가? |  |
| SQL FROM/JOIN에는 `STD_TBL_NM`만 사용하도록 했는가? |  |
| SQL 주석에 `LOGIC_TBL_NM`과 `PHYS_TBL_NM`을 함께 병기하도록 했는가? |  |
| 컬럼 존재성을 `STD_TBL_NM + PHYS_COL_NM` 기준으로 검증하는가? |  |
| 조인 조건을 PK/FK 또는 META 관계 기준으로 검증하는가? |  |
| PII 컬럼 조회 시 마스킹/권한 Rule을 검증하는가? |  |
| 원장성 테이블 직접 UPDATE/DELETE를 차단하는가? |  |
| 리터럴 직접 사용을 차단하고 바인드 변수를 강제하는가? |  |
| 운영 로그에 `STD_TBL_NM`, `LOGIC_TBL_NM`, `PHYS_TBL_NM`을 함께 남기는가? |  |
| CI/CD 정적 분석에서 META 존재성 검증을 수행하는가? |  |

---

## 부록 A. v1.1 대비 v1.2 주요 변경 요약

| 구분 | v1.1 | v1.2 |
| --- | --- | --- |
| `STD_TBL_NM` 표현 | 12자리 물리명으로 표현 | 12자리 표준테이블명으로 정정 |
| 표준명 성격 | 암호화 표준명 표현 | 코드형/부호화 표준테이블명으로 정정 |
| SQL 주석 | `/* TB_ORD_MST */` | `/* LOGIC_TBL_NM: 주문원장, PHYS_TBL_NM: TB_ORD_MST */` |
| RAG JSON | logical_name, phys_tbl_nm, std_tbl_nm 중심 | `LOGIC_TBL_NM`, `STD_TBL_NM`, `PHYS_TBL_NM`, `LEGACY_TBL_NM`, 컬럼 메타 속성 포함 |
| Retrieval | 논리명 Exact Match 중심 | 논리명, 동의어, 업무영역, 컬럼 존재성 기반 후보 확정 |
| Linter | 테이블명 형식, 바인드 변수, ANSI JOIN 중심 | 테이블 존재성, 컬럼 존재성, PK/FK, 코드, PII, Audit, 원장 무결성까지 확대 |
| 운영 로그 | 표준명 + 기존명 병기 | `STD_TBL_NM`, `LOGIC_TBL_NM`, `PHYS_TBL_NM` 동시 출력 |

