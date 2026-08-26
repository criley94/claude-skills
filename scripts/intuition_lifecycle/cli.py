# -*- coding: utf-8 -*-
"""Command-line surface over the intuition-map lifecycle engine.

Mirrors the house engine+CLI split (`scripts/delivery/delivery_manifest.py`):
the engine is the mechanism, this is the callable verb set the
`intuition-map-lifecycle` skill names.

    python scripts/intuition_lifecycle/cli.py ensure   --codebase <dir> [--json]
    python scripts/intuition_lifecycle/cli.py scaffold --codebase <dir> [--input P]...
    python scripts/intuition_lifecycle/cli.py validate --map <path> [--json]
    python scripts/intuition_lifecycle/cli.py grow --map <path> --json <flow.json> \\
        [--out <path>] [--questions-out <path>]
    python scripts/intuition_lifecycle/cli.py bug-path-upsert --map <path> \\
        --json <bug.json> [--out <path>] [--questions-out <path>]

The `grow` / `bug-path-upsert` payload is a JSON object:

    {"origin": "e2e/personas/shopper/checkout.spec.ts",
     "regression_refs": [{"test": "...", "ref": "SR-014"}],
     "elements": [{"route": "/cart", "label": "Checkout", "kind": "button",
                   "action": "...", "endpoint": {"method": "POST", "path": "..."}}]}

Exit codes: ``0`` clean, ``1`` blocking findings / an unresolved contradiction /
a map that must be produced, ``2`` a usage or payload error (including an
unreadable ``--map``), ``3`` an unexpected internal failure. A raised
contradiction exits ``1`` because it needs the USER — the domain gate the verb
exists to surface — and ``3`` exists so a crash can never be mistaken for that
gate firing.

The engine is loaded by file path (the `scripts/` tier's house idiom, the same
``spec_from_file_location`` dance `scripts/data_dictionary/annotations.py`
uses), so this CLI runs from any working directory without a package install.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_ENGINE_PATH = Path(__file__).resolve().parent / "engine.py"


def _load_engine() -> Any:
    spec = importlib.util.spec_from_file_location("ct6_intuition_lifecycle_engine",
                                                  _ENGINE_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load the engine from {_ENGINE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


engine = _load_engine()


def _safe_print(text: str = "") -> None:
    """Print without dying on a console codec that cannot represent ``text``.

    The contradiction question embeds the element label VERBATIM, and a Windows
    cp1252 console — the house-gated default — cannot encode an arrow, a check
    mark, or any CJK/Cyrillic label. That raised UnicodeEncodeError from the
    print itself (adversary-task-1 F3), so the operator got a traceback in place
    of the one output that requires a human decision, and the process still
    exited 1 — indistinguishable from the gate cleanly reporting a
    contradiction. A mangled character is a far better outcome than a lost
    contradiction, so unencodable characters are replaced rather than fatal.
    """
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(encoding, "replace").decode(encoding, "replace"))


def _print_findings(findings: List[Dict[str, Any]]) -> int:
    for finding in findings:
        _safe_print(f"[{finding['severity']:8s}] {finding['kind']}: "
              f"{finding.get('entry')} — {finding['detail']}")
    blocking = engine.errors_only(findings)
    _safe_print(f"{len(blocking)} blocking finding(s), "
          f"{len(findings) - len(blocking)} advisory.")
    return 1 if blocking else 0


def _emit_questions(questions: List[Dict[str, Any]], out: Optional[str]) -> None:
    if out:
        target = Path(out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(questions, indent=2), encoding="utf-8",
                          newline="\n")
        _safe_print(f"wrote {len(questions)} question artifact(s) to {out}")
    for question in questions:
        _safe_print(f"CONTRADICTION {question['element_id']}: {question['question']}")
        _safe_print(f"  -> {question['resolution']}")


def _cmd_ensure(args: argparse.Namespace) -> int:
    report = engine.ensure_support(args.codebase)
    if args.json:
        _safe_print(json.dumps(report, indent=2))
    else:
        _safe_print(f"map_path: {report['map_path']}")
        _safe_print(f"present: {report['present']}")
        _safe_print(f"action_required: {report['action_required']}")
        _safe_print(f"reason: {report['reason']}")
        if report["parse_error"]:
            _safe_print(f"parse_error: {report['parse_error']}")
    return 0 if report["action_required"] == "none" else 1


def _cmd_scaffold(args: argparse.Namespace) -> int:
    try:
        path = engine.scaffold_map(args.codebase, inputs=args.input or (),
                                   producer=args.producer, overwrite=args.overwrite)
    except FileExistsError as exc:
        _safe_print(str(exc))
        return 1
    _safe_print(f"wrote {path}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        doc = engine.load_map(args.map)
    except engine.MapParseError as exc:
        _safe_print(f"[error   ] unparseable-map: {args.map} — {exc}")
        return 1
    except OSError as exc:
        _safe_print(f"cannot read {args.map}: {exc}")
        return 2
    findings = engine.validate_map(doc)
    if args.json:
        _safe_print(json.dumps(findings, indent=2))
        return 1 if engine.errors_only(findings) else 0
    return _print_findings(findings)


def _load_payload(path: str) -> Dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        raise ValueError(
            f"{path} must be a JSON object with an 'elements' list "
            f"(see the CLI docstring for the shape)"
        )
    return payload


def _cmd_upsert(args: argparse.Namespace, verb: str) -> int:
    try:
        payload = _load_payload(args.json)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _safe_print(f"payload error: {exc}")
        return 2
    try:
        doc = engine.load_map(args.map)
    except engine.MapParseError as exc:
        _safe_print(f"[error   ] unparseable-map: {args.map} — {exc}")
        return 1
    except OSError as exc:
        _safe_print(f"cannot read {args.map}: {exc}")
        return 2

    try:
        if verb == "grow":
            result = engine.grow(doc, payload["elements"],
                                 origin=payload.get("origin"))
        else:
            result = engine.bug_path_upsert(
                doc, payload["elements"],
                regression_refs=payload.get("regression_refs") or [],
                origin=payload.get("origin"))
    except ValueError as exc:
        _safe_print(f"payload error: {exc}")
        return 2

    findings = engine.validate_map(doc)
    blocking = engine.errors_only(findings)
    if blocking:
        _safe_print("refusing to write — the upsert would leave the map invalid:")
        _print_findings(blocking)
        return 1

    target = args.out or args.map
    engine.write_map(doc, target)
    _safe_print(f"wrote {target}")
    _safe_print(f"created={result['created']} updated={result['updated']} "
          f"unchanged={result['unchanged']} blocked={result['blocked']}")
    if result["questions"]:
        _emit_questions(result["questions"], args.questions_out)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ensure, grow and bug-path-upsert an INTERACTION_INTUITION_MAP.md."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    ensure = sub.add_parser("ensure", help="Report whether a codebase has a usable map.")
    ensure.add_argument("--codebase", required=True)
    ensure.add_argument("--json", action="store_true")

    scaffold = sub.add_parser("scaffold", help="Write a minimal schema-valid empty map.")
    scaffold.add_argument("--codebase", required=True)
    scaffold.add_argument("--input", action="append", default=[])
    scaffold.add_argument("--producer", default="interaction-intuiter")
    scaffold.add_argument("--overwrite", action="store_true")

    validate = sub.add_parser("validate", help="Run the schema gate over a map.")
    validate.add_argument("--map", required=True)
    validate.add_argument("--json", action="store_true")

    for verb, helptext in (("grow", "Upsert user-specified flow elements as confirmed."),
                           ("bug-path-upsert",
                            "Upsert a bug path with source bug-path + regression refs.")):
        cmd = sub.add_parser(verb, help=helptext)
        cmd.add_argument("--map", required=True)
        cmd.add_argument("--json", required=True, help="Path to the payload JSON.")
        cmd.add_argument("--out", default=None, help="Write here instead of in place.")
        cmd.add_argument("--questions-out", default=None,
                         help="Write the contradiction question artifacts here.")
    return parser


def _dispatch(args: argparse.Namespace) -> int:
    if args.cmd == "ensure":
        return _cmd_ensure(args)
    if args.cmd == "scaffold":
        return _cmd_scaffold(args)
    if args.cmd == "validate":
        return _cmd_validate(args)
    return _cmd_upsert(args, args.cmd)


def main(argv: Optional[List[str]] = None) -> int:
    """Exit 0 clean, 1 blocking findings / an unresolved contradiction, 2 a
    usage or payload error, 3 an unexpected internal failure.

    The 3 matters: before it existed an unhandled exception exited 1 through
    Python's default, which a caller could not tell apart from the contradiction
    gate legitimately firing (adversary-task-1 F3). A crash and a working gate
    must never share an exit code."""
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except Exception as exc:  # noqa: BLE001 - the point is that NOTHING escapes as 1
        _safe_print(f"internal error: {type(exc).__name__}: {exc}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
