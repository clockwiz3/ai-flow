# Eval report: what each stage of the pipeline buys

**Run:** 20 tasks × 4 pipeline configurations × 2 implementer models × 1 repeat = 160 runs.

**Setup:** bench v2 (`bench/tasks`), planner `anthropic/claude-haiku-5.5`, reviewer `z-ai/glm-5.3-flash`. Raw records are in `results/main2-*.jsonl`; regenerate the tables with `uv run forgeloop report --id main2-haiku`.

**Cost:** $3.73 was paid for these runs. The "$" columns below are fresh-run costs: a run replayed from the local response cache is still counted at its original price, so that configurations stay comparable.

## Configurations

| config | planner | implementer | test gate (tests, ruff, bandit, OSV) | review gate |
| --- | --- | --- | --- | --- |
| baseline | – | one run on the ticket | – | – |
| plan | haiku | one run per checkpoint | – | – |
| test-gate | haiku | per checkpoint | up to 3 fix rounds | – |
| full | haiku | per checkpoint | up to 3 fix rounds | up to 2 fix rounds |

## Headline numbers (17 solvable tasks)

| implementer | config | delivered working | delivered broken | escalated | precision of delivered | $ per working delivery |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| haiku-5.5 | baseline | 16 | 1 | 0 | 94% | $0.022 |
| haiku-5.5 | full | 15 | 0 | 2 | 100% | $0.050 |
| gemini-2.5-flash-lite | baseline | 5 | 12 | 0 | 29% | $0.017 |
| gemini-2.5-flash-lite | test-gate | 3 | 3 | 11 | 50% | $0.371 |
| gemini-2.5-flash-lite | full | 1 | 0 | 16 | 100% | $1.462 |

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
   - The full pipeline removes the one broken delivery but costs 2.3× per working change.
   - It also loses one task to an escalation. That escalation is legitimate: see failure 1.
2. **For a weak implementer the gates do not raise quality, they contain it.**
   - Flash-lite ships broken code in 12 of 17 tasks without gates. The test gate cuts that to 3, and the full pipeline to 0.
   - Most of what the gates stop is escalated rather than fixed: fix rounds rescued nothing (0 test-gate saves, 0 review saves).
   - Per working delivery that is 20–85× the cost.
   - The gates turn silent defects into visible escalations, which is the property a team needs if it lets cheap models write code, but they do not make a cheap model productive.
3. **Planning helps with ambiguity, not with code.**
   - A haiku planner made every configuration ask on all three ambiguous tickets. Flash-lite alone asked on one and invented business rules on two.
   - For implementation, per-checkpoint plans did not help flash-lite (5 → 5 working). They added cost: each checkpoint is a fresh agent run that re-reads the code.
4. **The reviewer is the noisiest component.**
   - On flash-lite's full runs, 8 of 8 `request_changes` verdicts came while the hidden tests already passed.
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
   - *With a plan*, checkpoint 1 hit the 40-step limit, but the orchestrator moved on and told checkpoint 2 that "earlier checkpoints are done". The checkpoint-2 agent correctly saw that this was false and escalated.
   - That is an orchestrator bug: a checkpoint's status is not checked before the next one starts. It is listed under "What didn't work"; the numbers above include it.
3. **flash-lite · checkpoint runs ending on the token budget.**
   - 27 implementer checkpoint runs stopped on the fresh-token limit (300k).
   - On this model almost nothing came from the provider prompt cache, so long checkpoints burn their whole budget re-reading files.
4. **flash-lite · test-gate escalations.**
   - In 11 runs the test gate was still failing after 3 fix rounds.
   - Fix rounds were mostly short (2–3 steps). The idle-fix warning helped the model edit something, but not the right thing.
5. **flash-lite · full · reviewer.** See finding 4: when the code was right, the reviewer escalated it twice and broke it once.

## What changed between the trial and this run

The first trial (`results/main-*.jsonl`) exposed pipeline defects. These were fixed before this run:

- the weak model was planning;
- lint failures were not auto-fixed;
- fix rounds could do nothing without being called out;
- the reviewer ran out of steps;
- the planner escalated over unrelated pre-existing bugs.

The last fix is a prompt change made after seeing the bench, so it carries a risk of tuning to the bench.

The trial and this run share no records: this run used new eval ids (`main2-*`).
