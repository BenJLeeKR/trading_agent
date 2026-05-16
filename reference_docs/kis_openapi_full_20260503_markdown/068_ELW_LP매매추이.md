# ELW LP매매추이

- Sheet index: 68
- Non-empty rows: 72
- Max columns: 7

|Col1|Col2|Col3|Col4|Col5|Col6|Col7|
|---|---|---|---|---|---|---|
|ELW LP매매추이|||||||
|API 통신방식|REST||||||
|메뉴 위치|[국내주식] ELW 시세||||||
|API 명|ELW LP매매추이||||||
|API ID|국내주식-182||||||
|실전 TR_ID|FHPEW03760000||||||
|모의 TR_ID|||||||
|기본정보|||||||
|HTTP Method|GET||||||
|실전 Domain|https://openapi.koreainvestment.com:9443||||||
|모의 Domain|미지원||||||
|URL 명|/uapi/elw/v1/quotations/lp-trade-trend||||||
|개요|||||||
|개요|ELW LP매매추이 API입니다._x000D_<br>한국투자 HTS(eFriend Plus) &gt; [0376] ELW LP매매추이 화면 의 기능을 API로 개발한 사항으로, 해당 화면을 참고하시면 기능을 이해하기 쉽습니다.||||||
|Layout|||||||
|구분|Element|한글명|Type|Required|Length|Description|
|Request Header|content-type|컨텐츠타입|string|Y|40|application/json; charset=utf-8|
||authorization|접근토큰|string|Y|350|OAuth 토큰이 필요한 API 경우 발급한 Access token _x000D_<br>일반고객(Access token 유효기간 1일, OAuth 2.0의 Client Credentials Grant 절차를 준용) _x000D_<br>법인(Access token 유효기간 3개월, Refresh token 유효기간 1년, OAuth 2.0의 Authorization Code Grant 절차를 준용)|
||appkey|앱키|string|Y|36|한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.)|
||appsecret|앱시크릿키|string|Y|180|한국투자증권 홈페이지에서 발급받은 appkey (절대 노출되지 않도록 주의해주세요.)|
||personalseckey|고객식별키|string|N|180|[법인 필수] 제휴사 회원 관리를 위한 고객식별키|
||tr_id|거래ID|string|Y|13|FHPEW03760000|
||tr_cont|연속 거래 여부|string|N|1|tr_cont를 이용한 다음조회 불가 API|
||custtype|고객 타입|string|Y|1|B : 법인 _x000D_<br>P : 개인|
||seq_no|일련번호|string|N|2|[법인 필수] 001|
||mac_address|맥주소|string|N|12|법인고객 혹은 개인고객의 Mac address 값|
||phone_number|핸드폰번호|string|N|12|[법인 필수] 제휴사APP을 사용하는 경우 사용자(회원) 핸드폰번호 _x000D_<br>ex) 01011112222 (하이픈 등 구분값 제거)|
||ip_addr|접속 단말 공인 IP|string|N|12|[법인 필수] 사용자(회원)의 IP Address|
||gt_uid|Global UID|string|N|32|[법인 전용] 거래고유번호로 사용하므로 거래별로 UNIQUE해야 함|
|Request Query Parameter|FID_COND_MRKT_DIV_CODE|조건시장분류코드|string|Y|2|시장구분(W)|
||FID_INPUT_ISCD|입력종목코드|string|Y|12|입력종목코드(ex 52K577(미래 K577KOSDAQ150콜)|
|Response Header|content-type|컨텐츠타입|string|Y|40|application/json; charset=utf-8|
||tr_id|거래ID|string|Y|13|요청한 tr_id|
||tr_cont|연속 거래 여부|string|N|1|tr_cont를 이용한 다음조회 불가 API|
||gt_uid|Global UID|string|N|32|[법인 전용] 거래고유번호로 사용하므로 거래별로 UNIQUE해야 함|
|Response Body|rt_cd|성공 실패 여부|string|Y|1||
||msg_cd|응답코드|string|Y|8||
||msg1|응답메세지|string|Y|80||
||output1|응답상세|object|Y|||
||elw_prpr|ELW현재가|string|Y|10||
||prdy_vrss_sign|전일대비부호|string|Y|1||
||prdy_vrss|전일대비|string|Y|10||
||prdy_ctrt|전일대비율|string|Y|82||
||acml_vol|누적거래량|string|Y|18||
||prdy_vol|전일거래량|string|Y|18||
||stck_cnvr_rate|주식전환비율|string|Y|136||
||prit|패리티|string|Y|112||
||lvrg_val|레버리지값|string|Y|114||
||gear|기어링|string|Y|84||
||prls_qryr_rate|손익분기비율|string|Y|84||
||cfp|자본지지점|string|Y|112||
||invl_val|내재가치값|string|Y|132||
||tmvl_val|시간가치값|string|Y|132||
||acpr|행사가|string|Y|112||
||elw_ko_barrier|조기종료발생기준가격|string|Y|112||
||output2|응답상세|object array|Y||array|
||stck_bsop_date|주식영업일자|string|Y|8||
||elw_prpr|ELW현재가|string|Y|10||
||prdy_vrss_sign|전일대비부호|string|Y|1||
||prdy_vrss|전일대비|string|Y|10||
||prdy_ctrt|전일대비율|string|Y|82||
||lp_seln_qty|LP매도수량|string|Y|19||
||lp_seln_avrg_unpr|LP매도평균단가|string|Y|19||
||lp_shnu_qty|LP매수수량|string|Y|19||
||lp_shnu_avrg_unpr|LP매수평균단가|string|Y|19||
||lp_hvol|LP보유량|string|Y|18||
||lp_hldn_rate|LP보유비율|string|Y|84||
||prsn_deal_qty|개인매매수량|string|Y|19||
||apprch_rate|접근도|string|Y|112||
|Example|||||||
|Request Example (Python)|FID_COND_MRKT_DIV_CODE:W_x000D_<br>FID_INPUT_ISCD:57K281||||||
|Response Example|{_x000D_<br>    "output1": {_x000D_<br>        "elw_prpr": "40",_x000D_<br>        "prdy_vrss_sign": "2",_x000D_<br>        "prdy_vrss": "5",_x000D_<br>        "prdy_ctrt": "14.29",_x000D_<br>        "acml_vol": "320750",_x000D_<br>        "prdy_vol": "114850",_x000D_<br>        "stck_cnvr_rate": "0.010000",_x000D_<br>        "prit": "103.35",_x000D_<br>        "lvrg_val": "-12.130651",_x000D_<br>        "gear": "19.3500",_x000D_<br>        "prls_qryr_rate": "-1.8000",_x000D_<br>        "cfp": "-1.7100",_x000D_<br>        "invl_val": "27.00",_x000D_<br>        "tmvl_val": "13.00",_x000D_<br>        "acpr": "80000.00",_x000D_<br>        "elw_ko_barrier": "0.00"_x000D_<br>    },_x000D_<br>    "output2": [_x000D_<br>        {_x000D_<br>            "stck_bsop_date": "20240516",_x000D_<br>            "elw_prpr": "35",_x000D_<br>            "prdy_vrss_sign": "3",_x000D_<br>            "prdy_vrss": "0",_x000D_<br>            "prdy_ctrt": "0.00",_x000D_<br>            "lp_seln_qty": "30030",_x000D_<br>            "lp_seln_avrg_unpr": "30",_x000D_<br>            "lp_shnu_qty": "84810",_x000D_<br>            "lp_shnu_avrg_unpr": "34",_x000D_<br>            "lp_hvol": "7999900",_x000D_<br>            "lp_hldn_rate": "99.99",_x000D_<br>            "prsn_deal_qty": "10",_x000D_<br>            "apprch_rate": "0.00"_x000D_<br>        },_x000D_<br>        {_x000D_<br>            "stck_bsop_date": "20240514",_x000D_<br>            "elw_prpr": "35",_x000D_<br>            "prdy_vrss_sign": "5",_x000D_<br>            "prdy_vrss": "-5",_x000D_<br>            "prdy_ctrt": "-12.50",_x000D_<br>            "lp_seln_qty": "73510",_x000D_<br>            "lp_seln_avrg_unpr": "35",_x000D_<br>            "lp_shnu_qty": "74440",_x000D_<br>            "lp_shnu_avrg_unpr": "35",_x000D_<br>            "lp_hvol": "7945120",_x000D_<br>            "lp_hldn_rate": "99.31",_x000D_<br>            "prsn_deal_qty": "1260",_x000D_<br>            "apprch_rate": "0.00"_x000D_<br>        },_x000D_<br>        {_x000D_<br>            "stck_bsop_date": "20240513",_x000D_<br>            "elw_prpr": "40",_x000D_<br>            "prdy_vrss_sign": "2",_x000D_<br>            "prdy_vrss": "10",_x000D_<br>            "prdy_ctrt": "33.33",_x000D_<br>            "lp_seln_qty": "282010",_x000D_<br>            "lp_seln_avrg_unpr": "36",_x000D_<br>            "lp_shnu_qty": "277980",_x000D_<br>            "lp_shnu_avrg_unpr": "36",_x000D_<br>            "lp_hvol": "7944190",_x000D_<br>            "lp_hldn_rate": "99.30",_x000D_<br>            "prsn_deal_qty": "11140",_x000D_<br>            "apprch_rate": "0.00"_x000D_<br>        },_x000D_<br>        {_x000D_<br>            "stck_bsop_date": "20240510",_x000D_<br>            "elw_prpr": "30",_x000D_<br>            "prdy_vrss_sign": "2",_x000D_<br>            "prdy_vrss": "5",_x000D_<br>            "prdy_ctrt": "20.00",_x000D_<br>            "lp_seln_qty": "137480",_x000D_<br>            "lp_seln_avrg_unpr": "27",_x000D_<br>            "lp_shnu_qty": "209950",_x000D_<br>            "lp_shnu_avrg_unpr": "25",_x000D_<br>            "lp_hvol": "7948220",_x000D_<br>            "lp_hldn_rate": "99.35",_x000D_<br>            "prsn_deal_qty": "2040",_x000D_<br>            "apprch_rate": "0.00"_x000D_<br>        },_x000D_<br>        {_x000D_<br>            "stck_bsop_date": "20240509",_x000D_<br>            "elw_prpr": "25",_x000D_<br>            "prdy_vrss_sign": "3",_x000D_<br>            "prdy_vrss": "0",_x000D_<br>            "prdy_ctrt": "0.00",_x000D_<br>            "lp_seln_qty": "280020",_x000D_<br>            "lp_seln_avrg_unpr": "25",_x000D_<br>            "lp_shnu_qty": "209910",_x000D_<br>            "lp_shnu_avrg_unpr": "25",_x000D_<br>            "lp_hvol": "7875750",_x000D_<br>            "lp_hldn_rate": "98.44",_x000D_<br>            "prsn_deal_qty": "120",_x000D_<br>            "apprch_rate": "0.00"_x000D_<br>        },_x000D_<br>        {_x000D_<br>            "stck_bsop_date": "20240508",_x000D_<br>            "elw_prpr": "25",_x000D_<br>            "prdy_vrss_sign": "3",_x000D_<br>            "prdy_vrss": "0",_x000D_<br>            "prdy_ctrt": "0.00",_x000D_<br>            "lp_seln_qty": "630000",_x000D_<br>            "lp_seln_avrg_unpr": "25",_x000D_<br>            "lp_shnu_qty": "630000",_x000D_<br>            "lp_shnu_avrg_unpr": "25",_x000D_<br>            "lp_hvol": "7945860",_x000D_<br>            "lp_hldn_rate": "99.32",_x000D_<br>            "prsn_deal_qty": "10000",_x000D_<br>            "apprch_rate": "0.00"_x000D_<br>        },_x000D_<br>        {_x000D_<br>            "stck_bsop_date": "20240507",_x000D_<br>            "elw_prpr": "25",_x000D_<br>            "prdy_vrss_sign": "5",_x000D_<br>            "prdy_vrss": "-20",_x000D_<br>            "prdy_ctrt": "-44.44",_x000D_<br>            "lp_seln_qty": "98550",_x000D_<br>            "lp_seln_avrg_unpr": "27",_x000D_<br>            "lp_shnu_qty": "160420",_x000D_<br>            "lp_shnu_avrg_unpr": "28",_x000D_<br>            "lp_hvol": "7945860",_x000D_<br>            "lp_hldn_rate": "99.32",_x000D_<br>            "prsn_deal_qty": "26200",_x000D_<br>            "apprch_rate": "0.00"_x000D_<br>        },_x000D_<br>        {_x000D_<br>            "stck_bsop_date": "20240503",_x000D_<br>            "elw_prpr": "45",_x000D_<br>            "prdy_vrss_sign": "3",_x000D_<br>            "prdy_vrss": "0",_x000D_<br>            "prdy_ctrt": "0.00",_x000D_<br>            "lp_seln_qty": "501890",_x000D_<br>            "lp_seln_avrg_unpr": "40",_x000D_<br>            "lp_shnu_qty": "491690",_x000D_<br>            "lp_shnu_avrg_unpr": "40",_x000D_<br>            "lp_hvol": "7883990",_x000D_<br>            "lp_hldn_rate": "98.55",_x000D_<br>            "prsn_deal_qty": "8440",_x000D_<br>            "apprch_rate": "0.00"_x000D_<br>        },_x000D_<br>        {_x000D_<br>            "stck_bsop_date": "20240502",_x000D_<br>            "elw_prpr": "45",_x000D_<br>            "prdy_vrss_sign": "3",_x000D_<br>            "prdy_vrss": "0",_x000D_<br>            "prdy_ctrt": "0.00",_x000D_<br>            "lp_seln_qty": "402940",_x000D_<br>            "lp_seln_avrg_unpr": "40",_x000D_<br>            "lp_shnu_qty": "332240",_x000D_<br>            "lp_shnu_avrg_unpr": "40",_x000D_<br>            "lp_hvol": "7894190",_x000D_<br>            "lp_hldn_rate": "98.67",_x000D_<br>            "prsn_deal_qty": "54100",_x000D_<br>            "apprch_rate": "0.00"_x000D_<br>        },_x000D_<br>        {_x000D_<br>            "stck_bsop_date": "20240430",_x000D_<br>            "elw_prpr": "45",_x000D_<br>            "prdy_vrss_sign": "5",_x000D_<br>            "prdy_vrss": "-5",_x000D_<br>            "prdy_ctrt": "-10.00",_x000D_<br>            "lp_seln_qty": "27840",_x000D_<br>            "lp_seln_avrg_unpr": "48",_x000D_<br>            "lp_shnu_qty": "33540",_x000D_<br>            "lp_shnu_avrg_unpr": "45",_x000D_<br>            "lp_hvol": "7964890",_x000D_<br>            "lp_hldn_rate": "99.56",_x000D_<br>            "prsn_deal_qty": "710",_x000D_<br>            "apprch_rate": "0.00"_x000D_<br>        },_x000D_<br>        {_x000D_<br>            "stck_bsop_date": "20240429",_x000D_<br>            "elw_prpr": "50",_x000D_<br>            "prdy_vrss_sign": "3",_x000D_<br>            "prdy_vrss": "0",_x000D_<br>            "prdy_ctrt": "0.00",_x000D_<br>            "lp_seln_qty": "211510",_x000D_<br>            "lp_seln_avrg_unpr": "50",_x000D_<br>            "lp_shnu_qty": "175810",_x000D_<br>            "lp_shnu_avrg_unpr": "50",_x000D_<br>            "lp_hvol": "7959190",_x000D_<br>            "lp_hldn_rate": "99.49",_x000D_<br>            "prsn_deal_qty": "15700",_x000D_<br>            "apprch_rate": "0.00"_x000D_<br>        },_x000D_<br>        {_x000D_<br>            "stck_bsop_date": "20240426",_x000D_<br>            "elw_prpr": "50",_x000D_<br>            "prdy_vrss_sign": "3",_x000D_<br>            "prdy_vrss": "0",_x000D_<br>            "prdy_ctrt": "0.00",_x000D_<br>            "lp_seln_qty": "35700",_x000D_<br>            "lp_seln_avrg_unpr": "50",_x000D_<br>            "lp_shnu_qty": "91400",_x000D_<br>            "lp_shnu_avrg_unpr": "48",_x000D_<br>            "lp_hvol": "7994890",_x000D_<br>            "lp_hldn_rate": "99.93",_x000D_<br>            "prsn_deal_qty": "60",_x000D_<br>            "apprch_rate": "0.00"_x000D_<br>        },..._x000D_<br>    ],_x000D_<br>    "rt_cd": "0",_x000D_<br>    "msg_cd": "MCA00000",_x000D_<br>    "msg1": "정상처리 되었습니다."_x000D_<br>}||||||
