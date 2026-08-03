#!/usr/bin/env python3
"""skiff — the pre-flight gate. A run does not start until the user types the
current run's go word.

**Why a script and not the orchestrating model's own judgment.** A model asked to
"pick a random word" is not random. It converges on the same handful of words
within a few runs, and the moment the word becomes predictable the gate stops
being a gate — the user types it from muscle memory without reading what is
above it. ``random.SystemRandom`` is not predictable. The unpredictability IS
the mechanism: the user has to read to the end to find out what to type.

Design rules enforced here rather than left to prose:

- **Fresh word per run**, and fresh again on any re-confirmation after a change.
  The point is a deliberate read of the CURRENT state.
- **Never gibberish.** Drawn from a curated list of common English words, 4-8
  letters, one word, no tricky spelling — typeable correctly on the first try.
- **Case-insensitive, whitespace-tolerant.** Do not make the user fight
  capitalisation.
- **A wrong word is not a refusal.** A failed check leaves the gate ARMED and
  increments a counter; the caller re-shows the word and waits. A typo must
  never be read as "no".
- **Only the go word starts the run.** Not "yes", not "ok", not a bare Enter.

stdlib only.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# --------------------------------------------------------------------------- #
# the curated word list
# --------------------------------------------------------------------------- #
# Common, unambiguous English words. 4-8 letters, single word, no tricky
# spelling. A nautical set fits the plugin. Extend freely — the only hard
# requirements are that a word be typeable correctly on the first attempt
# without squinting, and that the list stay long enough that consecutive runs
# rarely collide.
GO_WORDS: tuple[str, ...] = (
    # the spec's ten
    "ANCHOR", "BEACON", "COMPASS", "HARBOR", "KEEL",
    "LANTERN", "RUDDER", "TIDE", "VOYAGE", "PIER",
    # extensions, same constraints
    "CARGO", "CHART", "DECK", "DRIFT", "HULL",
    "KAYAK", "LAGOON", "MARINA", "MAST", "OCEAN",
    "PADDLE", "RAFT", "REEF", "SHORE",
)

STATE_DIRNAME = ".skiff"
STATE_FILENAME = "run-state.json"

ON_FAILURE_CHOICES = ("ask", "stop", "escalate")

_rng = random.SystemRandom()


def state_path(workspace: Path) -> Path:
    return Path(workspace) / STATE_DIRNAME / STATE_FILENAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def pick_go_word(exclude: Optional[str] = None) -> str:
    """A fresh go word, never equal to ``exclude``.

    Excluding the previous word matters on re-confirmation: if a change produced
    the SAME word, the user could type it from the prior screen without reading
    the amended readback, which is the exact failure this gate exists to prevent.
    """
    pool = [w for w in GO_WORDS if w != (exclude or "").strip().upper()]
    if not pool:  # pragma: no cover — only if GO_WORDS were reduced to one
        pool = list(GO_WORDS)
    return _rng.choice(pool)


def normalize(typed: str) -> str:
    """Case-insensitive, whitespace-tolerant comparison form."""
    return (typed or "").strip().upper()


def matches(typed: str, expected: str) -> bool:
    return bool(expected) and normalize(typed) == normalize(expected)


def read_state(workspace: Path) -> Optional[dict]:
    p = state_path(workspace)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_state(workspace: Path, state: dict) -> Path:
    p = state_path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return p


def arm(workspace: Path, on_failure: str = "ask", summary: str = "",
        reconfirm: bool = False) -> dict:
    """Pick a fresh go word and arm the gate. Returns the new state.

    ``reconfirm=True`` is the after-a-change path: it excludes the current word
    so the user cannot satisfy the gate from the previous screen.
    """
    if on_failure not in ON_FAILURE_CHOICES:
        raise ValueError(
            f"on_failure must be one of {', '.join(ON_FAILURE_CHOICES)}; got {on_failure!r}"
        )
    prior = read_state(workspace) or {}
    exclude = prior.get("go_word") if reconfirm else None
    state = {
        "go_word": pick_go_word(exclude=exclude),
        "armed": True,
        "started": False,
        "on_failure": on_failure,
        "summary": summary,
        "armed_at": _now(),
        "wrong_attempts": 0,
        "reconfirm_count": prior.get("reconfirm_count", 0) + (1 if reconfirm else 0),
    }
    write_state(workspace, state)
    return state


def check(workspace: Path, typed: str) -> dict:
    """Compare ``typed`` against the armed word.

    Returns ``{"ok": bool, "reason": str, ...}``. A miss leaves the gate ARMED —
    a mistyped word is more conversation, never a refusal.
    """
    state = read_state(workspace)
    if not state:
        return {"ok": False, "reason": "not-armed",
                "message": "No pre-flight is armed for this workspace. Arm one first."}
    if not state.get("armed"):
        return {"ok": False, "reason": "not-armed",
                "message": "The pre-flight gate is not armed."}
    if matches(typed, state.get("go_word", "")):
        state["armed"] = False
        state["started"] = True
        state["started_at"] = _now()
        write_state(workspace, state)
        return {"ok": True, "reason": "match", "on_failure": state.get("on_failure"),
                "message": "Go word accepted. The run may start."}
    state["wrong_attempts"] = int(state.get("wrong_attempts", 0)) + 1
    write_state(workspace, state)
    return {
        "ok": False,
        "reason": "mismatch",
        "wrong_attempts": state["wrong_attempts"],
        "go_word": state.get("go_word"),
        "message": (
            "That is not the go word for this run. This is NOT a refusal — "
            "re-show the word plainly and keep talking."
        ),
    }


def bypass(workspace: Path, on_failure: str = "ask", summary: str = "") -> dict:
    """The one documented bypass (``--yes``) — for scripted or repeat runs.

    Must be explicit. Never a default. Recorded in state so the run report can
    say the gate was skipped rather than passed.
    """
    if on_failure not in ON_FAILURE_CHOICES:
        raise ValueError(
            f"on_failure must be one of {', '.join(ON_FAILURE_CHOICES)}; got {on_failure!r}"
        )
    state = {
        "go_word": None,
        "armed": False,
        "started": True,
        "bypassed": True,
        "on_failure": on_failure,
        "summary": summary,
        "armed_at": _now(),
        "started_at": _now(),
        "wrong_attempts": 0,
        "reconfirm_count": 0,
    }
    write_state(workspace, state)
    return state


def _cli(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="preflight", description=__doc__.splitlines()[0])
    ap.add_argument("--workspace", default=".", type=Path)
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("arm", help="pick a fresh go word and arm the gate")
    a.add_argument("--on-failure", default="ask", choices=ON_FAILURE_CHOICES)
    a.add_argument("--summary", default="")
    a.add_argument("--reconfirm", action="store_true",
                   help="after a change: exclude the current word")

    c = sub.add_parser("check", help="test a typed word against the armed one")
    c.add_argument("word")

    sub.add_parser("show", help="print the current state")

    y = sub.add_parser("bypass", help="the documented --yes bypass")
    y.add_argument("--on-failure", default="ask", choices=ON_FAILURE_CHOICES)
    y.add_argument("--summary", default="")

    sub.add_parser("words", help="print the curated word list")

    ns = ap.parse_args(argv)

    if ns.cmd == "arm":
        print(json.dumps(arm(ns.workspace, ns.on_failure, ns.summary, ns.reconfirm),
                         indent=2, sort_keys=True))
    elif ns.cmd == "check":
        res = check(ns.workspace, ns.word)
        print(json.dumps(res, indent=2, sort_keys=True))
        return 0 if res["ok"] else 1
    elif ns.cmd == "show":
        st = read_state(ns.workspace)
        print(json.dumps(st, indent=2, sort_keys=True) if st else "{}")
        return 0 if st else 1
    elif ns.cmd == "bypass":
        print(json.dumps(bypass(ns.workspace, ns.on_failure, ns.summary),
                         indent=2, sort_keys=True))
    elif ns.cmd == "words":
        print("\n".join(GO_WORDS))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_cli())
