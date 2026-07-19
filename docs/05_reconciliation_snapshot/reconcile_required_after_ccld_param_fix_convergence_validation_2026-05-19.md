# CCLD 파라미터 수정 후 Reconcile Required 수렴 검증 — 2026-05-19

## 1. Baseline (수정 직후)

| 항목 | Count |
|------|-------|
| broker_orders RR | 25 |
| order_requests RR | 25 |

**대표 주문 상태 요약:** 000150/000660/000810 총 15건 모두 `reconcile_required` 유지. broker_status와 order_status 모두 `reconcile_required`로 일치.

## 2. Cycle별 Count 변화

| 시간 (UTC) | 시간 (KST) | broker_orders RR | order_requests RR | 소요시간 | 비고 |
|-----------|-----------|-----------------|-------------------|---------|------|
| 07:14:47 | 16:14:47 | 25 | 25 | - | Baseline (최초 조회) |
| 07:16:18 | 16:16:18 | 25 | 25 | ~1.5분 | 변화 없음 |
| 07:17:49 | 16:17:49 | 25 | 25 | ~3분 | 변화 없음 (최종) |

**post-submit-sync 실행 이력:**
- 16:08:03 — `pre_post_submit_sync` Cycle 1 실행 (27초 소요)
- 16:08:31 — `eod_post_submit_sync` Cycle 1 실행 (27초 소요)
- 이후 post-submit-sync 미실행 (ops-scheduler가 `max_cycles=1`로 각각 1회만 실행)

## 3. 대표 주문 전이 결과

| Symbol | Side | broker_native_order_id | 상태 변화 | 최종 broker_status | 최종 order_status |
|--------|------|----------------------|----------|-------------------|------------------|
| 000150 | buy | 0000018145 | 변화 없음 | reconcile_required | reconcile_required |
| 000150 | buy | 0000019262 | 변화 없음 | reconcile_required | reconcile_required |
| 000150 | buy | 0000023214 | 변화 없음 | reconcile_required | reconcile_required |
| 000150 | buy | 0000024715 | 변화 없음 | reconcile_required | reconcile_required |
| 000150 | sell | 0000008278 | 변화 없음 | reconcile_required | reconcile_required |
| 000150 | sell | 0000009009 | 변화 없음 | reconcile_required | reconcile_required |
| 000150 | sell | 0000009510 | 변화 없음 | reconcile_required | reconcile_required |
| 000150 | sell | 0000010219 | 변화 없음 | reconcile_required | reconcile_required |
| 000660 | buy | 0000025805 | 변화 없음 | reconcile_required | reconcile_required |
| 000660 | sell | 0000011357 | 변화 없음 | reconcile_required | reconcile_required |
| 000810 | buy | 0000018688 | 변화 없음 | reconcile_required | reconcile_required |
| 000810 | buy | 0000020741 | 변화 없음 | reconcile_required | reconcile_required |
| 000810 | buy | 0000026021 | 변화 없음 | reconcile_required | reconcile_required |
| 000810 | sell | 0000011828 | 변화 없음 | reconcile_required | reconcile_required |
| 000810 | sell | 0000012868 | 변화 없음 | reconcile_required | reconcile_required |

**모든 대표 주문: 상태 변화 없음 (0건 해소)**

## 4. Matching 성공/실패 분석

### CCLD API 호출 분석

| 항목 | 값 |
|------|-----|
| output_count (첫 번째 CCLD 호출) | 15 |
| odnos_in_response | `['', '', '', '', '', '', '', '', '', '', '', '', '', '', '']` (15개 모두 빈 문자열) |
| matching SUCCESS | **0건** |
| matching FAILED | **1건** (broker_order_id=0000012868) |
| authoritative transition | **0회** |
| `_sync_reconcile_required_orders` 호출 | **0회** (sync cycle 내 RR 해소 단계 미도달) |

### REST Budget 고갈

```
resolve_unknown_state failed for broker_order=7365c36d-...: [global] Global REST cap exhausted (remaining=0/1)
resolve_unknown_state failed for broker_order=baf8a26b-...: [global] Global REST cap exhausted (remaining=0/1)
resolve_unknown_state failed for broker_order=569b2acb-...: [global] Global REST cap exhausted (remaining=0/1)
resolve_unknown_state failed for broker_order=d9a47f11-...: [global] Global REST cap exhausted (remaining=0/1)
resolve_unknown_state failed for broker_order=455e3a04-...: [global] Global REST cap exhausted (remaining=0/1)
```

총 **5건**의 `resolve_unknown_state`가 REST budget 부족으로 실패.

### sync-cycle 요약

```
sync-cycle  orders=25 (updated=0 filled=0 partial=25)  snapshots=0  errors=0  elapsed=27.15s
```

- 25개 주문 모두 `partial` (미해결)
- `updated=0`, `filled=0` — 단 한 건도 상태 변경 없음

## 5. 잔존 패턴 분류

| 분류 | Count | 설명 |
|------|-------|------|
| A. 아직 cycle 미도달 | 25 | post-submit-sync가 2회 실행되었으나 RR 해소 실패 |
| B. inquiry budget 부족 | 5 | `resolve_unknown_state` 5건 REST cap 소진으로 실패 |
| C. matching 실패 | 1 | `inquire-daily-ccld` 응답의 `ODNO`가 모두 빈 문자열 → matching 불가 |
| D. genuine manual | 0 | `_is_genuine_manual_reconciliation()`까지 도달하지 못함 |

**핵심 원인: `ORD_GNO_BRNO=00000` 하드코딩**

소스 코드 [`rest_client.py:987`](/workspace/agent_trading/src/agent_trading/brokers/koreainvestment/rest_client.py:987)에서 `ORD_GNO_BRNO` 파라미터가 여전히 `"00000"`으로 하드코딩되어 있음:

```python
"ORD_GNO_BRNO": "00000",      # 주문채번지점번호 (KIS 표준 기본값)
```

CCLD API 호출 로그에서도 확인:
```
ORD_GNO_BRNO=00000
```

이로 인해 KIS `inquire-daily-ccld` API가 올바른 주문 데이터를 반환하지 못하고, 모든 `ODNO` 필드가 빈 문자열로 응답. 결과적으로:
1. `matching strategies FAILED` — CCLD 응답에서 broker_order_id 매칭 불가
2. `resolve_unknown_state` 실패 — 올바른 체결 데이터를 얻을 수 없음
3. `_sync_reconcile_required_orders` 미실행 — sync cycle이 RR 해소 단계에 도달하지 못함

## 6. 최종 판정

**재block (수렴 실패)**

CCLD 파라미터 수정이 적용되지 않았거나, 수정 후 재배포되지 않아 `ORD_GNO_BRNO=00000`이 그대로 사용되고 있음. 25건의 RR 주문이 전혀 해소되지 않았으며, post-submit-sync는 2회 실행 후 종료됨.

## 7. Follow-up

1. **CCLD 파라미터 수정 확인 필요:** [`rest_client.py:987`](/workspace/agent_trading/src/agent_trading/brokers/koreainvestment/rest_client.py:987)의 `ORD_GNO_BRNO` 값을 각 broker_order의 `broker_native_order_id`에서 추출한 실제 지점번호로 변경해야 함
2. **재배포 필요:** 수정 후 Docker 컨테이너 재시작하여 변경사항 반영
3. **REST Budget 확인:** `Global REST cap exhausted (remaining=0/1)` — INQUIRY bucket budget이 1로 설정되어 있어 RR 해소에 충분하지 않음. budget 설정 검토 필요
4. **재검증 필요:** 재배포 후 동일한 검증 절차 반복하여 RR count 감소 확인
5. **`_sync_reconcile_required_orders` 로그 누락:** sync cycle 내 RR 해소 단계 로그가 전혀 없음. sync cycle 로직에서 `_sync_reconcile_required_orders`가 호출되는 조건 확인 필요
