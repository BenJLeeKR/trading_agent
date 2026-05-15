#!/usr/bin/env python3
"""
장후 cash balance 조회 테스트 스크립트 (read-only)
===================================================
목적: KIS paper API inquire-balance 호출 시 cash snapshot(output2)이
      장중 이후 끊기는 현상이 API 본질적 제약인지, 파라미터 문제인지 규명.

실행: cd /workspace/agent_trading && TZ=Asia/Seoul python3 _test_cash_balance.py
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

# python-dotenv 로드 (프로젝트 .env 파일)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_trading.config.settings import AppSettings
from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.brokers.rate_limit import BucketType


async def test_cash_balance() -> None:
    settings = AppSettings()

    now_kst = datetime.now(timezone.utc).astimezone()
    print("=" * 60)
    print(f"[시간] 기준시각 (KST)       = {now_kst.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[설정] KIS_ENV              = {settings.kis_env}")
    print(f"[설정] 계좌번호             = {settings.kis_account_number}")
    print(f"[설정] 상품코드             = {settings.kis_account_product_code}")
    print(f"[설정] Base URL             = {settings.kis_base_url or '(default paper)'}")
    print(f"[설정] Token Cache Enabled  = {settings.kis_dev_token_cache_enabled}")
    print("=" * 60)

    if not settings.kis_account_number:
        print("\n⚠️  계좌번호가 비어 있습니다. .env 파일 로드 확인 필요.")
        sys.exit(1)

    # ---- KISRestClient 직접 인스턴스화 (budget_manager=None → rate limit bypass) ----
    # NOTE: budget_manager가 없으면 token bucket 소비가 없지만,
    #       KIS 서버 자체 rate limit(paper 1 RPS)은 존재하므로
    #       수동으로 sleep을 삽입한다.
    client = KISRestClient(
        api_key=settings.kis_api_key,
        api_secret=settings.kis_api_secret,
        account_number=settings.kis_account_number,
        account_product_code=settings.kis_account_product_code,
        env=settings.kis_env,
        base_url=settings.kis_base_url,
        budget_manager=None,
        dev_token_cache_enabled=settings.kis_dev_token_cache_enabled,
        dev_token_cache_path=settings.kis_dev_token_cache_path,
    )

    # 공통 파라미터 베이스
    _base_params: dict[str, str] = {
        "CANO": settings.kis_account_number,
        "ACNT_PRDT_CD": settings.kis_account_product_code,
        "OFL_YN": "",
        "UNPR_DVSN": "01",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "COST_ICLD_YN": "N",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
    }

    try:
        # ==================================================================
        # 1. 현재 get_cash_balance() 호출 (조합 A)
        # ==================================================================
        print("\n" + "=" * 60)
        print(">>> [조합 A] 현재 get_cash_balance() — 기본 파라미터")
        print("    AFHR_FLPR_YN=N, INQR_DVSN=01, PRCS_DVSN=01, FUND_STTL_ICLD_YN=N")
        print("=" * 60)

        cash_result = await client.get_cash_balance()
        print(f"\n[get_cash_balance() 반환값 — output2 예수금총괄]")
        if isinstance(cash_result, dict):
            print(f"  type  : {type(cash_result).__name__}")
            print(f"  keys ({len(cash_result)}개): {list(cash_result.keys())}")
            print(f"  dnca_tot_amt (예수금총액)  : {cash_result.get('dnca_tot_amt', 'N/A')}")
            print(f"  nxdy_excc_amt (익일예수금)  : {cash_result.get('nxdy_excc_amt', 'N/A')}")
            print(f"  prvs_rcdl_excc_amt (전일이월): {cash_result.get('prvs_rcdl_excc_amt', 'N/A')}")
            print(f"  tot_evlu_amt (총평가금액)   : {cash_result.get('tot_evlu_amt', 'N/A')}")
            print(f"  nass_amt (순자산금액)      : {cash_result.get('nass_amt', 'N/A')}")
            print(f"\n  전문: {json.dumps(cash_result, indent=2, ensure_ascii=False)}")

        # ==================================================================
        # 2. get_positions() 호출 (비교)
        # ==================================================================
        await asyncio.sleep(2.0)
        print("\n" + "=" * 60)
        print(">>> [비교] get_positions() — 동일 endpoint, output1→output 추출")
        print("=" * 60)

        pos_result = await client.get_positions()
        print(f"\n[get_positions() 반환값 — output1/output 종목별잔고]")
        print(f"  count : {len(pos_result) if isinstance(pos_result, list) else 'not list'}")
        if pos_result and isinstance(pos_result, list):
            for i, p in enumerate(pos_result):
                print(f"  [{i}] pdno={p.get('pdno','')} qty={p.get('hldg_qty','')} "
                      f"evlu={p.get('evlu_amt','')} pfls={p.get('evlu_pfls_amt','')}")
            print(f"\n  상세(첫번째): {json.dumps(pos_result[0], indent=2, ensure_ascii=False)}")

        # ==================================================================
        # 3. 조합 B: 전체조회 (INQR_DVSN=00, PRCS_DVSN=00, FUND_STTL_ICLD_YN=Y)
        # ==================================================================
        await asyncio.sleep(2.0)
        print("\n" + "=" * 60)
        print(">>> [조합 B] 전체조회")
        print("    AFHR_FLPR_YN=N, INQR_DVSN=00, PRCS_DVSN=00, FUND_STTL_ICLD_YN=Y")
        print("=" * 60)

        params_b = dict(_base_params)
        params_b.update({
            "AFHR_FLPR_YN": "N",
            "INQR_DVSN": "00",
            "FUND_STTL_ICLD_YN": "Y",
            "PRCS_DVSN": "00",
        })
        data_b = await client._request(
            "GET",
            endpoint_key="inquire_balance",
            tr_id_key="inquire_balance",
            bucket=BucketType.INQUIRY,
            params=params_b,
        )

        print(f"\n[Normalized 응답]")
        print(f"  keys  : {list(data_b.keys())}")
        print(f"  output2 present: {'output2' in data_b}")
        if "output2" in data_b:
            o2 = data_b["output2"]
            print(f"  output2 type: {type(o2).__name__}")
            if isinstance(o2, dict):
                print(f"  dnca_tot_amt: {o2.get('dnca_tot_amt', 'N/A')}")
                print(f"  output2: {json.dumps(o2, indent=2, ensure_ascii=False)}")
            elif isinstance(o2, list):
                print(f"  output2 len: {len(o2)}")
                if o2:
                    print(f"  output2[0]: {json.dumps(o2[0], indent=2, ensure_ascii=False)}")
        if "output" in data_b:
            out = data_b["output"]
            print(f"  output count: {len(out) if isinstance(out, list) else 'not list'}")

        # ==================================================================
        # 4. 조합 C: 시간외단일가 (AFHR_FLPR_YN=Y)
        # ==================================================================
        await asyncio.sleep(2.0)
        print("\n" + "=" * 60)
        print(">>> [조합 C] 시간외단일가 ON")
        print("    AFHR_FLPR_YN=Y, INQR_DVSN=01, PRCS_DVSN=01, FUND_STTL_ICLD_YN=N")
        print("=" * 60)

        params_c = dict(_base_params)
        params_c.update({
            "AFHR_FLPR_YN": "Y",
            "INQR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "PRCS_DVSN": "01",
        })
        data_c = await client._request(
            "GET",
            endpoint_key="inquire_balance",
            tr_id_key="inquire_balance",
            bucket=BucketType.INQUIRY,
            params=params_c,
        )

        print(f"\n[Normalized 응답]")
        print(f"  keys  : {list(data_c.keys())}")
        print(f"  output2 present: {'output2' in data_c}")
        if "output2" in data_c:
            o2 = data_c["output2"]
            print(f"  output2 type: {type(o2).__name__}")
            if isinstance(o2, dict):
                print(f"  dnca_tot_amt: {o2.get('dnca_tot_amt', 'N/A')}")
                print(f"  output2: {json.dumps(o2, indent=2, ensure_ascii=False)}")
            elif isinstance(o2, list):
                print(f"  output2 len: {len(o2)}")
                if o2:
                    print(f"  output2[0]: {json.dumps(o2[0], indent=2, ensure_ascii=False)}")
        if "output" in data_c:
            out = data_c["output"]
            print(f"  output count: {len(out) if isinstance(out, list) else 'not list'}")

        # ==================================================================
        # 5. 종합 비교표
        # ==================================================================
        print("\n" + "=" * 70)
        print(">>> 종합 비교")
        print("=" * 70)

        rows: list[tuple[str, Any, str]] = [
            ("조합 A (get_cash_balance)", cash_result, "output2 dict"),
            ("조합 A (get_positions)  ", pos_result, "output1 list"),
            ("조합 B (전체조회)       ", data_b, "normalized"),
            ("조합 C (시간외)         ", data_c, "normalized"),
        ]

        for name, data, source in rows:
            print(f"\n--- {name} (source: {source}) ---")
            if isinstance(data, dict):
                keys = list(data.keys())
                dnca = "N/A"
                if "dnca_tot_amt" in data:
                    dnca = data["dnca_tot_amt"]
                elif "output2" in data:
                    o2 = data["output2"]
                    if isinstance(o2, dict):
                        dnca = o2.get("dnca_tot_amt", "N/A")
                    elif isinstance(o2, list) and o2:
                        dnca = o2[0].get("dnca_tot_amt", "N/A")
                print(f"  keys: {keys}")
                print(f"  dnca_tot_amt: {dnca}")
            elif isinstance(data, list):
                print(f"  list len: {len(data)}")
            else:
                print(f"  type: {type(data).__name__}")

        print("\n" + "=" * 70)
        print("✅ 모든 조회 완료 (read-only). 주문 submit 없음.")
        print("=" * 70)

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(test_cash_balance())
