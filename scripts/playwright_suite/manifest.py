# -*- coding: utf-8 -*-
"""Deterministic Playwright suite-manifest engine — the machine under the
`playwright-suite-builder` skill.

The manifest lives at ``<e2e-dir>/suite-manifest.json``, committed in the
TARGET repo (never in this one). It is the durable registry that answers "which
tests are written", binds each test to the intuition-map elements and routes it
covers, groups the suite by persona, and — the part with teeth — records
whether a test may run against production.

Two entry points:

* ``validate_manifest(data)`` — schema validity. Required top-level fields,
  required per-test fields, closed enums for ``kind`` / ``source`` / ``safety``,
  a real boolean for ``mutates_data``, personas drawn from the declared
  ``personas[]``, no duplicate file entries. Every blocking finding names the
  ENTRY and the FIELD, because "the manifest is invalid" is not actionable.

* ``verify_suite_manifest(data, repo_root)`` — the ship check, legs (a)-(d):

  (a) **Reconciliation, both directions.** Every listed ``file`` exists on
      disk, AND every spec file under the suite directories is listed. One
      direction alone is worthless: listing-only misses the test nobody
      registered, disk-only misses the entry whose file was deleted or renamed.
      A missing ``e2e_dir`` is itself a finding — an empty disk side agrees
      with any manifest.
  (b) **Prod default-deny.** The prod project is ``safety: prod`` entries. Each
      must be ``kind: prod-check``, must carry a real recorded classification,
      and must not mutate data — unless a ``prod_exceptions[]`` entry names its
      file and carries ALL THREE of recorded authorization (who / when / why),
      a test-only data tag following the ``it-`` prefix convention from
      `dev-api-integration-testing`, and a teardown declaration. A PARTIAL
      exception grants nothing and is itself a blocking finding. The dev
      project is untouched by this: dev tests may mutate data under the
      existing shared-state hygiene rules.
  (c) **Debug-flow provenance.** Every ``kind: debug-flow`` entry carries a
      non-null ``origin_ref`` whose artifact exists.
  (d) **Schema validity**, folded in — legs (a)-(c) read fields that leg (d)
      is what guarantees are there.

HONEST BOUNDARY: an ``origin_ref`` that is a bare bug SLUG rather than a repo
path cannot be dereferenced by a file-system check. The engine says so with an
advisory finding rather than pretending it verified something (or blocking a
legitimate slug). Path-shaped refs ARE dereferenced, and a dead one blocks.

Path convention: per-test ``file`` values and ``e2e_dir`` are both relative to
``repo_root`` (the target repo's root), using forward slashes.

CLI (``--json`` and ``--manifest`` are the same argument; ``--as-json`` switches
the FINDINGS to machine-readable output). Exit ``0`` no blocking findings,
``1`` blocking findings, ``2`` the manifest could not be read::

    python scripts/playwright_suite/manifest.py validate --manifest <path> [--as-json]
    python scripts/playwright_suite/manifest.py verify   --manifest <path> \\
        --repo-root <repo> [--as-json]

``validate`` takes no ``--repo-root``: schema validity is a property of the
document alone.

Stdlib-only; no import-time side effects; mirrors the engine+CLI shape of
``scripts/delivery/delivery_manifest.py``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

SCHEMA_VERSION = "playwright-suite-manifest/v1"

KINDS = ("journey", "debug-flow", "prod-check")
SOURCES = ("user-flow", "explorer", "gap-fill", "bug-path", "pre-existing")
SAFETY_LEVELS = ("dev", "prod")

REQUIRED_TOP_LEVEL_FIELDS = (
    "schema_version", "e2e_dir", "personas", "last_built", "prod_exceptions", "tests",
)
REQUIRED_TEST_FIELDS = (
    "file", "test_names", "persona", "kind", "source", "covers_elements",
    "covers_routes", "safety", "mutates_data", "origin_ref",
)

#: What counts as a Playwright test file on disk. Deliberately a superset of
#: ``.spec.ts``: ``.test.ts`` is an equally ordinary Playwright naming
#: convention, and a ``.spec.js`` under the suite directories is a test somebody
#: wrote. An unlisted one is exactly the drift reconciliation exists to catch.
#: Matched case-insensitively (see :func:`_is_spec`), and always against a
#: LEADING DOT so ``latest.ts`` and ``contest.ts`` are not swept in.
SPEC_SUFFIXES = (".spec.ts", ".spec.tsx", ".spec.js", ".spec.jsx", ".spec.mjs",
                 ".spec.cjs", ".test.ts", ".test.tsx", ".test.js", ".test.jsx",
                 ".test.mjs", ".test.cjs")

#: Directory names never walked during reconciliation.
_SKIP_DIRS = frozenset({"node_modules", ".git", "test-results", "playwright-report"})

#: The test-only data tag convention from `dev-api-integration-testing`: every
#: record a prod-exception test creates is prefixed so a sweep can find and
#: remove it.
TEST_DATA_TAG_PREFIX = "it-"

#: The three legs of an authorization. Missing ANY one leaves the exception
#: partial, and a partial exception authorizes nothing.
AUTHORIZATION_LEGS = ("who", "when", "why")


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _missing_text(value: Any) -> bool:
    """True unless ``value`` is a non-blank STRING.

    Deliberately stricter than :func:`_blank`, which rejects only ``None`` and
    blank strings and therefore reads every non-string falsy JSON value as
    PRESENT. That gap was a false pass in the prod default-deny gate
    (adversary-task-1 F1): ``teardown: false`` — an explicit declaration that
    the test cleans up NOTHING — satisfied "mandatory teardown", and
    ``authorization: {who: false, when: false, why: false}`` satisfied "recorded
    authorization". Nine such variants reached CLI exit 0 on a
    ``mutates_data: true`` production test, and the difference between the
    blocked form (``""``) and the passing form (``false``) is invisible to a
    human reading the manifest.

    An authorization leg is a thing somebody WROTE DOWN. Anything that is not
    text is the absence of a record, so this mirrors the isinstance discipline
    already applied to ``mutates_data``.

    KNOWN NON-GOAL (adversary-task-1 R2, accepted informationally): a field made
    only of ZERO-WIDTH characters (U+200B and relatives) is non-blank to
    ``str.strip()`` and therefore passes. Left as-is deliberately. Defeating it
    takes a unicode category sweep that would also have to decide about every
    other invisible-but-meaningful codepoint, and the threat model does not
    support it — the values this guards are authored by a human recording an
    authorization, not supplied by an adversary trying to smuggle one past a
    reviewer who is reading the same JSON. Recorded here so it is a decision
    someone can revisit, not a hole nobody noticed.
    """
    return not (isinstance(value, str) and value.strip())


def _finding(kind: str, severity: str, entry: Optional[str], field: Optional[str],
             detail: str) -> Dict[str, Any]:
    return {"kind": kind, "severity": severity, "entry": entry, "field": field,
            "detail": detail}


def errors_only(findings: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The blocking subset — an empty list means the manifest may ship."""
    return [f for f in findings if f.get("severity") == "error"]


def load_manifest(path: Any) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _tests_of(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    tests = data.get("tests")
    if not isinstance(tests, list):
        return []
    return [t for t in tests if isinstance(t, dict)]


def _entry_name(test: Dict[str, Any], position: int) -> str:
    value = test.get("file")
    return value if isinstance(value, str) and value.strip() else f"<test #{position}>"


def prod_project(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The tests the prod Playwright project would run.

    Default-deny in its purest form: membership requires an explicitly recorded
    ``safety: prod``. A new or unclassified test simply is not here.
    """
    return [t for t in _tests_of(data) if t.get("safety") == "prod"]


# --------------------------------------------------------------------------- #
# validate_manifest — schema validity
# --------------------------------------------------------------------------- #

def validate_manifest(data: Any) -> List[Dict[str, Any]]:
    """Schema gate. Findings are ``{kind, severity, entry, field, detail}``;
    ``severity`` is ``"error"`` (blocking) or ``"advisory"``."""
    findings: List[Dict[str, Any]] = []
    if not isinstance(data, dict):
        return [_finding("malformed-field", "error", None, None,
                         f"the manifest must be a JSON object, got "
                         f"{type(data).__name__}")]

    for field in REQUIRED_TOP_LEVEL_FIELDS:
        if field not in data:
            findings.append(_finding(
                "missing-field", "error", None, field,
                f"the manifest is missing required top-level field {field!r}"))

    version = data.get("schema_version")
    if "schema_version" in data and _blank(version):
        findings.append(_finding("malformed-field", "error", None, "schema_version",
                                 "schema_version is blank"))
    elif isinstance(version, str) and version.strip() \
            and version.strip() != SCHEMA_VERSION:
        findings.append(_finding(
            "unexpected-schema-version", "advisory", None, "schema_version",
            f"manifest declares schema_version {version!r}; this engine writes "
            f"{SCHEMA_VERSION!r}"))

    for field in ("e2e_dir", "last_built"):
        if field in data and _blank(data.get(field)):
            findings.append(_finding("malformed-field", "error", None, field,
                                     f"{field} is blank"))

    personas = data.get("personas")
    if "personas" in data:
        if not isinstance(personas, list) or any(_blank(p) for p in personas):
            findings.append(_finding(
                "malformed-field", "error", None, "personas",
                "personas must be a list of non-blank persona names"))
    known_personas = {p for p in personas if isinstance(p, str)} \
        if isinstance(personas, list) else set()

    if "prod_exceptions" in data and not isinstance(data.get("prod_exceptions"), list):
        findings.append(_finding(
            "malformed-field", "error", None, "prod_exceptions",
            f"prod_exceptions must be a list, got "
            f"{type(data.get('prod_exceptions')).__name__}"))

    tests = data.get("tests")
    if "tests" in data and not isinstance(tests, list):
        findings.append(_finding(
            "malformed-field", "error", None, "tests",
            f"tests must be a list of per-test entries, got {type(tests).__name__}"))
        return findings

    seen: Dict[str, int] = {}
    for position, test in enumerate(data.get("tests") or [], 1):
        if not isinstance(test, dict):
            findings.append(_finding(
                "malformed-field", "error", f"<test #{position}>", None,
                f"test entry #{position} is not a mapping"))
            continue
        entry = _entry_name(test, position)
        findings.extend(_validate_test(test, entry, position, known_personas))
        path = test.get("file")
        if isinstance(path, str) and path.strip():
            if path in seen:
                findings.append(_finding(
                    "duplicate-entry", "error", entry, "file",
                    f"file {path!r} is registered by entry #{seen[path]} and entry "
                    f"#{position}; the manifest keys on file"))
            else:
                seen[path] = position

    findings.extend(_validate_exceptions(data))
    return findings


def _validate_test(test: Dict[str, Any], entry: str, position: int,
                   known_personas: set) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for field in REQUIRED_TEST_FIELDS:
        if field not in test:
            findings.append(_finding(
                "missing-field", "error", entry, field,
                f"test entry #{position} ({entry}) is missing required field "
                f"{field!r}"))

    if "file" in test and _missing_text(test.get("file")):
        findings.append(_finding("malformed-field", "error", entry, "file",
                                 f"{entry}: file is blank"))

    names = test.get("test_names")
    if "test_names" in test and (not isinstance(names, list) or not names
                                 or any(_missing_text(n) for n in names)):
        findings.append(_finding(
            "malformed-field", "error", entry, "test_names",
            f"{entry}: test_names must be a non-empty list of test titles"))

    persona = test.get("persona")
    if "persona" in test:
        if _missing_text(persona):
            findings.append(_finding("malformed-field", "error", entry, "persona",
                                     f"{entry}: persona is blank"))
        elif known_personas and persona not in known_personas:
            findings.append(_finding(
                "unknown-persona", "error", entry, "persona",
                f"{entry}: persona {persona!r} is not one of the manifest's declared "
                f"personas {sorted(known_personas)}; an unknown persona is escalated, "
                f"never guessed"))

    for field, valid in (("kind", KINDS), ("source", SOURCES), ("safety", SAFETY_LEVELS)):
        if field not in test:
            continue
        value = test.get(field)
        if _missing_text(value):
            findings.append(_finding("malformed-field", "error", entry, field,
                                     f"{entry}: {field} is blank or not a string"))
        elif value not in valid:
            findings.append(_finding(
                f"unknown-{field}", "error", entry, field,
                f"{entry}: {field} {value!r} is not one of {list(valid)}"))

    for field in ("covers_elements", "covers_routes"):
        if field in test and (not isinstance(test.get(field), list)
                              or any(_missing_text(v) for v in test.get(field))):
            findings.append(_finding(
                "malformed-field", "error", entry, field,
                f"{entry}: {field} must be a list of non-blank ids"))

    if "mutates_data" in test and not isinstance(test.get("mutates_data"), bool):
        findings.append(_finding(
            "malformed-field", "error", entry, "mutates_data",
            f"{entry}: mutates_data must be a real boolean, got "
            f"{test.get('mutates_data')!r} — a recorded classification is what "
            f"keeps an unclassified test out of prod"))

    origin = test.get("origin_ref")
    if "origin_ref" in test and origin is not None \
            and (not isinstance(origin, str) or not origin.strip()):
        findings.append(_finding(
            "malformed-field", "error", entry, "origin_ref",
            f"{entry}: origin_ref must be a non-blank string or null"))
    return findings


def _validate_exceptions(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    exceptions = data.get("prod_exceptions")
    if not isinstance(exceptions, list):
        return findings
    for position, exception in enumerate(exceptions, 1):
        if not isinstance(exception, dict):
            findings.append(_finding(
                "malformed-field", "error", f"<prod_exception #{position}>", None,
                f"prod_exceptions[{position}] is not a mapping"))
            continue
        if _missing_text(exception.get("file")):
            findings.append(_finding(
                "missing-field", "error", f"<prod_exception #{position}>", "file",
                f"prod_exceptions[{position}] names no file — an exception that "
                f"names nothing authorizes nothing"))
    return findings


# --------------------------------------------------------------------------- #
# verify_suite_manifest — the deterministic ship check
# --------------------------------------------------------------------------- #

def _rel_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_spec(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(suffix) for suffix in SPEC_SUFFIXES)


def discover_specs(repo_root: Any, e2e_dir: str) -> List[str]:
    """Every Playwright spec under the suite directory, repo-relative, sorted."""
    root = Path(repo_root)
    suite_root = root / e2e_dir
    if not suite_root.is_dir():
        return []
    found: List[str] = []
    for path in sorted(suite_root.rglob("*")):
        if not path.is_file() or not _is_spec(path):
            continue
        if _SKIP_DIRS.intersection(path.relative_to(root).parts):
            continue
        found.append(_rel_posix(path, root))
    return sorted(found)


def _reconcile(data: Dict[str, Any], repo_root: Path) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    e2e_dir = data.get("e2e_dir")
    if _blank(e2e_dir):
        return findings
    suite_root = repo_root / str(e2e_dir)
    if not suite_root.is_dir():
        findings.append(_finding(
            "e2e-dir-missing", "error", None, "e2e_dir",
            f"e2e_dir {e2e_dir!r} does not resolve to a directory under "
            f"{repo_root} — reconciliation cannot run, and an empty disk side "
            f"would agree with any manifest"))
        return findings

    listed: Dict[str, str] = {}
    for position, test in enumerate(_tests_of(data), 1):
        path = test.get("file")
        if not isinstance(path, str) or not path.strip():
            continue
        normalized = path.replace("\\", "/").strip()
        listed[normalized] = _entry_name(test, position)
        if not (repo_root / normalized).is_file():
            findings.append(_finding(
                "missing-on-disk", "error", normalized, "file",
                f"the manifest lists {normalized!r} but no such file exists under "
                f"{repo_root}"))

    for spec in discover_specs(repo_root, str(e2e_dir)):
        if spec not in listed:
            findings.append(_finding(
                "unlisted-on-disk", "error", spec, "file",
                f"{spec} sits under the suite directory but no manifest entry "
                f"registers it — an unregistered test is invisible to the "
                f"full-suite run"))
    return findings


def _authorization_gaps(exception: Dict[str, Any]) -> List[str]:
    """Which of the three legs this exception is missing (empty means complete)."""
    gaps: List[str] = []
    authorization = exception.get("authorization")
    if not isinstance(authorization, dict):
        gaps.append("authorization (who / when / why)")
    else:
        missing = [leg for leg in AUTHORIZATION_LEGS
                   if _missing_text(authorization.get(leg))]
        if missing:
            gaps.append(f"authorization {missing} — each leg must be recorded text")

    tag = exception.get("test_data_tag")
    if _missing_text(tag):
        gaps.append(f"test_data_tag (the {TEST_DATA_TAG_PREFIX!r} test-only prefix)")
    elif not tag.startswith(TEST_DATA_TAG_PREFIX):
        # Compared UNSTRIPPED (adversary-task-1 R4). `"  it-x".strip()` starts
        # with the prefix, but the tag the test actually writes into the record
        # does not — so a teardown sweep keyed on `it-` would never match the
        # data this exception authorized creating.
        if tag.strip().startswith(TEST_DATA_TAG_PREFIX):
            # The prefix IS there — it is preceded by whitespace, which most
            # editors render invisibly. Blaming a missing prefix sends the
            # author hunting for a defect that is not the one they have.
            gaps.append(f"test_data_tag {tag!r} carries stray leading whitespace "
                        f"before the {TEST_DATA_TAG_PREFIX!r} prefix — the tag as "
                        f"written would not match a teardown sweep keyed on "
                        f"{TEST_DATA_TAG_PREFIX!r}")
        else:
            gaps.append(f"test_data_tag {tag!r} does not use the "
                        f"{TEST_DATA_TAG_PREFIX!r} test-only prefix convention")
    elif len(tag.strip()) <= len(TEST_DATA_TAG_PREFIX):
        # The bare prefix identifies every test-only record ever written, which
        # is the same as identifying none of them: a teardown sweep keyed on it
        # cannot tell this test's data from anyone else's.
        gaps.append(f"test_data_tag {tag!r} is the bare {TEST_DATA_TAG_PREFIX!r} "
                    f"prefix with nothing after it — a tag that identifies "
                    f"nothing cannot scope a teardown")

    if _missing_text(exception.get("teardown")):
        gaps.append("teardown (a declaration of how the created data is removed)")
    return gaps


def _authorized_files(data: Dict[str, Any],
                      findings: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Files carrying a COMPLETE prod exception. Partial exceptions are recorded
    as findings here and grant nothing."""
    authorized: Dict[str, Dict[str, Any]] = {}
    exceptions = data.get("prod_exceptions")
    if not isinstance(exceptions, list):
        return authorized
    for position, exception in enumerate(exceptions, 1):
        if not isinstance(exception, dict):
            continue
        path = exception.get("file")
        entry = path if isinstance(path, str) and path.strip() \
            else f"<prod_exception #{position}>"
        gaps = _authorization_gaps(exception)
        if gaps:
            findings.append(_finding(
                "prod-exception-incomplete", "error", entry, "prod_exceptions",
                f"prod_exceptions[{position}] for {entry} is incomplete — missing: "
                f"{'; '.join(gaps)}. A partial exception authorizes nothing: prod "
                f"mutation needs recorded authorization AND a test-only data tag "
                f"AND a teardown declaration."))
            continue
        if isinstance(path, str) and path.strip():
            authorized[path.replace("\\", "/").strip()] = exception
    return authorized


def _covers(exception: Dict[str, Any], test: Dict[str, Any]) -> bool:
    """An exception naming a specific test_name covers only that test."""
    named = exception.get("test_name")
    if _blank(named):
        return True
    names = test.get("test_names")
    return isinstance(names, list) and named in names


def _check_prod_project(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    authorized = _authorized_files(data, findings)

    for position, test in enumerate(_tests_of(data), 1):
        if test.get("safety") != "prod":
            continue
        entry = _entry_name(test, position)
        exception = authorized.get(str(test.get("file", "")).replace("\\", "/").strip())
        exempt = exception is not None and _covers(exception, test)

        mutates = test.get("mutates_data")
        if not isinstance(mutates, bool):
            findings.append(_finding(
                "prod-unclassified", "error", entry, "mutates_data",
                f"{entry} sits in the prod project with no recorded mutates_data "
                f"classification — default-deny: absence of a classification is "
                f"not permission, and an unclassified test lands dev-only"))
        elif mutates and not exempt:
            findings.append(_finding(
                "prod-mutating-unauthorized", "error", entry, "mutates_data",
                f"{entry} mutates data and sits in the prod project with no "
                f"authorized prod_exceptions[] entry; the prod suite is "
                f"navigation and assertion only"))

        if test.get("kind") != "prod-check" and not exempt:
            findings.append(_finding(
                "prod-non-check-kind", "error", entry, "kind",
                f"{entry} sits in the prod project with kind "
                f"{test.get('kind')!r}; the prod project is a subset of "
                f"kind:prod-check entries plus authorized exceptions"))
    return findings


def _looks_like_path(ref: str) -> bool:
    text = ref.strip()
    if "/" in text or "\\" in text:
        return True
    stem, dot, suffix = text.rpartition(".")
    return bool(stem and dot and 1 <= len(suffix) <= 6 and suffix.isalnum())


def _check_debug_flow_provenance(data: Dict[str, Any],
                                 repo_root: Path) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for position, test in enumerate(_tests_of(data), 1):
        if test.get("kind") != "debug-flow":
            continue
        entry = _entry_name(test, position)
        origin = test.get("origin_ref")
        if _blank(origin):
            findings.append(_finding(
                "debug-flow-missing-origin", "error", entry, "origin_ref",
                f"{entry} is registered as a debug-flow with no origin_ref — a "
                f"debug flow with no provenance cannot be traced back to the bug "
                f"it exists to keep fixed"))
            continue
        if not _looks_like_path(str(origin)):
            findings.append(_finding(
                "debug-flow-origin-undereferenceable", "advisory", entry,
                "origin_ref",
                f"{entry} names origin_ref {origin!r}, which is a slug rather than "
                f"a repo path — the engine cannot dereference it, so its liveness "
                f"is unverified rather than verified"))
            continue
        # F8: `.exists()` is satisfied by ANY filesystem node, so a directory
        # named bugs/SR-999.json and a zero-byte file both passed provenance.
        # Neither can be traced back to the bug the debug flow keeps fixed, and
        # dereferencing is the entire value of this check.
        target = repo_root / str(origin).replace("\\", "/").strip()
        try:
            live = target.is_file() and target.stat().st_size > 0
            reason = ("no such artifact exists" if not target.exists()
                      else "it is a directory, not a file" if target.is_dir()
                      else "the file is empty")
        except OSError as exc:
            live, reason = False, f"it could not be read ({exc})"
        if not live:
            findings.append(_finding(
                "debug-flow-dead-origin", "error", entry, "origin_ref",
                f"{entry} names origin_ref {origin!r} but {reason} under "
                f"{repo_root} — a debug flow's provenance must dereference to a "
                f"real, non-empty artifact"))
    return findings


def verify_suite_manifest(data: Any, repo_root: Any) -> List[Dict[str, Any]]:
    """The ship check — legs (a) reconciliation, (b) prod default-deny,
    (c) debug-flow provenance, (d) schema validity."""
    findings = list(validate_manifest(data))
    if not isinstance(data, dict):
        return findings
    root = Path(repo_root)
    findings.extend(_reconcile(data, root))
    findings.extend(_check_prod_project(data))
    findings.extend(_check_debug_flow_provenance(data, root))
    return findings


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _report(findings: Sequence[Dict[str, Any]], as_json: bool) -> int:
    if as_json:
        print(json.dumps(list(findings), indent=2))
        return 1 if errors_only(findings) else 0
    for finding in findings:
        anchor = finding.get("entry") or "<manifest>"
        print(f"[{finding['severity']:8s}] {finding['kind']}: {anchor} — "
              f"{finding['detail']}")
    blocking = errors_only(findings)
    print(f"{len(blocking)} blocking finding(s), "
          f"{len(findings) - len(blocking)} advisory.")
    return 1 if blocking else 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate and verify a Playwright suite manifest."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # `--json` is the house spelling (scripts/delivery/delivery_manifest.py);
    # `--manifest` is the alias the skill bodies document and reads better next
    # to `--as-json`. Same dest, so both call sites stay correct forever.
    validate = sub.add_parser("validate", help="Schema gate over a suite manifest.")
    validate.add_argument("--json", "--manifest", dest="json", required=True,
                          metavar="PATH", help="Path to suite-manifest.json.")
    validate.add_argument("--as-json", action="store_true",
                          help="Emit the findings as JSON.")
    # Deliberately NO --repo-root here: schema validation reads no tree, and a
    # flag accepted-then-ignored is worse than one refused.

    verify = sub.add_parser("verify", help="The full verify-suite-manifest ship check.")
    verify.add_argument("--json", "--manifest", dest="json", required=True,
                        metavar="PATH", help="Path to suite-manifest.json.")
    verify.add_argument("--repo-root", required=True,
                        help="The target repo root the manifest's paths are relative to.")
    verify.add_argument("--as-json", action="store_true",
                        help="Emit the findings as JSON.")

    args = parser.parse_args(argv)
    try:
        data = load_manifest(args.json)
    except (OSError, ValueError) as exc:
        print(f"cannot read {args.json}: {exc}")
        return 2

    if args.cmd == "validate":
        return _report(validate_manifest(data), args.as_json)
    return _report(verify_suite_manifest(data, args.repo_root), args.as_json)


if __name__ == "__main__":
    sys.exit(main())
