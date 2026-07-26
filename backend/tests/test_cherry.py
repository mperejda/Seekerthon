from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from jose import jwt
from starlette.requests import Request

from app.routers import cherry


def make_request(wallet_address: str | None = None) -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/api/v1/cherry-embed-token", "headers": []})
    if wallet_address is not None:
        request.state.wallet_address = wallet_address
    return request


@pytest.mark.asyncio
async def test_embed_token_uses_authenticated_wallet_and_exact_claims(monkeypatch):
    secret = "test-cherry-secret"
    wallet = "11111111111111111111111111111111"
    monkeypatch.setattr(cherry, "get_settings", lambda: SimpleNamespace(cherry_app_secret=secret))
    response = Response()

    result = await cherry.create_cherry_embed_token(make_request(wallet), response)
    claims = jwt.decode(result.token, secret, algorithms=["HS256"])

    assert claims["sub"] == wallet
    assert claims["app_id"] == cherry.CHERRY_APP_ID
    assert claims["exp"] - claims["iat"] == 300
    assert claims["jti"]
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Pragma"] == "no-cache"


@pytest.mark.asyncio
async def test_embed_token_rejects_missing_authenticated_wallet(monkeypatch):
    monkeypatch.setattr(
        cherry,
        "get_settings",
        lambda: SimpleNamespace(cherry_app_secret="test-cherry-secret"),
    )

    with pytest.raises(HTTPException) as error:
        await cherry.create_cherry_embed_token(make_request(), Response())

    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_embed_token_rejects_missing_secret(monkeypatch):
    monkeypatch.setattr(cherry, "get_settings", lambda: SimpleNamespace(cherry_app_secret=""))

    with pytest.raises(HTTPException) as error:
        await cherry.create_cherry_embed_token(make_request("wallet"), Response())

    assert error.value.status_code == 503
