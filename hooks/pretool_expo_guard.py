#!/usr/bin/env python3
"""PreToolUse guard: block web-only code from entering an Expo project.

An Expo app renders through React Native, not a browser. There is no DOM, no
CSS engine, and no browser globals on the device. Code that assumes otherwise
bundles cleanly, passes `expo export`, AND passes Playwright tests run against
the web target -- then crashes the instant the app opens on a phone.

Neither of the other two checks in `expo-standalone-app-build` can catch this
class of defect:

  * `npx expo export` never executes the code, so `<div>` exports fine.
  * Playwright runs against React Native Web in a real browser, which is
    precisely where `<div>` and `localStorage` still work.

This hook is the third layer -- it refuses the write outright, so a violation
never reaches the work tree regardless of whether the agent read the skill.

Scope is deliberately narrow. The guard stays silent unless ALL of:
  * the tool is Write / Edit / NotebookEdit,
  * the target file is a JS/TS source file,
  * the file lives inside a detected Expo project,
  * the file is not a legitimate web-target or test file.

Exit codes follow this repo's PreToolUse convention: 0 allow, 2 block with a
message on stderr.
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

MAX_PARENT_WALK = 8

SOURCE_SUFFIXES = (".tsx", ".jsx", ".ts", ".js", ".mjs", ".cjs")
JSX_SUFFIXES = (".tsx", ".jsx")

# Files that are legitimately web-only and must not be guarded.
WEB_TARGET_RE = re.compile(r"\.web\.(tsx|jsx|ts|js|mjs|cjs)$")
TEST_PATH_RE = re.compile(
    r"(^|/)(e2e|tests?|__tests__|playwright|cypress)(/|$)"
    r"|\.(spec|test|e2e)\.(tsx|jsx|ts|js|mjs|cjs)$"
)
SKIP_PATH_RE = re.compile(r"(^|/)(node_modules|\.expo|dist|build|ios|android)(/|$)")

# Expo DOM components legitimately render HTML inside a WebView.
USE_DOM_RE = re.compile(r"^\s*['\"]use dom['\"]\s*;?", re.MULTILINE)

HTML_TAGS = (
    "div|span|p|button|input|img|a|form|label|select|textarea|"
    "h1|h2|h3|h4|h5|h6|ul|ol|li|table|thead|tbody|tr|td|th|"
    "section|header|footer|nav|main|aside|article|"
    "br|hr|strong|em|b|i|small|pre|code|canvas|iframe|video|audio"
)
HTML_JSX_RE = re.compile(r"<(" + HTML_TAGS + r")(?=[\s/>])")

BROWSER_GLOBALS = (
    ("localStorage", "Use @react-native-async-storage/async-storage, expo-secure-store, or expo-sqlite."),
    ("sessionStorage", "Use @react-native-async-storage/async-storage, expo-secure-store, or expo-sqlite."),
)
BROWSER_MEMBER_RE = re.compile(r"\b(document|window)\s*\.")

FORBIDDEN_IMPORTS = (
    (re.compile(r"^react-router(-dom)?$"), "Use expo-router (file-based routes under app/)."),
    (re.compile(r"^@mui/"), "MUI renders HTML. Use a React Native component library."),
    (re.compile(r"^@chakra-ui/"), "Chakra renders HTML. Use a React Native component library."),
    (re.compile(r"^@radix-ui/"), "Radix renders HTML. Use a React Native component library."),
    (re.compile(r"^@headlessui/"), "Headless UI renders HTML. Use a React Native component library."),
    (re.compile(r"^(antd|bootstrap|react-bootstrap)$"), "Renders HTML. Use a React Native component library."),
    (re.compile(r"^(recharts|chart\.js|react-chartjs-2)$"), "Use a react-native-svg based charting library."),
    (re.compile(r"^d3(-|$)"), "d3 manipulates the DOM. Use react-native-svg."),
    (re.compile(r"^framer-motion$"), "Use react-native-reanimated."),
    (re.compile(r"^next(/|$)"), "Next.js is a web framework. Use Expo Router."),
    (re.compile(r"\.s?css$"), "There is no CSS engine on a phone. Use StyleSheet.create({})."),
)

IMPORT_RE = re.compile(
    r"""(?:^|\n)\s*import\s+(?:[^'"]*?\sfrom\s+)?['"]([^'"]+)['"]"""
    r"""|require\(\s*['"]([^'"]+)['"]\s*\)"""
)

LINE_COMMENT_RE = re.compile(r"//[^\n]*")
BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_comments(text: str) -> str:
    """Remove comments so guidance prose about forbidden constructs is not
    itself flagged. Replaces with spaces to preserve offsets loosely."""
    text = BLOCK_COMMENT_RE.sub(" ", text)
    return LINE_COMMENT_RE.sub(" ", text)


def _read_stdin_utf8() -> str:
    data = sys.stdin.buffer.read()
    return data.decode("utf-8", errors="replace")


def find_expo_root(file_path: str) -> str | None:
    """Walk up from file_path looking for an Expo project marker.

    Returns the project root, or None if this file is not inside an Expo
    project (in which case the guard must stay silent)."""
    directory = os.path.dirname(os.path.abspath(file_path))
    for _ in range(MAX_PARENT_WALK):
        app_json = os.path.join(directory, "app.json")
        if os.path.isfile(app_json):
            try:
                with open(app_json, "r", encoding="utf-8") as handle:
                    config = json.load(handle)
                if isinstance(config, dict) and "expo" in config:
                    return directory
            except (OSError, ValueError):
                pass

        pkg_json = os.path.join(directory, "package.json")
        if os.path.isfile(pkg_json):
            try:
                with open(pkg_json, "r", encoding="utf-8") as handle:
                    pkg = json.load(handle)
                deps = {}
                for key in ("dependencies", "devDependencies"):
                    value = pkg.get(key)
                    if isinstance(value, dict):
                        deps.update(value)
                if "expo" in deps:
                    return directory
                # A package.json without expo terminates the walk -- this is a
                # different project, not a parent of an Expo one.
                return None
            except (OSError, ValueError):
                pass

        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent
    return None


def scan(content: str, file_path: str) -> list[str]:
    """Return a list of violation messages for this content. Empty means clean."""
    violations: list[str] = []
    lowered_path = file_path.replace("\\", "/")
    is_test = bool(TEST_PATH_RE.search(lowered_path))
    code = _strip_comments(content)

    if lowered_path.endswith(JSX_SUFFIXES):
        seen: set[str] = set()
        for match in HTML_JSX_RE.finditer(code):
            tag = match.group(1)
            if tag not in seen:
                seen.add(tag)
                violations.append(
                    f"<{tag}> — HTML elements do not exist in React Native. "
                    f"Use <View>, <Text>, <Pressable>, <TextInput>, or <Image>."
                )

    # Browser globals. Test/e2e files legitimately drive a real browser.
    if not is_test:
        for name, fix in BROWSER_GLOBALS:
            if re.search(r"\b" + re.escape(name) + r"\b", code):
                violations.append(f"{name} — does not exist on a phone. {fix}")
        member = BROWSER_MEMBER_RE.search(code)
        if member:
            violations.append(
                f"{member.group(1)}. — there is no DOM on a phone. "
                f"Use the React Native / Expo equivalent."
            )

    for match in IMPORT_RE.finditer(code):
        module = match.group(1) or match.group(2)
        if not module:
            continue
        for pattern, fix in FORBIDDEN_IMPORTS:
            if pattern.search(module):
                violations.append(f"import '{module}' — {fix}")
                break

    return violations


def _extract_target(payload: dict[str, Any]) -> tuple[str, str]:
    """Return (file_path, content_to_scan) from a PreToolUse payload."""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return "", ""

    file_path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not isinstance(file_path, str):
        return "", ""

    parts: list[str] = []
    for key in ("content", "new_string", "new_source"):
        value = tool_input.get(key)
        if isinstance(value, str):
            parts.append(value)
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        for edit in edits:
            if isinstance(edit, dict) and isinstance(edit.get("new_string"), str):
                parts.append(edit["new_string"])

    return file_path, "\n".join(parts)


def check_payload(payload: dict[str, Any]) -> tuple[int, str]:
    if payload.get("tool_name") not in ("Write", "Edit", "NotebookEdit", "MultiEdit"):
        return 0, ""

    file_path, content = _extract_target(payload)
    if not file_path or not content:
        return 0, ""

    normalized = file_path.replace("\\", "/")
    if not normalized.endswith(SOURCE_SUFFIXES):
        return 0, ""
    if SKIP_PATH_RE.search(normalized) or WEB_TARGET_RE.search(normalized):
        return 0, ""
    if USE_DOM_RE.search(content):
        return 0, ""
    if not find_expo_root(file_path):
        return 0, ""

    violations = scan(content, normalized)
    if not violations:
        return 0, ""

    bullets = "\n".join(f"  - {v}" for v in violations)
    message = (
        "BLOCKED — web-only code in an Expo project.\n"
        f"\nFile: {file_path}\n"
        f"\nThis app ships to the App Store and Google Play through EAS. It renders\n"
        "through React Native, not a browser. The following will bundle cleanly,\n"
        "pass `expo export`, pass Playwright tests against the web target, and then\n"
        "crash when the app opens on a phone:\n\n"
        f"{bullets}\n"
        "\nSee the `expo-standalone-app-build` skill for the full technology contract.\n"
        "\nLegitimate exceptions, if and only if genuinely web-only:\n"
        "  - name the file `*.web.tsx` (platform-specific web target), or\n"
        "  - add the `'use dom'` directive at the top (Expo DOM component in a WebView).\n"
        "\nDo not reach for an exception to get unblocked. Rewrite it in React Native."
    )
    return 2, message


def main(argv: list[str] | None = None) -> int:
    try:
        stdin_text = "" if sys.stdin.isatty() else _read_stdin_utf8()
    except (OSError, ValueError):
        stdin_text = ""

    payload: dict[str, Any] = {}
    if stdin_text.strip():
        try:
            parsed = json.loads(stdin_text)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            pass

    exit_code, message = check_payload(payload)
    if message:
        print(message, file=sys.stderr)
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
