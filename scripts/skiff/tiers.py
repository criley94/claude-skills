#!/usr/bin/env python3
"""skiff — model tier lookup, ceiling enforcement, escalation, and cost preview.

The point of this module is that **the orchestrator looks the model up; it does
not decide the model at runtime.** Runtime judgment makes spend unpredictable,
which is the problem skiff exists to solve. The same request twice must produce
the same tier assignment, so the table is a literal and the lookup is total.

Three rules live here and nowhere else:

1. **The ceiling.** No role dispatches above ``DEFAULT_CEILING`` (Opus 5) unless
   the invoking command passed an explicit raise. Never inferred, never raised
   by a sub-skill, enforced at the moment of dispatch.
2. **Escalate one step, once.** A role that returns a failure or an explicit
   low-confidence verdict may retry exactly one tier up, one time, and the retry
   is logged. Never two steps, never above the ceiling, never silent.
3. **No fable.** ``fable`` appears in the tier order only because the ceiling
   logic has to be able to name it. skiff never selects it; ``model_for``
   refuses to return it.

The mechanism this rests on: an agent file's ``model:`` line is a DEFAULT, not a
lock. Whatever launches the agent names the model, and that beats the file. So
skiff names a model on every dispatch and edits no agent file — nothing to be
overwritten by a plugin update, no self-heal hook needed.

stdlib only.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Iterable, Optional

# --------------------------------------------------------------------------- #
# the tier order
# --------------------------------------------------------------------------- #
# Ascending cost/capability. The cost fact that drives the whole table: fable is
# ~2x Opus 5. Every role skiff runs sits at or below Opus 5, so nothing skiff
# dispatches costs more than the parent pipeline does today — including the 13
# roles that stay on Opus 5. No role is traded down in quality to save money.
TIER_ORDER: tuple[str, ...] = ("haiku", "sonnet", "opus", "fable")

DEFAULT_CEILING = "opus"

# What the Agent tool's `model` parameter accepts.
DISPATCH_ALIAS: dict[str, str] = {
    "haiku": "haiku",
    "sonnet": "sonnet",
    "opus": "opus",
    "fable": "fable",
}

# Full model ids — for the run report, not for dispatch.
MODEL_IDS: dict[str, str] = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-5",
    "opus": "claude-opus-5",
    "fable": "claude-fable-5",
}

# --------------------------------------------------------------------------- #
# the table — v1, all 39 agent roles
# --------------------------------------------------------------------------- #
# Re-tier from OBSERVED RETRY RATES, not from argument. A role that routinely
# escalates moves up; a role that never escalates gets tested one step down.
# The run report emits the per-role retry rate that feeds that decision.

_OPUS_ROLES: tuple[str, ...] = (
    "backend",                 # writes production code
    "frontend",                # writes production code
    "integration",             # cross-layer code + integration tests
    "mini-qa",                 # authors tests, renders the gating verdict
    "task-reviewer",           # judges shipped code, runs linters and tests
    "system-architect",        # architecture, master-review audit
    "structure-analyst",       # designs restructures
    "structure-adversary",     # refutation
    "adversarial-reviewer",    # catches what the producer missed
    "diagnostic-researcher",   # root-cause across a full code flow
    "reconciler",              # semantic merge of parallel work
    "master-synthesizer",      # collapses drafts into the canonical artifact
    "mcp-design-agent",        # designs output contracts
)

_SONNET_ROLES: tuple[str, ...] = (
    "test-completeness-verifier",
    "bug-classifier",
    "bug-replicator",
    "fix-sensibility-checker",
    "route-mapper",
    "endpoint-tracer",
    "interaction-intuiter",
    "editability-reviewer",
    "interaction-reviewer",
    "integration-explorer",
    "domain-researcher",
    "flow-explorer",
    "oracle-deriver",
    "prompt-refiner",
    "doc-updater",
    "closeout-agent",
    "scaffold-agent",
)

# Mechanical by the repo's own agent descriptions — capture, count, classify,
# re-run. No judgment in their contracts.
_HAIKU_ROLES: tuple[str, ...] = (
    "visual-capture",
    "visual-analyzer",
    "test-run-watcher",
    "reference-tracer",
    "flow-executor",
    "interaction-observer",
    "codebase-map-reviewer",
    "monitor-synthesizer",
    "qa-replayer",
)

TIERS: dict[str, str] = {
    **{r: "opus" for r in _OPUS_ROLES},
    **{r: "sonnet" for r in _SONNET_ROLES},
    **{r: "haiku" for r in _HAIKU_ROLES},
}

# Two assignments to verify before trusting the table. Both are cheap-tier roles
# whose OUTPUT GATES SOMETHING, which is exactly where an under-tier is expensive
# rather than economical. Watch their retry rate specifically.
WATCH_ROLES: dict[str, str] = {
    "qa-replayer": (
        "at haiku — its contract forbids judgment, but it emits a verdict that "
        "gates the run. Move to sonnet if the retry rate is high."
    ),
    "bug-classifier": (
        "at sonnet — simple work, but it picks which pipeline the run enters. "
        "Only test haiku with the retry rate watched."
    ),
}

# The fallback tier for a role skiff has never seen. Deliberately the CEILING,
# not the floor: an unknown role is unmeasured, and guessing cheap on unmeasured
# work is how quality silently degrades. Cost control comes from the table, not
# from optimism about roles that are not in it.
UNKNOWN_ROLE_TIER = DEFAULT_CEILING


class CeilingExceeded(ValueError):
    """Raised when a dispatch would exceed the run's model ceiling."""


def _rank(tier: str) -> int:
    try:
        return TIER_ORDER.index(tier)
    except ValueError:
        raise ValueError(
            f"unknown tier {tier!r}; expected one of {', '.join(TIER_ORDER)}"
        ) from None


def tier_for(role: str) -> str:
    """The table's tier for ``role``. Unknown roles fall back to the ceiling."""
    return TIERS.get(role, UNKNOWN_ROLE_TIER)


def model_for(role: str, ceiling: str = DEFAULT_CEILING) -> str:
    """The dispatch alias for ``role``, clamped to ``ceiling``.

    Clamping rather than raising is deliberate: the table is data, and a future
    edit could put a role above a lowered ceiling. A clamp degrades cost, which
    is safe. Nothing here can raise a role ABOVE the ceiling.

    The fable-free property is a consequence of the table plus the default
    ceiling, not of a special case here: no role is tiered to fable, and the
    default ceiling is opus, so fable is unreachable on a normal run. It becomes
    reachable ONLY when the invoking command explicitly raises the ceiling —
    which is the documented escape hatch, not a bug. ``assert_within_ceiling``
    is the hard enforcement point at dispatch.
    """
    tier = tier_for(role)
    if _rank(tier) > _rank(ceiling):
        tier = ceiling
    return DISPATCH_ALIAS[tier]


def assert_within_ceiling(tier: str, ceiling: str = DEFAULT_CEILING) -> str:
    """Hard-fail if ``tier`` exceeds ``ceiling``. Call this AT DISPATCH.

    ``model_for`` clamps, which protects the common path. This is the check that
    protects the path where a caller assembled a tier some other way — an
    escalation result, a config file, a hand-passed override. The ceiling is
    enforced at dispatch, not merely documented.
    """
    if _rank(tier) > _rank(ceiling):
        raise CeilingExceeded(
            f"dispatch at {tier!r} exceeds this run's ceiling {ceiling!r}. "
            "Raising the ceiling takes an explicit flag on the invoking command — "
            "never a default, never inferred, never raised by a sub-skill."
        )
    return tier


def escalate(tier: str, ceiling: str = DEFAULT_CEILING) -> Optional[str]:
    """One tier up from ``tier``, or None when already at the ceiling.

    Callers escalate at most ONCE per role per run and must log the retry.
    """
    nxt = _rank(tier) + 1
    if nxt >= len(TIER_ORDER) or _rank(TIER_ORDER[nxt]) > _rank(ceiling):
        return None
    return TIER_ORDER[nxt]


def preview(roles: Iterable[str], ceiling: str = DEFAULT_CEILING) -> dict:
    """Agent count and tier mix for a planned run — the pre-run cost picture."""
    roles = list(roles)
    mix: dict[str, int] = {t: 0 for t in TIER_ORDER}
    unknown: list[str] = []
    for r in roles:
        if r not in TIERS:
            unknown.append(r)
        tier = tier_for(r)
        if _rank(tier) > _rank(ceiling):
            tier = ceiling
        mix[tier] += 1
    return {
        "agent_count": len(roles),
        "mix": {t: n for t, n in mix.items() if n},
        "ceiling": ceiling,
        "roles": roles,
        "unknown_roles": unknown,
        "watch": [r for r in roles if r in WATCH_ROLES],
    }


def format_preview(p: dict) -> str:
    """The preview in plain language — this exact text is shown to the user.

    No invented vocabulary: this string is read out in the pre-flight readback,
    where jargon is banned outright.
    """
    n = p["agent_count"]
    if n == 0:
        return "No helpers needed for this one."
    parts = [f"{cnt} on {tier}" for tier, cnt in p["mix"].items()]
    line = f"{n} helper{'s' if n != 1 else ''}: " + ", ".join(parts) + "."
    if p["unknown_roles"]:
        line += (
            f" ({len(p['unknown_roles'])} I haven't measured before, so I'll use "
            f"the strongest one to be safe.)"
        )
    return line


def _cli(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="tiers", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("table", help="print the whole tier table as JSON")

    m = sub.add_parser("model", help="dispatch alias for one role")
    m.add_argument("role")
    m.add_argument("--ceiling", default=DEFAULT_CEILING, choices=TIER_ORDER)

    e = sub.add_parser("escalate", help="one tier up from the given tier")
    e.add_argument("tier", choices=TIER_ORDER)
    e.add_argument("--ceiling", default=DEFAULT_CEILING, choices=TIER_ORDER)

    p = sub.add_parser("preview", help="agent count + tier mix for a planned run")
    p.add_argument("roles", nargs="+")
    p.add_argument("--ceiling", default=DEFAULT_CEILING, choices=TIER_ORDER)
    p.add_argument("--plain", action="store_true", help="one plain-English line")

    a = ap.parse_args(argv)

    if a.cmd == "table":
        print(json.dumps(
            {"tiers": TIERS, "ceiling": DEFAULT_CEILING, "model_ids": MODEL_IDS,
             "watch": WATCH_ROLES},
            indent=2, sort_keys=True))
    elif a.cmd == "model":
        print(model_for(a.role, a.ceiling))
    elif a.cmd == "escalate":
        nxt = escalate(a.tier, a.ceiling)
        print(nxt if nxt else "")
        return 0 if nxt else 1
    elif a.cmd == "preview":
        pv = preview(a.roles, a.ceiling)
        print(format_preview(pv) if a.plain else json.dumps(pv, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_cli())
