"""Small async client for Safaricom Daraja M-Pesa Express (STK Push).

Provider callbacks are notifications only. Callers must query Daraja and match
the checkout ID, amount, and phone before they mark a ledger entry successful.
"""
import base64
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.core.config import Settings


class DarajaUnavailable(RuntimeError):
    pass


class DarajaError(RuntimeError):
    pass


class DarajaClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        if not settings.daraja_ready:
            raise DarajaUnavailable("M-Pesa checkout is not configured")
        if settings.daraja_transaction_type not in {"CustomerPayBillOnline", "CustomerBuyGoodsOnline"}:
            raise DarajaUnavailable("Daraja transaction type is invalid")
        self.settings = settings
        self._client = client
        self._owns_client = client is None
        self.base_url = (
            "https://sandbox.safaricom.co.ke" if settings.daraja_environment == "sandbox"
            else "https://api.safaricom.co.ke"
        )

    async def __aenter__(self):
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Use DarajaClient as an async context manager")
        return self._client

    async def _access_token(self) -> str:
        raw = f"{self.settings.daraja_consumer_key}:{self.settings.daraja_consumer_secret}".encode()
        auth = base64.b64encode(raw).decode("ascii")
        try:
            response = await self._http().get(
                f"{self.base_url}/oauth/v1/generate?grant_type=client_credentials",
                headers={"Authorization": f"Basic {auth}"},
            )
            response.raise_for_status()
            token = response.json().get("access_token")
        except (httpx.HTTPError, ValueError) as exc:
            raise DarajaError("Daraja authentication request failed") from exc
        if not isinstance(token, str) or not token:
            raise DarajaError("Daraja did not return an access token")
        return token

    def _timestamp(self) -> str:
        return datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y%m%d%H%M%S")

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        token = await self._access_token()
        try:
            response = await self._http().post(
                f"{self.base_url}{path}", json=body,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            response.raise_for_status()
            result = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise DarajaError("Daraja request failed") from exc
        if not isinstance(result, dict):
            raise DarajaError("Daraja returned an invalid response")
        if result.get("ResponseCode") not in (None, "0"):
            raise DarajaError("Daraja rejected the request")
        return result

    async def initiate_stk_push(
        self, *, phone_number: str, amount: Decimal, account_reference: str, description: str,
        callback_url: str | None = None,
    ) -> dict[str, Any]:
        # Daraja's STK Push amount is integer KES. Reject fractional values instead of rounding.
        if amount <= 0 or amount != amount.to_integral_value():
            raise ValueError("M-Pesa Express requires a positive whole-shilling amount")
        phone = phone_number.strip().replace("+", "")
        if phone.startswith("0"):
            phone = "254" + phone[1:]
        if not phone.isdigit() or not phone.startswith("254") or len(phone) != 12:
            raise ValueError("Use a Kenyan mobile number in 07XXXXXXXX or 2547XXXXXXXX format")
        timestamp = self._timestamp()
        shortcode = self.settings.daraja_shortcode
        passphrase = f"{shortcode}{self.settings.daraja_passkey}{timestamp}".encode()
        password = base64.b64encode(passphrase).decode("ascii")
        url = callback_url or f"{self.settings.daraja_callback_base_url.rstrip('/')}/api/v1/payments/daraja/callback"
        return await self._post("/mpesa/stkpush/v1/processrequest", {
            "BusinessShortCode": shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": self.settings.daraja_transaction_type,
            "Amount": int(amount),
            "PartyA": phone,
            "PartyB": shortcode,
            "PhoneNumber": phone,
            "CallBackURL": url,
            "AccountReference": account_reference[:12],
            "TransactionDesc": description[:20],
        })

    async def query_stk_push(self, *, checkout_request_id: str) -> dict[str, Any]:
        timestamp = self._timestamp()
        shortcode = self.settings.daraja_shortcode
        password = base64.b64encode(
            f"{shortcode}{self.settings.daraja_passkey}{timestamp}".encode()
        ).decode("ascii")
        return await self._post("/mpesa/stkpushquery/v1/query", {
            "BusinessShortCode": shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "CheckoutRequestID": checkout_request_id,
        })
