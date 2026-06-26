from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import uuid
from datetime import UTC, datetime
from urllib.parse import quote, urlencode

import httpx

from app.config import get_settings

_PHONE_DIGITS = re.compile(r"\D+")


def percent_encode(value: str) -> str:
    return quote(str(value), safe="~")


def sign_aliyun_rpc(params: dict[str, str], access_key_secret: str, method: str = "GET") -> str:
    canonicalized = "&".join(
        f"{percent_encode(key)}={percent_encode(value)}" for key, value in sorted(params.items())
    )
    string_to_sign = f"{method}&{percent_encode('/')}&{percent_encode(canonicalized)}"
    digest = hmac.new(
        f"{access_key_secret}&".encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def format_aliyun_phone(phone: str) -> str:
    digits = _PHONE_DIGITS.sub("", phone.strip())
    if digits.startswith("86") and len(digits) >= 13:
        return digits
    if len(digits) == 11 and digits.startswith("1"):
        return f"86{digits}"
    return digits


def build_send_sms_params(*, phone: str, code: str) -> dict[str, str]:
    settings = get_settings()
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "Format": "JSON",
        "Version": "2017-05-25",
        "AccessKeyId": settings.aliyun_sms_access_key_id,
        "SignatureMethod": "HMAC-SHA1",
        "Timestamp": timestamp,
        "SignatureVersion": "1.0",
        "SignatureNonce": uuid.uuid4().hex,
        "Action": "SendSms",
        "RegionId": settings.aliyun_sms_region,
        "PhoneNumbers": format_aliyun_phone(phone),
        "SignName": settings.aliyun_sms_sign_name,
        "TemplateCode": settings.aliyun_sms_template_code,
        "TemplateParam": json.dumps({"code": code}, ensure_ascii=False, separators=(",", ":")),
    }


async def send_aliyun_sms(phone: str, code: str) -> None:
    settings = get_settings()
    params = build_send_sms_params(phone=phone, code=code)
    params["Signature"] = sign_aliyun_rpc(params, settings.aliyun_sms_access_key_secret)
    url = f"{settings.aliyun_sms_endpoint.rstrip('/')}/?{urlencode(params)}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()

    if payload.get("Code") != "OK":
        message = payload.get("Message") or payload.get("Code") or "Unknown Aliyun SMS error"
        raise RuntimeError(f"Aliyun SMS failed: {message}")
