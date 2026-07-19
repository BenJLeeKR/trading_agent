# ETF_ETN 현재가

- Sheet index: 46
- Non-empty rows: 101
- Max columns: 7

|Col1|Col2|Col3|Col4|Col5|Col6|Col7|
|---|---|---|---|---|---|---|
|ETF_ETN 현재가|||||||
|API 통신방식|REST||||||
|메뉴 위치|[국내주식] 기본시세||||||
|API 명|ETF_ETN 현재가||||||
|API ID|v1_국내주식-068||||||
|실전 TR_ID|FHPST02400000||||||
|모의 TR_ID|모의투자 미지원||||||
|기본정보|||||||
|HTTP Method|GET||||||
|실전 Domain|https://openapi.koreainvestment.com:9443||||||
|모의 Domain|모의투자 미지원||||||
|URL 명|/uapi/etfetn/v1/quotations/inquire-price||||||
|개요|||||||
|개요|ETF/ETN 현재가 API입니다._x000D_<br>한국투자 HTS(eFriend Plus) &gt; [0240] ETF/ETN 현재가 화면의 기능을 API로 개발한 사항으로, 해당 화면을 참고하시면 기능을 이해하기 쉽습니다.||||||
|Layout|||||||
|구분|Element|한글명|Type|Required|Length|Description|
|Request Header|content-type|컨텐츠타입|string|Y|40|application/json; charset=utf-8|
||authorization|접근토큰|string|Y|350|OAuth 토큰이 필요한 API 경우 발급한 Access token _x000D_<br>일반고객(Access token 유효기간 1일, OAuth 2.0의 Client Credentials Grant 절차를 준용) _x000D_<br>법인(Access token 유효기간 3개월, Refresh token 유효기간 1년, OAuth 2.0의 Authorization Code Grant 절차를 준용)|
||appkey|앱키|string|Y|36|한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.)|
||appsecret|앱시크릿키|string|Y|180|한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.)|
||personalseckey|고객식별키|string|N|180|[법인 필수] 제휴사 회원 관리를 위한 고객식별키|
||tr_id|거래ID|string|Y|13|FHPST02400000|
||tr_cont|연속 거래 여부|string|N|1|tr_cont를 이용한 다음조회 불가 API|
||custtype|고객 타입|string|Y|1|B : 법인 _x000D_<br>P : 개인|
||seq_no|일련번호|string|N|2|[법인 필수] 001|
||mac_address|맥주소|string|N|12|법인고객 혹은 개인고객의 Mac address 값|
||phone_number|핸드폰번호|string|N|12|[법인 필수] 제휴사APP을 사용하는 경우 사용자(회원) 핸드폰번호 _x000D_<br>ex) 01011112222 (하이픈 등 구분값 제거)|
||ip_addr|접속 단말 공인 IP|string|N|12|[법인 필수] 사용자(회원)의 IP Address|
||gt_uid|Global UID|string|N|32|[법인 전용] 거래고유번호로 사용하므로 거래별로 UNIQUE해야 함|
|Request Query Parameter|fid_input_iscd|FID 입력 종목코드|string|Y|12|종목코드|
||fid_cond_mrkt_div_code|FID 조건 시장 분류 코드|string|Y|2|J|
|Response Header|content-type|컨텐츠타입|string|Y|40|application/json; charset=utf-8|
||tr_id|거래ID|string|Y|13|요청한 tr_id|
||tr_cont|연속 거래 여부|string|N|1|tr_cont를 이용한 다음조회 불가 API|
||gt_uid|Global UID|string|N|32|[법인 전용] 거래고유번호로 사용하므로 거래별로 UNIQUE해야 함|
|Response Body|rt_cd|성공 실패 여부|string|Y|1||
||msg_cd|응답코드|string|Y|8||
||msg1|응답메세지|string|Y|80||
||output|응답상세|object|Y|||
||stck_prpr|주식 현재가|string|Y|10||
||prdy_vrss_sign|전일 대비 부호|string|Y|1||
||prdy_vrss|전일 대비|string|Y|10||
||prdy_ctrt|전일 대비율|string|Y|82||
||acml_vol|누적 거래량|string|Y|18||
||prdy_vol|전일 거래량|string|Y|18||
||stck_mxpr|주식 상한가|string|Y|10||
||stck_llam|주식 하한가|string|Y|10||
||stck_prdy_clpr|주식 전일 종가|string|Y|10||
||stck_oprc|주식 시가2|string|Y|10||
||prdy_clpr_vrss_oprc_rate|전일 종가 대비 시가2 비율|string|Y|84||
||stck_hgpr|주식 최고가|string|Y|10||
||prdy_clpr_vrss_hgpr_rate|전일 종가 대비 최고가 비율|string|Y|84||
||stck_lwpr|주식 최저가|string|Y|10||
||prdy_clpr_vrss_lwpr_rate|전일 종가 대비 최저가 비율|string|Y|84||
||prdy_last_nav|전일 최종 NAV|string|Y|112||
||nav|NAV|string|Y|112||
||nav_prdy_vrss|NAV 전일 대비|string|Y|112||
||nav_prdy_vrss_sign|NAV 전일 대비 부호|string|Y|1||
||nav_prdy_ctrt|NAV 전일 대비율|string|Y|82||
||trc_errt|추적 오차율|string|Y|82||
||stck_sdpr|주식 기준가|string|Y|10||
||stck_sspr|주식 대용가|string|Y|10||
||nmix_ctrt|지수 대비율|string|Y|135||
||etf_crcl_stcn|ETF 유통 주수|string|Y|18||
||etf_ntas_ttam|ETF 순자산 총액|string|Y|22||
||etf_frcr_ntas_ttam|ETF 외화 순자산 총액|string|Y|22||
||frgn_limt_rate|외국인 한도 비율|string|Y|84||
||frgn_oder_able_qty|외국인 주문 가능 수량|string|Y|18||
||etf_cu_unit_scrt_cnt|ETF CU 단위 증권 수|string|Y|18||
||etf_cnfg_issu_cnt|ETF 구성 종목 수|string|Y|18||
||etf_dvdn_cycl|ETF 배당 주기|string|Y|2||
||crcd|통화 코드|string|Y|4||
||etf_crcl_ntas_ttam|ETF 유통 순자산 총액|string|Y|22||
||etf_frcr_crcl_ntas_ttam|ETF 외화 유통 순자산 총액|string|Y|22||
||etf_frcr_last_ntas_wrth_val|ETF 외화 최종 순자산 가치 값|string|Y|13||
||lp_oder_able_cls_code|LP 주문 가능 구분 코드|string|Y|2||
||stck_dryy_hgpr|주식 연중 최고가|string|Y|10||
||dryy_hgpr_vrss_prpr_rate|연중 최고가 대비 현재가 비율|string|Y|84||
||dryy_hgpr_date|연중 최고가 일자|string|Y|8||
||stck_dryy_lwpr|주식 연중 최저가|string|Y|10||
||dryy_lwpr_vrss_prpr_rate|연중 최저가 대비 현재가 비율|string|Y|84||
||dryy_lwpr_date|연중 최저가 일자|string|Y|8||
||bstp_kor_isnm|업종 한글 종목명|string|Y|40|※ 거래소 정보로 특정 종목은 업종구분이 없어 데이터 미회신|
||vi_cls_code|VI적용구분코드|string|Y|1||
||lstn_stcn|상장 주수|string|Y|18||
||frgn_hldn_qty|외국인 보유 수량|string|Y|18||
||frgn_hldn_qty_rate|외국인 보유 수량 비율|string|Y|84||
||etf_trc_ert_mltp|ETF 추적 수익률 배수|string|Y|126||
||dprt|괴리율|string|Y|82||
||mbcr_name|회원사 명|string|Y|50||
||stck_lstn_date|주식 상장 일자|string|Y|8||
||mtrt_date|만기 일자|string|Y|8||
||shrg_type_code|분배금형태코드|string|Y|2||
||lp_hldn_rate|LP 보유 비율|string|Y|84||
||etf_trgt_nmix_bstp_code|ETF대상지수업종코드|string|Y|4||
||etf_div_name|ETF 분류 명|string|Y|40||
||etf_rprs_bstp_kor_isnm|ETF 대표 업종 한글 종목명|string|Y|40||
||lp_hldn_vol|ETN LP 보유량|string|Y|18||
|Example|||||||
|Request Example (Python)|{_x000D_<br>"fid_cond_mrkt_div_code":"J",_x000D_<br>"fid_input_iscd":"069500"_x000D_<br>}||||||
|Response Example|{_x000D_<br>    "output": {_x000D_<br>        "stck_prpr": "36090",_x000D_<br>        "prdy_vrss_sign": "2",_x000D_<br>        "prdy_vrss": "110",_x000D_<br>        "prdy_ctrt": "0.31",_x000D_<br>        "acml_vol": "3719307",_x000D_<br>        "prdy_vol": "6463600",_x000D_<br>        "stck_mxpr": "46770",_x000D_<br>        "stck_llam": "25190",_x000D_<br>        "stck_prdy_clpr": "35980",_x000D_<br>        "stck_oprc": "36300",_x000D_<br>        "prdy_clpr_vrss_oprc_rate": "0.89",_x000D_<br>        "stck_hgpr": "36510",_x000D_<br>        "prdy_clpr_vrss_hgpr_rate": "1.47",_x000D_<br>        "stck_lwpr": "36040",_x000D_<br>        "prdy_clpr_vrss_lwpr_rate": "0.17",_x000D_<br>        "prdy_last_nav": "36036.22",_x000D_<br>        "nav": "36127.30",_x000D_<br>        "nav_prdy_vrss": "91.08",_x000D_<br>        "nav_prdy_vrss_sign": "2",_x000D_<br>        "nav_prdy_ctrt": "0.25",_x000D_<br>        "trc_errt": "0.53",_x000D_<br>        "stck_sdpr": "35980",_x000D_<br>        "stck_sspr": "28780",_x000D_<br>        "etf_crcl_stcn": "191550000",_x000D_<br>        "etf_ntas_ttam": "69027",_x000D_<br>        "etf_frcr_ntas_ttam": "0",_x000D_<br>        "frgn_limt_rate": "100.0000",_x000D_<br>        "frgn_oder_able_qty": "150950685",_x000D_<br>        "etf_cu_unit_scrt_cnt": "50000",_x000D_<br>        "etf_cnfg_issu_cnt": "201",_x000D_<br>        "etf_dvdn_cycl": "2",_x000D_<br>        "crcd": "KRW",_x000D_<br>        "etf_crcl_ntas_ttam": "0",_x000D_<br>        "etf_frcr_crcl_ntas_ttam": "0",_x000D_<br>        "etf_frcr_last_ntas_wrth_val": "0",_x000D_<br>        "lp_oder_able_cls_code": "N",_x000D_<br>        "stck_dryy_hgpr": "36510",_x000D_<br>        "dryy_hgpr_vrss_prpr_rate": "-1.15",_x000D_<br>        "dryy_hgpr_date": "20240223",_x000D_<br>        "stck_dryy_lwpr": "32748",_x000D_<br>        "dryy_lwpr_vrss_prpr_rate": "10.21",_x000D_<br>        "dryy_lwpr_date": "20240118",_x000D_<br>        "bstp_kor_isnm": "ETF(실물복제/수익증권)",_x000D_<br>        "vi_cls_code": "N",_x000D_<br>        "lstn_stcn": "191550000",_x000D_<br>        "frgn_hldn_qty": "40599315",_x000D_<br>        "frgn_hldn_qty_rate": "21.20",_x000D_<br>        "etf_trc_ert_mltp": "1.00",_x000D_<br>        "dprt": "-0.10",_x000D_<br>        "mbcr_name": "삼성자산운용(ETF)",_x000D_<br>        "stck_lstn_date": "20021014",_x000D_<br>        "mtrt_date": "0",_x000D_<br>        "shrg_type_code": "  ",_x000D_<br>        "lp_hldn_rate": "0.00",_x000D_<br>        "etf_trgt_nmix_bstp_code": "2001",_x000D_<br>        "etf_div_name": "수익증권형",_x000D_<br>        "etf_rprs_bstp_kor_isnm": "KOSPI200",_x000D_<br>        "lp_hldn_vol": "0"_x000D_<br>    },_x000D_<br>    "rt_cd": "0",_x000D_<br>    "msg_cd": "MCA00000",_x000D_<br>    "msg1": "정상처리 되었습니다."_x000D_<br>}||||||
