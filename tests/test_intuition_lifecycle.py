"""Tests for the intuition-map lifecycle engine (`scripts/intuition_lifecycle/`).

The engine is the deterministic mechanism under the `intuition-map-lifecycle`
skill's three verbs — `ensure`, `grow`, `bug-path-upsert` — against the
`interaction-intuition` artifact (`<codebase>/docs/INTERACTION_INTUITION_MAP.md`:
YAML frontmatter + per-element YAML-blocks-in-markdown).

Four properties carry the change and each is pinned in BOTH directions:

1. **The schema addition is additive.** `source` / `regression_refs[]` absent
   reads as `source: intuiter`, `regression_refs: []`. A map produced before
   this change parses unchanged, and a no-op rewrite is byte-identical.
2. **Untouched entries survive a rewrite content-identically.** The engine
   re-serializes only the blocks it changed; every other block is emitted from
   the raw text it was parsed from.
3. **A contradiction asks, it never overwrites.** `grow` against a CONFIRMED
   entry whose `confirmed_action` / `confirmed_endpoint` disagrees leaves the
   entry untouched and emits a question artifact naming BOTH readings — and the
   opposite direction is pinned too (an agreeing restatement raises no question
   and still upserts), so a mutation that drops the guard cannot pass by making
   the engine silent everywhere.
4. **Provenance is recorded, not inferred.** `grow` writes `source: user-flow`
   with `user_verdict: confirmed`; `bug-path-upsert` writes `source: bug-path`
   plus `regression_refs[]` naming the covering debug-flow test and the SR/bug.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests.helpers.module_loader import load_module

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG = REPO_ROOT / "scripts" / "intuition_lifecycle"
ENGINE_PATH = PKG / "engine.py"
CLI_PATH = PKG / "cli.py"
FIX = REPO_ROOT / "tests" / "fixtures" / "intuition_lifecycle"
PRE_CHANGE_MAP = FIX / "pre_change_map.md"
MALFORMED_MAP = FIX / "malformed_map.md"


@pytest.fixture(scope="module")
def eng() -> ModuleType:
    return load_module(ENGINE_PATH, "ct6_intuition_engine")


@pytest.fixture()
def pre_change_text() -> str:
    return PRE_CHANGE_MAP.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Test-local helpers (deliberately independent of the engine's own parser, so a
# bug in the parser cannot make these helpers agree with it).
# --------------------------------------------------------------------------- #

def _raw_block_for(text: str, element_id: str) -> str:
    """The verbatim fenced yaml block whose body declares ``element_id``."""
    blocks = []
    lines = text.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        if lines[i].startswith("```yaml"):
            start = i
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                i += 1
            blocks.append("".join(lines[start:i + 1]))
        i += 1
    hits = [b for b in blocks if f"element_id: {element_id}\n" in b]
    assert len(hits) == 1, (
        f"expected exactly one raw block declaring {element_id!r}, found {len(hits)}"
    )
    return hits[0]


def _finding_kinds(findings) -> set:
    return {f["kind"] for f in findings}


def _findings_mentioning(findings, needle: str) -> list:
    return [f for f in findings if needle in json.dumps(f)]


def _flow_element(**overrides) -> dict:
    base = {
        "route": "/dashboard",
        "label": "Save layout",
        "kind": "button",
        "action": "Persist the widget arrangement the user just dragged into place, "
                  "so the dashboard reopens the same way.",
        "endpoint": {"method": "PUT", "path": "/api/dashboard/layout"},
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# 1. Parse — a pre-change map reads unchanged, with additive defaults
# --------------------------------------------------------------------------- #

def test_pre_change_map_parses_with_every_element_in_document_order(eng, pre_change_text):
    doc = eng.parse_map(pre_change_text)
    assert [e.element_id for e in doc.elements] == [
        "dashboard__header__save-layout__1",
        "dashboard__row__archive__1",
        "items-id-edit__form__title-input__1",
        "items-id-edit__footer__delete__1",
    ]


def test_pre_change_entries_read_as_intuiter_with_empty_regression_refs(eng, pre_change_text):
    """The spec's backward-compatibility scenario: an entry without the new
    fields reads as intuiter-produced with no regression references."""
    doc = eng.parse_map(pre_change_text)
    for el in doc.elements:
        assert el.source == "intuiter", f"{el.element_id} defaulted to {el.source!r}"
        assert el.regression_refs == [], f"{el.element_id} invented regression refs"


def test_defaults_are_a_reading_not_a_rewrite(eng, pre_change_text):
    """The default must not be written back into the parsed entry — that would
    silently migrate every pre-change map the engine merely READS."""
    doc = eng.parse_map(pre_change_text)
    for el in doc.elements:
        assert "source" not in el.data
        assert "regression_refs" not in el.data


def test_frontmatter_parses_scalars_lists_and_nested_mappings(eng, pre_change_text):
    doc = eng.parse_map(pre_change_text)
    fm = doc.frontmatter
    assert fm["confirmed"] is True
    assert fm["confirmed_at"] == "2026-08-19T15:04:41Z"
    assert fm["producer"] == "interaction-intuiter"
    assert fm["covers_screens"] == 2
    assert fm["covers_elements"] == 4
    assert fm["inputs"] == [
        "docs/ROUTE_MAP.md",
        "docs/DESIGN_MAP.md",
        "../../docs/INTEGRATION_MAP.md",
    ]
    assert fm["confidence_summary"] == {"high": 2, "medium": 1, "low": 1, "unknown": 0}


def test_element_yaml_subset_parses_the_shapes_the_artifact_actually_uses(eng, pre_change_text):
    doc = eng.parse_map(pre_change_text)

    save = doc.get("dashboard__header__save-layout__1")
    # A double-quoted scalar containing ", so ..." keeps its commas and its colonless prose.
    assert save.data["intuited_action"].endswith("the dashboard reopens the same way.")
    # A block sequence of mappings.
    assert save.data["candidate_endpoints"] == [{
        "method": "PUT",
        "path": "/api/dashboard/layout",
        "source": "docs/INTEGRATION_MAP.md#put-api-dashboard-layout",
        "match_kind": "exact-by-action-noun",
    }]
    # A nested mapping value.
    assert save.data["confirmed_endpoint"]["method"] == "PUT"
    assert save.data["confirmed_endpoint"]["path"] == "/api/dashboard/layout"
    # null reads as None, not the string "null".
    assert save.data["ambiguity_question"] is None
    assert save.data["superseded_by"] is None

    archive = doc.get("dashboard__row__archive__1")
    # An empty flow sequence.
    assert archive.data["candidate_endpoints"] == []
    # A quoted string whose CONTENT contains ": " survives whole.
    assert archive.data["evidence"] == [
        "docs/DESIGN_MAP.md#dashboard-row-actions: an unlabelled box icon sits at "
        "the end of each row"
    ]
    assert archive.data["confidence"] == "low"
    assert archive.data["user_verdict"] is None


def test_a_no_op_serialize_is_byte_identical_to_disk(eng, pre_change_text):
    """Round-trip identity is what makes 'untouched entries survive' provable."""
    doc = eng.parse_map(pre_change_text)
    assert eng.serialize_map(doc) == pre_change_text


def test_load_map_reads_utf8_regardless_of_the_platform_locale(eng):
    """The fixture carries an em-dash; a locale-default read mojibakes or raises
    under Windows cp1252."""
    doc = eng.load_map(PRE_CHANGE_MAP)
    assert "storefront-web" in eng.serialize_map(doc)
    assert len(doc.elements) == 4


def test_the_parser_refuses_an_unsupported_construct_by_name(eng):
    text = (
        "---\nlast_intuited: 2026-08-01T00:00:00Z\nconfirmed: false\n"
        "confirmed_at: null\nproducer: interaction-intuiter\ninputs: []\n"
        "covers_screens: 0\ncovers_elements: 1\n"
        "confidence_summary:\n  high: 0\n  medium: 0\n  low: 1\n  unknown: 0\n---\n\n"
        "### x\n\n```yaml\n"
        "element_id: x__y__z__1\n"
        "route: /x\n"
        "element_label: X\n"
        "candidate_endpoints: {method: GET, path: /api/x}\n"
        "```\n"
    )
    with pytest.raises(eng.MapParseError) as exc:
        eng.parse_map(text)
    assert "flow" in str(exc.value).lower() or "unsupported" in str(exc.value).lower()


# --------------------------------------------------------------------------- #
# 2. Upsert preserves untouched entries content-identically
# --------------------------------------------------------------------------- #

def test_upsert_leaves_every_untouched_entry_content_identical(eng, pre_change_text):
    doc = eng.parse_map(pre_change_text)
    eng.grow(doc, [_flow_element(
        route="/catalog", label="Filter", kind="button",
        action="Narrow the catalog list to the chosen categories.",
        endpoint={"method": "GET", "path": "/api/catalog"},
    )], origin="e2e/personas/shopper/browse-catalog.spec.ts")
    out = eng.serialize_map(doc)

    for element_id in ("dashboard__header__save-layout__1",
                       "dashboard__row__archive__1",
                       "items-id-edit__form__title-input__1",
                       "items-id-edit__footer__delete__1"):
        assert _raw_block_for(pre_change_text, element_id) in out, (
            f"{element_id} was re-serialized even though nothing touched it"
        )


def test_upsert_preserves_the_prose_body_between_the_blocks(eng, pre_change_text):
    doc = eng.parse_map(pre_change_text)
    eng.grow(doc, [_flow_element(route="/catalog", label="Filter")],
             origin="e2e/personas/shopper/browse-catalog.spec.ts")
    out = eng.serialize_map(doc)
    assert "# Interaction intuition map — storefront-web" in out
    assert "Low and unknown items were resolved at the Phase -1D bulk-verify gate." in out
    assert "## /items/[id]/edit" in out


def test_a_written_map_reparses_to_the_same_elements(eng, pre_change_text, tmp_path):
    doc = eng.parse_map(pre_change_text)
    eng.grow(doc, [_flow_element(route="/catalog", label="Filter")], origin="flow.spec.ts")
    target = tmp_path / "docs" / "INTERACTION_INTUITION_MAP.md"
    eng.write_map(doc, target)
    reparsed = eng.load_map(target)
    assert len(reparsed.elements) == 5
    assert eng.errors_only(eng.validate_map(reparsed)) == []


# --------------------------------------------------------------------------- #
# 3. grow — user-specified flows land as confirmed entries
# --------------------------------------------------------------------------- #

def test_grow_creates_a_new_entry_as_a_confirmed_user_flow(eng, pre_change_text):
    doc = eng.parse_map(pre_change_text)
    result = eng.grow(doc, [_flow_element(
        route="/catalog", label="Filter", kind="button",
        action="Narrow the catalog list to the chosen categories.",
        endpoint={"method": "GET", "path": "/api/catalog"},
    )], origin="e2e/personas/shopper/browse-catalog.spec.ts")

    assert result["questions"] == []
    assert len(result["created"]) == 1
    created = doc.get(result["created"][0])
    assert created.source == "user-flow"
    assert created.data["user_verdict"] == "confirmed"
    assert created.data["confidence"] == "high"
    assert created.data["confirmed_action"] == "Narrow the catalog list to the chosen categories."
    assert created.data["confirmed_endpoint"]["method"] == "GET"
    assert created.data["confirmed_endpoint"]["path"] == "/api/catalog"
    assert created.data["route"] == "/catalog"
    assert created.data["element_label"] == "Filter"


def test_grow_confirms_an_existing_low_confidence_entry_without_asking(eng, pre_change_text):
    """The −1D gate resolves the INTUITER's uncertainty. A user-specified flow
    carries none — the user IS the source — so an unconfirmed entry is upserted
    outright (design decision D2, the documented bulk-verify bypass)."""
    doc = eng.parse_map(pre_change_text)
    result = eng.grow(doc, [_flow_element(
        route="/dashboard", label="Archive", kind="button",
        action="Take the row out of the active list; it stays queryable.",
        endpoint={"method": "POST", "path": "/api/items/{id}/archive"},
    )], origin="e2e/personas/ops/archive.spec.ts")

    assert result["questions"] == []
    assert result["updated"] == ["dashboard__row__archive__1"]
    el = doc.get("dashboard__row__archive__1")
    assert el.source == "user-flow"
    assert el.data["user_verdict"] == "confirmed"
    assert el.data["confidence"] == "high"
    assert el.data["confirmed_action"] == "Take the row out of the active list; it stays queryable."
    assert el.data["confirmed_endpoint"]["path"] == "/api/items/{id}/archive"


def test_grow_matches_an_existing_entry_by_route_and_label(eng, pre_change_text):
    """A flow names a route and a visible label, never an element_id — so the
    match has to happen on those or every grow would duplicate the map."""
    doc = eng.parse_map(pre_change_text)
    before = len(doc.elements)
    result = eng.grow(doc, [_flow_element(
        route="/dashboard", label="  save   LAYOUT ",
        action="Persist the widget arrangement the user just dragged into place, "
               "so the dashboard reopens the same way.",
    )], origin="flow.spec.ts")
    assert len(doc.elements) == before, "grow duplicated an element it should have matched"
    assert result["created"] == []
    assert "dashboard__header__save-layout__1" in (result["updated"] + result["unchanged"])


def test_grow_records_the_origin_flow_as_evidence(eng, pre_change_text):
    doc = eng.parse_map(pre_change_text)
    eng.grow(doc, [_flow_element(route="/catalog", label="Filter")],
             origin="e2e/personas/shopper/browse-catalog.spec.ts")
    created = doc.elements[-1]
    assert any("browse-catalog.spec.ts" in str(c) for c in created.data["evidence"]), (
        "a grown entry must cite the flow that confirmed it"
    )


# --------------------------------------------------------------------------- #
# 4. Contradiction — the load-bearing pin, both directions
# --------------------------------------------------------------------------- #

def test_a_contradicting_action_leaves_the_confirmed_entry_byte_identical(eng, pre_change_text):
    doc = eng.parse_map(pre_change_text)
    result = eng.grow(doc, [_flow_element(
        route="/dashboard", label="Save layout",
        action="Export the dashboard layout to a downloadable JSON file.",
        endpoint={"method": "PUT", "path": "/api/dashboard/layout"},
    )], origin="e2e/personas/ops/export.spec.ts")

    assert result["created"] == []
    assert result["updated"] == []
    assert result["blocked"] == ["dashboard__header__save-layout__1"]
    out = eng.serialize_map(doc)
    assert _raw_block_for(pre_change_text, "dashboard__header__save-layout__1") in out, (
        "a contradicting grow rewrote the confirmed entry instead of asking"
    )
    assert out == pre_change_text, "a blocked grow must change nothing at all"


def test_a_contradicting_action_emits_a_question_naming_both_readings(eng, pre_change_text):
    doc = eng.parse_map(pre_change_text)
    result = eng.grow(doc, [_flow_element(
        route="/dashboard", label="Save layout",
        action="Export the dashboard layout to a downloadable JSON file.",
    )], origin="e2e/personas/ops/export.spec.ts")

    assert len(result["questions"]) == 1
    q = result["questions"][0]
    json.dumps(q)  # the artifact is emitted as JSON — it must serialize
    assert q["element_id"] == "dashboard__header__save-layout__1"
    assert "confirmed_action" in q["fields"]
    blob = json.dumps(q)
    assert "Persist the widget arrangement" in blob, "the map's reading is missing"
    assert "Export the dashboard layout" in blob, "the flow's reading is missing"
    assert "e2e/personas/ops/export.spec.ts" in blob, "the origin flow is not named"
    assert q["question"].strip().endswith("?"), "the artifact must carry a real question"


def test_a_contradicting_endpoint_also_blocks_and_asks(eng, pre_change_text):
    doc = eng.parse_map(pre_change_text)
    result = eng.grow(doc, [_flow_element(
        route="/items/[id]/edit", label="Delete item",
        action="Remove this item permanently and return the user to the item list.",
        endpoint={"method": "POST", "path": "/api/items/{id}/archive"},
    )], origin="e2e/personas/ops/delete.spec.ts")

    assert result["blocked"] == ["items-id-edit__footer__delete__1"]
    q = result["questions"][0]
    assert "confirmed_endpoint" in q["fields"]
    blob = json.dumps(q)
    assert "DELETE" in blob and "/api/items/{id}" in blob
    assert "POST" in blob and "/api/items/{id}/archive" in blob
    assert eng.serialize_map(doc) == pre_change_text


def test_an_agreeing_restatement_raises_no_question_and_still_upserts(eng, pre_change_text):
    """The other direction. A guard that blocks EVERYTHING would satisfy the
    no-overwrite pin while making `grow` useless against confirmed entries."""
    doc = eng.parse_map(pre_change_text)
    result = eng.grow(doc, [_flow_element(
        route="/dashboard", label="Save layout",
        action="  persist the WIDGET arrangement the user just dragged into place,  "
               "so the dashboard reopens the same way. ",
        endpoint={"method": "put", "path": "/api/dashboard/layout"},
    )], origin="e2e/personas/ops/save.spec.ts")

    assert result["questions"] == [], "an agreeing restatement must not ask"
    assert result["blocked"] == []
    el = doc.get("dashboard__header__save-layout__1")
    assert el.source == "user-flow", "an agreeing grow still records the user-flow provenance"
    assert el.data["user_verdict"] == "confirmed"


def test_a_contradiction_against_an_unconfirmed_entry_is_not_a_contradiction(eng, pre_change_text):
    """Only a CONFIRMED reading can be contradicted. An intuiter guess the user
    never ratified is exactly what `grow` exists to overwrite."""
    doc = eng.parse_map(pre_change_text)
    result = eng.grow(doc, [_flow_element(
        route="/items/[id]/edit", label="Title", kind="form-input",
        action="Something entirely different from the intuiter's guess.",
        endpoint={"method": "POST", "path": "/api/items"},
    )], origin="flow.spec.ts")
    assert result["questions"] == []
    assert result["updated"] == ["items-id-edit__form__title-input__1"]


def test_one_contradiction_does_not_block_the_other_elements_in_the_same_flow(eng, pre_change_text):
    doc = eng.parse_map(pre_change_text)
    result = eng.grow(doc, [
        _flow_element(route="/dashboard", label="Save layout",
                      action="Export the dashboard layout to a downloadable JSON file."),
        _flow_element(route="/catalog", label="Filter",
                      action="Narrow the catalog list to the chosen categories.",
                      endpoint={"method": "GET", "path": "/api/catalog"}),
    ], origin="flow.spec.ts")
    assert result["blocked"] == ["dashboard__header__save-layout__1"]
    assert len(result["created"]) == 1
    assert len(result["questions"]) == 1


# --------------------------------------------------------------------------- #
# 5. bug-path-upsert — provenance plus a regression pointer
# --------------------------------------------------------------------------- #

def test_bug_path_upsert_records_source_and_regression_refs(eng, pre_change_text):
    doc = eng.parse_map(pre_change_text)
    result = eng.bug_path_upsert(
        doc,
        [_flow_element(route="/cart", label="Quantity", kind="form-input",
                       action="Change the line quantity and recompute the cart total.",
                       endpoint={"method": "PATCH", "path": "/api/cart/lines/{id}"})],
        regression_refs=[{"test": "e2e/debug-flows/sr-014-cart-total.spec.ts",
                          "ref": "SR-014"}],
    )
    assert result["questions"] == []
    el = doc.get(result["created"][0])
    assert el.source == "bug-path"
    assert el.regression_refs == [{"test": "e2e/debug-flows/sr-014-cart-total.spec.ts",
                                  "ref": "SR-014"}]
    assert eng.errors_only(eng.validate_map(doc)) == []


def test_bug_path_upsert_merges_refs_without_duplicating_them(eng, pre_change_text):
    doc = eng.parse_map(pre_change_text)
    element = _flow_element(route="/cart", label="Quantity", kind="form-input",
                            action="Change the line quantity and recompute the cart total.")
    ref = {"test": "e2e/debug-flows/sr-014-cart-total.spec.ts", "ref": "SR-014"}
    eng.bug_path_upsert(doc, [element], regression_refs=[ref])
    eng.bug_path_upsert(doc, [element], regression_refs=[ref])
    eng.bug_path_upsert(doc, [element], regression_refs=[
        {"test": "e2e/debug-flows/sr-021-cart-total.spec.ts", "ref": "SR-021"}])

    el = doc.get("cart__flow__quantity__1")
    assert [r["ref"] for r in el.regression_refs] == ["SR-014", "SR-021"]


def test_bug_path_contradiction_leaves_the_entry_entirely_unmodified(
        eng, pre_change_text):
    """SPEC AMENDMENT (2026-08-26): `bug-path-upsert` now applies THE SAME guard
    as `grow` — 'the existing entry is left unmodified'.

    The build originally shipped a deliberately weaker guard here (provenance
    and regression_refs still landed; only the confirmed_* fields were held
    back), reasoning that R3 requires the bug path to REACH the map. That was
    flagged as a judgement call, and the spec resolved it the other way: a
    partial write is still a write to an entry the user ratified, and 'left
    unmodified' has to mean unmodified. The regression pointer is not lost — it
    is carried in the question artifact until the user resolves the reading."""
    doc = eng.parse_map(pre_change_text)
    before = eng.serialize_map(doc)
    result = eng.bug_path_upsert(
        doc,
        [_flow_element(route="/dashboard", label="Save layout",
                       action="Silently drop the layout when the payload exceeds 1MB.",
                       endpoint={"method": "PUT", "path": "/api/dashboard/layout"})],
        regression_refs=[{"test": "e2e/debug-flows/sr-031-layout-size.spec.ts",
                          "ref": "SR-031"}],
    )
    el = doc.get("dashboard__header__save-layout__1")
    assert el.source == "intuiter", "a blocked bug-path still rewrote the provenance"
    assert el.regression_refs == [], "a blocked bug-path still wrote a regression ref"
    assert el.data["confirmed_action"].startswith("Persist the widget arrangement")
    assert eng.serialize_map(doc) == before, "a blocked bug-path changed the map"

    assert result["blocked"] == ["dashboard__header__save-layout__1"]
    question = result["questions"][0]
    assert "confirmed_action" in question["fields"]
    blob = json.dumps(question)
    assert "SR-031" in blob, "the regression pointer must survive in the question"
    assert "sr-031-layout-size.spec.ts" in blob


def test_a_non_contradicting_bug_path_still_records_provenance_and_refs(
        eng, pre_change_text):
    """The other direction: the guard must not swallow the ordinary case R3 is
    actually about."""
    doc = eng.parse_map(pre_change_text)
    result = eng.bug_path_upsert(
        doc,
        [_flow_element(route="/dashboard", label="Archive",
                       action="Take the row out of the active list.",
                       endpoint={"method": "POST", "path": "/api/items/{id}/archive"})],
        regression_refs=[{"test": "e2e/debug-flows/sr-040.spec.ts", "ref": "SR-040"}],
    )
    assert result["questions"] == []
    el = doc.get("dashboard__row__archive__1")
    assert el.source == "bug-path"
    assert [r["ref"] for r in el.regression_refs] == ["SR-040"]


def test_a_caller_marked_ambiguous_extraction_asks_instead_of_upserting(
        eng, pre_change_text):
    """SPEC AMENDMENT (2026-08-26). Extracting elements from a .spec.ts is
    heuristic; when the CALLER could not resolve one, a wrong upsert is worse
    than a question. No entry is written and the ambiguity is surfaced."""
    doc = eng.parse_map(pre_change_text)
    before = eng.serialize_map(doc)
    result = eng.grow(doc, [_flow_element(
        route="/catalog", label="Filter",
        action="Possibly opens the filter drawer, possibly applies a saved filter.",
        ambiguous=True,
        ambiguity_note="The selector matched two controls; the flow does not "
                       "disambiguate which one it clicked.",
    )], origin="e2e/personas/shopper/browse-catalog.spec.ts")

    assert result["created"] == [], "an ambiguous extraction was upserted anyway"
    assert result["updated"] == []
    assert eng.serialize_map(doc) == before
    assert len(result["questions"]) == 1
    question = result["questions"][0]
    assert question["kind"] == "ambiguous-extraction"
    blob = json.dumps(question)
    assert "selector matched two controls" in blob, "the ambiguity is not named"
    assert "Filter" in blob and "/catalog" in blob
    assert question["question"].strip().endswith("?")


def test_an_ambiguous_flag_that_is_false_upserts_normally(eng, pre_change_text):
    """The other direction — the flag must be opt-in, not a blanket refusal."""
    doc = eng.parse_map(pre_change_text)
    result = eng.grow(doc, [_flow_element(route="/catalog", label="Filter",
                                          ambiguous=False)],
                      origin="flow.spec.ts")
    assert len(result["created"]) == 1
    assert result["questions"] == []


def test_an_ambiguous_element_does_not_block_its_siblings(eng, pre_change_text):
    doc = eng.parse_map(pre_change_text)
    result = eng.grow(doc, [
        _flow_element(route="/catalog", label="Filter", ambiguous=True,
                      ambiguity_note="two controls matched"),
        _flow_element(route="/catalog", label="Sort",
                      action="Reorder the catalog list."),
    ], origin="flow.spec.ts")
    assert len(result["created"]) == 1
    assert len(result["questions"]) == 1


def test_bug_path_refs_survive_the_serialize_reparse_round_trip(eng, pre_change_text, tmp_path):
    doc = eng.parse_map(pre_change_text)
    eng.bug_path_upsert(
        doc,
        [_flow_element(route="/cart", label="Quantity", kind="form-input",
                       action="Change the line quantity and recompute the cart total.")],
        regression_refs=[{"test": "e2e/debug-flows/sr-014-cart-total.spec.ts",
                          "ref": "SR-014"}],
    )
    target = tmp_path / "INTERACTION_INTUITION_MAP.md"
    eng.write_map(doc, target)
    el = eng.load_map(target).get("cart__flow__quantity__1")
    assert el.source == "bug-path"
    assert el.regression_refs == [{"test": "e2e/debug-flows/sr-014-cart-total.spec.ts",
                                  "ref": "SR-014"}]


def test_a_regression_ref_needs_both_the_test_and_the_bug_reference(eng, pre_change_text):
    doc = eng.parse_map(pre_change_text)
    with pytest.raises(ValueError) as exc:
        eng.bug_path_upsert(
            doc,
            [_flow_element(route="/cart", label="Quantity", kind="form-input")],
            regression_refs=[{"test": "e2e/debug-flows/sr-014.spec.ts"}],
        )
    assert "ref" in str(exc.value)


# --------------------------------------------------------------------------- #
# 6. validate — malformed entries are named by entry and field
# --------------------------------------------------------------------------- #

def test_a_conforming_map_has_zero_blocking_findings(eng, pre_change_text):
    doc = eng.parse_map(pre_change_text)
    assert eng.errors_only(eng.validate_map(doc)) == []


def test_the_malformed_fixture_is_rejected_with_each_defect_named(eng):
    doc = eng.load_map(MALFORMED_MAP)
    findings = eng.errors_only(eng.validate_map(doc))
    kinds = _finding_kinds(findings)

    assert "unknown-element-kind" in kinds
    assert _findings_mentioning(findings, "teleporter")
    assert "unknown-confidence" in kinds
    assert _findings_mentioning(findings, "quite-sure")
    assert "missing-evidence" in kinds
    assert "missing-ambiguity-question" in kinds
    assert "duplicate-element-id" in kinds
    assert _findings_mentioning(findings, "settings__panel__save__1")
    assert "missing-field" in kinds
    assert "unknown-source" in kinds
    assert _findings_mentioning(findings, "telepathy")
    assert "malformed-regression-ref" in kinds
    assert "unknown-user-verdict" in kinds
    assert "malformed-candidate-endpoint" in kinds


def test_every_finding_names_the_entry_it_came_from(eng):
    doc = eng.load_map(MALFORMED_MAP)
    for f in eng.validate_map(doc):
        assert f.get("entry"), f"finding without an entry anchor: {f}"
        assert f.get("detail"), f"finding without a detail: {f}"


def test_a_block_missing_element_id_is_still_read_as_an_element(eng):
    """Otherwise the one entry most likely to be malformed is the one entry the
    validator never sees."""
    doc = eng.load_map(MALFORMED_MAP)
    assert len(doc.elements) == 4
    findings = eng.errors_only(eng.validate_map(doc))
    assert any(f["kind"] == "missing-field" and "element_id" in f["detail"] for f in findings)


# --------------------------------------------------------------------------- #
# 7. ensure-support + scaffold
# --------------------------------------------------------------------------- #

def test_ensure_support_reports_an_absent_map(eng, tmp_path):
    report = eng.ensure_support(tmp_path)
    assert report["present"] is False
    assert report["action_required"] == "produce-map"
    assert report["map_path"].replace("\\", "/").endswith("docs/INTERACTION_INTUITION_MAP.md")


def test_ensure_support_is_a_no_op_when_the_map_exists(eng, tmp_path):
    target = eng.map_path_for(tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(PRE_CHANGE_MAP.read_text(encoding="utf-8"), encoding="utf-8")
    report = eng.ensure_support(tmp_path)
    assert report["present"] is True
    assert report["action_required"] == "none"
    assert report["covers_elements"] == 4


def test_ensure_support_reports_a_present_but_unparseable_map(eng, tmp_path):
    target = eng.map_path_for(tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("no frontmatter here, just prose\n", encoding="utf-8")
    report = eng.ensure_support(tmp_path)
    assert report["present"] is True
    assert report["action_required"] == "repair-map"
    assert report["parse_error"]


def test_scaffold_writes_an_empty_but_schema_valid_map(eng, tmp_path):
    path = eng.scaffold_map(tmp_path, inputs=["docs/ROUTE_MAP.md"],
                            now="2026-08-25T12:00:00Z")
    doc = eng.load_map(path)
    assert doc.elements == []
    assert doc.frontmatter["confirmed"] is False
    assert doc.frontmatter["last_intuited"] == "2026-08-25T12:00:00Z"
    assert doc.frontmatter["covers_elements"] == 0
    assert doc.frontmatter["confidence_summary"] == {
        "high": 0, "medium": 0, "low": 0, "unknown": 0}
    assert eng.errors_only(eng.validate_map(doc)) == []
    # rev-R4: a scaffold is schema-valid but is NOT a completed ensure — the map
    # exists and describes nothing, so the verb still has work to do.
    assert eng.ensure_support(tmp_path)["action_required"] == "populate"


def test_scaffold_refuses_to_overwrite_an_existing_map(eng, tmp_path):
    target = eng.map_path_for(tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(PRE_CHANGE_MAP.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(FileExistsError):
        eng.scaffold_map(tmp_path)
    assert target.read_text(encoding="utf-8") == PRE_CHANGE_MAP.read_text(encoding="utf-8")


def test_a_scaffolded_map_accepts_a_grow_immediately(eng, tmp_path):
    path = eng.scaffold_map(tmp_path, now="2026-08-25T12:00:00Z")
    doc = eng.load_map(path)
    result = eng.grow(doc, [_flow_element(route="/catalog", label="Filter")],
                      origin="flow.spec.ts")
    assert len(result["created"]) == 1
    eng.write_map(doc, path)
    reloaded = eng.load_map(path)
    assert len(reloaded.elements) == 1
    assert reloaded.frontmatter["covers_elements"] == 1
    assert reloaded.frontmatter["confidence_summary"]["high"] == 1


# --------------------------------------------------------------------------- #
# 8. CLI
# --------------------------------------------------------------------------- #

def _cli(*args, cwd=None):
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(cwd) if cwd else None, timeout=120,
    )


def test_cli_validate_exits_zero_on_a_conforming_map():
    proc = _cli("validate", "--map", str(PRE_CHANGE_MAP))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 blocking" in proc.stdout


def test_cli_validate_exits_one_on_the_malformed_map():
    proc = _cli("validate", "--map", str(MALFORMED_MAP))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "unknown-element-kind" in proc.stdout


def test_cli_ensure_emits_json(tmp_path):
    proc = _cli("ensure", "--codebase", str(tmp_path), "--json")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["present"] is False
    assert payload["action_required"] == "produce-map"


def test_cli_grow_writes_the_map_and_reports_a_contradiction(tmp_path):
    target = tmp_path / "docs" / "INTERACTION_INTUITION_MAP.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(PRE_CHANGE_MAP.read_text(encoding="utf-8"), encoding="utf-8")
    payload = tmp_path / "flow.json"
    payload.write_text(json.dumps({
        "origin": "e2e/personas/ops/export.spec.ts",
        "elements": [{
            "route": "/dashboard", "label": "Save layout", "kind": "button",
            "action": "Export the dashboard layout to a downloadable JSON file.",
        }],
    }), encoding="utf-8")
    questions = tmp_path / "questions.json"

    proc = _cli("grow", "--map", str(target), "--json", str(payload),
                "--questions-out", str(questions))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert target.read_text(encoding="utf-8") == PRE_CHANGE_MAP.read_text(encoding="utf-8")
    emitted = json.loads(questions.read_text(encoding="utf-8"))
    assert emitted[0]["element_id"] == "dashboard__header__save-layout__1"


def test_cli_bug_path_upsert_writes_the_refs(tmp_path):
    target = tmp_path / "docs" / "INTERACTION_INTUITION_MAP.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(PRE_CHANGE_MAP.read_text(encoding="utf-8"), encoding="utf-8")
    payload = tmp_path / "bug.json"
    payload.write_text(json.dumps({
        "regression_refs": [{"test": "e2e/debug-flows/sr-014.spec.ts", "ref": "SR-014"}],
        "elements": [{"route": "/cart", "label": "Quantity", "kind": "form-input",
                      "action": "Change the line quantity and recompute the cart total."}],
    }), encoding="utf-8")

    proc = _cli("bug-path-upsert", "--map", str(target), "--json", str(payload))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    text = target.read_text(encoding="utf-8")
    assert "source: bug-path" in text
    assert "SR-014" in text


# --------------------------------------------------------------------------- #
# 9. House constraints — stdlib-only, explicit encodings
# --------------------------------------------------------------------------- #

_STDLIB_ROOTS = {
    "__future__", "argparse", "dataclasses", "datetime", "json", "os", "pathlib",
    "re", "sys", "typing", "importlib", "textwrap", "collections", "itertools",
    "engine",
}


def _import_roots(path: Path) -> set:
    roots = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize("path", [ENGINE_PATH, CLI_PATH])
def test_the_package_is_stdlib_only(path: Path):
    extra = _import_roots(path) - _STDLIB_ROOTS
    assert not extra, f"non-stdlib import in {path.name}: {sorted(extra)}"


@pytest.mark.parametrize("path", [ENGINE_PATH, CLI_PATH])
def test_every_file_read_or_write_pins_its_encoding(path: Path):
    """Green under Windows cp1252 AND PYTHONUTF8=1 is a house constraint, and
    the map fixture carries an em-dash."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(
            node.func, "id", "")
        if name not in {"open", "read_text", "write_text"}:
            continue
        assert any(k.arg == "encoding" for k in node.keywords), (
            f"{path.name}:{node.lineno} calls {name}() without an explicit encoding"
        )


def test_the_package_exposes_an_init_module():
    assert (PKG / "__init__.py").exists()


# --------------------------------------------------------------------------- #
# 10. Adversarial findings F2 / F3 / F6 / F7 (adversary-task-1, 2026-08-26)
# --------------------------------------------------------------------------- #

def _crlf_bytes(text: str) -> bytes:
    return text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")


def test_f2_a_crlf_map_round_trips_crlf_at_the_byte_level(eng, tmp_path, pre_change_text):
    """F2. The existing no-op pin compares text that already came through
    read_text's universal-newline translation, so it is blind to line endings BY
    CONSTRUCTION. This one reads BYTES on both sides. Measured before the fix: a
    no-op load+write turned 4354 bytes into 4222 and CRLF count 132 into 0."""
    target = tmp_path / "INTERACTION_INTUITION_MAP.md"
    target.write_bytes(_crlf_bytes(pre_change_text))
    before = target.read_bytes()
    assert before.count(b"\r\n") > 100, "the fixture did not actually get CRLF endings"

    eng.write_map(eng.load_map(target), target)
    assert target.read_bytes() == before, (
        "a no-op load+write rewrote a CRLF map's line endings"
    )


def test_f2_an_lf_map_stays_lf_at_the_byte_level(eng, tmp_path, pre_change_text):
    """The other direction: the fix must not start emitting CRLF everywhere."""
    target = tmp_path / "INTERACTION_INTUITION_MAP.md"
    target.write_bytes(pre_change_text.replace("\r\n", "\n").encode("utf-8"))
    before = target.read_bytes()
    assert b"\r\n" not in before

    eng.write_map(eng.load_map(target), target)
    after = target.read_bytes()
    assert after == before
    assert b"\r\n" not in after


def test_f2_a_grow_on_a_crlf_map_keeps_crlf_and_leaves_untouched_blocks_byte_intact(
        eng, tmp_path, pre_change_text):
    """The property this whole design exists for: a reviewer can see exactly what
    a verb changed. On a CRLF checkout the measured diff was 293 lines against a
    132-line file - 100% of the file - versus 37 on LF."""
    target = tmp_path / "INTERACTION_INTUITION_MAP.md"
    target.write_bytes(_crlf_bytes(pre_change_text))

    doc = eng.load_map(target)
    eng.grow(doc, [_flow_element(route="/catalog", label="Filter")], origin="flow.spec.ts")
    eng.write_map(doc, target)

    after = target.read_bytes()
    assert after.count(b"\r\n") > 100, "the grow flattened the file's line endings"
    assert after.count(b"\n") == after.count(b"\r\n"), "the rewrite left mixed endings"
    for element_id in ("dashboard__header__save-layout__1",
                       "items-id-edit__footer__delete__1"):
        raw = _raw_block_for(pre_change_text, element_id)
        assert _crlf_bytes(raw) in after, (
            f"{element_id} did not survive a CRLF grow byte-intact"
        )


def test_f6_a_block_with_a_single_marker_key_is_still_read_as_an_element(eng):
    """F6. The marker threshold meant the MORE degraded an entry was, the more
    likely it escaped the validator entirely - a truncated write reported CLEAN.
    Contract: any yaml-fenced block carrying a marker key is an element
    candidate, and the validator says what it is missing."""
    text = (
        "---\nlast_intuited: 2026-08-01T00:00:00Z\nconfirmed: false\n"
        "confirmed_at: null\nproducer: interaction-intuiter\ninputs: []\n"
        "covers_screens: 0\ncovers_elements: 0\n"
        "confidence_summary:\n  high: 0\n  medium: 0\n  low: 0\n  unknown: 0\n---\n\n"
        "### truncated\n\n```yaml\n"
        "element_label: Delete everything\n"
        "confidence: low\n"
        "```\n"
    )
    doc = eng.parse_map(text)
    assert len(doc.elements) == 1, "a degraded entry was silently dropped as prose"
    findings = eng.errors_only(eng.validate_map(doc))
    assert any(f["kind"] == "missing-field" and f.get("field") == "element_id"
               for f in findings), "the degraded entry was not reported"


def test_f6_a_yaml_block_carrying_no_marker_key_is_still_prose(eng, pre_change_text):
    """The other direction: a genuine non-element yaml block in the body must not
    become a phantom element, and the map must still round-trip byte-identically."""
    text = pre_change_text.replace(
        "## /items/[id]/edit",
        "```yaml\nbuild: 2026-08-01\nowner: platform-team\n```\n\n## /items/[id]/edit",
    )
    doc = eng.parse_map(text)
    assert len(doc.elements) == 4
    assert eng.serialize_map(doc) == text


@pytest.mark.parametrize("verb", ["validate", "grow"])
def test_f7_a_missing_map_exits_two_with_an_actionable_message(verb, tmp_path):
    """F7. Both call sites caught only MapParseError, so an OSError from the
    read escaped as a traceback at exit 1 - indistinguishable from 'blocking
    findings, act on them'. The sibling manifest CLI already got this right."""
    payload = tmp_path / "flow.json"
    payload.write_text(json.dumps({"elements": []}), encoding="utf-8")
    missing = tmp_path / "does" / "not" / "exist.md"

    args = ["--map", str(missing)]
    if verb == "grow":
        args += ["--json", str(payload)]
    proc = _cli(verb, *args)

    assert proc.returncode == 2, (
        f"expected the documented usage-error code 2, got {proc.returncode}\n"
        f"{proc.stdout}{proc.stderr}"
    )
    assert "Traceback" not in proc.stderr, "a raw traceback reached the operator"
    assert "exist.md" in (proc.stdout + proc.stderr), "the message does not name the path"


def _unicode_contradiction_map(text: str) -> str:
    return text.replace("element_label: Save layout", "element_label: Exporter → CSV")


def test_f3_the_contradiction_path_survives_a_non_cp1252_label_on_a_cp1252_console(
        tmp_path):
    """F3. The question text embeds the element label verbatim and is PRINTED;
    on the Windows-default cp1252 console any character outside cp1252 raised
    UnicodeEncodeError. The crash landed after the map and the artifact were
    written, and exited 1 - the same code as a clean contradiction, so a caller
    checking rc could not tell a crash from the gate doing its job."""
    target = tmp_path / "docs" / "INTERACTION_INTUITION_MAP.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        _unicode_contradiction_map(PRE_CHANGE_MAP.read_text(encoding="utf-8")),
        encoding="utf-8")
    before = target.read_text(encoding="utf-8")

    payload = tmp_path / "flow.json"
    payload.write_text(json.dumps({
        "origin": "e2e/personas/ops/export.spec.ts",
        "elements": [{"route": "/dashboard", "label": "Exporter → CSV",
                      "kind": "button",
                      "action": "Export the dashboard layout to a downloadable file."}],
    }), encoding="utf-8")
    questions = tmp_path / "questions.json"

    env = dict(os.environ, PYTHONIOENCODING="cp1252")
    proc = subprocess.run(
        [sys.executable, str(CLI_PATH), "grow", "--map", str(target),
         "--json", str(payload), "--questions-out", str(questions)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=120,
    )

    assert "Traceback" not in proc.stderr, (
        f"the contradiction path crashed instead of reporting:\n{proc.stderr}"
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "CONTRADICTION" in proc.stdout, "the operator never saw the contradiction"
    assert target.read_text(encoding="utf-8") == before, "the blocked grow wrote anyway"
    assert json.loads(questions.read_text(encoding="utf-8"))[0]["element_label"] \
        == "Exporter → CSV"


def test_f3_an_unexpected_error_exits_distinctly_from_a_contradiction(tmp_path):
    """The other half of F3: a crash must never be mistaken for the gate firing.
    Any unexpected exception now exits 3, which is neither 0 (clean), 1
    (blocking / contradiction) nor 2 (usage)."""
    cli = load_module(CLI_PATH, "ct6_intuition_cli_exit3")
    target = tmp_path / "docs" / "INTERACTION_INTUITION_MAP.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(PRE_CHANGE_MAP.read_text(encoding="utf-8"), encoding="utf-8")
    payload = tmp_path / "flow.json"
    payload.write_text(json.dumps({"elements": [
        {"route": "/catalog", "label": "Filter", "action": "Narrow the list."}]}),
        encoding="utf-8")

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated engine failure")

    original = cli.engine.grow
    cli.engine.grow = _boom
    try:
        code = cli.main(["grow", "--map", str(target), "--json", str(payload)])
    finally:
        cli.engine.grow = original
    assert code == 3, f"an unexpected failure exited {code}, not the distinct code 3"


# --------------------------------------------------------------------------- #
# 11. Question artifacts name the verb that raised them (lead ruling C,
#     2026-08-26). Both verbs now share ONE contradiction guard, so `source`
#     alone is the only thing distinguishing a grow question from a bug-path
#     question - and a consumer routing these to a human needs to say which
#     verb is asking without inferring it from a provenance field.
# --------------------------------------------------------------------------- #

def test_a_grow_contradiction_question_names_grow_as_its_origin_verb(eng, pre_change_text):
    doc = eng.parse_map(pre_change_text)
    result = eng.grow(doc, [_flow_element(
        route="/dashboard", label="Save layout",
        action="Export the dashboard layout to a downloadable JSON file.",
    )], origin="e2e/personas/ops/export.spec.ts")
    question = result["questions"][0]
    assert question["origin_verb"] == "grow"
    assert question["kind"] == "intuition-contradiction"


def test_a_bug_path_contradiction_question_names_bug_path_upsert(eng, pre_change_text):
    doc = eng.parse_map(pre_change_text)
    result = eng.bug_path_upsert(
        doc,
        [_flow_element(route="/dashboard", label="Save layout",
                       action="Silently drop the layout when the payload exceeds 1MB.")],
        regression_refs=[{"test": "e2e/debug-flows/sr-031.spec.ts", "ref": "SR-031"}],
    )
    question = result["questions"][0]
    assert question["origin_verb"] == "bug-path-upsert"
    assert question["kind"] == "intuition-contradiction"


def test_the_two_verbs_questions_are_distinguishable_on_the_same_element(
        eng, pre_change_text):
    """The point of the ruling: identical element, identical contradiction shape,
    and the artifacts must still say which verb produced each."""
    contradiction = dict(route="/dashboard", label="Save layout",
                         action="A different reading entirely.")
    grow_q = eng.grow(eng.parse_map(pre_change_text),
                      [_flow_element(**contradiction)], origin="f.spec.ts")["questions"][0]
    bug_q = eng.bug_path_upsert(
        eng.parse_map(pre_change_text), [_flow_element(**contradiction)],
        regression_refs=[{"test": "t.spec.ts", "ref": "SR-9"}])["questions"][0]

    assert grow_q["origin_verb"] != bug_q["origin_verb"]
    assert {grow_q["origin_verb"], bug_q["origin_verb"]} == {"grow", "bug-path-upsert"}


def test_an_ambiguity_question_also_names_its_origin_verb(eng, pre_change_text):
    doc = eng.parse_map(pre_change_text)
    result = eng.grow(doc, [_flow_element(
        route="/catalog", label="Filter", ambiguous=True,
        ambiguity_note="the selector matched two controls")], origin="f.spec.ts")
    question = result["questions"][0]
    assert question["kind"] == "ambiguous-extraction"
    assert question["origin_verb"] == "grow"


def test_every_question_artifact_carries_an_origin_verb(eng, pre_change_text):
    """Behavioural check that the three real call sites carry origin_verb.

    This test does NOT establish that a future kind cannot ship without the
    field — it constructs its own subjects, so it only ever checks the ones its
    author remembered. That claim belongs to the source-discovery sweep in
    section 13, which reconciles against the QUESTION_KINDS registry. The
    sentence that used to sit here asserted the stronger thing and was
    disproved by a differential mutation (adversary-task-1 R5)."""
    questions = []
    questions += eng.grow(eng.parse_map(pre_change_text), [_flow_element(
        route="/dashboard", label="Save layout",
        action="A different reading.")], origin="f.spec.ts")["questions"]
    questions += eng.grow(eng.parse_map(pre_change_text), [_flow_element(
        route="/catalog", label="Filter", ambiguous=True,
        ambiguity_note="two controls matched")], origin="f.spec.ts")["questions"]
    questions += eng.bug_path_upsert(
        eng.parse_map(pre_change_text),
        [_flow_element(route="/dashboard", label="Save layout",
                       action="Another different reading.")],
        regression_refs=[{"test": "t.spec.ts", "ref": "SR-2"}])["questions"]

    assert len(questions) == 3
    for question in questions:
        assert question.get("origin_verb") in ("grow", "bug-path-upsert"), question
        json.dumps(question)


# --------------------------------------------------------------------------- #
# 12. adversary-task-1 round-2 residuals (2026-08-26)
# --------------------------------------------------------------------------- #

def test_advR3_an_ambiguous_extraction_against_an_existing_unconfirmed_entry_asks(
        eng, pre_change_text):
    """adv-R3 / mutant M2. Every ambiguity pin so far used an element ABSENT from
    the map, so a guard confined to new elements escaped all 155 tests. The
    already-present case is the one that matters more: there is a real entry to
    damage, and an intuiter's low-confidence guess is exactly what a careless
    upsert would overwrite with a wrong `confirmed`.

    dashboard__row__archive__1 is confidence:low, user_verdict:null - unratified,
    so the contradiction guard does NOT protect it. Only the ambiguity guard does.
    """
    doc = eng.parse_map(pre_change_text)
    before = eng.serialize_map(doc)
    result = eng.grow(doc, [_flow_element(
        route="/dashboard", label="Archive",
        action="Either archives the row or deletes it; the flow does not say which.",
        ambiguous=True,
        ambiguity_note="The click resolved to a bare icon button with no accessible name.",
    )], origin="e2e/personas/ops/archive.spec.ts")

    assert result["created"] == [], "an ambiguous extraction created an entry"
    assert result["updated"] == [], "an ambiguous extraction updated an existing entry"
    assert eng.serialize_map(doc) == before, "the map changed on an ambiguous extraction"

    element = doc.get("dashboard__row__archive__1")
    assert element.source == "intuiter", "provenance was overwritten"
    assert element.data["confidence"] == "low", "confidence was overwritten"
    assert element.data["user_verdict"] is None, "an ambiguous flow marked it confirmed"

    assert result["ambiguous"] == ["dashboard__row__archive__1"]
    question = result["questions"][0]
    assert question["kind"] == "ambiguous-extraction"
    assert question["element_id"] == "dashboard__row__archive__1", (
        "the question does not name the existing entry it declined to touch"
    )
    assert "bare icon button" in json.dumps(question)


def test_advR3_an_ambiguous_extraction_against_a_CONFIRMED_entry_also_touches_nothing(
        eng, pre_change_text):
    """The ambiguity guard runs BEFORE the contradiction guard, so a ratified
    entry is protected by whichever fires - and neither may write."""
    doc = eng.parse_map(pre_change_text)
    before = eng.serialize_map(doc)
    result = eng.grow(doc, [_flow_element(
        route="/dashboard", label="Save layout",
        action="Unclear from the flow.", ambiguous=True,
        ambiguity_note="two candidate controls matched the selector",
    )], origin="f.spec.ts")

    assert eng.serialize_map(doc) == before
    assert result["created"] == [] and result["updated"] == []
    assert result["questions"][0]["kind"] == "ambiguous-extraction"
    element = doc.get("dashboard__header__save-layout__1")
    assert element.data["confirmed_action"].startswith("Persist the widget arrangement")


def test_advR3_bug_path_upsert_honours_the_ambiguity_guard_on_an_existing_entry(
        eng, pre_change_text):
    """The guard lives in the shared upsert path, so both verbs get it."""
    doc = eng.parse_map(pre_change_text)
    before = eng.serialize_map(doc)
    result = eng.bug_path_upsert(
        doc,
        [_flow_element(route="/dashboard", label="Archive", ambiguous=True,
                       ambiguity_note="the repro clicked an unnamed icon")],
        regression_refs=[{"test": "e2e/debug-flows/sr-050.spec.ts", "ref": "SR-050"}],
    )
    assert eng.serialize_map(doc) == before
    assert result["questions"][0]["origin_verb"] == "bug-path-upsert"
    assert doc.get("dashboard__row__archive__1").regression_refs == []


@pytest.mark.parametrize("bad_origin", [5, 0, True, ["e2e/a.spec.ts"], {"path": "a"}])
def test_advR4_a_non_string_origin_is_refused_rather_than_cited(
        eng, pre_change_text, bad_origin):
    """adv-R4. `origin` is interpolated straight into an evidence citation, so a
    non-string produces a bogus one - `5: user-specified flow exercised this
    element` reads like a citation and names nothing. Evidence that names
    nothing is the exact thing interaction-intuition's hard rule refuses."""
    doc = eng.parse_map(pre_change_text)
    with pytest.raises(ValueError) as exc:
        eng.grow(doc, [_flow_element(route="/catalog", label="Filter")],
                 origin=bad_origin)
    assert "origin" in str(exc.value)


def test_advR4_a_string_origin_and_an_absent_origin_both_remain_valid(
        eng, pre_change_text):
    """Both directions: origin is OPTIONAL, and a real path still works."""
    doc = eng.parse_map(pre_change_text)
    assert len(eng.grow(doc, [_flow_element(route="/catalog", label="Filter")],
                        origin=None)["created"]) == 1
    doc2 = eng.parse_map(pre_change_text)
    assert len(eng.grow(doc2, [_flow_element(route="/catalog", label="Sort",
                                             action="Reorder the list.")],
                        origin="e2e/a.spec.ts")["created"]) == 1


def test_revR4_ensure_over_a_zero_element_map_reports_populate(eng, tmp_path):
    """rev-R4 ruling. An empty scaffold is not a completed ensure: R1 is that
    test authoring never proceeds against a map that does not describe the
    codebase, and a map with zero elements describes nothing. Reporting `none`
    there told the caller the ensure verb was satisfied when the only thing that
    had happened was a file being created."""
    path = eng.scaffold_map(tmp_path, now="2026-08-26T09:00:00Z")
    report = eng.ensure_support(tmp_path)
    assert report["present"] is True
    assert report["covers_elements"] == 0
    assert report["action_required"] == "populate", (
        "an empty scaffold reported the ensure verb as satisfied"
    )
    assert path.exists()


def test_revR4_ensure_over_a_populated_map_still_reports_none(eng, tmp_path):
    """The other direction, so the fix is not 'always populate'."""
    target = eng.map_path_for(tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(PRE_CHANGE_MAP.read_text(encoding="utf-8"), encoding="utf-8")
    report = eng.ensure_support(tmp_path)
    assert report["covers_elements"] == 4
    assert report["action_required"] == "none"


def test_revR4_a_scaffold_then_one_grow_flips_populate_to_none(eng, tmp_path):
    """The transition the verb exists to drive."""
    path = eng.scaffold_map(tmp_path, now="2026-08-26T09:00:00Z")
    assert eng.ensure_support(tmp_path)["action_required"] == "populate"
    doc = eng.load_map(path)
    eng.grow(doc, [_flow_element(route="/catalog", label="Filter")], origin="f.spec.ts")
    eng.write_map(doc, path)
    assert eng.ensure_support(tmp_path)["action_required"] == "none"


# --------------------------------------------------------------------------- #
# 13. adv-R5 — the sweep must DISCOVER its subjects, not enumerate them
# --------------------------------------------------------------------------- #
#
# The previous sweep hand-built three questions from known call sites and then
# claimed "a future third question kind cannot ship without it". That claim was
# false: the adversary added a fourth kind WITH and WITHOUT origin_verb and both
# variants escaped with identical red sets, because a test that constructs its
# own subjects can only ever check the subjects its author remembered.
#
# The fix is structural, not a docstring downgrade. QUESTION_KINDS is the
# registry; the emitters are DISCOVERED from the source by their structural
# signature (a dict literal carrying both a string-literal `kind` and a
# `question`); and the two are reconciled in BOTH directions.


def _discover_question_emitters_in(source: str) -> list:
    """Every question artifact in ``source``, in EITHER construction form.

    Discovery is by structure, not by function name, so a new emitter cannot
    dodge the sweep by not being called `_something_question`.

    R6: the scan originally matched dict LITERALS only, so the same artifact
    written as ``dict(kind=..., question=...)`` was invisible to every
    assertion below — an emitter could escape the whole sweep by changing its
    SYNTAX rather than its behaviour, which is the escape the adversary
    demonstrated. Both forms are matched now.
    """
    emitters = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Dict):
            pairs = [(k.value, v) for k, v in zip(node.keys, node.values)
                     if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "dict"):
            pairs = [(kw.arg, kw.value) for kw in node.keywords if kw.arg]
        else:
            continue
        keys = {name for name, _ in pairs}
        if not {"kind", "question"} <= keys:
            continue
        kind_literal = next((v.value for name, v in pairs
                             if name == "kind" and isinstance(v, ast.Constant)), None)
        emitters.append({"kind": kind_literal, "keys": keys, "line": node.lineno})
    return emitters


def _discovered_question_emitters() -> list:
    """The emitters in the real engine module."""
    return _discover_question_emitters_in(ENGINE_PATH.read_text(encoding="utf-8"))


def test_advR5_the_sweep_actually_discovers_the_known_emitters(eng):
    """VACUITY GUARD, and the most important test of the four. A scanner that
    silently finds nothing makes every assertion below pass — so the sweep is
    only evidence once it is shown to have subjects."""
    emitters = _discovered_question_emitters()
    assert len(emitters) >= 2, (
        f"the source scan found {len(emitters)} question emitters; it is not "
        f"discovering anything and the sweep below would pass vacuously"
    )
    assert {e["kind"] for e in emitters} == set(eng.QUESTION_KINDS)


def test_advR5_every_DISCOVERED_question_emitter_carries_origin_verb(eng):
    """The claim the old sweep could not back: a NEW question kind cannot ship
    without origin_verb, because the sweep finds it in the source whether or not
    any test remembers to call it."""
    for emitter in _discovered_question_emitters():
        assert "origin_verb" in emitter["keys"], (
            f"engine.py:{emitter['line']} emits question kind {emitter['kind']!r} "
            f"with no origin_verb key"
        )


def test_advR5_every_discovered_kind_is_registered(eng):
    """Registry reconciliation, direction one: an emitter whose kind is not in
    QUESTION_KINDS is an unregistered question kind."""
    registered = set(eng.QUESTION_KINDS)
    for emitter in _discovered_question_emitters():
        assert emitter["kind"] in registered, (
            f"engine.py:{emitter['line']} emits unregistered question kind "
            f"{emitter['kind']!r}; add it to QUESTION_KINDS"
        )


def test_advR5_every_registered_kind_is_actually_emitted(eng):
    """Direction two: a registry entry whose emitter was deleted is a stale
    promise, and a registry nobody prunes stops describing the engine."""
    emitted = {e["kind"] for e in _discovered_question_emitters()}
    for kind in eng.QUESTION_KINDS:
        assert kind in emitted, (
            f"QUESTION_KINDS registers {kind!r} but no emitter in engine.py "
            f"produces it"
        )


def test_advR5_the_runtime_sweep_agrees_with_the_registry(eng, pre_change_text):
    """The runtime half. This one DOES enumerate call sites — that is legitimate
    as a behavioural check, and it is no longer the thing carrying the
    'a new kind cannot ship without it' claim (the source sweep above is)."""
    questions = []
    questions += eng.grow(eng.parse_map(pre_change_text), [_flow_element(
        route="/dashboard", label="Save layout",
        action="A different reading.")], origin="f.spec.ts")["questions"]
    questions += eng.grow(eng.parse_map(pre_change_text), [_flow_element(
        route="/catalog", label="Filter", ambiguous=True,
        ambiguity_note="two controls matched")], origin="f.spec.ts")["questions"]
    questions += eng.bug_path_upsert(
        eng.parse_map(pre_change_text),
        [_flow_element(route="/dashboard", label="Save layout",
                       action="Another different reading.")],
        regression_refs=[{"test": "t.spec.ts", "ref": "SR-2"}])["questions"]

    assert len(questions) == 3
    for question in questions:
        assert question["kind"] in eng.QUESTION_KINDS
        assert question.get("origin_verb") in ("grow", "bug-path-upsert")
        json.dumps(question)


# --------------------------------------------------------------------------- #
# 14. The adversary's two must-still-pass focal points
# --------------------------------------------------------------------------- #

def test_focal_ensure_populate_reports_through_the_documented_exit_codes(tmp_path):
    """Focal point (b). `populate` is a NEW verdict on an EXISTING contract, so
    it must travel on the documented codes (0/1/2/3) rather than inventing a
    fourth. Work-required is exit 1, the same as produce-map."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("ct6_cli_probe", CLI_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.engine.scaffold_map(tmp_path, now="2026-08-26T09:00:00Z")

    proc = _cli("ensure", "--codebase", str(tmp_path), "--json")
    assert proc.returncode == 1, (
        f"ensure over an empty map exited {proc.returncode}; the contract is "
        f"0 clean / 1 work-required / 2 usage / 3 internal, and populate is "
        f"work-required"
    )
    payload = json.loads(proc.stdout)
    assert payload["action_required"] == "populate"
    assert payload["present"] is True
    assert payload["covers_elements"] == 0
    assert "Traceback" not in proc.stderr


def test_focal_ensure_none_still_exits_zero(tmp_path):
    """The other direction of the same contract — populate must not have made
    every ensure non-zero."""
    target = eng_map = tmp_path / "docs" / "INTERACTION_INTUITION_MAP.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(PRE_CHANGE_MAP.read_text(encoding="utf-8"), encoding="utf-8")
    proc = _cli("ensure", "--codebase", str(tmp_path), "--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["action_required"] == "none"


def test_r6_the_scan_sees_both_dict_construction_forms():
    """R6. The scan originally matched only dict LITERALS, so an emitter written
    as `dict(kind=..., question=...)` was invisible to the whole sweep — an
    emitter could dodge every assertion by changing its SYNTAX rather than its
    behaviour. The adversary demonstrated exactly that escape.

    Feeding synthetic source rather than engine.py is deliberate: the engine
    contains no call-form emitter today, so a pin that only read engine.py could
    not tell a hardened scanner from an unhardened one."""
    source = (
        'def _a():\n'
        '    return {"kind": "literal-form", "question": "q?", "origin_verb": "grow"}\n'
        'def _b():\n'
        '    return dict(kind="call-form", question="q?")\n'
    )
    found = _discover_question_emitters_in(source)
    assert {e["kind"] for e in found} == {"literal-form", "call-form"}, (
        f"the scan missed a construction form: {found}"
    )
    call_form = [e for e in found if e["kind"] == "call-form"][0]
    assert "origin_verb" not in call_form["keys"], (
        "the call-form emitter must be VISIBLE and reported as lacking "
        "origin_verb — being invisible is the defect, not being compliant"
    )


def test_r6_the_hardened_scan_still_finds_the_real_engine_emitters(eng):
    """The refactor must not have broken discovery against the real module."""
    emitters = _discovered_question_emitters()
    assert {e["kind"] for e in emitters} == set(eng.QUESTION_KINDS)


def test_r6_a_dict_call_without_the_question_key_is_not_an_emitter():
    """The widened matcher must not start sweeping up ordinary dict() calls."""
    source = (
        'def _f():\n'
        '    return dict(kind="finding", severity="error", detail="d")\n'
        'def _g():\n'
        '    return dict(a=1, b=2)\n'
    )
    assert _discover_question_emitters_in(source) == []
