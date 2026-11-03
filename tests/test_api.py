"""API smoke tests against the real app and a real (short) live simulation."""

import time

from fastapi.testclient import TestClient

from evolutionx.api.app import app, live

client = TestClient(app)


def test_live_simulation_endpoints():
    assert client.get("/api/health").json()["real_trading"] is False
    assert client.get("/api/sim/state").json()["status"] in ("idle", "running", "finished", "stopped", "paused")
    r = client.post("/api/sim/start", json={"seed": 3, "duration_s": 600, "speed": 0})
    assert r.status_code == 200 and r.json()["n_agents"] == 256
    for _ in range(100):
        if client.get("/api/sim/state").json()["t_ms"] > 200_000:
            break
        time.sleep(0.05)
    st = client.get("/api/sim/state").json()
    assert st["data_label"] == "synthetic" and st["n_trades"] > 0
    assert len(client.get("/api/sim/agents").json()) == 256
    d = client.get("/api/sim/agents/30").json()
    assert {"params", "lineage", "observable_inputs", "trades", "neighbors"} <= set(d)
    assert client.get("/api/sim/book").json()["bids"]
    assert client.get("/api/sim/candles").json()["candles"]
    assert len(client.get("/api/sim/network").json()["nodes"]) == 256
    assert client.get("/api/sim/collective").json()["clusters"]
    assert client.post("/api/sim/inject", json={"type": "news_panic", "at_s": 0, "magnitude": 4}).status_code == 200
    assert client.post("/api/sim/stop").json()["status"] == "stopped"
    assert client.get("/api/sim/agents/9999").status_code == 404
    live.stop_thread()


def test_validation_errors():
    assert client.post("/api/sim/start", json={"scenario": "nope"}).status_code == 400
    assert client.post("/api/proposals/x/decision", json={"decision": "maybe", "reviewer": "a"}).status_code == 422


def test_job_endpoints_accept_json_body_and_run():
    r = client.post("/api/council/run", json={"question": "what drives spreads?"})
    assert r.status_code == 200, r.text
    jid = r.json()["id"]
    for _ in range(300):
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("finished", "failed"):
            break
        time.sleep(0.1)
    assert j["status"] == "finished", j.get("error")
    assert len(j["result"]["roles"]) == 8
    assert client.post("/api/experiments", json={"scenario": "nope"}).status_code == 400
