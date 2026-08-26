# -*- coding: utf-8 -*-
"""Deterministic intuition-map lifecycle engine — the machine under the
`intuition-map-lifecycle` skill.

`interaction-intuition` produces one artifact per frontend codebase,
`<codebase>/docs/INTERACTION_INTUITION_MAP.md`: YAML frontmatter plus a
markdown body whose per-element entries are themselves YAML-blocks-in-markdown.
The skill's three verbs need to READ that artifact, WRITE into it, and — the
part that carries the change — leave everything they did not touch exactly as
they found it.

What this engine provides:

* ``parse_map`` / ``load_map`` — the artifact as an :class:`IntuitionMap`.
* ``serialize_map`` / ``write_map`` — back to text. Every block the engine did
  not modify is emitted from the RAW TEXT it was parsed from, so a no-op
  round-trip is byte-identical and an upsert cannot reformat its neighbours.
* ``validate_map`` / ``errors_only`` — the schema gate, findings named by entry
  and field.
* ``ensure_support`` / ``scaffold_map`` — the deterministic half of the `ensure`
  verb: does a map exist, is it readable, and (when instructed) write a minimal
  empty-but-schema-valid one. Deciding to DERIVE a map — dispatching
  `interaction-intuiter`, or running the rubric inline — is the skill's job,
  never the engine's.
* ``grow`` — user-specified flows upsert as confirmed entries
  (``source: user-flow``).
* ``bug_path_upsert`` — debugging discoveries upsert with ``source: bug-path``
  plus ``regression_refs[]``.

THE ADDITIVE SCHEMA. ``source`` (``intuiter | user-flow | bug-path``) and
``regression_refs[]`` are additions. An entry that carries neither READS as
``source: intuiter`` with no regression refs — and the default is a reading,
not a rewrite: the parsed entry keeps exactly the keys the file had, so merely
loading a pre-change map can never migrate it.

THE CONTRADICTION RULE. Neither verb ever silently overwrites a reading the
user already confirmed. When an incoming action or endpoint disagrees with a
confirmed entry, the entry is left UNMODIFIED — nothing at all is written to it
— and a question artifact naming both readings goes back for the user (a domain
gate; only they can resolve it). ``bug_path_upsert`` applies the SAME guard as
``grow``: the build originally let its provenance and ``regression_refs`` land
anyway, reasoning that R3 requires the bug path to REACH the map, but the spec
resolved it the other way — a partial write is still a write to something the
user ratified. The regression pointer is not lost; it travels in the question
artifact's ``incoming.regression_refs`` until the reading is settled.

THE AMBIGUITY RULE. Extracting elements from a ``.spec.ts`` is heuristic. An
element the CALLER marks ambiguous (``ambiguous: true``, or
``extraction_confidence`` of ``low``/``unknown``) is never upserted: a wrong
confirmed entry is worse than a question, because every later flow treats it as
ratified. It routes to an ``ambiguous-extraction`` question instead, and its
siblings in the same flow are unaffected.

THE SUPPORTED YAML SUBSET (hand-rolled: `scripts/` is stdlib-only, so there is
no `yaml` module here). Block style only:

* mappings — ``key: value`` and ``key:`` followed by an indented block. Keys
  match ``[A-Za-z_][A-Za-z0-9_.-]*``.
* sequences — ``- scalar`` and ``- key: value`` with the item's continuation
  lines aligned under the first key.
* scalars — ``null`` / ``~`` (None), ``true`` / ``false``, integers, floats,
  double-quoted (``\\\\``, ``\\"``, ``\\n``, ``\\t`` escapes) and single-quoted
  (``''`` escape) strings, and plain strings taken verbatim.
* empty flow collections ``[]`` and ``{}``, because the artifact schema uses
  ``candidate_endpoints: []``.
* whole-line ``#`` comments and blank lines.

DELIBERATELY OUTSIDE the subset, each raising :class:`MapParseError` naming the
line and the construct: non-empty flow collections, block scalars (``|`` /
``>``), anchors / aliases / tags, and multi-document streams. A ``#`` inside a
plain scalar is LITERAL — trailing comments are not stripped, because guessing
wrong there silently truncates an element's prose.

Stdlib-only; no import-time side effects; mirrors the engine+CLI shape of
``scripts/delivery/delivery_manifest.py``.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SCHEMA_VERSION = "interaction-intuition-map/v2"

#: Where the artifact lives, relative to a frontend codebase root.
MAP_RELATIVE_PATH = ("docs", "INTERACTION_INTUITION_MAP.md")

ELEMENT_KINDS = (
    "button", "link", "form-input", "modal-trigger", "drag-target",
    "keyboard-shortcut", "conditional-render-gate",
)
CONFIDENCE_LEVELS = ("high", "medium", "low", "unknown")
USER_VERDICTS = ("confirmed", "corrected", "deferred-to-impl", "confirmed-stub")
#: A verdict in this set means the USER ratified the reading — the only state a
#: `grow` can contradict. `deferred-to-impl` is deliberately absent: it records
#: that nobody decided yet.
RATIFIED_VERDICTS = ("confirmed", "corrected", "confirmed-stub")

#: `intuiter` is the default for an entry that names no source (the additive
#: schema's backward-compatibility guarantee).
SOURCES = ("intuiter", "user-flow", "bug-path")
DEFAULT_SOURCE = "intuiter"

#: `observed-in-flow` is this engine's own match kind: a user-specified flow or
#: a reproduction artifact EXERCISED the endpoint rather than inferring it from
#: a map cross-walk. The four others are `interaction-intuition`'s.
MATCH_KINDS = (
    "exact-by-label", "exact-by-action-noun", "plausible-by-design-intent",
    "inferred-from-similar-route", "observed-in-flow",
)

#: The verb each question artifact came from. Both verbs now share ONE
#: contradiction guard, so `source` alone is the only thing telling a grow
#: question apart from a bug-path one — and a consumer routing these to a human
#: needs to say WHICH verb is asking without inferring it from a provenance
#: field (lead ruling C, 2026-08-26).
ORIGIN_VERB_BY_SOURCE = {"user-flow": "grow", "bug-path": "bug-path-upsert"}
DEFAULT_ORIGIN_VERB = "upsert"

#: Every question-artifact kind this engine can emit.
#:
#: A registry rather than a comment because the sweep pin RECONCILES against it
#: in both directions: the test discovers the emitters from this module's source
#: by their structural signature (a dict literal carrying both a string-literal
#: `kind` and a `question`), then asserts every discovered kind is registered
#: here and every registered kind is still emitted.
#:
#: The previous sweep hand-built questions from known call sites and claimed a
#: future kind could not ship without `origin_verb`. That claim was false and
#: was proved so (adversary-task-1 R5): a fourth kind added WITH and WITHOUT
#: `origin_verb` escaped identically, because a test that constructs its own
#: subjects only ever checks the subjects its author remembered. Adding a kind
#: now means adding it here, and the sweep is what notices if you do not.
QUESTION_KINDS = ("intuition-contradiction", "ambiguous-extraction")


REQUIRED_FRONTMATTER_FIELDS = (
    "last_intuited", "confirmed", "confirmed_at", "producer", "inputs",
    "covers_screens", "covers_elements", "confidence_summary",
)

#: Canonical per-element field order. The two additive fields sort LAST so a
#: grown entry reads as the pre-change schema plus provenance.
ELEMENT_FIELD_ORDER = (
    "element_id", "route", "element_label", "element_kind", "design_source",
    "intuited_action", "candidate_endpoints", "confidence", "evidence",
    "ambiguity_question", "user_verdict", "correction_note", "confirmed_action",
    "confirmed_endpoint", "superseded_by", "source", "regression_refs",
)

FRONTMATTER_FIELD_ORDER = REQUIRED_FRONTMATTER_FIELDS

#: A fenced yaml block is read as an ELEMENT when its body declares ANY of these
#: marker keys. An entry that FORGOT its element_id is exactly the entry the
#: validator most needs to see, and a marker-blind reader would silently demote
#: it to prose.
#:
#: The threshold was 3 until adversary-task-1 F6 measured the perverse
#: consequence: the MORE degraded an entry was, the more likely it escaped the
#: gate entirely. A block carrying only `element_label` and `confidence` — the
#: plausible output of an interrupted agent write — parsed to ZERO elements and
#: validate reported the map CLEAN. A gate whose purpose is catching mangled
#: entries must not fail open on the most mangled ones, so any marker key now
#: makes a block visible and the validator says what it is missing. A yaml block
#: carrying NO marker key is still prose.
_ELEMENT_MARKER_KEYS = (
    "element_id", "route", "element_label", "element_kind", "design_source",
    "intuited_action", "confidence", "candidate_endpoints",
)
_MIN_MARKERS = 1

_FENCE_OPEN_RE = re.compile(r"^(?P<fence>```+|~~~+)[ \t]*(?P<info>[A-Za-z0-9_-]*)[ \t]*$")
_KEY_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)[ \t]*:(?P<rest>[ \t].*|)$")
_INT_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?\d+\.\d+$")
_MARKER_LINE_RE = re.compile(r"^(" + "|".join(_ELEMENT_MARKER_KEYS) + r")[ \t]*:")


class MapParseError(ValueError):
    """The map (or one of its element blocks) is outside the supported subset."""


# --------------------------------------------------------------------------- #
# The restricted YAML-subset reader
# --------------------------------------------------------------------------- #

def _lines_of(text: str) -> List[Tuple[int, str, int]]:
    """``(indent, content, lineno)`` for every significant line."""
    out: List[Tuple[int, str, int]] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        if "\t" in raw[: len(raw) - len(raw.lstrip(" \t"))]:
            raise MapParseError(
                f"line {lineno}: tab used for indentation — the supported subset "
                f"indents with spaces only"
            )
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append((len(raw) - len(raw.lstrip(" ")), raw.rstrip(), lineno))
    return out


def _scalar(raw: str, lineno: int) -> Any:
    text = raw.strip()
    if text in ("null", "Null", "NULL", "~", ""):
        return None
    if text in ("true", "True", "TRUE"):
        return True
    if text in ("false", "False", "FALSE"):
        return False
    if text == "[]":
        return []
    if text == "{}":
        return {}
    if text[0] in "[{":
        raise MapParseError(
            f"line {lineno}: non-empty flow collection {text[:40]!r} — the supported "
            f"subset is block style; only the empty forms [] and {{}} are flow"
        )
    if text[0] in "|>":
        raise MapParseError(
            f"line {lineno}: block scalar {text[0]!r} — block scalars are outside "
            f"the supported subset; quote the string instead"
        )
    if text[0] in "&*!":
        raise MapParseError(
            f"line {lineno}: {text[0]!r} introduces an anchor, alias or tag — "
            f"unsupported in this subset"
        )
    if text[0] == '"':
        return _unquote_double(text, lineno)
    if text[0] == "'":
        return _unquote_single(text, lineno)
    if _INT_RE.match(text):
        return int(text)
    if _FLOAT_RE.match(text):
        return float(text)
    return text


def _unquote_double(text: str, lineno: int) -> str:
    if len(text) < 2 or not text.endswith('"'):
        raise MapParseError(f"line {lineno}: unterminated double-quoted string")
    body, out, i = text[1:-1], [], 0
    while i < len(body):
        ch = body[i]
        if ch == "\\":
            if i + 1 >= len(body):
                raise MapParseError(f"line {lineno}: dangling escape in quoted string")
            nxt = body[i + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}.get(nxt, nxt))
            i += 2
            continue
        if ch == '"':
            raise MapParseError(
                f"line {lineno}: unescaped quote inside a double-quoted string"
            )
        out.append(ch)
        i += 1
    return "".join(out)


def _unquote_single(text: str, lineno: int) -> str:
    if len(text) < 2 or not text.endswith("'"):
        raise MapParseError(f"line {lineno}: unterminated single-quoted string")
    return text[1:-1].replace("''", "'")


def _parse_mapping(lines: Sequence[Tuple[int, str, int]], i: int, indent: int
                   ) -> Tuple[Dict[str, Any], int]:
    result: Dict[str, Any] = {}
    while i < len(lines):
        line_indent, content, lineno = lines[i]
        if line_indent < indent:
            break
        if line_indent > indent:
            raise MapParseError(
                f"line {lineno}: unexpected indentation (expected {indent}, got "
                f"{line_indent}) in {content.strip()[:40]!r}"
            )
        match = _KEY_RE.match(content.strip())
        if not match:
            raise MapParseError(
                f"line {lineno}: expected a 'key: value' mapping entry, got "
                f"{content.strip()[:60]!r}"
            )
        key, rest = match.group("key"), match.group("rest").strip()
        if key in result:
            raise MapParseError(f"line {lineno}: duplicate key {key!r} in the same block")
        if rest:
            result[key] = _scalar(rest, lineno)
            i += 1
            continue
        value, i = _parse_child(lines, i + 1, indent)
        result[key] = value
    return result, i


def _parse_child(lines: Sequence[Tuple[int, str, int]], i: int, parent_indent: int
                 ) -> Tuple[Any, int]:
    """The block under a bare ``key:`` — a nested mapping, a sequence, or None."""
    if i >= len(lines) or lines[i][0] <= parent_indent:
        return None, i
    child_indent, content, _ = lines[i]
    if content.strip().startswith("- "):
        return _parse_sequence(lines, i, child_indent)
    return _parse_mapping(lines, i, child_indent)


def _parse_sequence(lines: Sequence[Tuple[int, str, int]], i: int, indent: int
                    ) -> Tuple[List[Any], int]:
    items: List[Any] = []
    while i < len(lines):
        line_indent, content, lineno = lines[i]
        if line_indent < indent:
            break
        stripped = content.strip()
        if line_indent > indent or not stripped.startswith("- "):
            raise MapParseError(
                f"line {lineno}: expected a '- ' sequence item at indent {indent}, "
                f"got {stripped[:60]!r}"
            )
        after = stripped[2:]
        # The item's own column: where the text after the dash actually starts.
        item_indent = line_indent + (len(stripped) - len(after.lstrip(" ")))
        after = after.lstrip(" ")
        if _KEY_RE.match(after):
            synthetic = [(item_indent, " " * item_indent + after, lineno)]
            j = i + 1
            while j < len(lines) and lines[j][0] > line_indent:
                synthetic.append(lines[j])
                j += 1
            value, consumed = _parse_mapping(synthetic, 0, item_indent)
            if consumed != len(synthetic):
                raise MapParseError(
                    f"line {synthetic[consumed][2]}: unexpected content inside a "
                    f"sequence item"
                )
            items.append(value)
            i = j
            continue
        items.append(_scalar(after, lineno))
        i += 1
    return items, i


def parse_yaml_subset(text: str) -> Dict[str, Any]:
    """Parse ``text`` as a block-style YAML mapping in the supported subset."""
    lines = _lines_of(text)
    if not lines:
        return {}
    data, consumed = _parse_mapping(lines, 0, lines[0][0])
    if consumed != len(lines):
        raise MapParseError(
            f"line {lines[consumed][2]}: unexpected content after the top-level "
            f"mapping"
        )
    return data


# --------------------------------------------------------------------------- #
# The serializer (the same subset, canonical order)
# --------------------------------------------------------------------------- #

_PLAIN_SAFE_RE = re.compile(r"^[A-Za-z0-9_./\-][^\n\r#]*$")
_RESERVED_PLAIN = frozenset({
    "null", "Null", "NULL", "~", "true", "True", "TRUE", "false", "False", "FALSE",
    "[]", "{}", "",
})


def _needs_quotes(text: str) -> bool:
    if text in _RESERVED_PLAIN:
        return True
    if text != text.strip():
        return True
    if _INT_RE.match(text) or _FLOAT_RE.match(text):
        return True
    if ": " in text or text.endswith(":"):
        return True
    if not _PLAIN_SAFE_RE.match(text):
        return True
    return False


def _quote(text: str) -> str:
    escaped = (text.replace("\\", "\\\\").replace('"', '\\"')
               .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t"))
    return f'"{escaped}"'


def _dump_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    return _quote(text) if _needs_quotes(text) else text


def _ordered_keys(data: Dict[str, Any], order: Sequence[str]) -> List[str]:
    known = [k for k in order if k in data]
    return known + [k for k in data if k not in order]


def dump_yaml_subset(data: Dict[str, Any], *, order: Sequence[str] = (),
                     indent: int = 0) -> str:
    """Serialize ``data`` back into the supported subset, deterministically."""
    pad = " " * indent
    out: List[str] = []
    for key in _ordered_keys(data, order):
        value = data[key]
        if isinstance(value, dict):
            if not value:
                out.append(f"{pad}{key}: {{}}")
                continue
            out.append(f"{pad}{key}:")
            out.append(dump_yaml_subset(value, indent=indent + 2).rstrip("\n"))
            continue
        if isinstance(value, (list, tuple)):
            if not value:
                out.append(f"{pad}{key}: []")
                continue
            out.append(f"{pad}{key}:")
            for item in value:
                if isinstance(item, dict):
                    if not item:
                        out.append(f"{pad}  - {{}}")
                        continue
                    body = dump_yaml_subset(item, indent=indent + 4).rstrip("\n")
                    body_lines = body.split("\n")
                    out.append(f"{pad}  - {body_lines[0].lstrip(' ')}")
                    out.extend(body_lines[1:])
                else:
                    out.append(f"{pad}  - {_dump_scalar(item)}")
            continue
        out.append(f"{pad}{key}: {_dump_scalar(value)}")
    return "\n".join(out) + ("\n" if out else "")


# --------------------------------------------------------------------------- #
# The document model
# --------------------------------------------------------------------------- #

class ElementBlock:
    """One per-element YAML block, plus the raw text it was parsed from.

    ``data`` holds exactly the keys the file carried. The additive defaults are
    exposed as READINGS (:attr:`source`, :attr:`regression_refs`) so parsing a
    pre-change map never migrates it.
    """

    def __init__(self, data: Dict[str, Any], raw: str, fence: str, info: str) -> None:
        self.data = data
        self.raw = raw
        self.dirty = False
        self._fence = fence
        self._info = info

    @property
    def element_id(self) -> Optional[str]:
        value = self.data.get("element_id")
        return value if isinstance(value, str) and value.strip() else None

    @property
    def route(self) -> Optional[str]:
        value = self.data.get("route")
        return value if isinstance(value, str) else None

    @property
    def element_label(self) -> Optional[str]:
        value = self.data.get("element_label")
        return value if isinstance(value, str) else None

    @property
    def source(self) -> str:
        value = self.data.get("source")
        return value if isinstance(value, str) and value.strip() else DEFAULT_SOURCE

    @property
    def regression_refs(self) -> List[Dict[str, Any]]:
        value = self.data.get("regression_refs")
        return list(value) if isinstance(value, list) else []

    @property
    def confidence(self) -> Optional[str]:
        value = self.data.get("confidence")
        return value if isinstance(value, str) else None

    def as_dict(self) -> Dict[str, Any]:
        """The entry with the additive defaults applied — a reading, not the file."""
        merged = dict(self.data)
        merged.setdefault("source", DEFAULT_SOURCE)
        merged.setdefault("regression_refs", [])
        return merged

    def touch(self) -> None:
        self.dirty = True

    def render(self) -> str:
        if not self.dirty:
            return self.raw
        body = dump_yaml_subset(self.data, order=ELEMENT_FIELD_ORDER)
        return f"{self._fence}{self._info}\n{body}{self._fence}\n"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ElementBlock {self.element_id!r} dirty={self.dirty}>"


class IntuitionMap:
    """A parsed `INTERACTION_INTUITION_MAP.md`."""

    def __init__(self, frontmatter: Dict[str, Any], head: str,
                 segments: List[Tuple[str, Any]], newline: str = "\n") -> None:
        self.frontmatter = frontmatter
        #: The line ending the source file used, re-applied on write. Parsing
        #: works on LF internally; see :func:`load_map`.
        self.newline = newline
        self._head = head
        self._segments = segments
        self._frontmatter_dirty = False

    @property
    def elements(self) -> List[ElementBlock]:
        return [payload for kind, payload in self._segments if kind == "element"]

    @property
    def element_ids(self) -> List[str]:
        return [e.element_id for e in self.elements if e.element_id]

    def get(self, element_id: str) -> Optional[ElementBlock]:
        for element in self.elements:
            if element.element_id == element_id:
                return element
        return None

    def append_element(self, data: Dict[str, Any], *, after: Optional[ElementBlock] = None
                       ) -> ElementBlock:
        """Insert a new element block, keeping the map route-grouped when it can.

        Insertion never rewrites a neighbour: the new block is a new segment
        between existing ones.
        """
        block = ElementBlock(dict(data), raw="", fence="```", info="yaml")
        block.dirty = True
        heading = f"\n### {data.get('element_id', 'element')}\n\n"
        index = len(self._segments)
        if after is not None:
            for position, (kind, payload) in enumerate(self._segments):
                if kind == "element" and payload is after:
                    index = position + 1
                    break
        self._segments.insert(index, ("text", heading))
        self._segments.insert(index + 1, ("element", block))
        return block

    def mark_frontmatter_dirty(self) -> None:
        self._frontmatter_dirty = True

    def render_head(self) -> str:
        if not self._frontmatter_dirty:
            return self._head
        body = dump_yaml_subset(self.frontmatter, order=FRONTMATTER_FIELD_ORDER)
        return f"---\n{body}---\n"

    def serialize(self) -> str:
        parts = [self.render_head()]
        for kind, payload in self._segments:
            parts.append(payload if kind == "text" else payload.render())
        return "".join(parts)


# --------------------------------------------------------------------------- #
# Parsing the artifact
# --------------------------------------------------------------------------- #

def _looks_like_element(inner: str) -> bool:
    markers = {m.group(1) for m in
               (_MARKER_LINE_RE.match(line) for line in inner.splitlines())
               if m is not None}
    return "element_id" in markers or len(markers) >= _MIN_MARKERS


def _split_frontmatter(text: str) -> Tuple[Dict[str, Any], str, str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise MapParseError(
            "the map has no YAML frontmatter — an INTERACTION_INTUITION_MAP.md "
            "opens with a '---' fenced frontmatter block"
        )
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            head = "".join(lines[: index + 1])
            inner = "".join(lines[1:index])
            body = "".join(lines[index + 1:])
            return parse_yaml_subset(inner), head, body
    raise MapParseError("the map's frontmatter block is never closed by a '---' line")


def parse_map(text: str) -> IntuitionMap:
    """Parse the artifact text into an :class:`IntuitionMap`."""
    frontmatter, head, body = _split_frontmatter(text)
    lines = body.splitlines(keepends=True)
    segments: List[Tuple[str, Any]] = []
    buffer: List[str] = []
    offset = len(head.splitlines())
    i = 0
    while i < len(lines):
        match = _FENCE_OPEN_RE.match(lines[i].rstrip("\r\n"))
        if match and match.group("info").lower() in ("yaml", "yml"):
            fence = match.group("fence")
            close = i + 1
            while close < len(lines) and lines[close].rstrip("\r\n").strip() != fence:
                close += 1
            if close < len(lines):
                inner = "".join(lines[i + 1:close])
                if _looks_like_element(inner):
                    try:
                        data = parse_yaml_subset(inner)
                    except MapParseError as exc:
                        raise MapParseError(
                            f"in the element block opening at map line "
                            f"{offset + i + 1}: {exc}"
                        ) from exc
                    if buffer:
                        segments.append(("text", "".join(buffer)))
                        buffer = []
                    segments.append(("element", ElementBlock(
                        data, raw="".join(lines[i:close + 1]),
                        fence=fence, info=match.group("info"))))
                    i = close + 1
                    continue
        buffer.append(lines[i])
        i += 1
    if buffer:
        segments.append(("text", "".join(buffer)))
    return IntuitionMap(frontmatter, head, segments)


def map_path_for(codebase_dir: Any) -> Path:
    """``<codebase>/docs/INTERACTION_INTUITION_MAP.md``."""
    return Path(codebase_dir).joinpath(*MAP_RELATIVE_PATH)


def detect_newline(raw: bytes) -> str:
    """The dominant line ending in ``raw`` — ``"\\r\\n"`` or ``"\\n"``.

    Ties and empty input fall to LF. A file mixing both is normalized to
    whichever it uses more; that is a deliberate simplification, and the only
    lossy case in the round trip.
    """
    crlf = raw.count(b"\r\n")
    return "\r\n" if crlf > (raw.count(b"\n") - crlf) else "\n"


def load_map(path: Any) -> IntuitionMap:
    """Parse the map at ``path``, remembering its line-ending convention.

    Reads BYTES rather than text because ``read_text`` applies universal-newline
    translation, which collapsed CRLF to LF before the parser ever saw it. Every
    untouched block then re-serialized from already-normalized raw text, so
    ``write_map`` silently rewrote the whole file (adversary-task-1 F2: a no-op
    load+write of a CRLF map changed 4354 bytes to 4222, and a one-element grow
    showed 100% of the file as changed instead of 37 lines). That destroyed the
    "untouched entries survive" property on Windows checkouts — where
    ``core.autocrlf`` makes CRLF the default — at exactly the moment a reviewer
    needs it. Parsing still works on LF internally; the convention is re-applied
    on write.
    """
    raw = Path(path).read_bytes()
    doc = parse_map(raw.decode("utf-8").replace("\r\n", "\n"))
    doc.newline = detect_newline(raw)
    return doc


def serialize_map(doc: IntuitionMap) -> str:
    return doc.serialize()


def write_map(doc: IntuitionMap, path: Any) -> Path:
    """Write ``doc`` back out in the line-ending convention it came in with."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(serialize_map(doc), encoding="utf-8", newline=doc.newline)
    return target


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _finding(kind: str, severity: str, entry: str, field: Optional[str],
             detail: str) -> Dict[str, Any]:
    return {"kind": kind, "severity": severity, "entry": entry,
            "field": field, "detail": detail}


def validate_map(doc: IntuitionMap) -> List[Dict[str, Any]]:
    """The schema gate. Findings are ``{kind, severity, entry, field, detail}``;
    ``severity`` is ``"error"`` (blocking) or ``"advisory"``."""
    findings: List[Dict[str, Any]] = []
    fm_entry = "<frontmatter>"

    for field in REQUIRED_FRONTMATTER_FIELDS:
        if field not in doc.frontmatter:
            findings.append(_finding(
                "missing-field", "error", fm_entry, field,
                f"frontmatter is missing required field {field!r}"))
    summary = doc.frontmatter.get("confidence_summary")
    if summary is not None and not isinstance(summary, dict):
        findings.append(_finding(
            "malformed-field", "error", fm_entry, "confidence_summary",
            f"confidence_summary must be a mapping of the four confidence "
            f"levels, got {type(summary).__name__}"))
    elif isinstance(summary, dict):
        total = sum(v for v in summary.values() if isinstance(v, int))
        declared = doc.frontmatter.get("covers_elements")
        if isinstance(declared, int) and total != declared:
            findings.append(_finding(
                "stale-counters", "advisory", fm_entry, "confidence_summary",
                f"confidence_summary sums to {total} but covers_elements is "
                f"{declared} — the counters are stale"))

    seen: Dict[str, int] = {}
    for position, element in enumerate(doc.elements, 1):
        entry = element.element_id or f"<element #{position}>"
        findings.extend(_validate_element(element, entry))
        if element.element_id:
            if element.element_id in seen:
                findings.append(_finding(
                    "duplicate-element-id", "error", entry, "element_id",
                    f"element_id {element.element_id!r} is declared by entry "
                    f"#{seen[element.element_id]} and entry #{position}; ids are "
                    f"the map's primary key"))
            else:
                seen[element.element_id] = position
    return findings


def _validate_element(element: ElementBlock, entry: str) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    data = element.data

    for field in ("element_id", "route", "element_label", "element_kind",
                  "intuited_action", "confidence", "candidate_endpoints"):
        if field not in data or _blank(data.get(field)):
            findings.append(_finding(
                "missing-field", "error", entry, field,
                f"entry {entry} is missing required field {field!r}"))

    kind = data.get("element_kind")
    if isinstance(kind, str) and kind.strip() and kind not in ELEMENT_KINDS:
        findings.append(_finding(
            "unknown-element-kind", "error", entry, "element_kind",
            f"entry {entry} declares element_kind {kind!r}; recognized kinds are "
            f"{list(ELEMENT_KINDS)}"))

    confidence = data.get("confidence")
    if isinstance(confidence, str) and confidence.strip() \
            and confidence not in CONFIDENCE_LEVELS:
        findings.append(_finding(
            "unknown-confidence", "error", entry, "confidence",
            f"entry {entry} declares confidence {confidence!r}; recognized levels "
            f"are {list(CONFIDENCE_LEVELS)}"))

    evidence = data.get("evidence")
    if not isinstance(evidence, list) or not [e for e in evidence if not _blank(e)]:
        findings.append(_finding(
            "missing-evidence", "error", entry, "evidence",
            f"entry {entry} cites no evidence — an intuition with no citation is a "
            f"guess (interaction-intuition hard rule)"))

    if confidence != "high" and _blank(data.get("ambiguity_question")):
        findings.append(_finding(
            "missing-ambiguity-question", "error", entry, "ambiguity_question",
            f"entry {entry} carries confidence {confidence!r} but no "
            f"ambiguity_question; every item below `high` must surface a concrete "
            f"question to the bulk-verify gate"))

    verdict = data.get("user_verdict")
    if verdict is not None and verdict not in USER_VERDICTS:
        findings.append(_finding(
            "unknown-user-verdict", "error", entry, "user_verdict",
            f"entry {entry} declares user_verdict {verdict!r}; recognized verdicts "
            f"are {list(USER_VERDICTS)}"))

    source = data.get("source")
    if source is not None and source not in SOURCES:
        findings.append(_finding(
            "unknown-source", "error", entry, "source",
            f"entry {entry} declares source {source!r}; recognized sources are "
            f"{list(SOURCES)} (an absent source reads as {DEFAULT_SOURCE!r})"))

    refs = data.get("regression_refs")
    if refs is not None:
        if not isinstance(refs, list):
            findings.append(_finding(
                "malformed-regression-ref", "error", entry, "regression_refs",
                f"entry {entry} declares regression_refs as "
                f"{type(refs).__name__}; it is a list of "
                f"{{test, ref}} mappings"))
        else:
            for position, ref in enumerate(refs, 1):
                if not isinstance(ref, dict) or _blank(ref.get("test")) \
                        or _blank(ref.get("ref")):
                    findings.append(_finding(
                        "malformed-regression-ref", "error", entry,
                        "regression_refs",
                        f"entry {entry} regression_refs[{position}] = {ref!r} must "
                        f"name both the covering test ('test') and the SR or bug "
                        f"slug ('ref')"))

    candidates = data.get("candidate_endpoints")
    if isinstance(candidates, list):
        for position, endpoint in enumerate(candidates, 1):
            findings.extend(_validate_endpoint(
                endpoint, entry, "candidate_endpoints",
                f"candidate_endpoints[{position}]", require_match_kind=True))
    confirmed = data.get("confirmed_endpoint")
    if confirmed is not None:
        findings.extend(_validate_endpoint(
            confirmed, entry, "confirmed_endpoint", "confirmed_endpoint",
            require_match_kind=False))
    return findings


def _validate_endpoint(endpoint: Any, entry: str, field: str, anchor: str,
                       *, require_match_kind: bool) -> List[Dict[str, Any]]:
    kind = "malformed-candidate-endpoint" if field == "candidate_endpoints" \
        else "malformed-confirmed-endpoint"
    if not isinstance(endpoint, dict):
        return [_finding(kind, "error", entry, field,
                         f"entry {entry} {anchor} = {endpoint!r} is not an endpoint "
                         f"mapping")]
    findings = []
    required = ["method", "path"] + (["source", "match_kind"] if require_match_kind else [])
    missing = [k for k in required if _blank(endpoint.get(k))]
    if missing:
        findings.append(_finding(
            kind, "error", entry, field,
            f"entry {entry} {anchor} is missing {missing} — an endpoint names its "
            f"method and path" + (", its source artifact and its match_kind"
                                  if require_match_kind else "")))
    match_kind = endpoint.get("match_kind")
    if isinstance(match_kind, str) and match_kind.strip() \
            and match_kind not in MATCH_KINDS:
        findings.append(_finding(
            kind, "error", entry, field,
            f"entry {entry} {anchor} declares match_kind {match_kind!r}; recognized "
            f"kinds are {list(MATCH_KINDS)}"))
    return findings


def errors_only(findings: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The blocking subset."""
    return [f for f in findings if f.get("severity") == "error"]


# --------------------------------------------------------------------------- #
# The `ensure` verb's deterministic half
# --------------------------------------------------------------------------- #

def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_support(codebase_dir: Any) -> Dict[str, Any]:
    """Does this codebase have a readable, schema-valid intuition map?

    HONEST BOUNDARY: this reports; it never derives. Producing a map means
    running the `interaction-intuition` rubric — an agent's job, dispatched by
    the skill. ``action_required`` names what the skill must do:
    ``produce-map`` (none exists), ``repair-map`` (one exists but does not
    parse or does not validate), ``populate`` (one exists and is schema-valid
    but carries zero elements - a scaffold is not a completed ensure), or
    ``none``.
    """
    path = map_path_for(codebase_dir)
    report: Dict[str, Any] = {
        "map_path": str(path),
        "present": path.exists(),
        "action_required": "produce-map",
        "parse_error": None,
        "findings": [],
        "covers_elements": 0,
        "last_intuited": None,
        "confirmed": None,
        "reason": "",
    }
    if not report["present"]:
        report["reason"] = (
            "no INTERACTION_INTUITION_MAP.md for this codebase — test authoring "
            "may not proceed against a missing map (R1)"
        )
        return report
    try:
        doc = load_map(path)
    except (MapParseError, OSError) as exc:
        report["action_required"] = "repair-map"
        report["parse_error"] = str(exc)
        report["reason"] = "the map exists but could not be parsed"
        return report

    findings = validate_map(doc)
    blocking = errors_only(findings)
    report["findings"] = findings
    report["covers_elements"] = len(doc.elements)
    report["last_intuited"] = doc.frontmatter.get("last_intuited")
    report["confirmed"] = doc.frontmatter.get("confirmed")
    if blocking:
        report["action_required"] = "repair-map"
        report["reason"] = (
            f"the map exists but carries {len(blocking)} blocking schema finding(s)")
    elif not doc.elements:
        # rev-R4. A scaffold is schema-valid and describes NOTHING. R1 is that
        # test authoring never proceeds against a map that does not describe the
        # codebase, so reporting `none` here told the caller the ensure verb was
        # satisfied when all that had happened was a file being created.
        report["action_required"] = "populate"
        report["reason"] = (
            "the map exists and is schema-valid but carries zero elements - a "
            "scaffold is not a completed ensure; derive the elements before "
            "treating test authoring as map-consulted"
        )
    else:
        report["action_required"] = "none"
        report["reason"] = (
            f"the map exists and validates clean over {len(doc.elements)} element(s)")
    return report


_SCAFFOLD_BODY = """
# Interaction intuition map{suffix}

Scaffolded by `intuition-map-lifecycle` so test authoring has a map to consult.
It carries no elements yet: run the `ensure` verb's derivation (the
`interaction-intuiter` agent in pipeline context, or the same rubric inline
ad-hoc) to populate it, then re-run the bulk-verify gate over the `low` and
`unknown` items.
"""


def scaffold_map(codebase_dir: Any, *, producer: str = "interaction-intuiter",
                 inputs: Sequence[str] = (), now: Optional[str] = None,
                 overwrite: bool = False) -> Path:
    """Write a minimal empty-but-schema-valid map and return its path."""
    path = map_path_for(codebase_dir)
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"{path} already exists — scaffold refuses to overwrite an existing "
            f"intuition map (pass overwrite=True only when the caller means it)"
        )
    frontmatter = {
        "last_intuited": now or _utc_now_iso(),
        "confirmed": False,
        "confirmed_at": None,
        "producer": producer,
        "inputs": list(inputs),
        "covers_screens": 0,
        "covers_elements": 0,
        "confidence_summary": {"high": 0, "medium": 0, "low": 0, "unknown": 0},
    }
    name = Path(codebase_dir).name
    body = _SCAFFOLD_BODY.format(suffix=f" - {name}" if name else "")
    head = "---\n" + dump_yaml_subset(frontmatter, order=FRONTMATTER_FIELD_ORDER) + "---\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(head + body, encoding="utf-8", newline="\n")
    return path


# --------------------------------------------------------------------------- #
# Upsert: the `grow` and `bug-path-upsert` verbs
# --------------------------------------------------------------------------- #

def _norm(text: Any) -> str:
    """Casefolded, whitespace-collapsed — the house comparison shape (v3.62.0)."""
    return " ".join(str(text or "").split()).casefold()


def _slug(text: Any) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(text or "").strip().casefold())
    return cleaned.strip("-") or "unnamed"


def route_slug(route: Any) -> str:
    """``/items/[id]/edit`` -> ``items-id-edit``; ``/`` -> ``root``."""
    stripped = str(route or "").strip().strip("/")
    return _slug(stripped) if stripped else "root"


def derive_element_id(route: Any, label: Any, *, region: str = "flow",
                      ordinal: int = 1) -> str:
    """``<route-slug>__<region>__<label-slug>__<ordinal>`` — the artifact's
    stable-id convention, applied to an element a flow named rather than one the
    intuiter walked."""
    return f"{route_slug(route)}__{_slug(region)}__{_slug(label)}__{ordinal}"


def find_element(doc: IntuitionMap, *, element_id: Optional[str] = None,
                 route: Any = None, label: Any = None) -> Optional[ElementBlock]:
    """Locate an entry by id, else by (route, label).

    A flow names a route and a visible label, never an element_id, so the second
    arm is what stops every `grow` from duplicating the map.
    """
    if element_id:
        hit = doc.get(element_id)
        if hit is not None:
            return hit
    if route is None or label is None:
        return None
    want = (_norm(route), _norm(label))
    for element in doc.elements:
        if (_norm(element.route), _norm(element.element_label)) == want:
            return element
    return None


#: How an endpoint with no named source artifact describes its own provenance.
#: Per-verb, because "observed in a user-specified flow" written onto a bug-path
#: entry is a small lie in a field whose whole job is saying where this came from.
_PROVENANCE_PHRASE = {
    "user-flow": "observed in a user-specified flow",
    "bug-path": "observed in a bug-path reproduction",
}
_PROVENANCE_DEFAULT = "observed in an intuition-map lifecycle upsert"


def _normalize_endpoint(endpoint: Any, origin: Optional[str],
                        provenance: str = _PROVENANCE_DEFAULT
                        ) -> Optional[Dict[str, Any]]:
    """Accept ``{"method": ..., "path": ...}`` or ``"POST /api/x"``."""
    if endpoint is None:
        return None
    if isinstance(endpoint, str):
        parts = endpoint.split(None, 1)
        if len(parts) != 2:
            raise ValueError(
                f"endpoint {endpoint!r} must read 'METHOD /path' or be a mapping "
                f"with 'method' and 'path'"
            )
        endpoint = {"method": parts[0], "path": parts[1]}
    if not isinstance(endpoint, dict):
        raise ValueError(f"endpoint {endpoint!r} must be a mapping or a "
                         f"'METHOD /path' string")
    method = str(endpoint.get("method") or "").strip().upper()
    path = str(endpoint.get("path") or "").strip()
    if not method or not path:
        raise ValueError(f"endpoint {endpoint!r} must name both a method and a path")
    return {
        "method": method,
        "path": path,
        "source": endpoint.get("source") or origin or provenance,
        "match_kind": endpoint.get("match_kind") or "observed-in-flow",
    }


def _same_endpoint(left: Any, right: Any) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return left == right
    return (_norm(left.get("method")) == _norm(right.get("method"))
            and str(left.get("path") or "").strip() == str(right.get("path") or "").strip())


def _normalize_flow_element(spec: Dict[str, Any], origin: Optional[str],
                            provenance: str = _PROVENANCE_DEFAULT) -> Dict[str, Any]:
    if not isinstance(spec, dict):
        raise ValueError(f"flow element {spec!r} must be a mapping")
    route = spec.get("route")
    label = spec.get("label", spec.get("element_label"))
    if _blank(route):
        raise ValueError(f"flow element {spec!r} names no route")
    if _blank(label):
        raise ValueError(f"flow element {spec!r} names no label")
    return {
        "element_id": spec.get("element_id"),
        "route": str(route).strip(),
        "label": " ".join(str(label).split()),
        "kind": spec.get("kind", spec.get("element_kind")) or "button",
        "action": spec.get("action", spec.get("intuited_action")),
        "endpoint": _normalize_endpoint(spec.get("endpoint"), origin, provenance),
        "region": spec.get("region") or "flow",
        "evidence": list(spec.get("evidence") or []),
        "design_source": spec.get("design_source"),
        # Extracting elements from a .spec.ts is heuristic. When the CALLER
        # could not resolve one, a wrong upsert is worse than a question, so an
        # ambiguous element routes to the user instead of being guessed at.
        "ambiguous": bool(spec.get("ambiguous"))
        or str(spec.get("extraction_confidence") or "").strip().casefold()
        in ("low", "unknown"),
        "ambiguity_note": spec.get("ambiguity_note") or spec.get("note") or "",
    }


def _normalize_refs(refs: Optional[Sequence[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for ref in refs or []:
        if not isinstance(ref, dict) or _blank(ref.get("test")) or _blank(ref.get("ref")):
            raise ValueError(
                f"regression ref {ref!r} must name both the covering debug-flow "
                f"test ('test') and the SR or bug slug ('ref')"
            )
        entry = {"test": str(ref["test"]).strip(), "ref": str(ref["ref"]).strip()}
        if not _blank(ref.get("note")):
            entry["note"] = str(ref["note"]).strip()
        normalized.append(entry)
    return normalized


def _contradiction_fields(element: ElementBlock, incoming: Dict[str, Any]) -> List[str]:
    """Which confirmed readings the incoming element disagrees with (possibly none)."""
    if element.data.get("user_verdict") not in RATIFIED_VERDICTS:
        return []
    fields: List[str] = []
    existing_action = element.data.get("confirmed_action")
    if not _blank(existing_action) and not _blank(incoming.get("action")) \
            and _norm(existing_action) != _norm(incoming["action"]):
        fields.append("confirmed_action")
    existing_endpoint = element.data.get("confirmed_endpoint")
    if existing_endpoint and incoming.get("endpoint") \
            and not _same_endpoint(existing_endpoint, incoming["endpoint"]):
        fields.append("confirmed_endpoint")
    return fields


def _ambiguity_question(existing: Optional[ElementBlock], incoming: Dict[str, Any],
                        *, source: str, origin: Optional[str],
                        refs: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The artifact for an element the CALLER could not resolve.

    Distinct from a contradiction: nothing in the map disagrees, the EXTRACTION
    itself is uncertain. Guessing here would write a wrong confirmed entry that
    later flows treat as ratified.
    """
    where = origin or f"the {source} upsert"
    note = incoming.get("ambiguity_note") or (
        "the caller marked this extraction ambiguous but gave no detail")
    return {
        "kind": "ambiguous-extraction",
        "origin_verb": ORIGIN_VERB_BY_SOURCE.get(source, DEFAULT_ORIGIN_VERB),
        "element_id": existing.element_id if existing is not None else None,
        "route": incoming["route"],
        "element_label": incoming["label"],
        "fields": [],
        "existing": None if existing is None else {
            "source": existing.source,
            "user_verdict": existing.data.get("user_verdict"),
            "confirmed_action": existing.data.get("confirmed_action"),
        },
        "incoming": {
            "source": source,
            "origin": origin,
            "confirmed_action": incoming.get("action"),
            "confirmed_endpoint": incoming.get("endpoint"),
            "regression_refs": list(refs),
        },
        "ambiguity_note": note,
        "question": (
            f"{where} exercises {incoming['label']!r} on {incoming['route']}, but "
            f"the extraction is ambiguous: {note} No entry was written. What does "
            f"{incoming['label']!r} on {incoming['route']} actually do?"
        ),
        "resolution": (
            "Nothing was upserted for this element. Resolve the ambiguity with "
            "the user (or re-extract the flow unambiguously), then re-run the verb."
        ),
    }


def _question(element: ElementBlock, incoming: Dict[str, Any], fields: Sequence[str],
              *, source: str, origin: Optional[str], resolution: str,
              refs: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    label = element.element_label or incoming["label"]
    route = element.route or incoming["route"]
    where = origin or f"the {source} upsert"
    sentences: List[str] = []
    if "confirmed_action" in fields:
        sentences.append(
            f"The map records that {label!r} on {route} does this: "
            f"{element.data.get('confirmed_action')} — {where} exercises it as: "
            f"{incoming.get('action')}"
        )
    if "confirmed_endpoint" in fields:
        existing = element.data.get("confirmed_endpoint") or {}
        proposed = incoming.get("endpoint") or {}
        sentences.append(
            f"The map records {label!r} on {route} calling "
            f"{existing.get('method')} {existing.get('path')} — {where} calls "
            f"{proposed.get('method')} {proposed.get('path')}"
        )
    question = ". ".join(sentences) + ". Which reading is correct?"
    return {
        "kind": "intuition-contradiction",
        "origin_verb": ORIGIN_VERB_BY_SOURCE.get(source, DEFAULT_ORIGIN_VERB),
        "element_id": element.element_id,
        "route": route,
        "element_label": label,
        "fields": list(fields),
        "existing": {
            "source": element.source,
            "user_verdict": element.data.get("user_verdict"),
            "confirmed_action": element.data.get("confirmed_action"),
            "confirmed_endpoint": element.data.get("confirmed_endpoint"),
        },
        "incoming": {
            "source": source,
            "origin": origin,
            "confirmed_action": incoming.get("action"),
            "confirmed_endpoint": incoming.get("endpoint"),
            # The pointer the blocked write was carrying. A bug-path upsert now
            # writes NOTHING on a contradiction, so if the refs did not travel
            # here the link back to the covering regression test would be lost.
            "regression_refs": list(refs),
        },
        "question": question,
        "resolution": resolution,
    }


def _next_element_id(doc: IntuitionMap, incoming: Dict[str, Any]) -> str:
    existing = set(doc.element_ids)
    ordinal = 1
    while True:
        candidate = derive_element_id(incoming["route"], incoming["label"],
                                      region=incoming["region"], ordinal=ordinal)
        if candidate not in existing:
            return candidate
        ordinal += 1


def _add_evidence(element: ElementBlock, citations: Sequence[str]) -> bool:
    evidence = element.data.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
    changed = False
    for citation in citations:
        if citation and citation not in evidence:
            evidence.append(citation)
            changed = True
    if changed or "evidence" not in element.data:
        element.data["evidence"] = evidence
    return changed


def _merge_refs(element: ElementBlock, refs: Sequence[Dict[str, Any]]) -> bool:
    current = element.data.get("regression_refs")
    if not isinstance(current, list):
        current = []
    seen = {(r.get("test"), r.get("ref")) for r in current if isinstance(r, dict)}
    changed = False
    for ref in refs:
        key = (ref["test"], ref["ref"])
        if key in seen:
            continue
        current.append(ref)
        seen.add(key)
        changed = True
    if changed or "regression_refs" not in element.data:
        element.data["regression_refs"] = current
    return changed


def _apply(element: ElementBlock, incoming: Dict[str, Any], *, source: str,
           citations: Sequence[str], refs: Sequence[Dict[str, Any]],
           confirm: bool) -> bool:
    """Write the incoming reading onto ``element``. Returns True when anything
    actually changed (an idempotent re-upsert must not dirty the block)."""
    before = _snapshot(element.data)
    element.data["source"] = source
    if not _blank(incoming.get("kind")):
        element.data.setdefault("element_kind", incoming["kind"])
    if not _blank(incoming.get("design_source")) and _blank(element.data.get("design_source")):
        element.data["design_source"] = incoming["design_source"]
    if confirm:
        if not _blank(incoming.get("action")):
            element.data["intuited_action"] = incoming["action"]
            element.data["confirmed_action"] = incoming["action"]
        if incoming.get("endpoint"):
            element.data["confirmed_endpoint"] = incoming["endpoint"]
            candidates = element.data.get("candidate_endpoints")
            if not isinstance(candidates, list):
                candidates = []
            if not any(_same_endpoint(c, incoming["endpoint"]) for c in candidates):
                candidates.append(incoming["endpoint"])
            element.data["candidate_endpoints"] = candidates
        element.data["confidence"] = "high"
        element.data["user_verdict"] = "confirmed"
        element.data["ambiguity_question"] = None
    _add_evidence(element, citations)
    if refs:
        _merge_refs(element, refs)
    if _snapshot(element.data) == before:
        return False
    element.touch()
    return True


def _snapshot(data: Dict[str, Any]) -> str:
    return dump_yaml_subset(data, order=ELEMENT_FIELD_ORDER)


def _new_entry(element_id: str, incoming: Dict[str, Any], *, source: str,
               citations: Sequence[str], refs: Sequence[Dict[str, Any]]
               ) -> Dict[str, Any]:
    if _blank(incoming.get("action")):
        raise ValueError(
            f"flow element {incoming['label']!r} on {incoming['route']} is new to "
            f"the map and names no action — an entry with no intuited_action "
            f"cannot be written"
        )
    endpoint = incoming.get("endpoint")
    return {
        "element_id": element_id,
        "route": incoming["route"],
        "element_label": incoming["label"],
        "element_kind": incoming["kind"],
        "design_source": incoming.get("design_source") or (citations[0] if citations else ""),
        "intuited_action": incoming["action"],
        "candidate_endpoints": [endpoint] if endpoint else [],
        "confidence": "high",
        "evidence": list(citations),
        "ambiguity_question": None,
        "user_verdict": "confirmed",
        "correction_note": None,
        "confirmed_action": incoming["action"],
        "confirmed_endpoint": endpoint,
        "superseded_by": None,
        "source": source,
        "regression_refs": list(refs),
    }


def _refresh_counters(doc: IntuitionMap) -> None:
    """Recompute the frontmatter counters, marking it dirty only on a real change.

    `last_intuited` is deliberately NOT touched: it is the intuiter's freshness
    stamp, and a lifecycle upsert bumping it would make a stale map look fresh
    to the suite-builder's P2 check.
    """
    elements = doc.elements
    summary = {level: 0 for level in CONFIDENCE_LEVELS}
    for element in elements:
        summary[element.confidence if element.confidence in summary else "unknown"] += 1
    updates = {
        "covers_elements": len(elements),
        "covers_screens": len({_norm(e.route) for e in elements if e.route}),
        "confidence_summary": summary,
    }
    if all(doc.frontmatter.get(k) == v for k, v in updates.items()):
        return
    doc.frontmatter.update(updates)
    doc.mark_frontmatter_dirty()


def _upsert(doc: IntuitionMap, elements: Sequence[Dict[str, Any]], *, source: str,
            origin: Optional[str], refs: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    if origin is not None and not isinstance(origin, str):
        raise ValueError(
            f"origin must be a string naming the flow or artifact (got "
            f"{type(origin).__name__}: {origin!r}). It is interpolated straight "
            f"into an evidence citation, and a non-string produces one that "
            f"names nothing - `5: user-specified flow exercised this element` "
            f"reads like a citation and cites nothing, which is exactly what "
            f"interaction-intuition's every-intuition-cites-a-source rule refuses."
        )
    result: Dict[str, Any] = {"created": [], "updated": [], "unchanged": [],
                              "blocked": [], "ambiguous": [], "questions": []}
    provenance = _PROVENANCE_PHRASE.get(source, _PROVENANCE_DEFAULT)
    for spec in elements:
        incoming = _normalize_flow_element(spec, origin, provenance)

        if incoming["ambiguous"]:
            existing = find_element(doc, element_id=incoming["element_id"],
                                    route=incoming["route"], label=incoming["label"])
            result["ambiguous"].append(
                existing.element_id if existing is not None else incoming["label"])
            result["questions"].append(_ambiguity_question(
                existing, incoming, source=source, origin=origin, refs=refs))
            continue

        citations = list(incoming["evidence"])
        if source == "user-flow" and origin:
            citations.append(f"{origin}: user-specified flow exercised this element")
        for ref in refs:
            citations.append(f"{ref['test']}: regression flow covering {ref['ref']}")

        existing = find_element(doc, element_id=incoming["element_id"],
                                route=incoming["route"], label=incoming["label"])
        if existing is None:
            element_id = incoming["element_id"] or _next_element_id(doc, incoming)
            data = _new_entry(element_id, incoming, source=source,
                              citations=citations, refs=refs)
            anchor = _last_element_on_route(doc, incoming["route"])
            doc.append_element(data, after=anchor)
            result["created"].append(element_id)
            continue

        conflicts = _contradiction_fields(existing, incoming)
        if conflicts:
            result["blocked"].append(existing.element_id)
            result["questions"].append(_question(
                existing, incoming, conflicts, source=source, origin=origin,
                refs=refs,
                resolution=(
                    "The map entry was left unmodified. Resolve the disagreement "
                    "with the user, then re-run the verb (or correct the flow). "
                    "Any regression pointer this write was carrying is recorded "
                    "under incoming.regression_refs."
                )))
            continue
        changed = _apply(existing, incoming, source=source, citations=citations,
                         refs=refs, confirm=True)
        (result["updated"] if changed else result["unchanged"]).append(existing.element_id)

    _refresh_counters(doc)
    return result


def _last_element_on_route(doc: IntuitionMap, route: Any) -> Optional[ElementBlock]:
    want = _norm(route)
    anchor = None
    for element in doc.elements:
        if _norm(element.route) == want:
            anchor = element
    return anchor


def grow(doc: IntuitionMap, flow_elements: Sequence[Dict[str, Any]], *,
         origin: Optional[str] = None) -> Dict[str, Any]:
    """Upsert user-specified flow elements as CONFIRMED entries.

    The Phase −1D bulk-verify gate resolves the INTUITER's uncertainty; a
    user-specified flow carries none, because the user is the source. That
    asymmetry is deliberate (design decision D2) and is why `grow` confirms
    without a round-trip.

    The one case that still asks is a contradiction with a reading the user
    already ratified: the entry is left UNMODIFIED and a question artifact
    naming both readings lands in ``result["questions"]``.

    Each flow element is ``{route, label, kind, action, endpoint}`` (``endpoint``
    optional, a mapping or a ``"POST /api/x"`` string). Returns
    ``{created, updated, unchanged, blocked, questions}``.
    """
    return _upsert(doc, flow_elements, source="user-flow", origin=origin,
                   refs=[])


def bug_path_upsert(doc: IntuitionMap, elements: Sequence[Dict[str, Any]], *,
                    regression_refs: Sequence[Dict[str, Any]],
                    origin: Optional[str] = None) -> Dict[str, Any]:
    """Upsert a debugging-discovered path with ``source: bug-path`` plus
    ``regression_refs[]`` naming the covering debug-flow test and the SR/bug.

    The guard is IDENTICAL to `grow`'s (spec amendment, 2026-08-26). A bug path
    that disagrees with a reading the user ratified writes NOTHING to that entry
    and raises the same question; the regression pointer travels in the
    question's ``incoming.regression_refs`` so the link to the covering
    debug-flow test survives until the reading is settled. An earlier cut let
    the provenance and refs land anyway on the grounds that R3 requires the bug
    path to reach the map — "left unmodified" has to mean unmodified.
    """
    refs = _normalize_refs(regression_refs)
    if not refs:
        raise ValueError(
            "bug_path_upsert needs at least one regression ref — the pointer back "
            "to the covering debug-flow test IS the verb's product"
        )
    return _upsert(doc, elements, source="bug-path", origin=origin, refs=refs,
                   )
