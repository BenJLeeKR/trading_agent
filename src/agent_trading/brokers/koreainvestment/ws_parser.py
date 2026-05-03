"""KIS WebSocket real-time data parser.

KIS WebSocket delivers two types of messages:
1. **JSON subscription ack** — ``{"header": {...}, "body": {...}}``
2. **Delimited-string real-time data** — ``|`` and ``^`` delimited fields

Channel reference
-----------------
- ``H0STCNT0`` — 실시간체결가 (KRX) — real-time trade price
- ``H0STASP0`` — 실시간호가 (KRX) — real-time orderbook
- ``H0STCNI0`` — 실시간체결통보 — real-time order fill notification (AES encrypted)
- ``H0STCNS0`` — 실시간체결가 (KOSDAQ)

Parsing rules
-------------
- JSON messages are parsed via ``json.loads()``
- Delimited-string messages are split by ``|`` then ``^``
- ``H0STCNI0`` body is AES-256-CBC encrypted; decryption key is the approval key
"""

from __future__ import annotations

import base64
import json
import struct
from collections.abc import Mapping
from typing import Any

from agent_trading.domain.enums import OrderSide
from agent_trading.domain.models import FillEvent


# ---------------------------------------------------------------------------
# KIS WebSocket channel → TR ID mapping
# ---------------------------------------------------------------------------

WS_CHANNEL_TR_IDS: Mapping[str, str] = {
    "H0STCNT0": "H0STCNT0",  # 실시간체결가 (KRX)
    "H0STASP0": "H0STASP0",  # 실시간호가 (KRX)
    "H0STCNI0": "H0STCNI0",  # 실시간체결통보
    "H0STCNS0": "H0STCNS0",  # 실시간체결가 (KOSDAQ)
}


# ---------------------------------------------------------------------------
# Message type detection
# ---------------------------------------------------------------------------


def is_json_message(raw: str) -> bool:
    """Detect whether a raw WebSocket message is JSON or delimited-string."""
    return raw.strip().startswith("{")


# ---------------------------------------------------------------------------
# JSON subscription ack parser
# ---------------------------------------------------------------------------


def parse_subscription_ack(raw: str) -> dict[str, Any]:
    """Parse a JSON subscription acknowledgement.

    Expected format::

        {
            "header": {
                "tr_id": "H0STCNT0",
                "tr_key": "005930",
                "encrypt": "N"
            },
            "body": {
                "rt_cd": "0",
                "msg1": "SUBSCRIBE SUCCESS",
                "output": {...}
            }
        }

    Returns the parsed dict with keys ``header`` and ``body``.
    Raises ``ValueError`` if the message is not valid JSON.
    """
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Delimited-string real-time data parser
# ---------------------------------------------------------------------------


def parse_delimited_message(raw: str) -> dict[str, Any]:
    """Parse a ``|`` and ``^`` delimited KIS real-time message.

    KIS format::

        tr_id|continuum_key|body_chunks...

    Where ``body_chunks`` are ``^``-delimited fields whose meaning
    depends on the ``tr_id``.

    Returns a dict with keys:
    - ``tr_id`` — the channel/TR ID
    - ``continuum_key`` — used for gap detection
    - ``fields`` — list of ``^``-delimited field values
    """
    parts = raw.split("|")
    if len(parts) < 3:
        raise ValueError(f"Malformed delimited message: too few pipe-delimited parts ({len(parts)})")

    tr_id = parts[0]
    continuum_key = parts[1]
    body = "|".join(parts[2:])  # Rejoin in case body contains |

    fields = body.split("^")
    return {
        "tr_id": tr_id,
        "continuum_key": continuum_key,
        "fields": fields,
    }


# ---------------------------------------------------------------------------
# Channel-specific parsers
# ---------------------------------------------------------------------------


def parse_trade_price(fields: list[str]) -> dict[str, Any]:
    """Parse H0STCNT0 (실시간체결가) fields.

    The raw KIS delimited message is::

        H0STCNT0|continuum|^stock_code^trade_time^trade_price^...

    After splitting by ``|`` then ``^``, the first element is an empty
    string (the leading ``^``).  Field layout (0-indexed):

        0:  (empty — leading ``^``)
        1:  stock_code
        2:  trade_time (HHMMSS)
        3:  trade_price
        4:  trade_volume
        5:  (unused)
        6:  sign (1:상한, 2:상승, 3:보합, 4:하한, 5:하락)
        7:  change_rate
        8:  open_price
        9:  high_price
        10: low_price
        11: (unused)
    """
    return {
        "stock_code": _safe_get(fields, 1),
        "trade_time": _safe_get(fields, 2),
        "trade_price": _safe_get(fields, 3),
        "trade_volume": _safe_get(fields, 4),
        "sign": _safe_get(fields, 6),
        "change_rate": _safe_get(fields, 7),
        "open_price": _safe_get(fields, 8),
        "high_price": _safe_get(fields, 9),
        "low_price": _safe_get(fields, 10),
    }


def parse_orderbook(fields: list[str]) -> dict[str, Any]:
    """Parse H0STASP0 (실시간호가) fields.

    The raw KIS delimited message is::

        H0STASP0|continuum|^stock_code^time^ask_prices^ask_volumes^bid_prices^bid_volumes

    After splitting by ``|`` then ``^``, the first element is an empty
    string (the leading ``^``).  Field layout (0-indexed):

        0:  (empty — leading ``^``)
        1:  stock_code
        2:  time (HHMMSS)
        3-12: ask_prices (10 levels)
        13-22: ask_volumes (10 levels)
        23-32: bid_prices (10 levels)
        33-42: bid_volumes (10 levels)
    """
    ask_prices = [_safe_get(fields, i) for i in range(3, 13)]
    ask_volumes = [_safe_get(fields, i) for i in range(13, 23)]
    bid_prices = [_safe_get(fields, i) for i in range(23, 33)]
    bid_volumes = [_safe_get(fields, i) for i in range(33, 43)]

    return {
        "stock_code": _safe_get(fields, 1),
        "time": _safe_get(fields, 2),
        "ask_prices": ask_prices,
        "ask_volumes": ask_volumes,
        "bid_prices": bid_prices,
        "bid_volumes": bid_volumes,
    }


def parse_fill_notification(fields: list[str]) -> dict[str, Any]:
    """Parse H0STCNI0 (실시간체결통보) fields.

    NOTE: The body of H0STCNI0 is AES-256-CBC encrypted when
    ``encrypt="Y"`` in the subscription ack.  This parser assumes
    the body has already been decrypted.

    The raw KIS delimited message is::

        H0STCNI0|continuum|^stock_code^stock_name^broker_order_id^...

    After splitting by ``|`` then ``^``, the first element is an empty
    string (the leading ``^``).  Field layout (0-indexed):

        0:  (empty — leading ``^``)
        1:  stock_code
        2:  stock_name
        3:  broker_order_id (ODNO)
        4:  original_order_id (ORGN_ODNO)
        5:  side (01:매도, 02:매수)
        6:  order_type (00:지정가, 01:시장가)
        7:  filled_qty
        8:  filled_price
        9:  filled_time (HHMMSS)
        10: order_qty
        11: order_price
        12: status (00:체결, 01:확인, 02:거부)
        13: (unused)
    """
    side_raw = _safe_get(fields, 5)
    side = OrderSide.BUY if side_raw == "02" else OrderSide.SELL

    return {
        "stock_code": _safe_get(fields, 1),
        "stock_name": _safe_get(fields, 2),
        "broker_order_id": _safe_get(fields, 3),
        "original_order_id": _safe_get(fields, 4),
        "side": side,
        "order_type": _safe_get(fields, 6),
        "filled_qty": _safe_get(fields, 7),
        "filled_price": _safe_get(fields, 8),
        "filled_time": _safe_get(fields, 9),
        "order_qty": _safe_get(fields, 10),
        "order_price": _safe_get(fields, 11),
        "status": _safe_get(fields, 12),
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_CHANNEL_PARSERS: dict[str, callable] = {
    "H0STCNT0": parse_trade_price,
    "H0STCNS0": parse_trade_price,  # Same layout as H0STCNT0
    "H0STASP0": parse_orderbook,
    "H0STCNI0": parse_fill_notification,
}


def parse_message(raw: str) -> dict[str, Any]:
    """Parse any KIS WebSocket message (JSON or delimited-string).

    Returns a normalised dict with at least a ``"type"`` key:
    - ``"subscription_ack"`` — JSON subscription acknowledgement
    - ``"real_time_data"`` — delimited-string real-time data
    - ``"error"`` — error message
    """
    if is_json_message(raw):
        data = parse_subscription_ack(raw)
        header = data.get("header", {})
        body = data.get("body", {})

        rt_cd = body.get("rt_cd", "0")
        if rt_cd != "0":
            return {
                "type": "error",
                "tr_id": header.get("tr_id", ""),
                "message": body.get("msg1", ""),
                "raw": data,
            }

        return {
            "type": "subscription_ack",
            "tr_id": header.get("tr_id", ""),
            "tr_key": header.get("tr_key", ""),
            "encrypt": header.get("encrypt", "N"),
            "raw": data,
        }

    # Delimited-string message
    parsed = parse_delimited_message(raw)
    tr_id = parsed["tr_id"]
    fields = parsed["fields"]

    parser = _CHANNEL_PARSERS.get(tr_id)
    if parser is None:
        return {
            "type": "unknown",
            "tr_id": tr_id,
            "fields": fields,
            "raw": raw,
        }

    channel_data = parser(fields)
    return {
        "type": "real_time_data",
        "tr_id": tr_id,
        "continuum_key": parsed["continuum_key"],
        "data": channel_data,
        "raw": raw,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_get(fields: list[str], index: int, default: str = "") -> str:
    """Safely get a field from a list, returning *default* if out of range."""
    if 0 <= index < len(fields):
        return fields[index]
    return default
