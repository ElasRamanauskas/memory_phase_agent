# Memory-Integrated, Risk-Gated Language Agents
Continuity Without Identity or Coercive Influence

## Abstract
- Memory-augmented language agents are necessary for continuity but introduce risks of identity formation, preference lock-in, and coercive influence.
- We present a reference architecture that decouples memory layers and enforces deterministic risk gating prior to long-term writeback.
- The system supports episodic recall, bounded semantic abstraction, and task persistence without modeling user identity.
- Evaluation across regression suites, soak tests, and threat scenarios demonstrates continuity and usability without subject formation or dependency.
- The results suggest that identity-like behavior is an architectural artifact, not a requirement for memory-enabled agents.

## Introduction
- Motivation: why stateless agents fail for long-running work.
- Problem statement: why memory + language tends to produce identity and influence.
- Observation: most deployed systems treat these effects as features, not failures.
- Contribution: a governed memory architecture that treats identity and coercion as failure modes.

## Failure Modes 
- Identity hardening through semantic abstraction.
- Preference lock-in via reinforcement without decay.
- Strategic behavior driven by self-consistency pressure.
- Dependency formation via task continuity and accountability framing.
- Loss of user agency due to opaque memory and lack of deletion.

## Constitution
- Constitutional Constraints and Design Principles
- Memory is functional, not identity.
- Forgetting is a stability requirement.
- Explicit signals dominate inferred intent.
- Consistency is not truth.
- Influence must be bounded, detectable, and reversible.
- User governance is mandatory, not optional.

## System Architecture
- Overview of the execution pipeline.
- Separation of: episodic memory, semantic memory, task memory.
- Placement and role of the risk gate.
- Writeback discipline and audit logging.
- Reference to frozen release v1.0-governed-memory.

## Episodic Memory: Continuity Without Abstraction
- Storage of interaction traces as events.
- Retrieval via similarity and decay-weighted strength.
- Absence of generalization or trait inference.
- Effects on conversational continuity.
- Forgetting behavior and access bumping.

## Semantic Memory: Bounded Abstraction Without User Modeling
- Namespace-gated belief representation.
- Explicit-only extraction and reinforcement rules
- Decay, contestation, and deprecation mechanisms.
- Evidence linking to episodic memory.
- Prevention of identity and personality modeling.

## Task Memory: Persistent Work State Without Coercion
- Rationale for separating task state from semantic beliefs.
- Explicit-only task creation and updates.
- Task lifecycle and audit trail.
- Absence of reminders, nudging, or accountability enforcement.
- Interaction between task suggestions and risk gating.

## Manipulation and Influence Risk Gating
- Deterministic risk scoring dimensions.
- Pair scoring: incorporating user intent and assistant draft.
- Policy actions: NONE, SOFT_REWRITE, HARD_REWRITE, BLOCK.
- Rewrite post-conditions and escalation logic.
- Why deterministic enforcement is preferred over LLM-only judgment.

## Governance and User Control Surfaces
- Memory inspection and export.
- Deletion and reset semantics.
- Traceability of outputs to memory and risk decisions.
- Task event auditing.
- Governance as a prerequisite for deployment.

## Evaluation
- Regression Test Suites: Phase-3 suite: classification accuracy, false positives, rewrite behavior. Phase-4 suite: explicit-only task policy and dependency detection.
- Long-Run Soak Testing: Mixed-intent, multi-session simulations. Drift detection criteria. Observed stability over time.
- Threat Model Validation: Six critical threat vectors. Mapping detection → enforcement → audit → user control. Verification that threats are blocked or contained.

## Counterfactual Analysis
- Removing namespace gating → identity belief accretion.
- Removing explicit-only task policy → covert nudging.
- Removing rewrite re-scoring → ineffective safety theater.
- Moving risk gate after writeback → unsafe memory contamination.
- Removing deletion/trace controls → loss of user agency.

## Limitations
- No autonomous planning or proactive behavior.
- No affective or emotional modeling.
- Conservative behavior under uncertainty.
- Deterministic scoring limits nuance.
- Single-agent, single-user scope.

## Implications
- Identity is not required for continuity.
- Safety properties can be architectural, not behavioral.
- User agency requires contestability, not alignment rhetoric.
- Memory governance should be first-class in deployment discussions.
