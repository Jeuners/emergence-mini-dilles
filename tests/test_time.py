"""Time-dilation framework tests (τ tracker, EWMA pace, CDC)."""
import time


def test_tau_starts_at_zero():
    from engine import time as time_mod
    c = time_mod.AgentClock("a")
    assert c.tau == 0.0
    assert c.pace == 0.0
    assert c.n_ops == 0


def test_tau_monotonic():
    from engine import time as time_mod
    c = time_mod.AgentClock("a")
    t0 = 1000.0
    c.tick("reasoning", 1.0, now=t0)
    c.tick("tool_call", 0.5, now=t0 + 1)
    c.tick("reasoning", 1.0, now=t0 + 2)
    assert c.tau == 2.5
    assert c.n_ops == 3
    assert c.tau >= 0  # monotonic non-decreasing


def test_tau_weight_per_op():
    from engine import time as time_mod
    c = time_mod.AgentClock("a")
    c.tick("reasoning", time_mod.W_REASONING_STEP)
    c.tick("tool_call", time_mod.W_TOOL_CALL)
    c.tick("memory_lookup", time_mod.W_MEMORY_LOOKUP)
    c.tick("reactive", time_mod.W_REACTIVE)
    expected = (time_mod.W_REASONING_STEP + time_mod.W_TOOL_CALL
               + time_mod.W_MEMORY_LOOKUP + time_mod.W_REACTIVE)
    assert abs(c.tau - expected) < 1e-6


def test_pace_ewma_initialized_on_first_tick():
    from engine import time as time_mod
    c = time_mod.AgentClock("a")
    c.tick("reasoning", 1.0, now=1000.0)
    assert c.pace > 0


def test_pace_ewma_converges():
    from engine import time as time_mod
    c = time_mod.AgentClock("a")
    # Simulate 10 ops at 1 second apart -> pace ~1.0 op/s
    for i in range(10):
        c.tick("r", 1.0, now=1000.0 + i)
    # EWMA should be near 1.0
    assert 0.5 < c.pace < 1.5, f"pace={c.pace}"


def test_pace_ewma_reacts_to_burst():
    from engine import time as time_mod
    c = time_mod.AgentClock("a")
    # slow start
    for i in range(5):
        c.tick("r", 1.0, now=1000.0 + i * 10)  # 10s apart
    slow_pace = c.pace
    # burst
    for i in range(5):
        c.tick("r", 1.0, now=1050.0 + i * 0.1)  # 0.1s apart
    fast_pace = c.pace
    assert fast_pace > slow_pace


def test_history_bounded():
    from engine import time as time_mod
    c = time_mod.AgentClock("a")
    for i in range(500):
        c.tick("r", 0.1, now=1000.0 + i)
    assert len(c.history) <= 200


def test_snapshot_roundtrips():
    from engine import time as time_mod
    c = time_mod.AgentClock("anchor")
    c.tick("r", 1.0, now=1000.0)
    snap = c.snapshot()
    assert snap["agent_id"] == "anchor"
    assert "tau" in snap
    assert "pace" in snap
    assert "n_ops" in snap


def test_registry_get_creates():
    from engine import time as time_mod
    time_mod.registry.reset("a")
    c = time_mod.registry.get("a")
    assert c.agent_id == "a"


def test_registry_singleton_state():
    from engine import time as time_mod
    time_mod.registry.reset("zzz_test")
    time_mod.record_reasoning("zzz_test")
    time_mod.record_tool_call("zzz_test")
    snap = time_mod.registry.snapshot_all()
    assert "zzz_test" in snap
    assert snap["zzz_test"]["tau"] == (time_mod.W_REASONING_STEP + time_mod.W_TOOL_CALL)
    time_mod.registry.reset("zzz_test")


def test_gamma_symmetry_inverse():
    from engine import time as time_mod
    time_mod.registry.reset("p")
    time_mod.registry.reset("q")
    # give them different paces
    for i in range(5):
        time_mod.registry.get("p").tick("r", 1.0, now=1000.0 + i * 0.5)  # 2 ops/s
        time_mod.registry.get("q").tick("r", 1.0, now=1000.0 + i * 2.0)  # 0.5 ops/s
    g_pq = time_mod.registry.gamma("p", "q")
    g_qp = time_mod.registry.gamma("q", "p")
    # γ_pq ≈ 4, γ_qp ≈ 0.25
    assert g_pq > 2.0
    assert g_qp < 0.5
    time_mod.registry.reset("p")
    time_mod.registry.reset("q")


def test_transform_uses_gamma():
    from engine import time as time_mod
    time_mod.registry.reset("a")
    time_mod.registry.reset("b")
    time_mod.registry.get("a").tau = 10.0
    time_mod.registry.get("a").pace = 2.0
    time_mod.registry.get("b").tau = 5.0
    time_mod.registry.get("b").pace = 1.0
    # γ_a->b = 2.0/1.0 = 2.0
    transformed = time_mod.registry.transform("a", "b")
    assert abs(transformed - 20.0) < 1e-6
    time_mod.registry.reset("a")
    time_mod.registry.reset("b")


def test_drift_report_with_divergence():
    from engine import time as time_mod
    time_mod.registry.reset("x")
    time_mod.registry.reset("y")
    # give x much more τ than y, similar pace
    time_mod.registry.get("x").tau = 100.0
    time_mod.registry.get("x").pace = 1.0
    time_mod.registry.get("y").tau = 5.0
    time_mod.registry.get("y").pace = 1.0
    report = time_mod.registry.drift_report()
    assert report["max_drift"] > 90
    assert any(p["divergent"] for p in report["pairs"])
    time_mod.registry.reset("x")
    time_mod.registry.reset("y")


def test_drift_report_empty_with_one_agent():
    from engine import time as time_mod
    # reset everything to ensure isolation
    for c in time_mod.registry.all():
        time_mod.registry.reset(c.agent_id)
    time_mod.registry.get("only")
    time_mod.registry.get("only").tau = 10.0
    report = time_mod.registry.drift_report()
    assert report["pairs"] == []
    assert report["max_drift"] == 0.0
    time_mod.registry.reset("only")
