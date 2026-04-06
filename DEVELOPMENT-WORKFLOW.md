# Development Workflow — AI Agent Instructions

This document defines how AI dev agents pick up, execute, and hand off work on the Golteris project. Every agent session must follow this workflow exactly.

For requirements, constraints, and tech stack: see [REQUIREMENTS.md](REQUIREMENTS.md).

---

## Project Board Status Flow

Issues move through these statuses on the [GitHub Project board](https://github.com/users/cg0296/projects/2):

```
Todo → Agent Work → Testing → Human Work → Done
```

| Status | Meaning |
|---|---|
| **Todo** | Queued. Not ready for agent work. A human moves it to Agent Work when it's prioritized. |
| **Agent Work** | **Dev agents pick up work here.** The human has approved this issue for development. |
| **Testing** | Dev agent is finished. **Testing agent picks up work here** — verifies against acceptance criteria, cross-cutting constraints, and code quality. See [TESTING-WORKFLOW.md](TESTING-WORKFLOW.md). |
| **Human Work** | Requires human action — either because testing failed and the human needs to decide next steps, or because the task itself requires human work (manual config, deployment, external account setup, etc.). Not for agents. |
| **Done** | Testing agent verified and passed. Complete. |

---

## Before You Start

### 1. Find your work

- Read the project board. **Only pick up issues in `Agent Work` status.**
- Never start work on issues in `Todo`, `Human Work`, `Testing`, or `Done`.
- If no issues are in `Agent Work`, stop and tell the human. Do not invent work.

### 2. Read the requirements

- Read [REQUIREMENTS.md](REQUIREMENTS.md) — especially §2 (Tech Stack), §3 (AI Dev Rules), and §5 (Cross-Cutting Constraints C1–C7).
- Read the issue body on GitHub. Understand the Goal, Scope, and Acceptance Criteria.
- Read any files referenced in the issue's Scope section.

### 3. Post your plan as a comment

Before writing any code, **add a comment to the GitHub issue** with:

```markdown
## Agent Starting Work

**Reasoning:** Why I'm picking up this issue now (e.g., dependencies are met, it's in Agent Work, it's the highest-priority item).

**Plan:**
1. [Step-by-step description of what you will do]
2. [Which files you will create or modify]
3. [Which existing patterns or utilities you will reuse]
4. [How you will verify the acceptance criteria]

**Dependencies:** [List any issues that must be complete first, or "None"]
```

This comment serves two purposes:
- The human can review your plan before you proceed (if they're watching).
- Future agents can understand what was intended if they need to pick up where you left off.

---

## While You Work

- Follow all rules in [REQUIREMENTS.md](REQUIREMENTS.md) §3 (AI Dev Rules) — especially:
  - §3.6 Code commenting standard (detailed comments on every file, function, and non-trivial block)
  - §3.7 Guardrails (no secrets, no weakening C1–C7, no bypassing HITL)
- One issue per branch: `git checkout -b issue-<number>-<short-description>`
- Every commit message references the issue: `#<number>`
- If you hit a blocker or need a decision from the human, stop and say so. Do not guess.

---

## After You Finish Coding — Self-Test First

### 0. Run the testing workflow yourself before anything else

**Do not post your completion comment or move to Testing until you have tested your own work.** This is a hard rule — it prevents broken code from reaching the testing agent or the human.

Follow the steps in [TESTING-WORKFLOW.md](TESTING-WORKFLOW.md) as if you were the testing agent:

1. **Run the acceptance criteria checks** — execute every command, visit every URL, run every test from the issue's acceptance criteria. Record what happened.
2. **Verify cross-cutting constraints** — check the relevant constraints from REQUIREMENTS.md §5 (C1–C7) against your code. Did you accidentally bypass HITL? Did you expose agent jargon in the UI? Are LLM calls logged?
3. **Check your own comments** — does every file have a top-level docstring? Does every function have a docstring? Are complex blocks explained inline? (§3.6)
4. **Run automated tests** — `pytest` for backend, `vitest` for frontend. All tests must pass.
5. **Fix anything that fails** — if you find bugs, fix them and commit the fixes before proceeding.

**Include the actual test results in your completion comment** (not just "I tested it" — show the commands you ran and the output you got). This proves to the testing agent and the human that the code was verified before handoff.

---

### 1. Post your completion comment

Add a second comment to the GitHub issue with:

```markdown
## Agent Work Complete

**What I did:**
- [Bullet list of what was implemented, created, or changed]
- [Files created or modified, with brief descriptions]

**Self-test results (ran before posting):**
- `[command I ran]` → [actual output, truncated if long]
- `[another command]` → [actual output]
- Cross-cutting constraints checked: [which ones, what I verified]
- Code quality: [confirmed comments per §3.6, no secrets, tech stack compliance]

**How to test (for human reviewer):**
1. [Step-by-step instructions a human can follow to verify the work]
2. [Include exact commands to run, URLs to visit, or UI paths to click]
3. [Describe what the expected result looks like]
4. [If applicable: "Run `pytest tests/path/to/test.py` — all tests should pass"]

**Acceptance criteria status:**
- [x] [Criterion 1 from the issue — met because ...]
- [x] [Criterion 2 from the issue — met because ...]
- [ ] [Criterion 3 — NOT met, reason: ...]

**PR:** #<pr-number> (if a PR was created)
```

### 2. Move the issue to Testing

After posting the completion comment, **move the issue status from `Agent Work` to `Testing`** on the project board.

### 3. Create a PR

- Push your branch and open a PR referencing the issue (`Closes #<number>`).
- The PR description should summarize the changes — but the detailed testing instructions live in the issue comment, not the PR.
- **Do not merge.** The human reviews and merges.

---

## Rules Summary

| Rule | Why |
|---|---|
| Only pick up `Agent Work` issues | Human controls what gets built and when (C1, C7) |
| Post a plan comment before coding | Human can course-correct before effort is wasted; future agents have context |
| **Self-test before posting completion** | **Catch bugs before they reach the testing agent or human — show actual test output** |
| Post a completion comment with test instructions | Human can verify without reading every line of code; keeps Testing status meaningful |
| Move to `Testing` when done | Human knows exactly what's waiting for their review |
| Never merge your own PR | Human approval required on every merge (C7) |
| One issue per branch | Small blast radius, easy to review and revert |
| Reference issue number in every commit | Traceability stays live automatically |

---

## Example: Full Lifecycle

**Issue #24: Build RFQ extraction agent**

1. Agent sees #24 is in `Agent Work` status.
2. Agent reads REQUIREMENTS.md and the issue body.
3. Agent posts a comment:
   > **Reasoning:** #24 is in Agent Work. Dependencies #11 (schema) and #20 (LLM API credentials) are Done. This is the core extraction agent.
   >
   > **Plan:**
   > 1. Create `backend/agents/extraction.py` with LLM tool-use schema for RFQ fields.
   > 2. Add confidence scoring per field (threshold 0.90 per §5 C2, FR-AG-2).
   > 3. Write to `rfqs` table and `agent_calls` table.
   > 4. Add 5 test cases using seed emails from `seed/beltmann/`.
   > 5. Verify with `pytest tests/agents/test_extraction.py`.

4. Agent creates branch `issue-24-extraction-agent`, writes code, commits.
5. Agent posts a completion comment:
   > **What I did:**
   > - Created `backend/agents/extraction.py` — LLM tool-use extraction with 10-field schema
   > - Created `tests/agents/test_extraction.py` — 5 test cases against seed emails
   > - Updated `db/migrations/0004_agent_calls.py` — added agent_calls table
   >
   > **How to test:**
   > 1. `cd backend && pytest tests/agents/test_extraction.py -v` — all 5 tests pass
   > 2. To test manually: `python -m agents.extraction seed/beltmann/email_01.json` — prints extracted fields with confidence scores
   > 3. Check Postgres: `SELECT * FROM rfqs ORDER BY created_at DESC LIMIT 1;` — should show extracted fields
   >
   > **Acceptance criteria:**
   > - [x] Extracts from 5 sample Beltmann-style emails correctly
   > - [x] Handles messy formatting
   > - [x] Flags low-confidence fields
   > - [x] Run duration and cost visible in agent_calls table

6. Agent moves #24 from `Agent Work` → `Testing`.
7. Agent opens PR: `Closes #24 — Build RFQ extraction agent`.
8. Human reviews, tests, merges (or sends back with feedback).
