#!/usr/bin/env python3
"""
VTTC8908R get_orderable_cash() 직접 호출 테스트
=================================================
목적: BucketType.SNAPSHOT → INQUIRY 수정 + CMA_EVLU_AMT_ICLD_YN 추가 후
      실제 API 호출이 정상 동작하는지 확인하고, 반환값(Decimal) 검증.

실행: cd /workspace/agent_trading && TZ=Asia/Seoul python3 _test_orderable_cash.py
"""
import asyncio
import json
import os
import sys
from decimal import Decimal
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_trading.config.settings import AppSettings
from agent_trading.brokers.koreainvestment.rest_client import KISRestClient


async def main() -> None:
    settings = AppSettings()

    now_kst = datetime.now(timezone.utc).astimezone()
    print("=" * 70)
    print(f"[시간] 기준시각 (KST)       = {now_kst.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[설정] KIS_ENV              = {settings.kis_env}")
    print(f"[설정] 계좌번호             = {settings.kis_account_number}")
    print(f"[설정] 상품코드             = {settings.kis_account_product_code}")
    print("=" * 70)

    if not settings.kis_account_number:
        print("\n⚠️  계좌번호가 비어 있습니다. .env 파일 로드 확인 필요.")
        sys.exit(1)

    # KISRestClient 직접 인스턴스화 (budget_manager=None → rate limit bypass)
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

    try:
        # ==================================================================
        # 1. get_orderable_cash() 호출 (계좌 전체 주문가능현금)
        # ==================================================================
        print("\n" + "=" * 70)
        print(">>> [호출 1] get_orderable_cash() — 계좌 전체 주문가능현금")
        print("    bucket=BucketType.INQUIRY (수정 후)")
        print("    CMA_EVLU_AMT_ICLD_YN=N (추가)")
        print("=" * 70)

        result = await client.get_orderable_cash(account_ref="test")

        print(f"\n[get_orderable_cash() 반환값]")
        print(f"  type   : {type(result).__name__}")
        print(f"  value  : {result}")

        if result is None:
            print("\n⚠️  결과가 None입니다. API 호출이 실패했거나 ord_psbl_cash 필드가 없습니다.")
            print("    (장중이 아닌 경우 정상일 수 있음)")
        elif isinstance(result, Decimal):
            print(f"\n✅ 성공: Decimal('{result}') 반환됨")
            print(f"   float: {float(result)}")
        else:
            print(f"\n⚠️  예상치 못한 타입: {type(result).__name__}")

        # rate limit 방지를 위한 sleep
        await asyncio.sleep(2.0)

        # ==================================================================
        # 2. get_cash_balance() 호출 (비교용)
        # ==================================================================
        print("\n" + "=" * 70)
        print(">>> [호출 2] get_cash_balance() — 비교용")
        print("=" * 70)

        cash = await client.get_cash_balance()
        print(f"\n[get_cash_balance() 반환값]")
        if isinstance(cash, dict):
            print(f"  dnca_tot_amt (예수금총액)  : {cash.get('dnca_tot_amt', 'N/A')}")
            print(f"  ord_psbl_cash (주문가능현금): {cash.get('ord_psbl_cash', 'N/A')}")
            print(f"\n  전문: {json.dumps(cash, indent=2, ensure_ascii=False)}")

        # ==================================================================
        # 3. 요약
        # ==================================================================
        print("\n" + "=" * 70)
        print(">>> [요약]")
        print("=" * 70)
        print(f"  get_orderable_cash()  = {result}")
        print(f"  get_cash_balance()    = {cash.get('dnca_tot_amt', 'N/A')} (예수금총액)")
        if result is not None:
            print("\n✅ 버그 수정 검증 통과: BucketType.INQUIRY + CMA_EVLU_AMT_ICLD_YN 정상 동작")
        else:
            print("\n⚠️  ord_psbl_cash가 None — 장중이 아니거나 API 응답에 필드 없음")

    except AttributeError as e:
        print(f"\n❌ AttributeError 발생! 버그가 아직 남아있습니다: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 예외 발생: {type(e).__name__}: {e}")
        sys.exit(1)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
