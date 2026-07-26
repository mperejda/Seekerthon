from app.routers.mint import _format_usdc, _is_confirmed_mint


def test_builder_pass_price_display_uses_raw_usdc_units():
    assert _format_usdc(50_000_000) == "50"


def test_incomplete_builder_pass_ledger_row_is_not_a_successful_retry():
    row = {
        "status": "reconciled_error",
        "mint_pubkey": "",
        "mint_tx_signature": "payment-signature",
        "payment_tx_signature": "payment-signature",
    }

    assert not _is_confirmed_mint(row)


def test_confirmed_builder_pass_ledger_row_is_a_successful_retry():
    row = {
        "status": "confirmed",
        "mint_pubkey": "mint-address",
        "mint_tx_signature": "mint-signature",
        "payment_tx_signature": "payment-signature",
    }

    assert _is_confirmed_mint(row)
