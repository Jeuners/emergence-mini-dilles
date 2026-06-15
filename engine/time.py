"""Time-Dilation framework for Emergence-Mini.

Implements the formal pieces of:
    "Time Dilation in LLM Agent Systems" (Dillenberg 2026)
that are useful inside our own simulation:

- Per-agent proper time τ (Eigenzeit) — monotonic, accumulated from
  reasoning-step weight + tool-call weight.
- Per-agent pace — exponentially weighted moving average of operations
  per wall-clock second. Merged by causal recency, not by max.
- Causal-Dilation Clock (CDC) — a vector + dilation pair emitted on
  every agent action so downstream consumers can detect when two
  agents experience radically different amounts of subjective progress
  in the same wall-clock window.

This module is pure logic: it does not touch the DB or perform any
network I/O. Persistence is the caller's responsibility.
"""
from __future__ import annotations
import math
import time
from dataclasses import dataclass, field
from typing import Dict


# Operation weights from §3.2 of the paper, calibrated for our engine.
W_REASONING_STEP = 1.0
W_TOOL_CALL = 0.5
W_MEMORY_LOOKUP = 0.2
W_REACTIVE = 0.3

# EWMA smoothing factor. Higher = more reactive to recent pace.
PACE_ALPHA = 0.3

# Drift threshold: γ_ij * |τ_a - τ_b| above which we flag a divergence.
DRIFT_THRESHOLD = 3.0


@dataclass
class AgentClock:
    """Causal-Dilation Clock state for one agent (frame-local)."""
    agent_id: str
    tau: float = 0.0                  # cumulative proper time
    pace: float = 0.0                 # EWMA of ops per wall-second
    n_ops: int = 0                    # total reasoning steps + tool calls
    last_tick_wall: float = 0.0       # wall-clock at last update
    history: list = field(default_factory=list)  # [(wall, tau, pace, op)]

    def tick(self, op: str, weight: float = 1.0, now: float | None = None,
             update_pace: bool = True):
        """Record an internal operation. Advances τ and updates the pace
        EWMA. Should be called once per reasoning step / tool call.

        Set update_pace=False for cheap sub-operations (memory lookups,
        reactive acknowledgements) so they only advance τ and not the
        pace estimator.
        """
        now = now if now is not None else time.time()
        if update_pace:
            if self.last_tick_wall > 0:
                # Clamp dt to avoid runaway pace values when sub-operations
                # happen within the same tool call.
                dt = max(min(now - self.last_tick_wall, 60.0), 0.1)
                instant_pace = 1.0 / dt
            else:
                instant_pace = 1.0
            if self.pace <= 0:
                self.pace = instant_pace
            else:
                self.pace = PACE_ALPHA * instant_pace + (1 - PACE_ALPHA) * self.pace
        # Always advance τ
        self.tau += weight
        self.n_ops += 1
        self.last_tick_wall = now
        self.history.append((now, self.tau, self.pace, op))
        if len(self.history) > 200:
            self.history = self.history[-200:]

    def snapshot(self) -> dict:
        """Return a serialisable snapshot of this clock."""
        return {
            "agent_id": self.agent_id,
            "tau": round(self.tau, 3),
            "pace": round(self.pace, 4),
            "n_ops": self.n_ops,
            "last_tick_wall": self.last_tick_wall,
        }

    def history_series(self, n: int = 60):
        """Return the last n (wall, tau) points for plotting."""
        return [(round(w, 1), round(t, 3)) for w, t, _, _ in self.history[-n:]]


class ClockRegistry:
    """Holds the per-agent clocks. One global instance lives in turn.py."""

    def __init__(self):
        self._clocks: Dict[str, AgentClock] = {}

    def get(self, agent_id: str) -> AgentClock:
        if agent_id not in self._clocks:
            self._clocks[agent_id] = AgentClock(agent_id=agent_id)
        return self._clocks[agent_id]

    def all(self):
        return list(self._clocks.values())

    def reset(self, agent_id: str):
        self._clocks.pop(agent_id, None)

    def snapshot_all(self) -> dict:
        return {c.agent_id: c.snapshot() for c in self._clocks.values()}

    def tau_vector(self) -> dict:
        """The D component of the Causal-Dilation Clock: {agent_id: τ}."""
        return {a: c.tau for a, c in self._clocks.items()}

    def gamma(self, src: str, dst: str) -> float:
        """Heuristic frame transformation γ_{src→dst} from pace ratio.

        γ = pace(src) / pace(dst).  >1 means src is "faster" than dst.
        """
        a = self.get(src)
        b = self.get(dst)
        if a.pace <= 0 or b.pace <= 0:
            return 1.0
        return a.pace / b.pace

    def transform(self, src: str, dst: str, tau: float | None = None) -> float:
        """Φ_{src→dst}(τ_src) = γ * τ_src."""
        if tau is None:
            tau = self.get(src).tau
        return self.gamma(src, dst) * tau

    def drift_report(self) -> dict:
        """Compute pairwise drift across all live agents. A pair is
        'divergent' when |τ_a - Φ(τ_b)| > DRIFT_THRESHOLD."""
        clocks = self.all()
        if len(clocks) < 2:
            return {"pairs": [], "max_drift": 0.0, "threshold": DRIFT_THRESHOLD}
        pairs = []
        max_drift = 0.0
        for i, a in enumerate(clocks):
            for b in clocks[i + 1:]:
                gamma = self.gamma(a.agent_id, b.agent_id)
                tau_b_in_a = self.transform(b.agent_id, a.agent_id)
                diff = abs(a.tau - tau_b_in_a)
                if diff > max_drift:
                    max_drift = diff
                pairs.append({
                    "a": a.agent_id, "b": b.agent_id,
                    "tau_a": round(a.tau, 3),
                    "tau_b": round(b.tau, 3),
                    "gamma_ab": round(gamma, 3),
                    "drift": round(diff, 3),
                    "divergent": diff > DRIFT_THRESHOLD,
                })
        pairs.sort(key=lambda p: -p["drift"])
        return {
            "pairs": pairs,
            "max_drift": round(max_drift, 3),
            "threshold": DRIFT_THRESHOLD,
        }


# Module-level singleton; engine imports and uses this.
registry = ClockRegistry()


def record_reasoning(agent_id: str):
    registry.get(agent_id).tick("reasoning", W_REASONING_STEP)


def record_tool_call(agent_id: str):
    registry.get(agent_id).tick("tool_call", W_TOOL_CALL)


def record_memory_lookup(agent_id: str):
    # sub-op: advance τ but do not perturb pace
    registry.get(agent_id).tick("memory_lookup", W_MEMORY_LOOKUP, update_pace=False)


def record_reactive(agent_id: str):
    # sub-op: same reasoning
    registry.get(agent_id).tick("reactive", W_REACTIVE, update_pace=False)
