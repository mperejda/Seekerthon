import base64

import pytest

from app.services import solana_service
from app.services.solana_service import SkrBalances, get_skr_balance


WALLET = "11111111111111111111111111111111"
SHARE_PRICE = 1_112_736_759
SHARES = 13_093_093_698


def _stake_config(share_price: int = SHARE_PRICE) -> bytes:
    data = bytearray(193)
    data[:8] = bytes([238, 151, 43, 3, 11, 151, 63, 176])
    data[137:153] = share_price.to_bytes(16, "little")
    return bytes(data)


def _user_stake(shares: int = SHARES) -> bytes:
    data = bytearray(169)
    data[:8] = bytes([102, 53, 163, 107, 9, 138, 87, 153])
    data[105:121] = shares.to_bytes(16, "little")
    return bytes(data)


def _b64(data: bytes) -> list[str]:
    return [base64.b64encode(data).decode("ascii"), "base64"]


@pytest.mark.asyncio
async def test_get_skr_balance_matches_official_share_math(monkeypatch):
    async def fake_rpc(method, params, rpc_url):
        if method == "getTokenAccountsByOwner":
            return {
                "result": {
                    "value": [
                        {
                            "account": {
                                "data": {
                                    "parsed": {
                                        "info": {
                                            "tokenAmount": {
                                                "amount": "544267204",
                                                "decimals": 6,
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    ]
                }
            }
        if method == "getAccountInfo":
            return {"result": {"value": {"data": _b64(_stake_config())}}}
        if method == "getProgramAccounts":
            return {
                "result": [
                    {"account": {"data": _b64(_user_stake())}},
                ]
            }
        raise AssertionError(f"Unexpected RPC method: {method}")

    monkeypatch.setattr(solana_service, "_rpc_post", fake_rpc)

    balances = await get_skr_balance(WALLET)

    assert balances.liquid_raw == 544_267_204
    assert balances.liquid_display == "544.267204"
    assert balances.staked_raw == 14_569_166_646
    assert balances.staked_display == "14569.166646"
    assert balances.staked_whole == 14_569


@pytest.mark.asyncio
async def test_get_skr_balance_rejects_wrong_stake_config(monkeypatch):
    bad_config = bytearray(_stake_config())
    bad_config[0] ^= 0xFF

    async def fake_rpc(method, params, rpc_url):
        if method == "getTokenAccountsByOwner":
            return {"result": {"value": []}}
        if method == "getAccountInfo":
            return {"result": {"value": {"data": _b64(bytes(bad_config))}}}
        raise AssertionError(f"Unexpected RPC method: {method}")

    monkeypatch.setattr(solana_service, "_rpc_post", fake_rpc)

    with pytest.raises(RuntimeError, match="discriminator"):
        await get_skr_balance(WALLET)


@pytest.mark.asyncio
async def test_rpc_json_error_raises_instead_of_becoming_zero(monkeypatch):
    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"error": {"code": -32000, "message": "upstream unavailable"}}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, rpc_url, json):
            return FakeResponse()

    monkeypatch.setattr(solana_service.httpx, "AsyncClient", lambda timeout: FakeClient())

    with pytest.raises(RuntimeError, match="upstream unavailable"):
        await solana_service._rpc_post("getBalance", [WALLET])


def test_cached_whole_balance_has_stable_display_value():
    balances = SkrBalances.from_whole(544, 14_569)

    assert balances.liquid_display == "544"
    assert balances.staked_display == "14569"
