"""Tests for hooks/pretool_expo_guard.py.

The guard is the third enforcement layer of `expo-standalone-app-build`. The
first two layers cannot catch this class of defect: `expo export` never runs
the code, and Playwright runs against React Native Web in a real browser --
which is exactly where `<div>` and `localStorage` still work.

These tests pin both directions: violations must block, and legitimate code
must not. A false positive here halts a build team mid-run, so the negative
cases matter as much as the positive ones.
"""

from __future__ import annotations

import json

import pytest

from hooks import pretool_expo_guard as guard


ALLOW = 0
BLOCK = 2


@pytest.fixture()
def expo_project(tmp_path):
    """A minimal on-disk Expo project the guard will recognize."""
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "notes", "dependencies": {"expo": "~57.0.0"}}),
        encoding="utf-8",
    )
    (tmp_path / "app.json").write_text(
        json.dumps({"expo": {"name": "Notes", "slug": "notes"}}), encoding="utf-8"
    )
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    return tmp_path


def payload(file_path, content, tool_name="Write"):
    return {
        "tool_name": tool_name,
        "tool_input": {"file_path": str(file_path), "content": content},
    }


def run(file_path, content, tool_name="Write"):
    return guard.check_payload(payload(file_path, content, tool_name))


# --------------------------------------------------------------------------
# Violations must block
# --------------------------------------------------------------------------


def test_blocks_html_element(expo_project):
    src = expo_project / "app" / "index.tsx"
    code, message = run(src, "export default () => <div>hello</div>;")
    assert code == BLOCK
    assert "<div>" in message
    assert "<View>" in message


@pytest.mark.parametrize("tag", ["span", "button", "input", "img", "h1", "form", "ul"])
def test_blocks_each_html_tag(expo_project, tag):
    src = expo_project / "app" / "index.tsx"
    code, message = run(src, f"export default () => <{tag} />;")
    assert code == BLOCK
    assert f"<{tag}>" in message


def test_blocks_local_storage(expo_project):
    src = expo_project / "app" / "store.ts"
    code, message = run(src, "export const save = (v: string) => localStorage.setItem('k', v);")
    assert code == BLOCK
    assert "localStorage" in message
    assert "async-storage" in message


def test_blocks_document_access(expo_project):
    src = expo_project / "app" / "focus.ts"
    code, message = run(src, "export const f = () => document.getElementById('x');")
    assert code == BLOCK
    assert "no DOM" in message


@pytest.mark.parametrize(
    "module",
    ["react-router-dom", "@mui/material", "@radix-ui/react-dialog", "recharts", "framer-motion"],
)
def test_blocks_web_only_imports(expo_project, module):
    src = expo_project / "app" / "index.tsx"
    code, message = run(src, f"import x from '{module}';\nexport default x;")
    assert code == BLOCK
    assert module in message


def test_blocks_css_import(expo_project):
    src = expo_project / "app" / "index.tsx"
    code, message = run(src, "import './styles.css';")
    assert code == BLOCK
    assert "StyleSheet" in message


def test_blocks_on_edit_new_string(expo_project):
    """Edit payloads carry new_string rather than content."""
    src = expo_project / "app" / "index.tsx"
    result = guard.check_payload(
        {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(src),
                "old_string": "<View />",
                "new_string": "<div className='x' />",
            },
        }
    )
    assert result[0] == BLOCK


def test_reports_every_violation_not_just_the_first(expo_project):
    src = expo_project / "app" / "index.tsx"
    code, message = run(
        src,
        "import './a.css';\nexport default () => <div><span>{localStorage.x}</span></div>;",
    )
    assert code == BLOCK
    assert "<div>" in message and "<span>" in message
    assert "localStorage" in message and "a.css" in message


# --------------------------------------------------------------------------
# Legitimate code must NOT block
# --------------------------------------------------------------------------


def test_allows_correct_react_native(expo_project):
    src = expo_project / "app" / "index.tsx"
    code, _ = run(
        src,
        "import { View, Text } from 'react-native';\n"
        "export default () => <View><Text>hello</Text></View>;",
    )
    assert code == ALLOW


def test_allows_async_storage(expo_project):
    src = expo_project / "app" / "store.ts"
    code, _ = run(
        src,
        "import AsyncStorage from '@react-native-async-storage/async-storage';\n"
        "export const save = (v: string) => AsyncStorage.setItem('k', v);",
    )
    assert code == ALLOW


def test_allows_dimensions_window_string(expo_project):
    """Dimensions.get('window') is React Native, not a browser global."""
    src = expo_project / "app" / "size.ts"
    code, _ = run(
        src,
        "import { Dimensions } from 'react-native';\n"
        "export const w = Dimensions.get('window').width;",
    )
    assert code == ALLOW


def test_allows_generics_in_plain_ts(expo_project):
    """`<p` inside a generic must not be mistaken for an HTML tag."""
    src = expo_project / "app" / "util.ts"
    code, _ = run(src, "export type R<pending> = Array<pending>;\nexport const a: Array<props> = [];")
    assert code == ALLOW


def test_allows_forbidden_constructs_inside_comments(expo_project):
    """Guidance prose about what not to do must not itself be blocked."""
    src = expo_project / "app" / "index.tsx"
    code, _ = run(
        src,
        "// Never use <div> or localStorage here.\n"
        "/* <span> and document.body are also forbidden. */\n"
        "import { View } from 'react-native';\n"
        "export default () => <View />;",
    )
    assert code == ALLOW


def test_allows_web_target_file(expo_project):
    """*.web.tsx is a legitimate platform-specific web implementation."""
    src = expo_project / "app" / "chart.web.tsx"
    code, _ = run(src, "export default () => <div>web only</div>;")
    assert code == ALLOW


def test_allows_use_dom_component(expo_project):
    """Expo DOM components legitimately render HTML inside a WebView."""
    src = expo_project / "app" / "editor.tsx"
    code, _ = run(src, "'use dom';\nexport default () => <div>rich text</div>;")
    assert code == ALLOW


def test_allows_browser_globals_in_playwright_specs(expo_project):
    """E2E tests legitimately drive a real browser."""
    tests_dir = expo_project / "e2e"
    tests_dir.mkdir()
    src = tests_dir / "notes.spec.ts"
    code, _ = run(src, "await page.evaluate(() => document.title);")
    assert code == ALLOW


# --------------------------------------------------------------------------
# Scope: the guard must stay silent outside Expo projects
# --------------------------------------------------------------------------


def test_silent_outside_expo_project(tmp_path):
    """A plain React web app is not this hook's business."""
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "site", "dependencies": {"react": "^19.0.0"}}), encoding="utf-8"
    )
    src = tmp_path / "App.tsx"
    code, _ = run(src, "export default () => <div>hello</div>;")
    assert code == ALLOW


def test_silent_with_no_project_marker(tmp_path):
    src = tmp_path / "scratch.tsx"
    code, _ = run(src, "export default () => <div>hello</div>;")
    assert code == ALLOW


def test_silent_on_node_modules(expo_project):
    nm = expo_project / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    src = nm / "index.tsx"
    code, _ = run(src, "export default () => <div/>;")
    assert code == ALLOW


def test_silent_on_non_source_file(expo_project):
    src = expo_project / "README.md"
    code, _ = run(src, "Use <div> in web projects.")
    assert code == ALLOW


def test_silent_on_unrelated_tool(expo_project):
    src = expo_project / "app" / "index.tsx"
    code, _ = run(src, "<div/>", tool_name="Read")
    assert code == ALLOW


def test_empty_payload_allows():
    assert guard.check_payload({}) == (ALLOW, "")
