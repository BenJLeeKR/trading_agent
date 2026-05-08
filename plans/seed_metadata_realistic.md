# Seed/Metadata 현실화 — broker/account 식별 코드 품질 개선

## 현황 분석

### 문제: 현재 DB에 저장된 seed 데이터가 테스트 흔적을 강하게 드러냄

| 컬럼 | 현재 값 | 문제점 |
|------|---------|--------|
| `broker_account_code` | `ENTR-PAPER-****-ref` | `-ref`는 `account_ref="entrypoint-broker-ref"`의 마지막 4글자. 숫자 계좌번호가 아닌 문자열이라 `-ref`가 보임 |
| `account_code` | `ENTRYPOINT_CLIENT-PAPER-ENTRYPOINTACCOUNT` | `ENTRYPOINTACCOUNT`는 `account_alias="entrypoint-account"`의 첫 단어. 테스트 데이터처럼 보임 |

### 근본 원인

**`scripts/run_orchestrator_once.py`** (line 48-52, 73-78) 의 seed 상수값:

```python
CLIENT_CODE = "ENTRYPOINT_CLIENT"      # 너무 긴 코드
ACCOUNT_ALIAS = "entrypoint-account"    # 테스트용 lowercase alias
# in broker_account:
broker_name="ENTRYPOINT_BROKER"         # broker short-code가 "ENTR" (첫 4글자)
account_ref="entrypoint-broker-ref"     # 숫자가 아닌 string ref
```

**`tests/integration/test_orchestrator_entrypoint.py`** (line 41-43) 에 동일한 상수가 mirror되어 있음.

### 영향받는 파일

| 파일 | 역할 | 변경 필요 |
|------|------|-----------|
| `scripts/run_orchestrator_once.py` | 실제 entrypoint seed (DB data source) | ✅ 상수값 현실화 |
| `tests/integration/test_orchestrator_entrypoint.py` | 테스트 mirror (동일 seed 로직) | ✅ 상수 + assertion 변경 |
| `scripts/backfill_identifier_codes.py` | backfill SQL 규칙 | ✅ 비숫자 `account_ref` fallback 개선 |
| `tests/integration/test_orchestrator_entrypoint.py` (line 71) | `broker_account_code` 값 | ✅ 현실화된 값으로 변경 |
| 기존 test fixture들 | broker_account_code 이미 설정됨 | ❌ 변경 불필요 (test 전용) |

---

## 작업 계획

### Step 1: `scripts/run_orchestrator_once.py` seed 상수 현실화

| 상수 | 현재 | 변경 |
|------|------|------|
| `CLIENT_CODE` | `"ENTRYPOINT_CLIENT"` | `"EPC001"` |
| `ACCOUNT_ALIAS` | `"entrypoint-account"` | `"Entrypoint Paper"` |
| `broker_name` | `"ENTRYPOINT_BROKER"` | `"KoreaInvestment"` |
| `account_ref` | `"entrypoint-broker-ref"` | `"50045678"` |
| `broker_account_code` | (미설정) | `"KIS-PAPER-****5678"` |
| `account_code` | (미설정) | `"EPC001-PAPER-ENTRYPOINT"` |

변경 후 예상되는 broker_account_code 생성 결과:
- `broker_name="KoreaInvestment"` → short code `"KIS"`
- `account_ref="50045678"` → 마지막 4자리 `"5678"`
- → **`"KIS-PAPER-****5678"`**

변경 후 예상되는 account_code 생성 결과 (backfill 실행 시):
- `client_code="EPC001"` + `environment="paper"` + `account_alias` 첫 단어 "Entrypoint"
- → **`"EPC001-PAPER-ENTRYPOINT"`**

**`scripts/run_orchestrator_once.py` 구체 변경사항:**

1. line 48: `CLIENT_CODE = "ENTRYPOINT_CLIENT"` → `"EPC001"`
2. line 49: `ACCOUNT_ALIAS = "entrypoint-account"` → `"Entrypoint Paper"`
3. line 73: `broker_name="ENTRYPOINT_BROKER"` → `"KoreaInvestment"`
4. line 74: `account_ref="entrypoint-broker-ref"` → `"50045678"`
5. line 78: `broker_account_code` 추가 → `"KIS-PAPER-****5678"`
6. line 98-101: `account_code="EPC001-PAPER-ENTRYPOINT"` 추가

### Step 2: `tests/integration/test_orchestrator_entrypoint.py` mirror 동기화

**상수 변경** (line 41-43):
1. `CLIENT_CODE = "ENTRYPOINT_CLIENT"` → `"EPC001"`
2. `ACCOUNT_ALIAS = "entrypoint-account"` → `"Entrypoint Paper"`

**`_seed_if_empty` 함수 변경** (line 63-92):
1. line 65: `broker_name="ENTRYPOINT_BROKER"` → `"KoreaInvestment"`
2. line 66: `account_ref="entrypoint-broker-ref"` → `"50045678"`
3. line 71: `broker_account_code="ENTR-PAPER-****0ref"` → `"KIS-PAPER-****5678"`
4. line 88-92: `account_code="EPC001-PAPER-ENTRYPOINT"` 추가

**`test_entrypoint_readable_via_api` 테스트 assertion 변경** (이 테스트에서 API 응답의 `client_code`와 `account_alias`를 검증할 가능성):
- API 응답에서 `account_alias`가 `"Entrypoint Paper"`로 표시되는지 확인
- broker_account_code가 `"KIS-PAPER-****5678"`인지 확인
- account_code가 `"EPC001-PAPER-ENTRYPOINT"`인지 확인

### Step 3: `scripts/backfill_identifier_codes.py` fallback 개선

**`_BROKER_ACCOUNT_CODE_SQL`** (line 54-68):
현재 비숫자 `account_ref`에 대해 마지막 4글자를 그대로 사용 (`-ref` 등).

변경: 숫자만 추출하여 마지막 4자리를 사용. 숫자가 없으면 `'0000'` fallback.

```sql
-- 변경 전
CASE
    WHEN LENGTH(account_ref) >= 4 THEN RIGHT(account_ref, 4)
    ELSE LPAD(account_ref, 4, '0')
END

-- 변경 후: 숫자만 추출하여 처리
CASE
    WHEN account_ref ~ '\d{4,}'
        THEN RIGHT(REGEXP_REPLACE(account_ref, '[^0-9]', '', 'g'), 4)
    WHEN account_ref ~ '\d'
        THEN LPAD(REGEXP_REPLACE(account_ref, '[^0-9]', '', 'g'), 4, '0')
    ELSE '0000'
END
```

`REGEXP_REPLACE(account_ref, '[^0-9]', '', 'g')`는 `account_ref`에서 숫자가 아닌 문자를 모두 제거합니다. 예:
- `"entrypoint-broker-ref"` → `""` (빈 문자열) → `'0000'`
- `"ACCT-001"` → `"001"` → LPAD → `"0001"`
- `"50045678"` → `"50045678"` → RIGHT → `"5678"`
- `"TEST-ACCT-001"` → `"001"` → LPAD → `"0001"`

**`_ACCOUNT_CODE_SQL`** (line 70-79):
현재 로직은 `account_alias`의 첫 번째 word를 추출합니다. 이 로직은 alias가 자연스러운 이름일 때 잘 동작하므로 큰 변경 불필요.

단, `account_alias`가 여러 단어일 때 첫 단어만 사용하는 것이 적절한지 확인:
- `"Entrypoint Paper"` → `SPLIT_PART(..., ' ', 1)` → `"Entrypoint"` → UPPER → `"ENTRYPOINT"`
- → `"EPC001-PAPER-ENTRYPOINT"` (자연스러움)

### Step 4: 기존 DB row 재-backfill

backfill script은 idempotent (`WHERE broker_account_code IS NULL`)이므로, 
기존 row에 이미 값이 있으면 재실행해도 업데이트되지 않음.

**옵션 A**: 직접 UPDATE SQL 실행 (1 row만 존재)
```sql
-- 기존 broker_account_code 업데이트
UPDATE trading.broker_accounts
SET broker_account_code = 'KIS-PAPER-****5678'
WHERE broker_account_id = '22222222-2222-2222-2222-222222222222';

-- 기존 account_code 업데이트
UPDATE trading.accounts
SET account_code = 'EPC001-PAPER-ENTRYPOINT'
WHERE account_id = '33333333-3333-3333-3333-333333333333';
```

**옵션 B**: backfill script에 `--force` 플래그 추가 → `WHERE` 조건 없이 전체 업데이트

**권장: 옵션 A** (단발성, 명확, 안전)

### Step 5: API 응답 확인

```bash
curl -s http://localhost:8000/accounts?client_id=11111111-1111-1111-1111-111111111111 \
  -H "Authorization: Bearer dev-token-123" | python3 -m json.tool
```

예상 응답:
```json
{
    "broker_account_code": "KIS-PAPER-****5678",
    "account_code": "EPC001-PAPER-ENTRYPOINT",
    "account_alias": "Entrypoint Paper",
    "account_masked": "****0001",
    "account_id": "33333333-..."
}
```

### Step 6: Admin UI 번들 rebuild 및 확인

```bash
cd admin_ui && npm run build
docker compose cp admin_ui/dist/. api:/app/admin_ui/dist/
```

UI에서 기대되는 표시:
- **Account (table column)**: `EPC001-PAPER-ENTRYPOINT` (← account_code)
- **Account # (table column)**: `KIS-PAPER-****5678` (← broker_account_code)
- **Detail panel**: Account Code: `EPC001-PAPER-ENTRYPOINT`, Account #: `KIS-PAPER-****5678`, Alias: `Entrypoint Paper`

### Step 7: Python 테스트 검증

```bash
python -m pytest tests/integration/test_orchestrator_entrypoint.py -v --no-header -x 2>&1
```

`test_entrypoint_readable_via_api` 테스트에서 변경된 상수값과 assertion이 통과하는지 확인.

---

## 최종 상태 요약

### 변경 전 (현재 DB)
```
broker_account_code: ENTR-PAPER-****-ref      ← "ENTR" + "-ref" (테스트 흔적)
account_code:        ENTRYPOINT_CLIENT-PAPER-ENTRYPOINTACCOUNT  ← 너무 긴 코드
account_alias:       entrypoint-account       ← 테스트용 lowercase
```

### 변경 후 (예상)
```
broker_account_code: KIS-PAPER-****5678        ← "KIS" + "5678" (자연스러운 broker code)
account_code:        EPC001-PAPER-ENTRYPOINT   ← 간결한 client code + alias 첫 단어
account_alias:       Entrypoint Paper          ← 자연스러운 alias
```

---

## 영향도 체크리스트

| 항목 | 영향 | 조치 |
|------|------|------|
| `scripts/run_orchestrator_once.py` seed | 직접 변경 | Step 1 |
| `tests/integration/test_orchestrator_entrypoint.py` mirror | mirror 동기화 필요 | Step 2 |
| `scripts/backfill_identifier_codes.py` | 비숫자 fallback 개선 | Step 3 |
| `broker_name="KoreaInvestment"` 변경 | broker submit semantics 영향 없음 (broker adapter는 별도 config) | 확인 완료 |
| `account_alias` 변경 | `SubmitOrderRequest.account_ref` 매칭 영향 없음 (같은 상수 사용) | 확인 완료 |
| UUID PK/FK | 변경 없음 | N/A |
| 기존 test fixtures | broker_account_code 이미 설정됨, 변경 불필요 | 확인 완료 |
| accounts.test.tsx | `"CLIENT1-PAPER-PAPER"` 등은 E2E 테스트 fixture 값. `"ENTRYPOINT_CLIENT-PAPER-ENTRYPOINTACCOUNT"`는 accounts.test.tsx에서 사용 안 함 | 확인 완료 |
