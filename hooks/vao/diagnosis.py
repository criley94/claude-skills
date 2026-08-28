"""VAO diagnosis family (1 tool) — v3.66.0.

``verify-diagnosis-falsified`` is the 24th Layer-3 tool. It answers the one
question a diagnostic plan could not answer about itself before v3.66.0: *was
the leading hypothesis actually put to an executed falsification test — and did
it survive one while its competitors were executed and refuted?*

The originating failures (review 2026-08-28): the diagnostic loop's terminal
artifact was a RANKED HYPOTHESIS SET. Researchers were told not to run anything,
the architect was told not to pick a winner, breadth was scored and convergence
penalised, and the rank-1 code-reading inference was then relayed as "the named
root cause". Two field symptoms fall out of that one design: *"I researched it
and nobody concluded"* and *"I was wrong — it was never X"*. Replication had
``artifact_executed: true`` mechanically enforced; diagnosis had no executed /
captured-output / verdict field at all. This tool is that field.

It reads the diagnostic-plan SIDECAR (``diagnostic-plan-<ts>.json``, written
beside the markdown plan by the system-architect at Phase C of
``diagnostic-research-team``) and returns ``{valid, gaps[]}``, biting on six
escape modes:

  * ``diagnosis-leading-hypothesis-unexecuted`` — the leading hypothesis has no
    ``falsification_executed: true`` (or the block is missing). A ranked guess
    is not a diagnosis.
  * ``diagnosis-falsification-output-missing`` — a hypothesis claims execution
    but carries no captured ``observed_output``. "I ran it" without the output
    is a described run.
  * ``diagnosis-leading-hypothesis-not-survived`` — the leading hypothesis was
    executed and did NOT survive (``status != "survived"``). A refuted
    hypothesis cannot lead.
  * ``diagnosis-competitor-unexecuted`` — a competitor was neither executed nor
    honestly marked ``not-executable`` WITH a ``not_executable_reason`` naming
    the missing input only the owner can supply. Deferring a competitor's
    falsification to "the fix team" is the deferral this tool exists to refuse.
  * ``diagnosis-root-cause-without-refuted-competitor`` — ``root_cause_claimed``
    is true but no competitor was executed-refuted. A survived-only hypothesis
    is a LEADING HYPOTHESIS; calling it the root cause is the "it was never X"
    shape.
  * ``diagnosis-fewer-than-three-hypotheses`` — fewer than two competitors are
    listed (the three-hypotheses contract of the researchers).

Sidecar contract::

    {
      "schema_version": 1,
      "test_id": "<test-id>",
      "leading_hypothesis": {
        "id": "H1", "candidate": "<one line>",
        "falsification_executed": true,
        "falsification_command": "<what was run>",
        "observed_output": "<verbatim capture>",
        "status": "survived"
      },
      "competitors": [
        {"id": "H2", ..., "status": "refuted"},
        {"id": "H3", "falsification_executed": false,
         "status": "not-executable",
         "not_executable_reason": "<the input only the owner holds>"}
      ],
      "root_cause_claimed": true | false
    }

Deterministic, stdlib-only; never runs the experiments itself — the sidecar is
the researchers' executed output. The only write is the verdict file. The
run-level backstop that BLOCKS an in-flight SR on an unfalsified plan is
``_audit_diagnosis_falsified`` in ``hooks/pipeline-completion-audit.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:  # package shape: repo root on sys.path
    from hooks.vao.core import _utc_now_iso, _write_verdict
except ImportError:  # hooks/ on sys.path (vao is the package)
    try:
        from vao.core import _utc_now_iso, _write_verdict
    except ImportError:  # hooks/vao/ on sys.path (bare sibling)
        from core import _utc_now_iso, _write_verdict


_SURVIVED = "survived"
_REFUTED = "refuted"
_NOT_EXECUTABLE = "not-executable"

# The minimum number of competitors a plan must carry beside its leading
# hypothesis — the researchers' "three hypotheses minimum" contract.
_MIN_COMPETITORS = 2


def _blank(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip()


def _hyp_id(hyp: dict[str, Any], fallback: str) -> str:
    hid = hyp.get("id")
    return hid if isinstance(hid, str) and hid.strip() else fallback


def _status(hyp: dict[str, Any]) -> str:
    st = hyp.get("status")
    return st.strip().lower() if isinstance(st, str) else ""


def _executed(hyp: dict[str, Any]) -> bool:
    return hyp.get("falsification_executed") is True


def _output_gap(hid: str, role: str) -> dict[str, Any]:
    return {
        "severity": "diagnosis-falsification-output-missing",
        "hypothesis_id": hid,
        "evidence": (
            f"{role} {hid!r} claims falsification_executed: true but carries no "
            f"observed_output — a run with no captured output is a described run."
        ),
        "remediation": (
            "Re-run the falsification and paste the verbatim captured output into "
            "observed_output (the command that produced it goes in "
            "falsification_command)."
        ),
    }


def verify_diagnosis_falsified(
    plan_sidecar: dict[str, Any] | None = None,
    out_path: Path | str | None = None,
) -> dict[str, Any]:
    """v3.66.0 Layer-3 tool — verify a diagnostic plan's leading hypothesis was
    EXECUTED and SURVIVED while its competitors were executed and refuted (or
    honestly marked not-executable with the missing input named).

    Returns ``{tool, valid, gaps[], leading_hypothesis_id, executed_count,
    refuted_count, checked_at}``; ``valid`` is ``len(gaps) == 0``.
    """
    plan = plan_sidecar or {}
    gaps: list[dict[str, Any]] = []
    executed_count = 0
    refuted_count = 0

    leading = plan.get("leading_hypothesis")
    leading_id = "<none>"
    if not isinstance(leading, dict):
        gaps.append({
            "severity": "diagnosis-leading-hypothesis-unexecuted",
            "hypothesis_id": leading_id,
            "evidence": "the plan sidecar carries no leading_hypothesis block.",
            "remediation": (
                "Write the leading_hypothesis block with falsification_executed, "
                "falsification_command, observed_output and status per "
                "skills/diagnostic-research-team Phase C."
            ),
        })
    else:
        leading_id = _hyp_id(leading, "H1")
        if not _executed(leading):
            gaps.append({
                "severity": "diagnosis-leading-hypothesis-unexecuted",
                "hypothesis_id": leading_id,
                "evidence": (
                    f"leading hypothesis {leading_id!r} has no falsification_executed: "
                    "true — it is a ranked guess, not a diagnosis."
                ),
                "remediation": (
                    "Execute the falsification test the hypothesis names (a targeted "
                    "probe, an instrumented reproduction, a direct call — never a "
                    "code read) and record the command + verbatim output."
                ),
            })
        else:
            executed_count += 1
            if _blank(leading.get("observed_output")):
                gaps.append(_output_gap(leading_id, "leading hypothesis"))
            if _status(leading) != _SURVIVED:
                gaps.append({
                    "severity": "diagnosis-leading-hypothesis-not-survived",
                    "hypothesis_id": leading_id,
                    "evidence": (
                        f"leading hypothesis {leading_id!r} was executed and its status "
                        f"is {_status(leading) or '<blank>'!r}, not 'survived' — a refuted "
                        "hypothesis cannot lead the plan."
                    ),
                    "remediation": (
                        "Promote the hypothesis that survived executed falsification, "
                        "or run the remaining falsifications until one survives; "
                        "escalate ONLY a named missing input, never exhaustion."
                    ),
                })

    competitors_raw = plan.get("competitors")
    competitors = [c for c in competitors_raw if isinstance(c, dict)] if isinstance(competitors_raw, list) else []
    if len(competitors) < _MIN_COMPETITORS:
        gaps.append({
            "severity": "diagnosis-fewer-than-three-hypotheses",
            "hypothesis_id": leading_id,
            "evidence": (
                f"the plan lists {len(competitors)} competitor hypothesis(es) beside the "
                f"leading one; the researchers' contract is three hypotheses minimum."
            ),
            "remediation": (
                "Record at least two competing hypotheses with their executed "
                "falsification (or an honest not-executable reason)."
            ),
        })

    for idx, comp in enumerate(competitors, start=2):
        cid = _hyp_id(comp, f"H{idx}")
        if _executed(comp):
            executed_count += 1
            if _blank(comp.get("observed_output")):
                gaps.append(_output_gap(cid, "competitor"))
            if _status(comp) == _REFUTED:
                refuted_count += 1
            continue
        if _status(comp) == _NOT_EXECUTABLE and not _blank(comp.get("not_executable_reason")):
            continue  # the honest boundary — the missing input is named
        gaps.append({
            "severity": "diagnosis-competitor-unexecuted",
            "hypothesis_id": cid,
            "evidence": (
                f"competitor {cid!r} was neither executed nor marked not-executable "
                "with a not_executable_reason naming the missing input."
            ),
            "remediation": (
                "Execute its falsification test, or — only when an input the owner "
                "alone holds is missing — set status 'not-executable' and NAME that "
                "input in not_executable_reason. Deferring it to the fix team is not "
                "a disposition."
            ),
        })

    if plan.get("root_cause_claimed") is True and refuted_count == 0:
        gaps.append({
            "severity": "diagnosis-root-cause-without-refuted-competitor",
            "hypothesis_id": leading_id,
            "evidence": (
                "root_cause_claimed is true but no competitor was executed-refuted — "
                "a survived-only hypothesis is a LEADING HYPOTHESIS, not a root cause."
            ),
            "remediation": (
                "Either execute-refute at least one competitor, or set "
                "root_cause_claimed false and relay the finding as 'leading "
                "hypothesis (unfalsified competitors: ...)'."
            ),
        })

    verdict = {
        "tool": "verify-diagnosis-falsified",
        "valid": len(gaps) == 0,
        "gaps": gaps,
        "leading_hypothesis_id": leading_id,
        "executed_count": executed_count,
        "refuted_count": refuted_count,
        "checked_at": _utc_now_iso(),
    }
    return _write_verdict(verdict, out_path)


__all__ = ["verify_diagnosis_falsified"]
