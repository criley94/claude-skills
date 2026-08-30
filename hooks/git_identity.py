# -*- coding: utf-8 -*-
"""Per-checkout git commit identity — the v3.67.0 discipline substrate.

CT6 runs commit on behalf of whoever is driving the run, in whatever repo they
point it at. Before v3.67.0 the identity came from wherever git happened to find
one: the repo's ambient config (often unset on a fresh clone, or wrong), or a
hardcoded author override that belonged to ONE maintainer's own repo and leaked
into a shipped skill body. Neither is a decision the tool may make for the user.

The record — ``<main-worktree>/.architect-team/git-identity.json``::

    {"name": "...", "email": "...", "source": "asked" | "confirmed-local-git-config"
     | "confirmed-global-git-config" | "user-stated", "recorded_at": "<UTC ISO>"}

is written ONCE per checkout after the front-door command asks the user (a
domain gate — see ``common-pipeline-conventions`` ``## Git commit identity
discipline (v3.67.0)``); it is gitignored with the rest of ``.architect-team/``
(identity is per PERSON, never committed into the repo) and resolved to the MAIN
worktree so every run worktree of the checkout shares it. Every commit-authoring
git command a run issues then carries it explicitly — ``-c user.name=…
-c user.email=…`` or the ``git --`` wrapper below — and the PreToolUse arm in
``hooks/pretool_skill_gate.py`` (Arm 4) refuses a commit-authoring command in an
ACTIVE run that lacks or contradicts the record.

Resolution order (``resolve``): recorded -> candidate from the repo's LOCAL git
config -> candidate from the GLOBAL git config -> missing. A candidate is NEVER
adopted silently: the caller confirms it with the user, then ``record``s it. This
module never writes git config and never invents a name.

NOT a wired hook — a substrate (the ``deploy_config.py`` / ``open_work.py``
shape) importable by the gate and runnable as a CLI. Stdlib-only; every read is
fail-safe (a malformed record reads as absent); console output is ASCII-only so
it survives a cp1252 Windows console.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

STATE_DIRNAME = ".architect-team"
IDENTITY_FILENAME = "git-identity.json"

#: git subcommands that AUTHOR a commit (the ones the discipline governs).
AUTHORING_SUBCOMMANDS = frozenset({"commit", "merge", "revert"})
#: flags that turn an authoring subcommand into a non-authoring invocation.
_NON_AUTHORING_FLAGS = frozenset({
    "--abort", "--continue", "--quit", "--no-commit", "--dry-run", "--help", "-h",
})
#: git global options that consume the NEXT token when not `=`-joined.
_GIT_GLOBAL_VALUE_OPTS = frozenset({
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path",
    "--super-prefix", "--config-env",
})
#: a token naming this module marks the wrapper form (`... git_identity.py git -- ...`).
WRAPPER_MARKER = "git_identity.py"

VALID_SOURCES = (
    "asked",
    "user-stated",
    "confirmed-local-git-config",
    "confirmed-global-git-config",
)

_GIT_TIMEOUT_SECONDS = 15


# --------------------------------------------------------------------------- #
# git plumbing (fail-safe)
# --------------------------------------------------------------------------- #

def _run_git(args: List[str], cwd: Optional[str], env: Optional[Dict[str, str]] = None):
    """Run git; return the CompletedProcess, or ``None`` on any OS/timeout error."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd or None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT_SECONDS,
            env=env,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def main_worktree_root(cwd) -> Path:
    """The MAIN worktree's root for ``cwd`` (``parent(git rev-parse --git-common-dir)``).

    A run worktree resolves to the checkout it was created from, so one record
    serves every worktree of the checkout — the ``shared_state_dir()`` rule.
    Falls back to ``cwd`` itself outside a git repo (the degenerate case)."""
    base = Path(str(cwd)).resolve()
    proc = _run_git(["rev-parse", "--git-common-dir"], str(base))
    if proc is None or proc.returncode != 0:
        return base
    out = (proc.stdout or "").strip()
    if not out:
        return base
    common = Path(out)
    if not common.is_absolute():
        common = base / common
    return common.resolve().parent


def identity_path(cwd) -> Path:
    """``<main-worktree>/.architect-team/git-identity.json`` for ``cwd``."""
    return main_worktree_root(cwd) / STATE_DIRNAME / IDENTITY_FILENAME


# --------------------------------------------------------------------------- #
# the record
# --------------------------------------------------------------------------- #

def _clean_record(data: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(data, dict):
        return None
    name, email = data.get("name"), data.get("email")
    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(email, str) or not email.strip():
        return None
    return {
        "name": name.strip(),
        "email": email.strip(),
        "source": data.get("source") if isinstance(data.get("source"), str) else "unknown",
        "recorded_at": data.get("recorded_at") if isinstance(data.get("recorded_at"), str) else None,
    }


def read_record(cwd) -> Optional[Dict[str, Any]]:
    """The recorded identity, or ``None`` when absent / unreadable / malformed."""
    path = identity_path(cwd)
    try:
        if not path.is_file():
            return None
        return _clean_record(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def validate_identity(name: Any, email: Any) -> Optional[str]:
    """``None`` when acceptable, else a one-line reason. Deliberately loose on the
    email shape (a noreply address is fine) and strict on the two things git
    itself chokes on: blanks and newlines."""
    if not isinstance(name, str) or not name.strip():
        return "name must be a non-blank string"
    if "\n" in name or "\r" in name:
        return "name must not contain a newline"
    if not isinstance(email, str) or not email.strip():
        return "email must be a non-blank string"
    e = email.strip()
    if any(ch.isspace() for ch in e) or "<" in e or ">" in e:
        return "email must not contain whitespace or angle brackets"
    if "@" not in e[1:-1]:
        return "email must look like local@domain"
    return None


def record(cwd, name: str, email: str, source: str = "asked") -> Path:
    """Write the record atomically. Raises ``ValueError`` on an unacceptable
    identity or source — a refusal, never a silent default."""
    problem = validate_identity(name, email)
    if problem:
        raise ValueError(problem)
    if source not in VALID_SOURCES:
        raise ValueError(f"source must be one of {', '.join(VALID_SOURCES)}")
    path = identity_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": name.strip(),
        "email": email.strip(),
        "source": source,
        "recorded_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def commit_args(cwd) -> List[str]:
    """The recorded identity as git global options, or ``[]`` when unrecorded."""
    rec = read_record(cwd)
    if rec is None:
        return []
    return ["-c", f"user.name={rec['name']}", "-c", f"user.email={rec['email']}"]


# --------------------------------------------------------------------------- #
# candidates + resolution
# --------------------------------------------------------------------------- #

def git_config_identity(cwd, scope: str, env: Optional[Dict[str, str]] = None) -> Optional[Dict[str, str]]:
    """``{"name", "email"}`` from ``git config --<scope>`` when BOTH are set, else ``None``.

    ``env`` is passed straight to git so callers (and tests) can point
    ``GIT_CONFIG_GLOBAL`` / ``HOME`` wherever they need without touching the
    real global config."""
    if scope not in ("local", "global"):
        raise ValueError("scope must be 'local' or 'global'")
    values = {}
    for key in ("user.name", "user.email"):
        proc = _run_git(["config", f"--{scope}", "--get", key], str(cwd), env)
        if proc is None or proc.returncode != 0:
            return None
        value = (proc.stdout or "").strip()
        if not value:
            return None
        values[key.split(".")[1]] = value
    return values


def resolve(cwd, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Resolve the identity for ``cwd``.

    Returns ``{"status": "recorded" | "candidate" | "missing", "name", "email",
    "source", "record_path"}``. A ``candidate`` is a proposal the caller must
    CONFIRM with the user before recording; ``missing`` means ASK."""
    path = identity_path(cwd)
    rec = read_record(cwd)
    if rec is not None:
        return {
            "status": "recorded",
            "name": rec["name"],
            "email": rec["email"],
            "source": rec["source"],
            "record_path": str(path),
        }
    for scope in ("local", "global"):
        cand = git_config_identity(cwd, scope, env)
        if cand is not None:
            return {
                "status": "candidate",
                "name": cand["name"],
                "email": cand["email"],
                "source": f"{scope}-git-config",
                "record_path": str(path),
            }
    return {"status": "missing", "name": None, "email": None, "source": None, "record_path": str(path)}


# --------------------------------------------------------------------------- #
# command inspection (what the PreToolUse arm reads)
# --------------------------------------------------------------------------- #

_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||;|\||\n")


def _segments(command: str) -> List[str]:
    return [s.strip() for s in _SEGMENT_SPLIT_RE.split(command or "") if s.strip()]


def _tokens(segment: str) -> List[str]:
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def _git_subcommand(tokens: List[str]) -> Tuple[Optional[str], List[str]]:
    """``(subcommand, tokens_before_it)`` for the FIRST git invocation in ``tokens``,
    skipping git's global options; ``(None, [])`` when the segment is not git."""
    for i, tok in enumerate(tokens):
        if os.path.basename(tok) not in ("git", "git.exe"):
            continue
        j = i + 1
        while j < len(tokens):
            t = tokens[j]
            if not t.startswith("-"):
                return t, tokens[i:j]
            if t in _GIT_GLOBAL_VALUE_OPTS:
                j += 2
            else:
                j += 1
        return None, tokens[i:]
    return None, []


def is_commit_authoring_command(command: str) -> bool:
    """True when ANY shell segment of ``command`` runs a git subcommand that
    authors a commit (``commit`` / ``merge`` / ``revert``) for real — the
    ``--abort`` / ``--no-commit`` / ``--dry-run`` forms author nothing."""
    for seg in _segments(command):
        tokens = _tokens(seg)
        sub, _ = _git_subcommand(tokens)
        if sub in AUTHORING_SUBCOMMANDS and not (_NON_AUTHORING_FLAGS & set(tokens)):
            return True
    return False


def _is_wrapper_segment(tokens: List[str]) -> bool:
    """``... git_identity.py [--cwd X] git -- ...`` — the wrapper injects the record."""
    for i, tok in enumerate(tokens):
        if os.path.basename(tok) == WRAPPER_MARKER:
            return "git" in tokens[i + 1:]
    return False


def identity_in_command(segment: str) -> Dict[str, str]:
    """The ``user.name`` / ``user.email`` values a segment passes via ``-c``."""
    found: Dict[str, str] = {}
    tokens = _tokens(segment)
    for i, tok in enumerate(tokens):
        pair = None
        if tok == "-c" and i + 1 < len(tokens):
            pair = tokens[i + 1]
        elif tok.startswith("-c") and "=" in tok and len(tok) > 2:
            pair = tok[2:]
        if not pair or "=" not in pair:
            continue
        key, _, value = pair.partition("=")
        if key in ("user.name", "user.email"):
            found[key.split(".")[1]] = value
    return found


def check_command(command: str, rec: Dict[str, Any]) -> Tuple[bool, str]:
    """Does every commit-authoring segment of ``command`` carry the recorded
    identity? ``(True, "")`` when it does (or nothing authors a commit);
    ``(False, reason)`` naming the first offending segment otherwise."""
    for seg in _segments(command):
        tokens = _tokens(seg)
        sub, _ = _git_subcommand(tokens)
        if sub not in AUTHORING_SUBCOMMANDS or (_NON_AUTHORING_FLAGS & set(tokens)):
            continue
        if _is_wrapper_segment(tokens):
            continue
        given = identity_in_command(seg)
        if "name" not in given or "email" not in given:
            return False, f"missing-identity: `{seg}` carries no -c user.name= / -c user.email= pair"
        if given["name"].strip() != rec["name"] or given["email"].strip() != rec["email"]:
            return False, (
                f"mismatch: `{seg}` commits as {given['name']} <{given['email']}> but the "
                f"checkout's recorded identity is {rec['name']} <{rec['email']}>"
            )
    return True, ""


# --------------------------------------------------------------------------- #
# the wrapper
# --------------------------------------------------------------------------- #

def run_git_with_identity(cwd, git_args: List[str]) -> int:
    """``git -c user.name=… -c user.email=… <git_args>`` in ``cwd``; returns git's
    exit code. Refuses (exit 2) when the checkout has no record — the caller
    must resolve + ask first; the wrapper never invents an identity."""
    args = commit_args(cwd)
    if not args:
        print(
            "git-identity: REFUSED - no recorded commit identity for this checkout. "
            f"Run `git_identity.py resolve` (record path: {identity_path(cwd)}), confirm or "
            "ask the user, then `git_identity.py set --name ... --email ...`.",
            file=sys.stderr,
        )
        return 2
    try:
        return subprocess.call(["git", *args, *git_args], cwd=str(cwd))
    except OSError as exc:
        print(f"git-identity: could not run git: {exc}", file=sys.stderr)
        return 2


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _print_resolution(res: Dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(res, sort_keys=True))
        return
    status = res["status"]
    if status == "recorded":
        print(f"git-identity: recorded - {res['name']} <{res['email']}> (source: {res['source']}; {res['record_path']})")
    elif status == "candidate":
        print(
            f"git-identity: candidate - {res['name']} <{res['email']}> from the {res['source']}; "
            "CONFIRM with the user, then `set` (never adopt silently)"
        )
    else:
        print(f"git-identity: missing - ASK the user for name + email, then `set` ({res['record_path']})")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="git_identity.py",
        description="Per-checkout git commit identity (CT6 v3.67.0).",
    )
    parser.add_argument("--cwd", default=None, help="a directory inside the checkout (default: the current directory)")
    sub = parser.add_subparsers(dest="verb", required=True)

    p_resolve = sub.add_parser("resolve", help="recorded -> local config -> global config -> missing")
    p_resolve.add_argument("--json", action="store_true")

    p_status = sub.add_parser("status", help="print the record (exit 2 when unrecorded)")
    p_status.add_argument("--json", action="store_true")

    p_set = sub.add_parser("set", help="record the identity the user confirmed or stated")
    p_set.add_argument("--name", required=True)
    p_set.add_argument("--email", required=True)
    p_set.add_argument("--source", default="asked", choices=VALID_SOURCES)

    sub.add_parser("args", help="print the record as shell-quoted `-c user.name=... -c user.email=...`")

    p_git = sub.add_parser("git", help="run git with the recorded identity injected: `git -- commit -m ...`")
    p_git.add_argument("git_args", nargs=argparse.REMAINDER)

    ns = parser.parse_args(argv)
    cwd = ns.cwd or os.getcwd()

    if ns.verb == "resolve":
        _print_resolution(resolve(cwd), ns.json)
        return 0
    if ns.verb == "status":
        rec = read_record(cwd)
        if rec is None:
            print(json.dumps({"status": "missing", "record_path": str(identity_path(cwd))}) if ns.json
                  else f"git-identity: missing ({identity_path(cwd)})")
            return 2
        print(json.dumps({"status": "recorded", **rec, "record_path": str(identity_path(cwd))}, sort_keys=True) if ns.json
              else f"git-identity: {rec['name']} <{rec['email']}> (source: {rec['source']})")
        return 0
    if ns.verb == "set":
        try:
            path = record(cwd, ns.name, ns.email, ns.source)
        except ValueError as exc:
            print(f"git-identity: REFUSED - {exc}", file=sys.stderr)
            return 2
        print(f"git-identity: recorded {ns.name.strip()} <{ns.email.strip()}> at {path}")
        return 0
    if ns.verb == "args":
        args = commit_args(cwd)
        if not args:
            print("git-identity: missing - nothing to print", file=sys.stderr)
            return 2
        print(" ".join(shlex.quote(a) for a in args))
        return 0
    if ns.verb == "git":
        git_args = list(ns.git_args)
        if git_args and git_args[0] == "--":
            git_args = git_args[1:]
        if not git_args:
            print("git-identity: usage: git -- <git arguments>", file=sys.stderr)
            return 2
        return run_git_with_identity(cwd, git_args)
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
