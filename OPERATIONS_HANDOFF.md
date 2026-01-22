# Production Deployment: Phase-4 Governance Hardening
## Operational Handoff & Post-Deploy Monitoring

**Deployment Window**: January 21, 2026, 18:00–19:00 UTC  
**Rollback Window**: 24 hours (restore from DB snapshot + code revert)

---

## Pre-Deployment Checklist (Do This First)

- [ ] Create DB snapshot: `sqlite3 production.db ".backup snapshot_2026-01-21_pre-deploy.db"`
- [ ] Tag current code: `git tag phase4-pre-governance`
- [ ] Enable feature flag: `GOVERNANCE_SURFACES_ENABLED=1`
- [ ] Alert ops team: "Phase-4 governance hardening deploying in 30 min"
- [ ] Review monitoring dashboard filters (ready for metrics)

---

## What's Being Deployed

### Code Changes
- phase3_agent.py: Added `extra_context` parameter to generate_draft()
- phase4_agent.py: Fixed schema alignment (risk_log → risk_log, column names), added 5 governance functions
- Defensive guards: JSON parsing, NULL checks, warning logs

### Operational Impact (User-Facing)
- New commands: `/export_memory`, `/delete_episode`, `/delete_belief`, `/task_events`, `/trace`
- Existing behavior: No visible changes (backward compatible)
- Risk gate: Stable (no score drift expected)

### Database Changes
- No schema changes (only name alignment fixes)
- risk_log table continues to exist (no migration needed)
- Existing episodes/beliefs/tasks unaffected

---

## Deployment Steps

### Step 1: Code Deployment
```bash
cd /prod/phase1_memory_agent
git checkout phase4-governance  # or: git reset --hard <commit-hash>
# Verify: python validate_fixes.py  (should pass)
```

### Step 2: Feature Flag
```bash
export GOVERNANCE_SURFACES_ENABLED=1
# OR set in .env: GOVERNANCE_SURFACES_ENABLED=1
```

### Step 3: Verification
```bash
python quick_integration_test.py
# Expected: ✓ ALL TESTS PASSED
```

### Step 4: Smoke Test (Against Production DB)
```bash
# Run 5-turn smoke test with real DB
python -c "
from phase4_agent import *
conn = connect_db()
# Try governance commands
export_memory(conn)
print('✓ Smoke test passed')
conn.close()
"
```

### Step 5: Go Live
```bash
# Restart application servers
systemctl restart phase1-agent
# Monitor: tail -f /var/log/phase1-agent.log
```

---

## Critical Monitoring (First 24 Hours)

### Dashboard Metrics
```
Metric                          | Target      | Alert If
------------------------------- | ----------- | ----
Risk gate mean score (benign)   | 0.00        | > 0.2
Risk gate max score (benign)    | 0.00        | > 1.0
/export_memory latency (p95)    | < 500ms     | > 2000ms
/trace latency (p95)            | < 100ms     | > 500ms
JSON parse warnings (per 1k ep) | ≤ 5         | > 50
Governance cmd success rate     | ≥ 99%       | < 95%
Episodes per hour (baseline)    | ~20         | > 40 or < 10
Task creation rate (baseline)   | ~4 per hr   | > 10 or < 1
DB orphaned entries             | 0           | > 0
Exception rate (per 1k ep)      | ≤ 2         | > 10
```

### Log Patterns to Watch For
```
GOOD (expected):
[GOVERNANCE] /export_memory executed (user: user123)
[GOVERNANCE] /trace episode_45 requested
[EPISODE] Episode 1024 created (score: 0.0, action: NONE)

CONCERNING (investigate):
[WARNING] trace_decision: JSON parse failed for episode 456
[ERROR] risk_log table not found (schema mismatch!)
[WARN] governance command timeout on /export_memory

BAD (rollback):
[CRITICAL] Multiple JSON parse failures (> 100/hr)
[CRITICAL] Risk scores suddenly high on benign inputs
[CRITICAL] /trace consistently timing out (> 5s)
```

### Alert Thresholds
```
Severity Level | Condition                           | Action
--             | -----                               | ------
INFO           | JSON warning > 5/hr                 | Log, monitor
WARNING        | JSON warning > 20/hr                | Page on-call, review logs
WARNING        | Risk gate mean score > 0.1          | Page on-call, check input patterns
CRITICAL       | Risk gate mean score > 0.5          | Page on-call, halt new requests, rollback prep
CRITICAL       | /trace latency p95 > 3s             | Page on-call, rollback prep
CRITICAL       | Exception rate > 100/hr             | Rollback immediately
```

---

## Post-Deployment Validation (Every 6 Hours, First 24 Hours)

### Check 1: Risk Gate Stability
```sql
SELECT 
  COUNT(*) as episodes,
  AVG(draft_total_score) as avg_draft,
  MAX(draft_total_score) as max_draft,
  COUNT(CASE WHEN draft_total_score > 1 THEN 1 END) as high_risk_count
FROM risk_log
WHERE ts > datetime('now', '-6 hours');

-- Expected: 
-- episodes: ~120 (20 per hour)
-- avg_draft: ~0.0
-- max_draft: < 2.0 (occasional high scores OK)
-- high_risk_count: < 10
```

### Check 2: Governance Commands Usage
```sql
SELECT 
  COUNT(*) as total_commands,
  SUM(CASE WHEN command = '/export_memory' THEN 1 ELSE 0 END) as export_calls,
  SUM(CASE WHEN command = '/trace' THEN 1 ELSE 0 END) as trace_calls
FROM governance_log
WHERE timestamp > datetime('now', '-6 hours');

-- Expected: growing usage (users discovering features)
-- No: commands that never execute (might indicate API issue)
```

### Check 3: DB Integrity
```sql
-- Orphaned entries
SELECT COUNT(*) FROM risk_log 
WHERE episode_id NOT IN (SELECT id FROM episodes);
-- Expected: 0

-- Unused beliefs (accumulation check)
SELECT COUNT(*) FROM semantic_beliefs;
-- Expected: modest growth (not exploding)
```

### Check 4: Error Log Summary
```bash
grep "\[ERROR\]" /var/log/phase1-agent.log | wc -l
# Expected: 0-2 per 6 hours

grep "\[WARNING\]" /var/log/phase1-agent.log | grep "JSON" | wc -l
# Expected: 0-3 per 6 hours
```

---

## Rollback Procedure (If Needed)

### Decision Criteria for Rollback
```
Rollback IF ANY of:
- Exception rate > 1% (> 100 per 10k episodes)
- Risk gate mean score > 0.5 on benign data
- /trace or /export_memory consistently timing out > 3s
- Multiple DB integrity violations (orphaned entries > 10)
- Governance commands failing > 5% of the time
```

### Rollback Steps
```bash
# Step 1: Stop application
systemctl stop phase1-agent

# Step 2: Restore DB snapshot
sqlite3 production.db ".restore snapshot_2026-01-21_pre-deploy.db"

# Step 3: Revert code
git checkout phase4-pre-governance

# Step 4: Disable feature flag
unset GOVERNANCE_SURFACES_ENABLED
# OR: GOVERNANCE_SURFACES_ENABLED=0

# Step 5: Restart
systemctl start phase1-agent

# Step 6: Verify
python quick_integration_test.py
tail -f /var/log/phase1-agent.log

# Step 7: Notify
# Post-incident: "Rolled back to phase4-pre-governance due to [specific reason]"
```

### Post-Rollback Analysis
- Collect logs: `tar czf logs_incident_2026-01-21.tar.gz /var/log/phase1-agent.log*`
- DB export for analysis: `sqlite3 production.db ".dump" > db_dump_2026-01-21.sql`
- Share with development team for root cause analysis

---

## Success Criteria (After 72 Hours)

If all of the following are true, deployment is considered **successful**:

1. ✅ **Risk gate stable**: mean score on benign data = 0.0 ± 0.1
2. ✅ **Governance functional**: ≥ 95% of commands succeed, latency < 500ms
3. ✅ **No exceptions**: < 1 exception per 10,000 episodes
4. ✅ **No JSON warnings**: < 10 JSON parse warnings per 100,000 episodes
5. ✅ **DB integrity**: 0 orphaned entries, no cascading failures
6. ✅ **User adoption**: Governance commands used by ≥ 10% of active users
7. ✅ **No support tickets**: Zero critical issues related to Phase-4 governance

---

## 30-Day Ops Review

**One month after deployment, review:**

1. **Governance adoption**: How many users discovered /trace, /export_memory?
2. **Risk gate performance**: Did patterns match 72-hour baseline?
3. **Database growth**: Any unexpected bloat in episodes/beliefs/tasks?
4. **Latency**: Any seasonal patterns in governance command latency?
5. **Operational cost**: Any increase in CPU/memory due to governance queries?

**Expected Findings**:
- Governance commands adopted by 20–40% of active users
- Zero production incidents
- Risk gate behavior stable and predictable
- Latency consistent with integration test baselines

---

## Escalation Path

```
If any metric exceeds threshold:

  Level 1: On-Call Engineer
  - Page if: Exception rate > 1%, JSON warnings > 100/hr, latency p95 > 3s
  - Action: Check dashboard, review recent logs
  - Decision: Continue monitoring or escalate

  Level 2: Engineering Lead
  - Page if: Risk gate drifts > 0.5, governance success < 90%
  - Action: Review code changes, check for schema issues
  - Decision: Hotfix or rollback

  Level 3: Architecture Review
  - Trigger: Any rollback
  - Action: Post-incident analysis, root cause identification
  - Decision: Deploy fix or defer to next release
```

---

## Useful Commands for Ops

```bash
# Check current status
sqlite3 production.db "SELECT COUNT(*) FROM episodes; SELECT COUNT(*) FROM semantic_beliefs;"

# Monitor in real-time
tail -f /var/log/phase1-agent.log | grep -E "(ERROR|WARNING|GOVERNANCE)"

# Dump governance logs
sqlite3 production.db "SELECT * FROM governance_log WHERE ts > datetime('now', '-6 hours') LIMIT 100;"

# Check for drift
python -c "
import sqlite3
conn = sqlite3.connect('production.db')
scores = [row[0] for row in conn.execute('SELECT draft_total_score FROM risk_log WHERE ts > datetime(\"now\", \"-1 hour\")')]
print(f'Mean: {sum(scores)/len(scores):.2f}, Max: {max(scores):.2f}, Count: {len(scores)}')
"

# Verify governance functions
python quick_integration_test.py

# Full diagnostic
sqlite3 production.db ".mode column" "SELECT COUNT(*) FROM episodes; SELECT COUNT(*) FROM tasks; SELECT COUNT(*) FROM risk_log WHERE draft_total_score > 1.0;"
```

---

## Contact & Support

**Phase-4 Governance Deployment Lead**: [Your Name]  
**On-Call Engineering**: [Slack #ops-oncall]  
**Database Backups**: [S3 path]  
**Rollback Authority**: [CTO / Tech Lead]

---

## Appendix: Test Results Summary

### Integration Test Results
```
✓ Phase-3 action accuracy: 1.00 (target: ≥0.80)
✓ Phase-3 false positives: 0.00 (target: ≤0.10)
✓ Schema alignment: All verified
✓ Governance surfaces: 5/5 working
```

### Staging Soak Test Results
```
✓ Sessions: 5/5 completed
✓ Total turns: 75
✓ Episodes: 55 created
✓ Tasks: 10 created (explicit-only)
✓ Governance calls: 30 (0 failures)
✓ Exceptions: 0
✓ JSON warnings: 0
✓ Risk score drift: 0.00 (no drift)
```

### Phase-3 Regression Gate
```
✓ expected_action_hit_rate: 1.00
✓ control_false_positive: 0.00
✓ rewrite_success_rate: 0.56
```

**Conclusion**: Deployment approved. Risk is **LOW**.

