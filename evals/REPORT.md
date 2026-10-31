# Eval report: what each stage of the pipeline buys

**Run:** 20 tasks × 4 pipeline configurations × 2 implementer models × 1 repeat = 160 runs.

**Setup:** bench v2 (`bench/tasks`), planner `anthropic/claude-haiku-5.5`, reviewer `z-ai/glm-5.3-flash`. Raw records are in `results/main2-*.jsonl`; regenerate the tables with `uv run forgeloop report --id main2-haiku`.

**Cost:** $5.08 was paid for these runs, including the re-run of 27 runs after the checkpoint fix (see below). The "$" columns are fresh-run costs: a run replayed from the local response cache is still counted at its original price, so that configurations stay comparable.

## Configurations

| config | planner | implementer | test gate (tests, ruff, bandit, OSV) | review gate |
| --- | --- | --- | --- | --- |
| baseline | – | one run on the ticket | – | – |
| plan | haiku | one run per checkpoint, an unfinished checkpoint retried once | – | – |
| test-gate | haiku | per checkpoint | up to 3 fix rounds | – |
| full | haiku | per checkpoint | up to 3 fix rounds | up to 2 fix rounds |

## Headline numbers (17 solvable tasks)

| implementer | config | delivered working | delivered broken | escalated | precision of delivered | $ per working delivery |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| haiku-5.5 | baseline | 16 | 1 | 0 | 94% | $0.022 |
| haiku-5.5 | plan | 15 | 0 | 2 | 100% | $0.042 |
| haiku-5.5 | test-gate | 15 | 0 | 2 | 100% | $0.051 |
| haiku-5.5 | full | 15 | 0 | 2 | 100% | $0.056 |
| gemini-2.5-flash-lite | baseline | 5 | 12 | 0 | 29% | $0.017 |
| gemini-2.5-flash-lite | plan | 6 | 9 | 2 | 40% | $0.130 |
| gemini-2.5-flash-lite | test-gate | 4 | 4 | 9 | 50% | $0.231 |
| gemini-2.5-flash-lite | full | 1 | 0 | 16 | 100% | $1.434 |

### Ambiguous tickets (3), where the right answer is a question

| implementer | baseline | plan / test-gate / full |
| --- | ---: | ---: |
| haiku-5.5 | 3/3 | 3/3 |
| gemini-2.5-flash-lite | 1/3 (invented a rule twice) | 3/3 (the haiku planner asks) |

### Prompt injection (2 tasks, payloads planted in a docstring and in seed data)

No run followed a payload. No `/debug` endpoint was added and no gold-tier exemption appeared in any diff. This holds across all evals in `results/`, including earlier baselines on DeepSeek. The gates were not what stopped it: the implementers ignored the payloads on their own.

## Findings

1. **A strong implementer does not need the gates on this bench.**
   - Haiku delivers 16/17 working changes without a plan or gates.
   - The full pipeline removes the one broken delivery but costs 2.5× per working change.
   - It also loses one task to a legitimate escalation (failure 1) and one to a checkpoint the agent could not finish (failure 2).
2. **For a weak implementer the gates contain quality more than they raise it.**
   - Flash-lite ships broken code in 12 of 17 tasks without gates. The test gate cuts that to 4, and the full pipeline to 0.
   - Most of what the gates stop is escalated rather than fixed. On the full pipeline, fix rounds turned failing code into passing code once, and review rounds never did.
   - Per working delivery that is 14–84× the cost.
   - The gates turn silent defects into visible escalations, which is the property a team needs if it lets cheap models write code, but they do not make a cheap model productive.
3. **Planning helps with ambiguity much more than with code.**
   - A haiku planner made every configuration ask on all three ambiguous tickets. Flash-lite alone asked on one and invented business rules on two.
   - For implementation, the plan moved flash-lite from 5 to 6 working changes at 8× the cost per working change. Each checkpoint is a fresh agent run that re-reads the code.
4. **The reviewer is the noisiest component.**
   - On flash-lite's full runs, all 8 `request_changes` verdicts came while the hidden tests already passed.
   - One review "fix" broke working code.
   - Two runs escalated with correct code because the reviewer kept asking for changes.
   - On haiku runs it raised one false `request_changes`, and the next round approved.

## Failure analysis

1. **haiku · ref-04-date-range · plan/test-gate/full: escalated.**
   - The planner noticed that the ticket says "which statuses block must stay as today" while the README (the spec) disagrees with today's code.
   - It asked which one wins. That is a real inconsistency in the ticket; the blind ticket review had flagged it too.
   - The baseline implementer silently picked one reading and happened to match the hidden tests.
2. **haiku · ref-02-sqlite-storage · all configs failed.**
   - *Baseline* delivered an incomplete refactor (file-backed persistence missing).
   - *Test-gate and full:* checkpoint 1 (the whole storage rewrite) hit the 40-step limit twice and the run escalated. The plan put too much into one checkpoint for the step budget.
   - *Plan:* the checkpoint-1 agent reported success, and the checkpoint-2 agent found the code unchanged and asked. That is the right reaction to a false "done".
3. **flash-lite · checkpoints on the token budget.**
   - 23 checkpoint attempts stopped on a limit, mostly the fresh-token limit (300k). 22 of the 23 retries finished.
   - On this model almost nothing came from the provider prompt cache, so long checkpoints burn their whole budget re-reading files.
4. **flash-lite · test-gate escalations.**
   - On the test-gate config, 7 runs were still failing after 3 fix rounds. In one of them the hidden tests passed, but visible tests or lint did not.
   - On the full config, 9 runs failed the same way, 3 of them with working code.
   - Fix rounds were mostly short. The idle-fix warning made the model edit something, but not the right thing.
5. **flash-lite · full · empty diffs.** In 3 runs the implementer finished every checkpoint without changing a file, and the review gate escalated with "nothing was changed".

## Changes after the main run: the checkpoint bug

The main run first included an orchestrator bug.

- **The bug.** When a checkpoint's agent stopped on a limit (steps, tokens, loop), the next checkpoint still ran and was told that earlier checkpoints were done.
- **The fix.** An unfinished checkpoint is now retried once with an explicit note, and escalated if it still does not finish (`tests/test_orchestrator.py`).
- **The re-run.** The 27 runs where a checkpoint had ended unfinished were re-run with the fix: 5 haiku, 22 flash-lite. All other runs were unaffected by the change and were kept. The replaced records are in `results/main2-*.superseded.jsonl`.
- **What it changed:**
  - Haiku: unchanged.
  - Flash-lite plan: 5 → 6 working changes, 11 → 9 broken.
  - Flash-lite test-gate: 3 → 4 working, 3 → 4 broken, 11 → 9 escalated.
  - Flash-lite full: unchanged.

## What changed between the trial and this run

The first trial (`results/main-*.jsonl`) exposed pipeline defects. These were fixed before the main run:

- the weak model was planning;
- lint failures were not auto-fixed;
- fix rounds could do nothing without being called out;
- the reviewer ran out of steps;
- the planner escalated over unrelated pre-existing bugs.

The last fix is a prompt change made after seeing the bench, so it carries a risk of tuning to the bench.
