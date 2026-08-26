"""Tests for the Playwright suite-manifest engine (`scripts/playwright_suite/`).

The manifest (`<e2e-dir>/suite-manifest.json`, committed in the TARGET repo) is
the durable per-codebase registry: which tests are written, which intuition-map
elements and routes each covers, which persona it belongs to, and — the part
with teeth — whether it may run against production.

Two checks live here and each is pinned so a one-sided implementation fails:

* `validate_manifest` — schema validity. Every blocking finding names the entry
  AND the field, because "the manifest is invalid" is not actionable.
* `verify_suite_manifest` — the deterministic ship check:
  (a) manifest-to-disk reconciliation in BOTH directions (a listed file that is
      gone, and a spec file on disk nobody listed),
  (b) the prod project is default-deny — `prod-check` kind, no data mutation,
      an explicitly recorded classification — and a `prod_exceptions[]` entry
      buys an exemption only when it carries ALL THREE of recorded
      authorization (who/when/why), an `it-` test-only data tag, and a
      teardown declaration. A partial exception STILL BLOCKS,
  (c) every `kind: debug-flow` entry carries a live `origin_ref`,
  (d) schema validity (the (d) leg is (a)-(c)'s precondition, so it is folded in).
"""
from __future__ import annotations

import ast
import copy
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests.helpers.module_loader import load_module

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG = REPO_ROOT / "scripts" / "playwright_suite"
ENGINE_PATH = PKG / "manifest.py"
FIX = REPO_ROOT / "tests" / "fixtures" / "playwright_suite"
VALID_MANIFEST = FIX / "suite-manifest.json"
MALFORMED_MANIFEST = FIX / "malformed-manifest.json"

# The fixture project's spec files are MATERIALIZED per test rather than
# committed under tests/fixtures/. `hooks/discipline_registry.py` globs
# `**/*.spec.ts` across the WHOLE repo to decide whether the
# prod-safe-test-classification discipline applies; four committed fixture
# specs flipped this plugin repo from "no Playwright/QA-shaped tests" to
# "4 unclassified QA tests" and redded tests/test_discipline_applicability.py
# (measured 2026-08-25). Materializing costs nothing, keeps the tree just as
# realistic, and lets every test mutate its own copy freely.
_SPEC_FILES = {
    "e2e/personas/shopper/checkout.spec.ts": """import { test, expect } from '@playwright/test';

test('shopper completes a card checkout', async ({ page }) => {
  await page.goto('/cart');
  await page.getByRole('button', { name: 'Checkout' }).click();
  await page.getByRole('button', { name: 'Pay' }).click();
  await expect(page.getByText('Order confirmed')).toBeVisible();
});

test('shopper sees the order in their history', async ({ page }) => {
  await page.goto('/orders');
  await expect(page.getByRole('listitem').first()).toContainText('Order confirmed');
});
""",
    "e2e/personas/shopper/browse-catalog.spec.ts": """import { test, expect } from '@playwright/test';

test('shopper filters the catalog by category', async ({ page }) => {
  await page.goto('/catalog');
  await page.getByRole('checkbox', { name: 'Outdoor' }).check();
  await expect(page.getByTestId('result-count')).not.toHaveText('0');
});
""",
    "e2e/debug-flows/sr-014-cart-total.spec.ts": """import { test, expect } from '@playwright/test';

// Stands in for a Phase B2 reproduction artifact promoted into the durable
// suite as a kind:debug-flow entry.
test('SR-014 cart total recomputes after a quantity change', async ({ page }) => {
  await page.goto('/cart');
  await page.getByLabel('Quantity').fill('3');
  await expect(page.getByTestId('cart-total')).toHaveText('$44.97');
});
""",
    "e2e/prod-checks/home-smoke.spec.ts": """import { test, expect } from '@playwright/test';

// Read-only prod smoke check: navigation and assertion only.
test('the storefront home page renders for an anonymous visitor', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
});
""",
}

_BUG_ARTIFACT = ("bugs/SR-014.json", json.dumps({
    "id": "SR-014",
    "origin": {"kind": "rca-product-bug", "reported_at": "2026-08-12T11:04:00Z"},
    "symptom": "Changing an item's quantity in the cart left the displayed total "
               "at its previous value until a full page reload.",
    "resolution": "fixed",
    "regression_artifact": "e2e/debug-flows/sr-014-cart-total.spec.ts",
}, indent=2) + "\n")


def _materialize(root: Path) -> Path:
    """Write the fixture project tree — the same tree the manifest describes."""
    for relative, body in list(_SPEC_FILES.items()) + [_BUG_ARTIFACT]:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8", newline="\n")
    (root / "e2e" / "suite-manifest.json").write_text(
        VALID_MANIFEST.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    return root


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    return _materialize(tmp_path / "project")


@pytest.fixture(scope="module")
def eng() -> ModuleType:
    return load_module(ENGINE_PATH, "ct6_suite_manifest")


def _valid() -> dict:
    return json.loads(VALID_MANIFEST.read_text(encoding="utf-8"))


def _entry(data: dict, file_suffix: str) -> dict:
    hits = [t for t in data["tests"] if t["file"].endswith(file_suffix)]
    assert len(hits) == 1, f"expected one entry ending {file_suffix!r}, got {len(hits)}"
    return hits[0]


def _kinds(findings) -> set:
    return {f["kind"] for f in findings}


def _mentioning(findings, needle: str) -> list:
    return [f for f in findings if needle in json.dumps(f)]


def _authorization(**overrides) -> dict:
    base = {
        "file": "e2e/prod-checks/home-smoke.spec.ts",
        "authorization": {
            "who": "paul",
            "when": "2026-08-25T10:00:00Z",
            "why": "The prod checkout smoke check must place one throwaway order "
                   "to prove the payment provider is reachable.",
        },
        "test_data_tag": "it-prodsmoke-",
        "teardown": "afterEach deletes every it-prodsmoke- order through the admin API.",
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# 1. validate_manifest — schema validity, findings named by entry and field
# --------------------------------------------------------------------------- #

def test_the_conforming_fixture_validates_clean(eng):
    assert eng.errors_only(eng.validate_manifest(_valid())) == []


def test_the_malformed_fixture_is_rejected_with_entry_and_field_named(eng):
    data = json.loads(MALFORMED_MANIFEST.read_text(encoding="utf-8"))
    findings = eng.errors_only(eng.validate_manifest(data))
    kinds = _kinds(findings)

    assert "missing-field" in kinds
    assert _mentioning(findings, "last_built"), "the missing top-level field is not named"
    assert _mentioning(findings, "persona"), "the entry missing a persona is not named"
    assert "unknown-kind" in kinds and _mentioning(findings, "smoke-ish")
    assert "unknown-source" in kinds and _mentioning(findings, "handwritten")
    assert "unknown-safety" in kinds and _mentioning(findings, "staging")
    assert "malformed-field" in kinds and _mentioning(findings, "mutates_data")
    assert "unknown-persona" in kinds and _mentioning(findings, "night-ops")

    for f in findings:
        assert f.get("detail")
        if f.get("entry") is not None:
            assert f.get("field"), f"entry-scoped finding without a field: {f}"


@pytest.mark.parametrize("field", ["schema_version", "e2e_dir", "personas",
                                   "last_built", "prod_exceptions", "tests"])
def test_each_required_top_level_field_is_required(eng, field):
    data = _valid()
    del data[field]
    findings = eng.errors_only(eng.validate_manifest(data))
    assert any(f["kind"] == "missing-field" and f.get("field") == field for f in findings), (
        f"dropping {field!r} produced no missing-field finding"
    )


@pytest.mark.parametrize("field", ["file", "test_names", "persona", "kind", "source",
                                   "covers_elements", "covers_routes", "safety",
                                   "mutates_data", "origin_ref"])
def test_each_required_per_test_field_is_required(eng, field):
    data = _valid()
    del data["tests"][0][field]
    findings = eng.errors_only(eng.validate_manifest(data))
    named = [f for f in findings
             if f["kind"] == "missing-field" and f.get("field") == field]
    assert named, f"dropping per-test {field!r} produced no missing-field finding"
    assert named[0].get("entry"), "the finding does not name which entry is missing it"


def test_origin_ref_may_be_null_but_may_not_be_absent(eng):
    """`null` is a recorded answer ("this test has no upstream artifact"); an
    absent key is an unanswered question, and a debug-flow's provenance is
    exactly what must never be left unanswered."""
    data = _valid()
    _entry(data, "browse-catalog.spec.ts")["origin_ref"] = None
    assert eng.errors_only(eng.validate_manifest(data)) == []


def test_mutates_data_must_be_a_real_boolean(eng):
    data = _valid()
    _entry(data, "checkout.spec.ts")["mutates_data"] = "true"
    findings = eng.errors_only(eng.validate_manifest(data))
    assert any(f["kind"] == "malformed-field" and f.get("field") == "mutates_data"
               for f in findings)


def test_test_names_must_be_a_non_empty_list_of_strings(eng):
    data = _valid()
    _entry(data, "checkout.spec.ts")["test_names"] = []
    findings = eng.errors_only(eng.validate_manifest(data))
    assert any(f.get("field") == "test_names" for f in findings)


def test_a_duplicate_file_entry_is_a_finding(eng):
    data = _valid()
    data["tests"].append(copy.deepcopy(data["tests"][0]))
    findings = eng.errors_only(eng.validate_manifest(data))
    assert any(f["kind"] == "duplicate-entry" for f in findings)


# --------------------------------------------------------------------------- #
# 2. verify — reconciliation, BOTH directions
# --------------------------------------------------------------------------- #

def test_the_fixture_project_verifies_clean(eng, project):
    findings = eng.errors_only(eng.verify_suite_manifest(_valid(), project))
    assert findings == [], findings


def test_a_listed_file_that_is_not_on_disk_blocks_and_names_the_path(eng, project):
    data = _valid()
    _entry(data, "checkout.spec.ts")["file"] = "e2e/personas/shopper/ghost.spec.ts"
    findings = eng.errors_only(eng.verify_suite_manifest(data, project))
    assert "missing-on-disk" in _kinds(findings)
    assert _mentioning(findings, "e2e/personas/shopper/ghost.spec.ts")


def test_a_spec_on_disk_that_nobody_listed_blocks_and_names_the_path(eng, project):
    (project / "e2e" / "personas" / "shopper" / "wishlist.spec.ts").write_text(
        "import { test } from '@playwright/test';\n", encoding="utf-8")
    findings = eng.errors_only(eng.verify_suite_manifest(_valid(), project))
    assert "unlisted-on-disk" in _kinds(findings)
    assert _mentioning(findings, "wishlist.spec.ts")


def test_reconciliation_covers_both_directions_in_one_run(eng, project):
    """The mutation witness for this pin removes one direction; a test that only
    ever exercises the other would pass a half-broken reconciliation."""
    (project / "e2e" / "personas" / "shopper" / "wishlist.spec.ts").write_text(
        "import { test } from '@playwright/test';\n", encoding="utf-8")
    data = _valid()
    _entry(data, "checkout.spec.ts")["file"] = "e2e/personas/shopper/ghost.spec.ts"

    kinds = _kinds(eng.errors_only(eng.verify_suite_manifest(data, project)))
    assert "missing-on-disk" in kinds
    assert "unlisted-on-disk" in kinds


def test_reconciliation_finds_specs_in_every_suite_subdirectory(eng, project):
    (project / "e2e" / "debug-flows" / "sr-021-orphan.spec.ts").write_text(
        "import { test } from '@playwright/test';\n", encoding="utf-8")
    (project / "e2e" / "prod-checks" / "catalog-orphan.spec.js").write_text(
        "import { test } from '@playwright/test';\n", encoding="utf-8")
    findings = eng.errors_only(eng.verify_suite_manifest(_valid(), project))
    assert _mentioning(findings, "sr-021-orphan.spec.ts")
    assert _mentioning(findings, "catalog-orphan.spec.js")


def test_reconciliation_ignores_node_modules_and_non_spec_files(eng, project):
    vendored = project / "e2e" / "node_modules" / "some-pkg"
    vendored.mkdir(parents=True)
    (vendored / "index.spec.ts").write_text("// vendored\n", encoding="utf-8")
    (project / "e2e" / "fixtures.ts").write_text("export const user = {};\n", encoding="utf-8")
    (project / "e2e" / "playwright.config.ts").write_text("export default {};\n", encoding="utf-8")

    findings = eng.errors_only(eng.verify_suite_manifest(_valid(), project))
    assert findings == [], findings


def test_a_missing_e2e_dir_blocks_rather_than_silently_reconciling_nothing(eng, project):
    """An e2e_dir typo would otherwise make the disk side of reconciliation
    EMPTY, and an empty disk side agrees with any manifest."""
    data = _valid()
    data["e2e_dir"] = "tests/e2e"
    findings = eng.errors_only(eng.verify_suite_manifest(data, project))
    assert "e2e-dir-missing" in _kinds(findings)


# --------------------------------------------------------------------------- #
# 3. verify — prod default-deny
# --------------------------------------------------------------------------- #

def test_an_unauthorized_mutating_prod_test_blocks_and_names_the_test(eng, project):
    data = _valid()
    entry = _entry(data, "home-smoke.spec.ts")
    entry["mutates_data"] = True
    findings = eng.errors_only(eng.verify_suite_manifest(data, project))
    assert "prod-mutating-unauthorized" in _kinds(findings)
    assert _mentioning(findings, "e2e/prod-checks/home-smoke.spec.ts")


def test_a_non_prod_check_kind_may_not_sit_in_the_prod_project(eng, project):
    data = _valid()
    _entry(data, "home-smoke.spec.ts")["kind"] = "journey"
    findings = eng.errors_only(eng.verify_suite_manifest(data, project))
    assert "prod-non-check-kind" in _kinds(findings)


def test_a_prod_entry_with_no_recorded_classification_blocks(eng, project):
    """Default-deny: absence of a classification is not permission."""
    data = _valid()
    del _entry(data, "home-smoke.spec.ts")["mutates_data"]
    findings = eng.errors_only(eng.verify_suite_manifest(data, project))
    assert "prod-unclassified" in _kinds(findings)


def test_an_unclassified_test_is_dev_only_and_never_reaches_the_prod_project(eng, project):
    data = _valid()
    entry = _entry(data, "browse-catalog.spec.ts")
    del entry["safety"]
    project = eng.prod_project(data)
    assert entry["file"] not in [t["file"] for t in project]


def test_a_fully_authorized_exception_admits_a_mutating_prod_test(eng, project):
    data = _valid()
    _entry(data, "home-smoke.spec.ts")["mutates_data"] = True
    data["prod_exceptions"] = [_authorization()]
    findings = eng.errors_only(eng.verify_suite_manifest(data, project))
    assert findings == [], findings


@pytest.mark.parametrize("drop,expected_needle", [
    ("test_data_tag", "test_data_tag"),
    ("teardown", "teardown"),
    ("authorization", "authorization"),
])
def test_a_partial_exception_still_blocks(eng, drop, expected_needle, project):
    data = _valid()
    _entry(data, "home-smoke.spec.ts")["mutates_data"] = True
    exception = _authorization()
    del exception[drop]
    data["prod_exceptions"] = [exception]

    findings = eng.errors_only(eng.verify_suite_manifest(data, project))
    kinds = _kinds(findings)
    assert "prod-exception-incomplete" in kinds, (
        f"a {drop}-less exception was accepted as authorization"
    )
    assert _mentioning(findings, expected_needle)
    assert "prod-mutating-unauthorized" in kinds, (
        "the test itself must still block — an incomplete exception grants nothing"
    )


@pytest.mark.parametrize("who,when,why", [
    ("", "2026-08-25T10:00:00Z", "reason"),
    ("paul", "", "reason"),
    ("paul", "2026-08-25T10:00:00Z", ""),
])
def test_authorization_needs_who_and_when_and_why(eng, who, when, why, project):
    data = _valid()
    _entry(data, "home-smoke.spec.ts")["mutates_data"] = True
    exception = _authorization()
    exception["authorization"] = {"who": who, "when": when, "why": why}
    data["prod_exceptions"] = [exception]

    findings = eng.errors_only(eng.verify_suite_manifest(data, project))
    assert "prod-exception-incomplete" in _kinds(findings)
    assert "prod-mutating-unauthorized" in _kinds(findings)


def test_a_data_tag_that_is_not_the_it_prefix_convention_still_blocks(eng, project):
    data = _valid()
    _entry(data, "home-smoke.spec.ts")["mutates_data"] = True
    exception = _authorization(test_data_tag="smoke-")
    data["prod_exceptions"] = [exception]

    findings = eng.errors_only(eng.verify_suite_manifest(data, project))
    assert "prod-exception-incomplete" in _kinds(findings)
    assert _mentioning(findings, "it-")


def test_an_exception_only_covers_the_file_it_names(eng, project):
    orders = project / "e2e" / "prod-checks" / "orders-smoke.spec.ts"
    orders.write_text("import { test } from '@playwright/test';\n", encoding="utf-8")

    data = _valid()
    _entry(data, "home-smoke.spec.ts")["mutates_data"] = True
    data["tests"].append({
        "file": "e2e/prod-checks/orders-smoke.spec.ts",
        "test_names": ["ops sees the order dashboard"],
        "persona": "ops", "kind": "prod-check", "source": "gap-fill",
        "covers_elements": [], "covers_routes": ["/orders"],
        "safety": "prod", "mutates_data": True, "origin_ref": None,
    })
    data["prod_exceptions"] = [_authorization(file="e2e/prod-checks/orders-smoke.spec.ts")]

    findings = eng.errors_only(eng.verify_suite_manifest(data, project))
    assert "prod-mutating-unauthorized" in _kinds(findings)
    assert _mentioning(findings, "home-smoke.spec.ts")
    assert not _mentioning(
        [f for f in findings if f["kind"] == "prod-mutating-unauthorized"],
        "orders-smoke.spec.ts")


def test_a_dev_test_that_mutates_data_is_perfectly_fine(eng, project):
    """The other direction of default-deny: the dev project allows mutation, so
    a guard that blocks every mutating test would be wrong, not safe."""
    data = _valid()
    assert _entry(data, "checkout.spec.ts")["mutates_data"] is True
    assert eng.errors_only(eng.verify_suite_manifest(data, project)) == []


# --------------------------------------------------------------------------- #
# 4. verify — debug-flow provenance
# --------------------------------------------------------------------------- #

def test_a_debug_flow_with_a_null_origin_ref_blocks(eng, project):
    data = _valid()
    _entry(data, "sr-014-cart-total.spec.ts")["origin_ref"] = None
    findings = eng.errors_only(eng.verify_suite_manifest(data, project))
    assert "debug-flow-missing-origin" in _kinds(findings)
    assert _mentioning(findings, "sr-014-cart-total.spec.ts")


def test_a_debug_flow_whose_origin_artifact_is_gone_blocks(eng, project):
    data = _valid()
    _entry(data, "sr-014-cart-total.spec.ts")["origin_ref"] = "bugs/SR-999.json"
    findings = eng.errors_only(eng.verify_suite_manifest(data, project))
    assert "debug-flow-dead-origin" in _kinds(findings)
    assert _mentioning(findings, "bugs/SR-999.json")


def test_a_live_origin_artifact_passes(eng, project):
    data = _valid()
    assert _entry(data, "sr-014-cart-total.spec.ts")["origin_ref"] == "bugs/SR-014.json"
    assert eng.errors_only(eng.verify_suite_manifest(data, project)) == []


def test_a_bare_slug_origin_is_advisory_not_blocking(eng, project):
    """HONEST BOUNDARY: a bug slug is not a path, so the engine cannot
    dereference it. It says so rather than pretending either way."""
    data = _valid()
    _entry(data, "sr-014-cart-total.spec.ts")["origin_ref"] = "SR-014"
    findings = eng.verify_suite_manifest(data, project)
    assert eng.errors_only(findings) == []
    assert "debug-flow-origin-undereferenceable" in _kinds(findings)


def test_a_journey_entry_needs_no_origin_ref(eng, project):
    data = _valid()
    assert _entry(data, "checkout.spec.ts")["origin_ref"] is None
    assert eng.errors_only(eng.verify_suite_manifest(data, project)) == []


# --------------------------------------------------------------------------- #
# 5. verify — schema validity is folded in (leg d)
# --------------------------------------------------------------------------- #

def test_verify_reports_schema_findings_too(eng, project):
    data = _valid()
    _entry(data, "checkout.spec.ts")["kind"] = "smoke-ish"
    findings = eng.errors_only(eng.verify_suite_manifest(data, project))
    assert "unknown-kind" in _kinds(findings)


def test_verify_survives_a_structurally_broken_manifest_without_crashing(eng, project):
    findings = eng.errors_only(eng.verify_suite_manifest({"tests": "not a list"},
                                                         project))
    assert findings, "a broken manifest must produce findings, not an exception"
    assert "malformed-field" in _kinds(findings) or "missing-field" in _kinds(findings)


# --------------------------------------------------------------------------- #
# 6. CLI
# --------------------------------------------------------------------------- #

def _cli(*args):
    return subprocess.run(
        [sys.executable, str(ENGINE_PATH), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )


def test_cli_validate_exits_zero_on_the_conforming_manifest():
    proc = _cli("validate", "--json", str(VALID_MANIFEST))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 blocking" in proc.stdout


def test_cli_validate_exits_one_on_the_malformed_manifest():
    proc = _cli("validate", "--json", str(MALFORMED_MANIFEST))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "unknown-kind" in proc.stdout


def test_cli_verify_exits_zero_on_the_fixture_project(project):
    proc = _cli("verify", "--json", str(VALID_MANIFEST), "--repo-root", str(project))
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_cli_verify_exits_one_on_an_unauthorized_prod_mutation(tmp_path, project):
    data = _valid()
    _entry(data, "home-smoke.spec.ts")["mutates_data"] = True
    target = tmp_path / "suite-manifest.json"
    target.write_text(json.dumps(data), encoding="utf-8")

    proc = _cli("verify", "--json", str(target), "--repo-root", str(project))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "prod-mutating-unauthorized" in proc.stdout


@pytest.mark.parametrize("flag", ["--json", "--manifest"])
def test_cli_accepts_either_spelling_of_the_manifest_path(flag, project):
    """`--json` is the house spelling (scripts/delivery/delivery_manifest.py);
    `--manifest` is what the skill bodies document, and it reads better beside
    `--as-json`. Both resolve to the same argument so neither call site can rot
    into a usage error."""
    assert _cli("validate", flag, str(VALID_MANIFEST)).returncode == 0
    proc = _cli("verify", flag, str(VALID_MANIFEST), "--repo-root", str(project))
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_cli_validate_refuses_repo_root_rather_than_ignoring_it(project):
    """Schema validation reads no tree, so `--repo-root` on `validate` is a
    call-site mistake. Refusing it (argparse exit 2) beats accepting a flag that
    would do nothing — a silently ignored flag is the kind of thing a skill body
    documents forever and nobody ever catches."""
    proc = _cli("validate", "--manifest", str(VALID_MANIFEST), "--repo-root", str(project))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "unrecognized arguments" in proc.stderr


# --------------------------------------------------------------------------- #
# 7. House constraints — stdlib-only, explicit encodings
# --------------------------------------------------------------------------- #

_STDLIB_ROOTS = {
    "__future__", "argparse", "dataclasses", "datetime", "json", "os", "pathlib",
    "posixpath", "re", "sys", "typing", "collections", "itertools",
}


def _import_roots(path: Path) -> set:
    roots = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_the_engine_is_stdlib_only():
    extra = _import_roots(ENGINE_PATH) - _STDLIB_ROOTS
    assert not extra, f"non-stdlib import in manifest.py: {sorted(extra)}"


def test_every_file_read_or_write_pins_its_encoding():
    tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(
            node.func, "id", "")
        if name not in {"open", "read_text", "write_text"}:
            continue
        assert any(k.arg == "encoding" for k in node.keywords), (
            f"manifest.py:{node.lineno} calls {name}() without an explicit encoding"
        )


def test_the_package_exposes_an_init_module():
    assert (PKG / "__init__.py").exists()


# --------------------------------------------------------------------------- #
# 8. Adversarial findings F1 / F4 / F5 / F8 (adversary-task-1, 2026-08-26)
# --------------------------------------------------------------------------- #

def _mutating_prod(data: dict) -> dict:
    """The manifest an exception has to be complete to authorize."""
    _entry(data, "home-smoke.spec.ts")["mutates_data"] = True
    return data


#: The nine bypass variants the adversary drove to CLI exit 0. Every one is a
#: FALSY-BUT-NOT-BLANK value that the old `_blank()` read as present, so an
#: exception declaring there is NO teardown authorized a production-mutating
#: test. `teardown: false` is the sharpest: it is an explicit statement that the
#: test cleans up nothing, and it read as satisfying "mandatory teardown".
_F1_BYPASS_VARIANTS = {
    "teardown-false": {"teardown": False},
    "teardown-zero": {"teardown": 0},
    "teardown-empty-list": {"teardown": []},
    "teardown-empty-dict": {"teardown": {}},
    "authorization-legs-false": {"authorization": {"who": False, "when": False, "why": False}},
    "authorization-legs-zero": {"authorization": {"who": 0, "when": 0, "why": 0}},
    "authorization-legs-empty-list": {"authorization": {"who": [], "when": [], "why": []}},
    "all-falsy-together": {"teardown": False, "test_data_tag": "it-",
                           "authorization": {"who": False, "when": False, "why": False}},
    "bare-it-prefix-tag": {"test_data_tag": "it-"},
}


@pytest.mark.parametrize("variant", sorted(_F1_BYPASS_VARIANTS))
def test_f1_a_falsy_exception_leg_does_not_authorize_a_prod_mutation(eng, variant, project):
    """F1 (blocking). A non-string falsy leg is not a recorded value - it is the
    absence of one, sometimes an explicit denial of one. Nine of these reached
    exit 0 on a mutating prod test."""
    data = _mutating_prod(_valid())
    data["prod_exceptions"] = [_authorization(**_F1_BYPASS_VARIANTS[variant])]

    findings = eng.errors_only(eng.verify_suite_manifest(data, project))
    kinds = _kinds(findings)
    assert "prod-exception-incomplete" in kinds, (
        f"{variant}: a falsy leg was accepted as a complete authorization"
    )
    assert "prod-mutating-unauthorized" in kinds, (
        f"{variant}: the mutating prod test was exempted by an incomplete exception"
    )


@pytest.mark.parametrize("variant", sorted(_F1_BYPASS_VARIANTS))
def test_f1_the_real_cli_refuses_every_bypass_variant(variant, project, tmp_path):
    """The adversary's end-to-end reproduction: the same nine manifests driven
    through the real CLI, which reported '0 blocking finding(s)' on all nine."""
    data = _mutating_prod(_valid())
    data["prod_exceptions"] = [_authorization(**_F1_BYPASS_VARIANTS[variant])]
    target = tmp_path / f"bypass-{variant}.json"
    target.write_text(json.dumps(data), encoding="utf-8")

    proc = _cli("verify", "--manifest", str(target), "--repo-root", str(project))
    assert proc.returncode == 1, f"{variant} SHIPPED: {proc.stdout}{proc.stderr}"
    assert "prod-mutating-unauthorized" in proc.stdout


def test_f1_a_tag_that_is_the_bare_prefix_plus_a_real_suffix_is_still_accepted(eng, project):
    """The other direction - the fix must not reject legitimate tags."""
    data = _mutating_prod(_valid())
    data["prod_exceptions"] = [_authorization(test_data_tag="it-prodsmoke-")]
    assert eng.errors_only(eng.verify_suite_manifest(data, project)) == []


@pytest.mark.parametrize("leg", ["teardown", "test_data_tag"])
def test_f1_a_non_string_leg_is_named_in_the_finding(eng, leg, project):
    data = _mutating_prod(_valid())
    data["prod_exceptions"] = [_authorization(**{leg: False})]
    findings = eng.errors_only(eng.verify_suite_manifest(data, project))
    assert _mentioning(findings, leg), f"the finding does not name the {leg} leg"


def test_f4_an_exception_scoped_to_one_test_name_does_not_exempt_another(eng, project):
    """F4. Mutation N3 (`_covers` returns True unconditionally) escaped all 106
    tests: the FILE axis was pinned, the test_name axis was not."""
    data = _mutating_prod(_valid())
    data["prod_exceptions"] = [_authorization(test_name="some other test entirely")]

    findings = eng.errors_only(eng.verify_suite_manifest(data, project))
    assert "prod-mutating-unauthorized" in _kinds(findings), (
        "an exception naming a test this entry does not declare still exempted it"
    )


def test_f4_an_exception_scoped_to_a_declared_test_name_does_exempt_it(eng, project):
    """The other direction, so the fix cannot be 'ignore test_name entirely'."""
    data = _mutating_prod(_valid())
    named = _entry(data, "home-smoke.spec.ts")["test_names"][0]
    data["prod_exceptions"] = [_authorization(test_name=named)]
    assert eng.errors_only(eng.verify_suite_manifest(data, project)) == []


def test_f5_reconciliation_sees_a_case_variant_spec_extension(eng, project):
    """F5. Mutation N2 (drop `.lower()` in `_is_spec`) escaped all 106 tests.
    A case-variant spec that reconciliation cannot see is an unregistered test
    that the full-suite run silently skips."""
    (project / "e2e" / "debug-flows" / "Orphan.Spec.TS").write_text(
        "import { test } from '@playwright/test';\n", encoding="utf-8")
    findings = eng.errors_only(eng.verify_suite_manifest(_valid(), project))
    assert "unlisted-on-disk" in _kinds(findings)
    assert _mentioning(findings, "Orphan.Spec.TS")


def test_f8_an_origin_ref_pointing_at_a_directory_blocks(eng, project):
    """F8. `.exists()` is satisfied by any filesystem node; a directory carries
    no provenance."""
    (project / "bugs" / "SR-777.json").mkdir(parents=True)
    data = _valid()
    _entry(data, "sr-014-cart-total.spec.ts")["origin_ref"] = "bugs/SR-777.json"
    findings = eng.errors_only(eng.verify_suite_manifest(data, project))
    assert "debug-flow-dead-origin" in _kinds(findings)


def test_f8_an_origin_ref_pointing_at_an_empty_file_blocks(eng, project):
    (project / "bugs" / "SR-778.json").write_text("", encoding="utf-8")
    data = _valid()
    _entry(data, "sr-014-cart-total.spec.ts")["origin_ref"] = "bugs/SR-778.json"
    findings = eng.errors_only(eng.verify_suite_manifest(data, project))
    assert "debug-flow-dead-origin" in _kinds(findings)


def test_f8_a_real_non_empty_origin_artifact_still_passes(eng, project):
    """The other direction - the committed fixture SR artifact must stay live."""
    assert eng.errors_only(eng.verify_suite_manifest(_valid(), project)) == []


def test_s3_reconciliation_covers_dot_test_files_as_well_as_dot_spec(eng, project):
    """SPEC AMENDMENT (2026-08-26): reconciliation covers every Playwright test
    file - `*.spec.ts` OR `*.test.ts`, case-insensitively. `.test.ts` is an
    ordinary Playwright naming convention, and an unregistered one is exactly
    the drift the unlisted-on-disk arm exists to catch."""
    body = "import { test } from '@playwright/test';\n"
    (project / "e2e" / "personas" / "shopper" / "wishlist.test.ts").write_text(
        body, encoding="utf-8")
    (project / "e2e" / "debug-flows" / "Legacy.Test.TS").write_text(
        body, encoding="utf-8")

    findings = eng.errors_only(eng.verify_suite_manifest(_valid(), project))
    assert _mentioning(findings, "wishlist.test.ts"), "a .test.ts spec is invisible"
    assert _mentioning(findings, "Legacy.Test.TS"), "a case-variant .test.ts is invisible"


def test_s3_a_listed_dot_test_file_reconciles_clean(eng, project):
    """The other direction: once registered, a .test.ts entry must not then be
    reported as missing."""
    (project / "e2e" / "personas" / "shopper" / "wishlist.test.ts").write_text(
        "import { test } from '@playwright/test';\n", encoding="utf-8")
    data = _valid()
    data["tests"].append({
        "file": "e2e/personas/shopper/wishlist.test.ts",
        "test_names": ["shopper saves an item to their wishlist"],
        "persona": "shopper", "kind": "journey", "source": "pre-existing",
        "covers_elements": [], "covers_routes": ["/wishlist"],
        "safety": "dev", "mutates_data": True, "origin_ref": None,
    })
    assert eng.errors_only(eng.verify_suite_manifest(data, project)) == []


def test_s3_a_non_test_typescript_file_is_still_ignored(eng, project):
    """`latest.ts` and `contest.ts` merely CONTAIN the substring 'test'; they are
    not tests, and the widened match must not swallow them."""
    (project / "e2e" / "latest.ts").write_text("export const x = 1;\n", encoding="utf-8")
    (project / "e2e" / "contest.ts").write_text("export const y = 2;\n", encoding="utf-8")
    assert eng.errors_only(eng.verify_suite_manifest(_valid(), project)) == []


def test_the_exact_spec_suffix_set_is_published_for_spec_alignment(eng):
    """CHARACTERIZATION pin, not a red-first fix - it asserts what the engine
    already does so the set is readable off a test rather than off the source.

    The spec's leg (a) names the family as "`*.spec.ts` or `*.test.ts`,
    case-insensitively". This engine sweeps a deliberate SUPERSET: both stems
    across six JS/TS extensions. A `.spec.js` or `.test.tsx` under an e2e
    directory is a Playwright test somebody wrote, and an unregistered one is
    precisely the drift leg (a) exists to catch, so narrowing to the two literal
    forms would reintroduce the vacuous-pass the amendment closed.

    RULED IN (lead, 2026-08-26): the superset stands and the spec's leg (a) was
    AMENDED to cite this published family — "a `.spec.*` or `.test.*` stem with
    a JS/TS extension — the engine's published SPEC_SUFFIXES set of 12, both
    stems across js/jsx/ts/tsx/mjs/cjs, case-insensitively and leading-dot
    anchored". So this pin is no longer flagging a divergence; it is the
    alignment anchor the spec text points at, and changing the tuple means
    changing the spec.
    """
    assert eng.SPEC_SUFFIXES == (
        ".spec.ts", ".spec.tsx", ".spec.js", ".spec.jsx", ".spec.mjs", ".spec.cjs",
        ".test.ts", ".test.tsx", ".test.js", ".test.jsx", ".test.mjs", ".test.cjs",
    )
    # Both stems the spec names literally are in the set...
    assert ".spec.ts" in eng.SPEC_SUFFIXES and ".test.ts" in eng.SPEC_SUFFIXES
    # ...and every entry is anchored on a leading dot, which is what keeps
    # `latest.ts` and `contest.ts` out of the sweep.
    assert all(s.startswith(".") for s in eng.SPEC_SUFFIXES)


# --------------------------------------------------------------------------- #
# 9. adversary-task-1 round-2 residuals (2026-08-26)
# --------------------------------------------------------------------------- #

#: adv-R1. F1 closed the falsy-value class in the prod-exception arm but left it
#: open in the SCHEMA arm, which still used `_blank`. Same defect, same file:
#: `false` is not a blank string, so it read as a present value.
_R1_FALSY_SCHEMA_CASES = {
    "file-false": ("file", False),
    "file-zero": ("file", 0),
    "persona-false": ("persona", False),
    "test_names-item-false": ("test_names", [False]),
    "test_names-item-zero": ("test_names", [0]),
    "covers_routes-item-false": ("covers_routes", [False]),
    "covers_elements-item-false": ("covers_elements", [False]),
}


@pytest.mark.parametrize("case", sorted(_R1_FALSY_SCHEMA_CASES))
def test_advR1_a_falsy_schema_value_blocks_exactly_like_null_does(eng, case):
    field, value = _R1_FALSY_SCHEMA_CASES[case]
    data = _valid()
    _entry(data, "checkout.spec.ts")[field] = value
    findings = eng.errors_only(eng.validate_manifest(data))
    assert any(f.get("field") == field for f in findings), (
        f"{case}: {field}={value!r} was accepted as a present value"
    )


@pytest.mark.parametrize("case", sorted(_R1_FALSY_SCHEMA_CASES))
def test_advR1_the_null_form_of_each_case_blocks_too(eng, case):
    """The control the falsy cases are measured against - if null did NOT block,
    the parametrization above would be proving nothing."""
    field, value = _R1_FALSY_SCHEMA_CASES[case]
    data = _valid()
    _entry(data, "checkout.spec.ts")[field] = [None] if isinstance(value, list) else None
    findings = eng.errors_only(eng.validate_manifest(data))
    assert any(f.get("field") == field for f in findings)


def test_advR1_legitimate_string_values_still_validate_clean(eng):
    """The other direction: the tightened check must not reject real manifests."""
    assert eng.errors_only(eng.validate_manifest(_valid())) == []


#: adv-R4. `"  it-x".strip().startswith("it-")` was True, so a tag whose stored
#: form begins with whitespace passed - while a teardown sweep keyed on the `it-`
#: prefix would never match the record it actually wrote.
_R4_WHITESPACE_TAGS = ["  it-x", "\tit-prodsmoke-", " it-order-", "\n it-x"]


@pytest.mark.parametrize("tag", _R4_WHITESPACE_TAGS)
def test_advR4_a_leading_whitespace_test_data_tag_still_blocks(eng, tag, project):
    data = _valid()
    _entry(data, "home-smoke.spec.ts")["mutates_data"] = True
    data["prod_exceptions"] = [_authorization(test_data_tag=tag)]

    findings = eng.errors_only(eng.verify_suite_manifest(data, project))
    assert "prod-exception-incomplete" in _kinds(findings), (
        f"tag {tag!r} was accepted despite leading whitespace"
    )
    assert "prod-mutating-unauthorized" in _kinds(findings)


def test_advR4_a_clean_tag_is_still_accepted(eng, project):
    """The other direction - the comparison must not become 'reject everything'."""
    data = _valid()
    _entry(data, "home-smoke.spec.ts")["mutates_data"] = True
    data["prod_exceptions"] = [_authorization(test_data_tag="it-prodsmoke-")]
    assert eng.errors_only(eng.verify_suite_manifest(data, project)) == []


def test_advR2_missing_text_records_zero_width_only_fields_as_a_known_non_goal(eng):
    """adv-R2, accepted as informational. A field of only zero-width characters
    (U+200B and friends) is non-blank to str.strip() and would pass. Recording it
    as a decided non-goal rather than leaving it an unexamined hole - the
    docstring is the record, and this pin makes the record load-bearing so it
    cannot be quietly dropped."""
    doc = eng._missing_text.__doc__ or ""
    assert "zero-width" in doc.lower(), (
        "_missing_text's docstring no longer records the zero-width non-goal"
    )
    # And the behaviour the docstring describes is the actual behaviour.
    assert eng._missing_text("​") is False
    assert eng._missing_text("") is True
    assert eng._missing_text(False) is True


# --------------------------------------------------------------------------- #
# 10. Focal point (a) — the _missing_text spread must not FALSE-BLOCK
# --------------------------------------------------------------------------- #
#
# adv-R1 widened `_missing_text` from 4 call sites to 10. Every pin for it so
# far asserts the BLOCKING direction. A guard that blocks everything would pass
# all of them, so each newly-guarded field needs its legitimate value pinned
# too — otherwise "we tightened it" is indistinguishable from "we broke it".

_R1_LEGITIMATE_VALUES = {
    "file": "e2e/personas/shopper/checkout.spec.ts",
    "persona": "shopper",
    "kind": "journey",
    "source": "user-flow",
    "safety": "dev",
    "test_names": ["shopper completes a card checkout"],
    "covers_elements": ["cart__summary__checkout__1"],
    "covers_routes": ["/cart"],
}


@pytest.mark.parametrize("field", sorted(_R1_LEGITIMATE_VALUES))
def test_focal_a_legitimate_value_for_each_newly_guarded_field_is_accepted(eng, field):
    data = _valid()
    _entry(data, "checkout.spec.ts")[field] = _R1_LEGITIMATE_VALUES[field]
    findings = eng.errors_only(eng.validate_manifest(data))
    offending = [f for f in findings if f.get("field") == field]
    assert not offending, (
        f"the tightened guard FALSE-BLOCKS a legitimate {field}="
        f"{_R1_LEGITIMATE_VALUES[field]!r}: {offending}"
    )


def test_focal_a_whitespace_padded_string_is_still_accepted_where_it_is_legal(eng):
    """`_missing_text` strips before judging emptiness, so a padded but non-empty
    value is a PRESENT value. Only the prod-exception TAG compares unstripped,
    and only because a sweep keys on that exact prefix."""
    data = _valid()
    _entry(data, "checkout.spec.ts")["persona"] = "shopper"
    data["personas"] = ["shopper", "ops"]
    assert eng.errors_only(eng.validate_manifest(data)) == []


def test_focal_the_whole_conforming_fixture_still_validates_and_verifies_clean(
        eng, project):
    """The blunt end-to-end control for the spread: if the widened guard
    false-blocked anything at all in a real manifest, this goes red."""
    assert eng.errors_only(eng.validate_manifest(_valid())) == []
    assert eng.errors_only(eng.verify_suite_manifest(_valid(), project)) == []


@pytest.mark.parametrize("tag", ["  it-x", "\tit-prodsmoke-", " it-order-"])
def test_r6_the_whitespace_refusal_names_whitespace_as_the_cause(eng, tag, project):
    """R6 item 3. The tag DOES carry the `it-` prefix — it just carries stray
    whitespace in front of it. Reporting "does not use the 'it-' prefix
    convention" sends the author looking for a defect that is not there, and the
    one that IS there is invisible in most editors."""
    data = _valid()
    _entry(data, "home-smoke.spec.ts")["mutates_data"] = True
    data["prod_exceptions"] = [_authorization(test_data_tag=tag)]

    findings = eng.errors_only(eng.verify_suite_manifest(data, project))
    incomplete = [f for f in findings if f["kind"] == "prod-exception-incomplete"]
    assert incomplete, "the whitespace tag stopped blocking"
    detail = incomplete[0]["detail"]
    assert "whitespace" in detail.lower(), (
        f"the refusal does not name the real cause: {detail}"
    )
    assert "does not use the" not in detail, (
        f"the refusal still blames a missing prefix the tag actually has: {detail}"
    )


def test_r6_a_genuinely_wrong_prefix_still_names_the_prefix(eng, project):
    """The other direction — the new branch must not swallow the real
    wrong-prefix case, which is a different defect with a different fix."""
    data = _valid()
    _entry(data, "home-smoke.spec.ts")["mutates_data"] = True
    data["prod_exceptions"] = [_authorization(test_data_tag="smoke-")]

    findings = eng.errors_only(eng.verify_suite_manifest(data, project))
    detail = [f for f in findings if f["kind"] == "prod-exception-incomplete"][0]["detail"]
    assert "does not use the" in detail, detail
    assert "whitespace" not in detail.lower(), (
        f"a genuinely wrong prefix was misreported as a whitespace problem: {detail}"
    )
