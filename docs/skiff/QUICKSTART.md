# Your first run in five minutes

For `/architect-team:skiff` — the small-build lane.

You do not need to read anything else first. If a word here is unfamiliar, it is
in `GLOSSARY.md` next to this file.

---

## What you need

- A project directory. **An empty one is fine.**
- Nothing else. No test suite, no deployed site, no GitHub repository.

If your project has those things, skiff uses them. If it doesn't, skiff works
anyway — that is the main thing separating it from the other pipelines here.

---

## The run

### 1. Say what you want, in a sentence

```
/architect-team:skiff add a page that lists my saved recipes with a search box
```

A folder of notes works too, if you'd rather point at one:

```
/architect-team:skiff ~/notes/recipe-feature
```

Plain sentences are a first-class input. You never have to write a spec first.

### 2. Read the summary

skiff reads the job back to you before it does anything. Four short things:

1. **What it heard** — the job in your own words. Correct it if it's wrong.
2. **What it will use** — which model, and how many helpers. This is your cost
   picture, shown *before* anything is spent.
3. **What happens if it struggles** — by default it stops after three tries and
   comes back to you. Say so here if you'd rather it hand off to the big
   pipeline instead. **You are only asked this once.**
4. **Anything else** — your chance to change anything above.

Everything is in plain language. If you meet a term you have to decode, that's a
bug — tell Claude and it will say it differently.

### 3. Type the word

At the end you'll see something like:

```
When you're ready, type RUDDER and I'll begin.
```

Type it. Capitals don't matter; extra spaces don't matter.

**The word is different every run.** That's deliberate — it means you can't
start a run out of habit. You have to read to the bottom to find out what to
type, which means you've read the summary.

**"yes" will not start it.** Neither will "ok" or pressing Enter. Only the word.

If you mistype it, nothing bad happens — skiff shows it again and waits. A typo
is never read as "no".

If you change anything, you get a fresh summary **and a fresh word**. You can't
reuse the word from the previous screen.

### 4. It builds

It writes the plan, does the work, and checks it against your app running
locally. If your project has no tests, it will tell you and offer to write
them — and when it writes them, it writes thorough ones.

### 5. It reports

At the end you get: what ran, on what, how many retries, what it cost, and
**anything it skipped and why**. If it couldn't verify something, it says so
rather than staying quiet.

---

## If it gets stuck

By default: it stops after three tries and tells you what it tried.

It will **not** quietly hand your job to a larger, more expensive pipeline. That
only happens if you asked for it at step 2 — and if it does happen, it's
announced and goes on its own branch.

---

## The three flags worth knowing

| Flag | What it does |
|---|---|
| `--on-failure stop` | Skip the question — just stop after three tries |
| `--on-failure escalate` | Skip the question — hand off to the big pipeline if stuck |
| `--yes` | Skip the summary and go word entirely. For repeat runs you've done before |

Plain English works too: *"stop if it doesn't work"*, *"escalate if you get
stuck"*.

Flags answer the questions in advance — **they don't skip the summary.** Only
`--yes` does that, and it's never on by default.

---

## When to use something bigger

Reach for `/architect-team` instead when:

- The change is large, or you're not sure how big it is.
- It touches two projects that talk to each other.
- Getting it wrong would be expensive.

For those, the big pipeline is cheaper than fixing it afterward. skiff will say
so if it thinks you're on the wrong one.

---

## The one-line version

> Say what you want → read the summary → type the word → it builds → it tells
> you what happened.
