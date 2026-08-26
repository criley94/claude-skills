# -*- coding: utf-8 -*-
"""Playwright suite-manifest engine package.

The deterministic mechanism under the `playwright-suite-builder` skill:
`manifest.py` validates the per-codebase suite manifest and implements the
`verify-suite-manifest` ship check. Stdlib-only, no import-time side effects.

The module is also loadable by file path (the ``scripts/`` tier's house idiom),
so this ``__init__`` deliberately imports nothing.
"""
