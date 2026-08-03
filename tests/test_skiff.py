"""skiff — the light lane.

Pins the three mechanisms that make skiff different from the other pipelines,
because each one silently degrades into the parent's behavior if it breaks:

1. The pre-flight go word (a run cannot start by reflex).
2. The model tier table (spend is looked up, never decided at runtime).
3. The stop-by-default failure rule (escalation is consented, never automatic).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from tests.helpers import frontmatter

REPO_ROOT = Path(__file__).resolve().parent.parent
SKIFF_SCRIPTS = REPO_ROOT / "scripts" / "skiff"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"skiff_{name}", SKIFF_SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def tiers():
    return _load("tiers")


@pytest.fixture(scope="module")
def preflight():
    return _load("preflight")


# --------------------------------------------------------------------------- #
# the tier table
# --------------------------------------------------------------------------- #

def test_table_covers_all_39_agent_roles(tiers) -> None:
    assert len(tiers.TIERS) == 39, sorted(tiers.TIERS)


def test_every_agent_on_disk_that_the_table_names_actually_exists(tiers) -> None:
    """A tier entry for a role with no agent file is a typo waiting to mis-dispatch."""
    on_disk = {p.stem for p in (REPO_ROOT / "agents").glob("*.md")}
    # `backend` / `frontend` / `integration` etc. are agent files; every table key
    # should resolve to one. Report the whole delta so a rename is obvious.
    missing = sorted(r for r in tiers.TIERS if r not in on_disk)
    assert not missing, f"tier table names roles with no agent file: {missing}"


def test_no_role_is_pinned_to_fable(tiers) -> None:
    """skiff is the fable-free lane. Fable is ~2x Opus 5."""
    assert not [r for r, t in tiers.TIERS.items() if t == "fable"]


def test_fable_is_unreachable_on_a_normal_run(tiers) -> None:
    """The fable-free property, stated as the invariant that actually holds:
    at the default ceiling no role dispatches fable and nothing can escalate
    into it. Not a special case in `model_for` — a consequence of the table."""
    assert tiers.DEFAULT_CEILING == "opus"
    for role in tiers.TIERS:
        assert tiers.model_for(role) != "fable", role
        assert tiers.escalate(tiers.tier_for(role)) != "fable", role


def test_fable_needs_an_explicit_ceiling_raise(tiers) -> None:
    """The documented escape hatch still works — it just cannot happen by
    default, by inference, or from a sub-skill."""
    assert tiers.escalate("opus", ceiling="fable") == "fable"


def test_ceiling_is_enforced_at_dispatch_not_just_documented(tiers) -> None:
    """Protects the path where a tier was assembled some other way — an
    escalation result, a config file, a hand-passed override."""
    assert tiers.assert_within_ceiling("opus") == "opus"
    with pytest.raises(tiers.CeilingExceeded):
        tiers.assert_within_ceiling("fable")
    with pytest.raises(tiers.CeilingExceeded):
        tiers.assert_within_ceiling("opus", ceiling="sonnet")


def test_ceiling_clamps_rather_than_raises(tiers) -> None:
    """A lowered ceiling degrades cost, which is safe."""
    assert tiers.model_for("backend", ceiling="haiku") == "haiku"
    assert tiers.model_for("backend") == "opus"


def test_unknown_role_falls_back_to_the_ceiling_not_the_floor(tiers) -> None:
    """An unmeasured role is not a cheap role. Guessing cheap degrades quality."""
    assert tiers.tier_for("a-role-that-does-not-exist") == tiers.DEFAULT_CEILING


def test_escalation_is_exactly_one_step_and_stops_at_the_ceiling(tiers) -> None:
    assert tiers.escalate("haiku") == "sonnet"
    assert tiers.escalate("sonnet") == "opus"
    assert tiers.escalate("opus") is None          # at the ceiling
    assert tiers.escalate("haiku", ceiling="haiku") is None


def test_lookup_is_deterministic(tiers) -> None:
    """Same request twice must produce the same tier assignment."""
    roles = sorted(tiers.TIERS)
    first = [tiers.model_for(r) for r in roles]
    second = [tiers.model_for(r) for r in roles]
    assert first == second


def test_the_two_flagged_assignments_are_recorded(tiers) -> None:
    """Both are cheap-tier roles whose output gates something."""
    assert set(tiers.WATCH_ROLES) == {"qa-replayer", "bug-classifier"}
    assert tiers.TIERS["qa-replayer"] == "haiku"
    assert tiers.TIERS["bug-classifier"] == "sonnet"


# --------------------------------------------------------------------------- #
# the cost preview — this string is read out to the user
# --------------------------------------------------------------------------- #

_BANNED = (
    "phase", "dispatch", "coverage map", "oracle", "parity verb", "vao",
    "ralph loop", "solution requirement", "fan-out", "convergence", "gate",
    "orchestrator", "agent tier",
)


def test_cost_preview_is_plain_english(tiers) -> None:
    line = tiers.format_preview(tiers.preview(["backend", "frontend", "qa-replayer"]))
    low = line.lower()
    hits = [w for w in _BANNED if w in low]
    assert not hits, f"cost preview leaks jargon into the readback: {hits} in {line!r}"
    assert "3 helpers" in line


def test_cost_preview_counts_and_mix(tiers) -> None:
    p = tiers.preview(["backend", "frontend", "qa-replayer"])
    assert p["agent_count"] == 3
    assert p["mix"] == {"haiku": 1, "opus": 2}
    assert p["watch"] == ["qa-replayer"]


# --------------------------------------------------------------------------- #
# the pre-flight go word
# --------------------------------------------------------------------------- #

def test_go_words_are_typeable(preflight) -> None:
    """Never gibberish: one word, 4-8 letters, alphabetic."""
    for w in preflight.GO_WORDS:
        assert w.isalpha() and w.isupper(), w
        assert 4 <= len(w) <= 8, f"{w} is {len(w)} letters"
    assert len(set(preflight.GO_WORDS)) == len(preflight.GO_WORDS)


def test_word_varies_across_runs(preflight) -> None:
    """A constant word becomes muscle memory and stops being a check."""
    seen = {preflight.pick_go_word() for _ in range(60)}
    assert len(seen) > 1, "go word is not varying"


def test_reconfirm_never_reuses_the_current_word(preflight, tmp_path) -> None:
    """Else the user could satisfy the check from the previous screen."""
    first = preflight.arm(tmp_path, on_failure="stop")["go_word"]
    for _ in range(25):
        again = preflight.arm(tmp_path, on_failure="stop", reconfirm=True)["go_word"]
        assert again != first
        first = again


def test_only_the_go_word_starts_the_run(preflight, tmp_path) -> None:
    preflight.arm(tmp_path, on_failure="stop")
    for reflex in ("yes", "ok", "", "  ", "y", "sure", "go"):
        assert not preflight.check(tmp_path, reflex)["ok"], reflex


def test_a_wrong_word_is_not_a_refusal(preflight, tmp_path) -> None:
    """A typo must leave the gate armed and be treated as more conversation."""
    preflight.arm(tmp_path, on_failure="stop")
    res = preflight.check(tmp_path, "not-the-word")
    assert res["ok"] is False and res["reason"] == "mismatch"
    assert res["wrong_attempts"] == 1
    assert preflight.read_state(tmp_path)["armed"] is True


def test_match_is_case_and_whitespace_tolerant(preflight, tmp_path) -> None:
    word = preflight.arm(tmp_path, on_failure="stop")["go_word"]
    assert preflight.check(tmp_path, f"  {word.lower()} \n")["ok"]


def test_success_consumes_the_gate_and_carries_the_failure_answer(preflight, tmp_path) -> None:
    """Beat 3's answer sets the run's behavior — it is never asked twice."""
    word = preflight.arm(tmp_path, on_failure="escalate")["go_word"]
    res = preflight.check(tmp_path, word)
    assert res["ok"] and res["on_failure"] == "escalate"
    state = preflight.read_state(tmp_path)
    assert state["armed"] is False and state["started"] is True


def test_the_default_failure_behavior_is_stop_not_escalate(preflight, tmp_path) -> None:
    """Escalation is consented. `ask` means the readback asks; it never assumes."""
    assert preflight.arm(tmp_path)["on_failure"] == "ask"
    with pytest.raises(ValueError):
        preflight.arm(tmp_path, on_failure="whatever")


def test_bypass_is_recorded_as_skipped_not_passed(preflight, tmp_path) -> None:
    state = preflight.bypass(tmp_path, on_failure="stop")
    assert state["bypassed"] is True and state["go_word"] is None
    assert state["started"] is True


# --------------------------------------------------------------------------- #
# the shipped files
# --------------------------------------------------------------------------- #

def test_skill_and_command_frontmatter_valid() -> None:
    skill = REPO_ROOT / "skills" / "skiff-pipeline" / "SKILL.md"
    cmd = REPO_ROOT / "commands" / "skiff.md"
    sfm, sbody = frontmatter.parse(skill)
    cfm, cbody = frontmatter.parse(cmd)
    assert sfm["name"] == "skiff-pipeline"
    assert len(sfm["description"]) <= 1024
    assert len(cfm["description"]) <= 1024
    assert sbody.lstrip().startswith("# ")
    assert cbody.lstrip().startswith("# ")


def test_skill_records_which_parent_conventions_it_depends_on() -> None:
    """Every borrowed convention is a line to re-sync later; the list stays short
    and stays written down."""
    body = (REPO_ROOT / "skills" / "skiff-pipeline" / "SKILL.md").read_text(encoding="utf-8")
    assert "What skiff borrows from the rest of the plugin" in body
    assert "common-pipeline-conventions" in body
    assert "reuse-first-design" in body


def test_glossary_and_quickstart_ship() -> None:
    for name in ("GLOSSARY.md", "QUICKSTART.md"):
        p = REPO_ROOT / "docs" / "skiff" / name
        assert p.exists() and p.stat().st_size > 500, name
