# Change Policy (v1.0-governed-memory)

This project treats governed memory and risk enforcement as safety-critical.

## Patch/Minor Changes (allowed without major version bump)
- documentation edits (no change to meaning of constitution or guarantees)
- test additions that do not relax acceptance criteria
- refactors that preserve behavior (verified by regression gates)
- performance improvements that do not alter scoring, thresholds, or memory policy

## Major Changes (require a major version bump)
- changes to memory schemas (episodes/semantic/tasks/risk logs)
- changes to risk scoring dimensions, triggers, thresholds, or hard overrides
- changes to rewrite enforcement logic or acceptance conditions
- changes to explicit-only policies (beliefs/tasks)
- any addition of autonomous planning, reminders, or proactive engagement behavior
- any expansion of semantic belief scope beyond current namespaces

## Forbidden Changes (incompatible with v1.0 constitution)
- storing user traits, psychological labels, or identity claims as semantic beliefs
- adding engagement optimization (retention prompts, dependency cultivation)
- removing auditability or user governance controls
