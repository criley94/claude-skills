---
name: expo-standalone-app-build
description: Use when the deliverable is a React app that will ship to the Apple App Store and Google Play as a native app via Expo and EAS — not a website. Governs every architect-team phase that writes frontend code for such a target. Triggers include "build an Expo app", "this needs to go to the App Store", "React Native app", "mobile app to both stores", "EAS build", "expo-router", any requirement naming iOS/Android as the delivery target, and any run where app.json / eas.json exist in the work tree. Establishes the technology contract (which React libraries are valid input to Expo and which are structurally impossible on a phone), the required project files, and the three mechanical checks that prove the artifact is a valid Expo project. Explicitly bounds what a Linux build machine can and cannot prove, and hands the remainder to the on-device release process.
---

# Expo Standalone App Build

The deliverable is **an Expo project that EAS can turn into App Store and Google Play binaries.** It is not a website. A website that happens to be written in React is not a partial success here — it is a total failure that will not be discovered until someone tries to build it.

This skill exists because the default hand of every agent in this pipeline — Vite, Tailwind, shadcn/ui, react-router-dom, `<div>` — produces exactly that failure. Left ungoverned, the pipeline will build a competent web app and report success.

## The prime directive

> Every line of frontend code in this run must be able to execute on a phone that has no browser, no DOM, and no CSS engine.

React Native does not render HTML. There is no `document`. There is no stylesheet cascade. Code that assumes otherwise compiles, bundles, passes tests in a browser, and crashes on the device.

---

## The technology contract

### Structurally impossible — never use

| Forbidden | Why | Use instead |
| --- | --- | --- |
| `<div>`, `<span>`, `<p>`, `<section>`, any lowercase JSX tag | HTML elements do not exist in React Native | `<View>`, `<Text>` |
| `<button>` | " | `<Pressable>` |
| `<input>`, `<textarea>` | " | `<TextInput>` |
| `<img>` | " | `<Image>` (prefer `expo-image`) |
| `<a href>` | " | `<Link>` from `expo-router` |
| `.css`, `.scss`, CSS modules, styled-components (web build) | No stylesheet engine on device | `StyleSheet.create({})` |
| Tailwind CSS | Compiles to CSS classes | NativeWind |
| Vite, Webpack, Parcel | Wrong bundler; Expo uses Metro | Metro (default, no config needed) |
| Next.js, Remix, Gatsby | Web frameworks | Expo Router |
| `react-router`, `react-router-dom` | DOM router | Expo Router (file-based, `app/`) |
| MUI, shadcn/ui, Chakra, Radix, Ant Design, Bootstrap, Headless UI | All render HTML | React Native component libraries |
| `localStorage`, `sessionStorage` | Browser-only API | `@react-native-async-storage/async-storage`, `expo-secure-store`, `expo-sqlite` |
| `document`, `window`, `navigator` (most), `alert()` | No DOM, no browser globals | React Native / Expo equivalents |
| Chart.js, Recharts, D3 (DOM-based) | Draw into HTML/SVG DOM | `react-native-svg`-based charting |
| Framer Motion (web) | DOM animation | `react-native-reanimated` |
| `fetch` to `/relative/paths` | No origin on device | Absolute URLs only |

### The rule agents forget most often

**Every string must be inside a `<Text>` component.**

```tsx
<View>Hello</View>              // crashes on device
<View><Text>Hello</Text></View> // correct
```

On web this renders fine. On a phone it throws. This is the single most common way a browser-green project dies on first launch.

### Required baseline

- **Expo SDK 57** or the current stable SDK. Do not pin an older major without a recorded reason.
- **TypeScript.**
- **Expo Router** for all navigation. Routes are files under `app/`.
- **React Native Web enabled** — the project must also run in a browser. This is load-bearing: it is what lets the pipeline's existing Playwright gate function. See *Testing* below.

---

## Required project files

An artifact is not complete unless all of these exist and are populated with real values. Placeholder values (`com.example.app`, `"name": "my-app"`) are a failure.

| File | Must contain |
| --- | --- |
| `app.json` (or `app.config.ts`) | App display name, `slug`, `version`, `ios.bundleIdentifier`, `android.package`, `icon`, `splash`, `scheme` |
| `eas.json` | Build profiles for `development`, `preview`, `production` |
| `package.json` | `expo` dependency; no forbidden packages from the table above |
| `assets/icon.png` | 1024×1024, square, no transparency, no rounded corners |
| `assets/splash.png` | Splash image referenced by `app.json` |
| `app/` | At least one route file; `_layout.tsx` present |
| `eslint.config.js` | The rule set in *Check 1* below |

`ios.bundleIdentifier` and `android.package` are permanent once published. Derive them from the product name in reverse-DNS form and record the choice; do not invent a throwaway.

---

## The three checks

These are the completion criteria. All three must be **executed with output captured** — per this pipeline's standing rule that testing is executed, not described. An agent asserting "the project is Expo-valid" without these three command outputs has not verified anything.

### Check 1 — Lint. The important one.

This is the only check that catches web code that would otherwise pass everything else. Neither bundling nor browser tests will catch `<div>` or `localStorage`, because both work in a browser.

Required in `eslint.config.js`, extending `eslint-config-expo`:

```js
rules: {
  // HTML elements do not exist in React Native.
  'no-restricted-syntax': ['error', {
    selector: 'JSXOpeningElement[name.name=/^[a-z]/]',
    message: 'HTML elements do not exist on a phone. Use <View>, <Text>, <Pressable>, <TextInput>, <Image>.',
  }],

  // Browser globals do not exist on a phone.
  'no-restricted-globals': ['error',
    { name: 'localStorage', message: 'Use AsyncStorage / expo-secure-store / expo-sqlite.' },
    { name: 'sessionStorage', message: 'Use AsyncStorage / expo-secure-store / expo-sqlite.' },
    { name: 'document', message: 'There is no DOM on a phone.' },
    { name: 'alert', message: 'Use the Alert API from react-native.' },
  ],

  // Web-only packages will bundle successfully and then crash.
  'no-restricted-imports': ['error', {
    patterns: [
      { group: ['react-router', 'react-router-dom'], message: 'Use expo-router.' },
      { group: ['@mui/*', '@chakra-ui/*', '@radix-ui/*', 'antd', 'bootstrap', '@headlessui/*'],
        message: 'DOM component libraries do not render on a phone.' },
      { group: ['recharts', 'chart.js', 'd3'], message: 'Use a react-native-svg charting library.' },
      { group: ['framer-motion'], message: 'Use react-native-reanimated.' },
      { group: ['*.css', '*.scss'], message: 'There is no CSS engine on a phone. Use StyleSheet.' },
    ],
  }],

  // Every string must live inside <Text>.
  'react-native/no-raw-text': 'error',
}
```

Run:

```bash
npx expo lint
```

**Zero errors is the pass condition.** A disabled rule, an `eslint-disable` comment on a forbidden construct, or a rule removed from the config is a failure of this check, not a workaround for it. If a rule genuinely blocks legitimate work, escalate — do not silence it.

### Check 2 — Package.

Proves the project assembles as a real Expo app: every import resolves, syntax is valid, config is readable, referenced assets exist.

```bash
npx expo export --platform ios
npx expo export --platform android
```

Both must exit clean. This runs on Linux and requires no phone, no Mac, and no simulator.

**What this does not prove:** it never executes your code, so it catches no runtime error. A project full of `<div>` exports successfully.

### Check 3 — Browser tests.

The project runs in a browser via React Native Web, so the pipeline's existing Playwright discipline applies unchanged. Serve the web target and run the flows against it per `playwright-user-flows`.

```bash
npx expo start --web
```

This satisfies the Phase 5 integration gate. Do not attempt to substitute a native test runner, and do not mark the frontend test gate `n/a` — the web target is a real, running instance of the app and the gate is fully satisfiable.

**What this does not prove:** the browser is precisely where `<div>` and `localStorage` still work. Check 3 verifies the *features* are correct. It does not verify the app is native-valid — that is Check 1's job, and Check 1 cannot be skipped because Check 3 is green.

---

## Enforcement — three layers, and the order they must be installed in

Knowledge does not enforce itself. The pipeline spawns many agents across many phases and this skill is not guaranteed to be loaded by every one of them. Three layers carry the contract, weakest to strongest:

| Layer | Mechanism | Depends on |
| --- | --- | --- |
| 1. Told | This skill | An agent loading it |
| 2. Caught | `npx expo lint` at each review gate | An agent running it |
| 3. Blocked | `hooks/pretool_expo_guard.py` | Nothing — it refuses the write |

**Layer 3 is the only one that requires no cooperation.** The guard is a `PreToolUse` hook on Write / Edit / NotebookEdit. It detects an Expo project by walking up for `app.json` with an `expo` key or a `package.json` with an `expo` dependency, then refuses any JS/TS write containing HTML elements, browser globals, or web-only imports. It stays silent outside Expo projects, on `*.web.tsx` files, on files carrying the `'use dom'` directive, and on test/e2e files that legitimately drive a browser.

### Setup runs BEFORE the build, not during it

This ordering is a hard requirement, not a preference. Installing the contract as a task *inside* the build run is circular — an agent would have to already be following the skill in order to install the thing that enforces the skill.

```
/architect-team:expo-standalone-app-build ./my-app    # 1. install the contract
/architect-team "add the notes screen"                # 2. now constrained
```

Step 1 must complete before any implementation agent is spawned. It:

1. Writes the technology contract into `<project>/CLAUDE.md` under `## This is an Expo app, not a website` — the prime directive, the forbidden/allowed table, the every-string-inside-`<Text>` rule, and the three check commands. Every agent working in the repo reads this file even when it never loads this skill.
2. Ensures `eslint.config.js` extends `eslint-config-expo` and carries the *Check 1* rules.
3. Confirms `app.json` and `eas.json` exist with real values.

If a run reaches implementation and `<project>/CLAUDE.md` has no Expo section, **stop and install the contract before writing code.** Do not proceed on the assumption that the hook will catch everything — the hook catches the constructs it knows about, and it is a backstop, not a substitute for the other two layers.

---

## Pipeline integration

| Phase | Applies |
| --- | --- |
| Phase −1 mapping | `ROUTE_MAP.md` maps Expo Router file-based routes under `app/`. The route-mapper already supports Expo Router. |
| Phase 0/1 spec + coverage | Acceptance criteria are phone behaviors. Every frontend criterion must be verifiable through the web target. |
| Phase 3 review gates | Checks 1 and 2 run per slice. A slice with lint errors does not pass its gate. |
| Phase 5 integration | Check 3 — Playwright against `expo start --web`. |
| Phase 8 | Checks 1–3 all green before commit. |

`dev-api-integration-testing` is `n/a` for a self-contained app with no backend. Record it as `n/a` with that reason, not silently.

**Reuse-first still governs.** When an Expo project already exists in the work tree, `reuse-first-design` applies with full force: match the existing screen structure, styling approach, and storage layer rather than introducing a second way to do the same thing.

---

## What this skill does not prove

Bounding this honestly is part of the contract. All three checks green means:

- The project is a structurally valid Expo app that EAS will accept.
- No web-only code the rules cover has entered the codebase.
- The features behave as specified.

It does **not** mean the app is ready to ship. Not proven, and not provable on a Linux machine:

- How it looks on a phone screen — layout, text sizing, spacing.
- Safe areas around notches and home indicators.
- Whether the on-screen keyboard covers the input the user is typing into.
- Touch target sizes and gesture behavior.
- Performance on real hardware.
- Anything requiring camera, location, notifications, or permission dialogs.

None of these are lint-detectable and none appear in a desktop browser. **A build that passes all three checks has not been seen on a phone.** Verifying that, and everything from binary to store listing, belongs to the on-device release process (`build-to-expo-release`), which runs on a Mac.

Do not describe a run as "ready for the App Store." The accurate statement is: *"valid Expo project, all three checks green, not yet run on a device."*

---

## Red flags

Any of these thoughts means stop — the contract is being rationalized away.

| Thought | Reality |
| --- | --- |
| "I'll use a `<div>` here, it's just a wrapper." | It is not a wrapper. It is a crash. Use `<View>`. |
| "Tailwind is basically fine, it's just classes." | Classes require a CSS engine. There is none. Use NativeWind or StyleSheet. |
| "The browser tests pass, so it works." | The browser is where the forbidden constructs still work. That is why Check 1 exists. |
| "shadcn has exactly the component I need." | It renders HTML. It cannot appear on a phone at any cost. |
| "I'll disable this lint rule, it's being pedantic." | The rule is the only thing standing between you and a crash on launch. Escalate instead. |
| "localStorage is simpler than AsyncStorage for now." | It does not exist on the device. There is no "for now." |
| "I'll wire up navigation with react-router and swap it later." | Routing is structural. "Later" means rewriting every screen. |
| "It exported successfully, so it's valid." | Export never runs the code. A project full of `<div>` exports clean. |
| "The hook blocked me, I'll rename the file `.web.tsx`." | That exception exists for genuinely web-only code. Using it to get unblocked ships a screen that does not exist on the phone. |
| "I'll add `'use dom'` so it goes through." | That wraps the component in a WebView. It is a deliberate architectural choice, not a way past a guard. |
| "This is ready for the App Store." | It has never been on a phone. Say what is actually true. |
