"""Tests for hermes_screener.dashboard (static HTML approach)."""

import os
import json
import pytest

os.environ.setdefault("HERMES_HOME", "/tmp/test_hermes")
for key in ["COINGECKO_API_KEY", "ETHERSCAN_API_KEY", "GMGN_API_KEY", "SURF_API_KEY",
            "DEFI_API_KEY", "ZERION_API_KEY", "COINSTATS_API_KEY"]:
    os.environ.pop(key, None)


@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient
    os.environ["HERMES_HOME"] = str(tmp_path)
    (tmp_path / "data" / "token_screener").mkdir(parents=True)
    json.dump({
        "generated_at_iso": "2026-04-14T12:00:00Z",
        "total_candidates": 50,
        "enriched": 32,
        "tokens": [
            {"contract_address": "TEST123", "chain": "solana", "symbol": "TEST", "name": "Test",
             "score": 85.5, "channel_count": 5, "mentions": 10, "fdv": 1000000,
             "volume_h24": 500000, "volume_h1": 25000, "age_hours": 12.5,
             "price_change_h1": 5.2, "price_change_h6": -2.1,
             "gmgn_smart_wallets": 3, "positives": ["social HOT"], "negatives": [],
             "dex_url": "https://dexscreener.com/solana/TEST123"},
            {"contract_address": "LOW456", "chain": "base", "symbol": "LOW", "name": "Low",
             "score": 15.0, "channel_count": 1, "mentions": 1, "fdv": 5000,
             "volume_h24": 1000, "volume_h1": 100, "age_hours": 48.0,
             "price_change_h1": -10.0, "price_change_h6": -25.0,
             "positives": [], "negatives": ["low vol"]},
        ],
    }, open(tmp_path / "data" / "token_screener" / "top100.json", "w"))

    from importlib import reload
    from hermes_screener import config
    reload(config)
    from hermes_screener.dashboard import app
    reload(app)
    return TestClient(app.app)


def test_index(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Token Leaderboard" in r.text
    assert "TEST" in r.text


def test_scores(client):
    r = client.get("/")
    assert "85.5" in r.text
    assert "15.0" in r.text


def test_chains(client):
    r = client.get("/")
    assert "solana" in r.text
    assert "base" in r.text


def test_api_top100(client):
    r = client.get("/api/top100")
    assert r.status_code == 200
    d = r.json()
    assert len(d["tokens"]) == 2


def test_api_stats(client):
    r = client.get("/api/stats")
    assert r.status_code == 200
    assert r.json()["tokens_scored"] == 2


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_token_detail(client):
    r = client.get("/token/TEST123")
    assert r.status_code == 200
    assert "TEST" in r.text
    assert "85.5" in r.text


def test_token_not_found(client):
    r = client.get("/token/UNKNOWN")
    assert r.status_code == 200
    assert "Not Found" in r.text


def test_wallets_page(client):
    r = client.get("/wallets")
    assert r.status_code == 200
    assert "Smart Money" in r.text
