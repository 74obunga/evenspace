from decimal import Decimal
import asyncio
import json

import httpx
import pytest

from app.core.config import Settings
from app.modules.payments.providers.daraja import DarajaClient, DarajaUnavailable


def configured(monkeypatch):
    monkeypatch.setenv("PAYMENT_PROVIDER", "daraja")
    monkeypatch.setenv("DARAJA_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("DARAJA_CONSUMER_KEY", "test-key")
    monkeypatch.setenv("DARAJA_CONSUMER_SECRET", "test-secret")
    monkeypatch.setenv("DARAJA_SHORTCODE", "174379")
    monkeypatch.setenv("DARAJA_PASSKEY", "test-passkey")
    monkeypatch.setenv("DARAJA_CALLBACK_BASE_URL", "https://sample.example")
    monkeypatch.setenv("DARAJA_TRANSACTION_TYPE", "CustomerPayBillOnline")
    return Settings()


def test_daraja_client_requires_explicit_configuration(monkeypatch):
    monkeypatch.setenv("PAYMENT_PROVIDER", "none")
    with pytest.raises(DarajaUnavailable):
        DarajaClient(Settings())


def test_stk_push_uses_sandbox_and_integer_kes(monkeypatch):
    settings = configured(monkeypatch)
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("/oauth/v1/generate"):
            return httpx.Response(200, json={"access_token": "sandbox-token"})
        return httpx.Response(200, json={
            "ResponseCode": "0", "CheckoutRequestID": "ws_CO_123", "MerchantRequestID": "mr_1"
        })

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            async with DarajaClient(settings, http) as daraja:
                result = await daraja.initiate_stk_push(
                    phone_number="0712345678", amount=Decimal("250"),
                    account_reference="EVEN123", description="Event ticket",
                )
        return result

    response = asyncio.run(run())
    assert response["CheckoutRequestID"] == "ws_CO_123"
    assert "sandbox.safaricom.co.ke" in str(seen[0].url)
    sent = json.loads(seen[1].content)
    assert sent["Amount"] == 250
    assert sent["PhoneNumber"] == "254712345678"
    assert sent["CallBackURL"] == "https://sample.example/api/v1/payments/daraja/callback"


def test_stk_push_rejects_fractional_kes(monkeypatch):
    settings = configured(monkeypatch)
    async def run():
        async with DarajaClient(settings, httpx.AsyncClient()) as daraja:
            await daraja.initiate_stk_push(
                phone_number="0712345678", amount=Decimal("250.50"),
                account_reference="EVEN123", description="Event ticket",
            )
    with pytest.raises(ValueError, match="whole-shilling"):
        asyncio.run(run())
