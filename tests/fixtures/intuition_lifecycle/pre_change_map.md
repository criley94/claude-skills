---
last_intuited: 2026-08-19T14:22:05Z
confirmed: true
confirmed_at: 2026-08-19T15:04:41Z
producer: interaction-intuiter
inputs:
  - docs/ROUTE_MAP.md
  - docs/DESIGN_MAP.md
  - ../../docs/INTEGRATION_MAP.md
covers_screens: 2
covers_elements: 4
confidence_summary:
  high: 2
  medium: 1
  low: 1
  unknown: 0
---

# Interaction intuition map — storefront-web

Produced at Phase -1B from ROUTE_MAP.md x DESIGN_MAP.md x INTEGRATION_MAP.md.
Low and unknown items were resolved at the Phase -1D bulk-verify gate.

## /dashboard

### dashboard__header__save-layout__1

```yaml
element_id: dashboard__header__save-layout__1
route: /dashboard
element_label: Save layout
element_kind: button
design_source: docs/DESIGN_MAP.md#dashboard-header
intuited_action: "Persist the widget arrangement the user just dragged into place, so the dashboard reopens the same way."
candidate_endpoints:
  - method: PUT
    path: /api/dashboard/layout
    source: docs/INTEGRATION_MAP.md#put-api-dashboard-layout
    match_kind: exact-by-action-noun
confidence: high
evidence:
  - "docs/DESIGN_MAP.md#dashboard-header: the header spec names a Save layout control"
  - "docs/INTEGRATION_MAP.md#put-api-dashboard-layout: PUT /api/dashboard/layout persists a layout document"
ambiguity_question: null
user_verdict: confirmed
correction_note: null
confirmed_action: "Persist the widget arrangement the user just dragged into place, so the dashboard reopens the same way."
confirmed_endpoint:
  method: PUT
  path: /api/dashboard/layout
  source: docs/INTEGRATION_MAP.md#put-api-dashboard-layout
  match_kind: exact-by-action-noun
superseded_by: null
```

### dashboard__row__archive__1

```yaml
element_id: dashboard__row__archive__1
route: /dashboard
element_label: Archive
element_kind: button
design_source: docs/DESIGN_MAP.md#dashboard-row-actions
intuited_action: "Take the row out of the active list without destroying it."
candidate_endpoints: []
confidence: low
evidence:
  - "docs/DESIGN_MAP.md#dashboard-row-actions: an unlabelled box icon sits at the end of each row"
ambiguity_question: "Should the row-level Archive control call POST /api/items/{id}/archive (the row survives, archived=true, still queryable) or DELETE /api/items/{id} (the row is removed and cannot be recovered)?"
user_verdict: null
correction_note: null
confirmed_action: null
confirmed_endpoint: null
superseded_by: null
```

## /items/[id]/edit

### items-id-edit__form__title-input__1

```yaml
element_id: items-id-edit__form__title-input__1
route: /items/[id]/edit
element_label: Title
element_kind: form-input
design_source: docs/ROUTE_MAP.md#items-id-edit
intuited_action: "Capture the item title the edit form will submit."
candidate_endpoints:
  - method: PATCH
    path: /api/items/{id}
    source: docs/INTEGRATION_MAP.md#patch-api-items-id
    match_kind: plausible-by-design-intent
confidence: medium
evidence:
  - "docs/ROUTE_MAP.md#items-id-edit: the edit route renders a title field bound to form state"
ambiguity_question: "Does the Title field save on blur (a PATCH per field) or only when the form's Save button submits the whole item?"
user_verdict: null
correction_note: null
confirmed_action: null
confirmed_endpoint: null
superseded_by: null
```

### items-id-edit__footer__delete__1

```yaml
element_id: items-id-edit__footer__delete__1
route: /items/[id]/edit
element_label: Delete item
element_kind: button
design_source: docs/DESIGN_MAP.md#items-edit-footer
intuited_action: "Remove this item permanently and return the user to the item list."
candidate_endpoints:
  - method: DELETE
    path: /api/items/{id}
    source: docs/INTEGRATION_MAP.md#delete-api-items-id
    match_kind: exact-by-label
confidence: high
evidence:
  - "docs/DESIGN_MAP.md#items-edit-footer: the footer spec names a destructive Delete item control"
  - "docs/INTEGRATION_MAP.md#delete-api-items-id: DELETE /api/items/{id} removes an item"
ambiguity_question: null
user_verdict: confirmed
correction_note: null
confirmed_action: "Remove this item permanently and return the user to the item list."
confirmed_endpoint:
  method: DELETE
  path: /api/items/{id}
  source: docs/INTEGRATION_MAP.md#delete-api-items-id
  match_kind: exact-by-label
superseded_by: null
```
