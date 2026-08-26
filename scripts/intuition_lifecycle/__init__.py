# -*- coding: utf-8 -*-
"""Intuition-map lifecycle engine package.

The deterministic mechanism under the `intuition-map-lifecycle` skill's three
verbs (`ensure`, `grow`, `bug-path-upsert`) against the `interaction-intuition`
artifact. Stdlib-only, no import-time side effects.

* ``engine`` — parse / upsert / validate / serialize the map.
* ``cli``    — the command-line surface over ``engine``.

Modules are also loadable by file path (the ``scripts/`` tier's house idiom),
so this ``__init__`` deliberately imports nothing.
"""
