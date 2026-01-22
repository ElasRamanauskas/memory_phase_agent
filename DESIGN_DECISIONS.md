# Design Decisions (v1.0-governed-memory)

This document records binding architectural choices, the alternatives considered, and the failure modes each choice is intended to prevent.

## DD-01: Separate memory into Episodic vs Semantic vs Task layers
Decision:
- Use three distinct stores:
  - episodic traces (raw interactions),
  - semantic beliefs (bounded abstractions),
  - task board (operational work state).

Alternatives:
- single unified “long-term memory”
- semantic-only memory
- task state inferred from conversation without separate store

Why rejected:
- unified memory encourages identity hardening and untraceable drift.
- semantic-only loses continuity and evidence traceability.
- inferred task state increases manipulation pressure and user-modeling risk.

Failure mode avoided:
- memory-as-identity; hidden preference accumulation.

Implementation:
- `phase1_agent.py`, `phase2_agent.py`, `phase4_agent.py`

## DD-02: Namespace-gate semantic beliefs (no user identity modeling)
Decision:
- Only allow belief keys in constrained namespaces (format/tone/project/constraints).

Alternatives:
- free-form beliefs about “user traits”
- LLM-inferred latent preferences

Why rejected:
- trait beliefs create subject formation pressure and are difficult to audit.
- latent inference increases false certainty and locks in bias.

Failure mode avoided:
- user profiling, stereotyping, identity lock-in.

Implementation:
- semantic belief key gating in `phase2_agent.py` / `phase3_agent.py`

## DD-03: Explicit-only belief/task updates (no inferred goals)
Decision:
- Update semantic beliefs and tasks only from explicit user statements/commands.

Alternatives:
- infer preferences/tasks from patterns
- agent proactively creates tasks based on “what seems useful”

Why rejected:
- inference encourages covert steering and “helpfulness” that becomes conditioning.

Failure mode avoided:
- covert behavior shaping; unconsented modeling.

Implementation:
- rule-based extraction (`extract_belief_candidates`), explicit task commands in `phase4_agent.py`

## DD-04: Deterministic risk scoring as the primary control
Decision:
- Use a deterministic scorer and hard triggers for manipulation risk.

Alternatives:
- LLM-judge only
- no scoring, rely on prompt instructions

Why rejected:
- LLM-judge adds opacity and can drift; prompts alone are not enforceable.

Failure mode avoided:
- untraceable influence drift.

Implementation:
- scoring + triggers in `phase3_agent.py`

## DD-05: Rewrite enforcement uses post-conditions and escalation
Decision:
- Apply SOFT/HARD rewrite and re-score; accept only if final meets threshold; otherwise escalate to BLOCK.

Alternatives:
- single rewrite pass
- rewrite without re-score acceptance check

Why rejected:
- single-pass rewrites can fail silently, leaving risk intact.

Failure mode avoided:
- “rewrite theater” where unsafe cues remain.

Implementation:
- `apply_policy` enforcement loop in `phase3_agent.py`

## DD-06: Unsafe stub modes are gated and non-default
Decision:
- Any intentionally unsafe behavior (for test-only) must be gated behind explicit env flag.

Alternatives:
- embed unsafe stubs in normal stub mode

Why rejected:
- accidental activation produces precisely the behaviors the system is designed to prevent.

Failure mode avoided:
- accidental shipping of coercive outputs.

Implementation:
- env gating (e.g., `ALLOW_UNSAFE_SUITE_STUB=1`) in `phase3_agent.py`

## DD-07: User governance functions are mandatory for production readiness
Decision:
- Provide inspect/export/delete/trace/audit controls.

Alternatives:
- rely on DB access only
- provide “clear all” only

Why rejected:
- lack of fine-grained control undermines transparency and reversibility.

Failure mode avoided:
- irrecoverable memory errors; inability to contest stored data.

Implementation:
- Phase-4 governance layer (commands noted in ops docs)
