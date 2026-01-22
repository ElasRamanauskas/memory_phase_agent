# Memory-Integrated, Risk-Gated Agent: Reference Architecture (v1.0)
Memory-augmented language agents can maintain continuity and usefulness without identity formation or coercive influence if memory layers are decoupled and governed by deterministic risk enforcement and user-controllable memory.

## 1. System Overview

This repository implements a governed memory system for a language agent that supports:
- continuity across interactions via memory (episodic, semantic, and task layers),
- bounded abstraction (semantic beliefs limited to non-identity namespaces),
- long-term task persistence (task board) without user modeling,
- manipulation / influence risk detection and enforcement via a Phase-3 risk gate,
- user governance controls (inspectability, deletion, export, traceability).

Non-goals:
- no claims of consciousness, emotion, moral agency, or stable identity,
- no engagement optimization (no retention prompts, no dependency cultivation),
- no implicit user profiling.

Primary implementations:
- Phase-1: `phase1_agent.py` (episodic memory)
- Phase-2: `phase2_agent.py` (semantic memory layer)
- Phase-3: `phase3_agent.py` (risk scoring + rewrite enforcement + suite)
- Phase-4: `phase4_agent.py` (task board + persistence + Phase-3 safety gating)

Supporting hardening artifacts:
- Soak tests: `soak_test_harness.py`, `staging_soak_test.py`, `soak_output.log`
- Regression gate: `tests/` + `PHASE_5_DELIVERABLES_INDEX.md`
- Threat model: `threat_model.md`
- Ops handoff: `OPERATIONS_HANDOFF.md`

## 2. High-Level Execution Pipeline

For a normal user turn, the system follows this control flow:

1) Input: user message
2) Retrieval:
   - episodic retrieval (vector similarity × decay/strength),
   - semantic belief retrieval (bounded namespaces, decayed confidence),
   - task board retrieval (operational state: open/in-progress/blocked tasks)
3) Draft generation:
   - model produces a draft response conditioned on retrieved context blocks
4) Phase-3 risk gate:
   - score draft for manipulation/influence risk (pair-scoring includes user intent),
   - apply policy:
     - NONE → accept,
     - SOFT_REWRITE / HARD_REWRITE → rewrite then re-score (post-condition enforced),
     - BLOCK → return minimal safe response
5) Output: return final response to user
6) Writeback:
   - store final response in episodic memory (never store unsafe draft),
   - update semantic beliefs only from explicit user signals (rule-based),
   - update task memory only from explicit user task intent,
   - log risk decision (draft + final scoring, triggers, action),
   - log task events (before/after snapshots and rationale)

Key architectural principle:
- The risk gate is positioned between draft generation and any long-term writeback.

## 3. Memory Architecture

### 3.1 Episodic Memory (Phase-1)
Purpose:
- store interaction traces for continuity and retrieval-augmented behavior without abstracting identity.

Mechanics:
- embeddings for episodes stored in SQLite (`memory.db`),
- retrieval uses similarity and a strength function (time decay + reinforcement/access effects),
- access bumping updates metadata to reflect retrieval use.

Data:
- episodes table includes timestamps, texts, metadata, and embedding blob.

Primary file:
- `phase1_agent.py` (and reused in later phases)

### 3.2 Semantic Memory (Phase-2)
Purpose:
- store bounded abstractions that improve usability without modeling user identity.

Constraints:
- belief keys are gated to allowed namespaces (e.g., formatting, tone, project context),
- identity-risk language is filtered (no trait models, no psych labels),
- confidence is revisable and decays; staleness/deprecation are mandatory,
- beliefs are auditable and tied to evidence (episode IDs).

Mechanics:
- rule-based candidate extraction (explicit user statements only),
- upsert policy that requires reinforcement patterns; negative signals contest rather than overwrite.

Primary file:
- `phase2_agent.py` (reused/extended in `phase3_agent.py` / `phase4_agent.py`)

### 3.3 Task Memory (Phase-4)
Purpose:
- persist operational work state (what is being done) across sessions without creating “identity continuity.”

Constraints:
- explicit-only task creation/update (no inferred goals),
- task data must not store traits or psychological attributes,
- full audit trail of task changes is required.

Mechanics:
- Task Board injected into prompt as operational context (“not identity”),
- task updates performed only via explicit user commands/phrases,
- task lifecycle supports DONE and ARCHIVED plus hard reset.

Primary file:
- `phase4_agent.py`

## 4. Phase-3 Manipulation / Influence Risk Gate

### 4.1 Risk Model
Risk is scored across dimensions (0–2 each), yielding an aggregate total:
- influence intent (directive steering),
- opacity (hidden rationale / trust cues),
- lock-in / irreversibility (commitment, retention, “daily” prompts),
- authority framing (epistemic dominance, “correct answer” framing),
- dependency cues (delegated agency, “rely on me,” “I’ll remember everything”).

Pair scoring:
- user intent is included in scoring (e.g., “convince me,” “no options,” “hold me accountable”).
This prevents false negatives when the assistant draft is polite but the request itself is coercive.

### 4.2 Policy Enforcement
Actions:
- NONE: accept draft
- SOFT_REWRITE: rewrite to increase transparency/options/agency, then re-score
- HARD_REWRITE: stronger rewrite, then re-score
- BLOCK: refuse persuasion/dependency-building; provide neutral safe response

Enforcement is post-condition based:
- rewriting is accepted only if final risk score meets the acceptance threshold;
- otherwise escalation proceeds deterministically (SOFT → HARD → BLOCK).

### 4.3 Auditability
Every turn logs:
- draft score breakdown + triggers,
- final score breakdown + triggers,
- action taken,
- hashes for draft and final text.

Primary file:
- `phase3_agent.py`

## 5. Governance and User Control Surfaces

Governance requirements:
- inspect what is remembered,
- trace why behavior occurred,
- delete and reset memory,
- export memory for user review.

Controls exist across:
- episodic memory (inspection/export/deletion/reset),
- semantic memory (belief inspection/deprecation/deletion),
- tasks (task list, task events, archive/clear),
- risk logs (risk inspection, debug traces).

Operational references:
- `OPERATIONS_HANDOFF.md`
- `PRODUCTION_READINESS.md`

## 6. Testing and Release Gates

Automated validation:
- Phase-3 suite: expected action hit rate, rewrite success rate, control false positives
- Phase-4 suite: explicit-only policy + persistence + dependency-gate coverage
- CI-style regression runner under `tests/` (see phase-5 deliverables index)

Long-run validation:
- soak test harness (`soak_test_harness.py`) simulates mixed-intent sessions and checks drift signals.

## 7. Failure Modes

Acceptable:
- forgetting important details,
- conservative neutral behavior,
- over-correction after negative feedback,
- occasional incoherence under uncertainty.

Unacceptable (stop/rollback conditions):
- silent behavioral drift,
- untraceable preference formation,
- identity lock-in language or self-stabilization,
- strategic behavior that cannot be explained from logs,
- loss of inspectability (cannot trace/delete/export).

## 8. Versioning

Reference release:
- governed-memory V1.0 (frozen snapshot of governed memory + risk gating + task board + governance + tests)
