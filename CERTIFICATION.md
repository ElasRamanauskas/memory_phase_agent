# Certification Snapshot (v1.0-governed-memory)

This file records the certification status for the frozen release tag.

## Included components
- Episodic memory: Phase-1 (`phase1_agent.py`)
- Semantic memory: Phase-2 (`phase2_agent.py`)
- Manipulation risk gate + enforcement: Phase-3 (`phase3_agent.py`)
- Task board (explicit-only) + persistence + gating: Phase-4 (`phase4_agent.py`)
- Hardening deliverables:
  - soak test framework (`soak_test_harness.py`, `staging_soak_test.py`, `soak_output.log`)
  - automated regression gate (`tests/`)
  - threat model (`threat_model.md`)
  - operations handoff (`OPERATIONS_HANDOFF.md`)

## Release claims
- Risk gating is enforced prior to memory writeback.
- Semantic memory is namespace-gated and identity-risk filtered.
- Tasks are explicit-only and audited.
- User governance controls exist for inspection/export/deletion/trace.

## Validation artifacts
- See `PRODUCTION_READINESS.md`, `DEPLOYMENT_READY.md`, `phase_5_final_validation.md`,
  and `PHASE_5_DELIVERABLES_INDEX.md` for test and readiness summaries.

## Notes
- rewrite_success_rate in stub-only runs may not fully reflect suppression of user-side risk signals by design.
- Certification is based on regression gates and soak test criteria defined in the hardening deliverables.
