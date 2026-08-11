---
description: Declare that this run's deliverable is an Expo app destined for the Apple App Store and Google Play via EAS — not a website. Loads the expo-standalone-app-build technology contract, writes it into the project's CLAUDE.md so every spawned agent inherits it, and installs the three completion checks (lint / package / browser tests) that every frontend slice must pass. Use alongside /architect-team, /architect-team:mini, or /architect-team:bug-fix when the target is a phone app.
argument-hint: "[project-path] [--verify-only]"
---

# /architect-team:expo-standalone-app-build

Establish and enforce the Expo delivery contract for this run.

Without this, the pipeline's default hand — Vite, Tailwind, shadcn/ui, `react-router-dom`, `<div>` — produces a competent web app that cannot be built for a phone, and reports success.

## What this does

1. **Loads the `expo-standalone-app-build` skill.** The technology contract, the required project files, the three checks, and the honest bounds on what a Linux machine can prove.

2. **Propagates the contract.** Writes the forbidden/allowed table and the three check commands into `<project>/CLAUDE.md` under `## This is an Expo app, not a website`. The pipeline spawns many agents and not all of them load every skill — every one of them reads the project's `CLAUDE.md`. This step is the enforcement mechanism.

3. **Installs the lint contract.** Ensures `eslint.config.js` extends `eslint-config-expo` and carries the ban rules from the skill — lowercase JSX tags, browser globals, web-only packages, raw text outside `<Text>`.

4. **Registers the completion checks** for every frontend slice in the run:
   - `npx expo lint` — zero errors
   - `npx expo export --platform ios` and `--platform android` — both clean
   - Playwright flows against `npx expo start --web` — satisfies the existing Phase 5 gate

## Usage

Invoke before or alongside the build command:

```
/architect-team:expo-standalone-app-build ./my-app
/architect-team "add a notes screen that saves locally and shows them on return"
```

`--verify-only` runs the three checks against an existing project and reports, without modifying anything.

## Arguments

| Argument | Meaning |
| --- | --- |
| `project-path` | Root of the Expo project. Defaults to the current working directory. |
| `--verify-only` | Run the three checks and report. No edits, no contract propagation. |

## What this does not do

It does not build binaries, does not talk to EAS, and does not submit anything to a store. It also cannot prove the app looks or behaves correctly on a phone — layout, keyboard, safe areas, and touch targets are invisible to all three checks.

A clean run means: **valid Expo project, three checks green, not yet run on a device.**

Everything from binary to store listing belongs to the on-device release process, run on a Mac.
