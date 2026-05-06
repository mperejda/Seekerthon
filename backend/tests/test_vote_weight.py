import pytest
import math
from app.services.solana_service import compute_vote_weight


def test_vote_weight_base():
    """0 staked = 1.0x"""
    assert compute_vote_weight(0) == 1.0


def test_vote_weight_100():
    """100 staked = 2.0x"""
    result = compute_vote_weight(100)
    assert abs(result - 2.0) < 0.01


def test_vote_weight_cap():
    """Very large stake is capped at 5.0x"""
    assert compute_vote_weight(1_000_000) == 5.0


def test_vote_weight_monotonic():
    """More stake = more weight"""
    weights = [compute_vote_weight(s) for s in [0, 100, 300, 700, 1500]]
    assert weights == sorted(weights)


def test_vote_weight_formula():
    """Manual formula check for 300 staked"""
    expected = min(1 + math.log2(1 + 300 / 100), 5.0)
    assert abs(compute_vote_weight(300) - round(expected, 4)) < 0.001
