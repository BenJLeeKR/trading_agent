import pandas as pd
import FinanceDataReader as fdr
import requests
from bs4 import BeautifulSoup


def get_kospi_master():
    kospi = fdr.StockListing("KOSPI")

    print("KOSPI raw columns:", list(kospi.columns))
    print(kospi.head())

    # FinanceDataReader 버전별 컬럼명 대응
    if "Code" in kospi.columns:
        code_col = "Code"
    elif "Symbol" in kospi.columns:
        code_col = "Symbol"
    else:
        raise RuntimeError(f"종목코드 컬럼을 찾지 못했습니다: {list(kospi.columns)}")

    if "Name" in kospi.columns:
        name_col = "Name"
    else:
        raise RuntimeError(f"종목명 컬럼을 찾지 못했습니다: {list(kospi.columns)}")

    df = kospi[[code_col, name_col]].copy()
    df.columns = ["code", "name"]
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["market"] = "KOSPI"

    return df


def get_kospi200_from_naver():
    """
    네이버 금융 KOSPI200 구성종목 페이지에서 종목코드 수집.
    페이지 구조 변경 가능성이 있으므로 운영용에서는 예외처리 필수.
    """
    codes = set()

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    for page in range(1, 30):
        url = f"https://finance.naver.com/sise/entryJongmok.naver?&page={page}"
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()

        soup = BeautifulSoup(res.text, "html.parser")

        page_codes = set()
        for a in soup.select("a[href*='code=']"):
            href = a.get("href", "")
            if "code=" not in href:
                continue

            code = href.split("code=")[-1].split("&")[0].strip()
            if code.isdigit() and len(code) == 6:
                page_codes.add(code)

        if not page_codes:
            break

        codes.update(page_codes)

    return codes


def main():
    kospi_df = get_kospi_master()

    try:
        kospi200_codes = get_kospi200_from_naver()
    except Exception as e:
        print("KOSPI200 구성종목 조회 실패:", e)
        kospi200_codes = set()

    kospi_df["is_kospi200"] = kospi_df["code"].isin(kospi200_codes)

    print(kospi_df.head())
    print("KOSPI count:", len(kospi_df))
    print("KOSPI200 count:", int(kospi_df["is_kospi200"].sum()))

    if kospi200_codes and kospi_df["is_kospi200"].sum() < 150:
        print("WARNING: KOSPI200 구성종목 수가 비정상적으로 적습니다. 네이버 페이지 구조 변경 가능성이 있습니다.")

    output_path = "kospi_master.csv"
    kospi_df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print("saved:", output_path)


if __name__ == "__main__":
    main()
