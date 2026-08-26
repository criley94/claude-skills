---
last_intuited: 2026-08-20T09:00:00Z
confirmed: false
confirmed_at: null
producer: interaction-intuiter
inputs:
  - docs/ROUTE_MAP.md
covers_screens: 1
covers_elements: 4
confidence_summary:
  high: 0
  medium: 0
  low: 4
  unknown: 0
---

# Interaction intuition map — broken-fixture

Every element below violates at least one schema rule. This fixture exists so
the validator's findings can be pinned by kind, entry, and field.

## /settings

### settings__panel__mystery__1

```yaml
element_id: settings__panel__mystery__1
route: /settings
element_label: ...
element_kind: teleporter
design_source: docs/ROUTE_MAP.md#settings
intuited_action: "Do something to the settings panel."
candidate_endpoints: []
confidence: quite-sure
evidence: []
ambiguity_question: null
user_verdict: null
correction_note: null
confirmed_action: null
confirmed_endpoint: null
superseded_by: null
```

### settings__panel__save__1

```yaml
element_id: settings__panel__save__1
route: /settings
element_label: Save
element_kind: button
design_source: docs/ROUTE_MAP.md#settings
intuited_action: ""
candidate_endpoints:
  - method: POST
    path: /api/settings
confidence: low
evidence:
  - "docs/ROUTE_MAP.md#settings: a Save control closes the panel"
ambiguity_question: null
user_verdict: probably
correction_note: null
confirmed_action: null
confirmed_endpoint: null
superseded_by: null
```

### settings__panel__save__1

```yaml
element_id: settings__panel__save__1
route: /settings
element_label: Save (duplicate id)
element_kind: button
design_source: docs/ROUTE_MAP.md#settings
intuited_action: "A second entry claiming the same element_id as the one above."
candidate_endpoints: []
confidence: low
evidence:
  - "docs/ROUTE_MAP.md#settings"
ambiguity_question: "Which of the two Save entries is the real one?"
user_verdict: null
correction_note: null
confirmed_action: null
confirmed_endpoint: null
superseded_by: null
```

### settings__panel__export__1

```yaml
route: /settings
element_label: Export
element_kind: button
design_source: docs/ROUTE_MAP.md#settings
intuited_action: "Download the settings as JSON."
candidate_endpoints: []
confidence: low
source: telepathy
regression_refs:
  - ref: SR-000
evidence:
  - "docs/ROUTE_MAP.md#settings"
ambiguity_question: "Does Export download a file or open a share dialog?"
user_verdict: null
correction_note: null
confirmed_action: null
confirmed_endpoint: null
superseded_by: null
```
