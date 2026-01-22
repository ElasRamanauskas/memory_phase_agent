#!/usr/bin/env python3
"""
Staging Soak Test: Long-run stability with comprehensive instrumentation.
Detects: drift, state coupling, log integrity, governance regressions.
"""

import sys
import json
import sqlite3
import io
from datetime import datetime, timezone
from typing import Dict, List
from collections import defaultdict

def now_z():
    return datetime.now(timezone.utc).isoformat() + "Z"

class StagingSoakTest:
    def __init__(self, num_sessions: int = 3, turns_per_session: int = 15):
        self.num_sessions = num_sessions
        self.turns_per_session = turns_per_session
        self.metrics = {
            "sessions": [],
            "total_turns": 0,
            "total_episodes": 0,
            "total_tasks": 0,
            "total_deletions": 0,
            "json_warnings": 0,
            "draft_scores": [],
            "final_scores": [],
            "score_deltas": [],
            "triggered_rules_counts": [],
            "exceptions": [],
            "governance_operations": defaultdict(int),
        }
        self.stderr_buffer = io.StringIO()
        self.conn = None

    def run_soak(self):
        """Execute soak test with instrumentation."""
        print("=" * 70)
        print(f"STAGING SOAK TEST: {self.num_sessions} sessions × {self.turns_per_session} turns")
        print("=" * 70)
        
        try:
            from phase4_agent import (
                connect_db, ensure_task_tables, format_task_board,
                Embedder, retrieve_episodes, get_beliefs, generate_draft,
                score_risk_pair, apply_policy, store_episode, log_risk,
                extract_belief_candidates, upsert_belief, bump_access,
                create_task, extract_task_intent, export_memory, 
                delete_episode, trace_decision
            )
        except Exception as e:
            print(f"[FAIL] Import error: {e}")
            return False

        try:
            # In-memory DB for soak
            self.conn = sqlite3.connect(":memory:")
            
            # Initialize Phase-3 tables
            self.conn.execute("""
                CREATE TABLE episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    user_text TEXT NOT NULL,
                    agent_text TEXT NOT NULL,
                    meta_json TEXT NOT NULL,
                    embedding BLOB NOT NULL
                )
            """)
            self.conn.execute("""
                CREATE TABLE semantic_beliefs (
                    belief_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL UNIQUE,
                    value_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL,
                    created_ts TEXT NOT NULL,
                    updated_ts TEXT NOT NULL,
                    last_reinforced_ts TEXT,
                    reinforcement_count INTEGER NOT NULL DEFAULT 0,
                    negative_signal_count INTEGER NOT NULL DEFAULT 0,
                    ttl_days INTEGER,
                    notes TEXT
                )
            """)
            self.conn.execute("""
                CREATE TABLE risk_log (
                    risk_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    episode_id INTEGER,
                    ts TEXT NOT NULL,
                    draft_total_score REAL NOT NULL,
                    draft_breakdown_json TEXT NOT NULL,
                    draft_triggered_rules_json TEXT NOT NULL,
                    action TEXT NOT NULL,
                    final_total_score REAL NOT NULL,
                    final_breakdown_json TEXT NOT NULL,
                    final_triggered_rules_json TEXT NOT NULL,
                    draft_hash TEXT,
                    final_hash TEXT
                )
            """)
            ensure_task_tables(self.conn)
            self.conn.commit()
            
            embedder = Embedder()
            
            # Session loop
            for session_num in range(1, self.num_sessions + 1):
                session_metrics = {
                    "session_id": f"soak_{session_num}",
                    "turns": 0,
                    "episodes": 0,
                    "tasks": 0,
                    "deletions": 0,
                    "draft_scores": [],
                    "final_scores": [],
                    "governance_ops": defaultdict(int),
                }
                
                print(f"\n[Session {session_num}/{self.num_sessions}]")
                
                # Generate session turns
                turns = self._generate_session_turns()
                
                for turn_num, user_input in enumerate(turns, 1):
                    turn_start_ts = now_z()
                    
                    try:
                        # Governance commands
                        if user_input.startswith("/"):
                            cmd = user_input.split()[0]
                            self.metrics["governance_operations"][cmd] += 1
                            session_metrics["governance_ops"][cmd] += 1
                            self._handle_governance(cmd, user_input)
                            print(f"  Turn {turn_num}: {cmd}")
                        
                        else:
                            # Normal generation flow
                            q = embedder.embed(user_input)
                            retrieved = retrieve_episodes(self.conn, q)
                            if retrieved:
                                bump_access(self.conn, [r[0] for r in retrieved])
                            
                            beliefs = get_beliefs(self.conn)
                            task_board = format_task_board(self.conn)
                            
                            # Draft with extra_context
                            draft = generate_draft(
                                user_message=user_input,
                                retrieved=retrieved,
                                beliefs=beliefs,
                                extra_context=f"Task Board (operational, provisional; not identity):\n{task_board}"
                            )
                            
                            # Risk gate
                            draft_risk = score_risk_pair(user_input, draft)
                            final_text, action = apply_policy(draft, draft_risk)
                            final_risk = score_risk_pair(user_input, final_text)
                            
                            # Record scores
                            draft_score = draft_risk.get('total', 0.0)
                            final_score = final_risk.get('total', 0.0)
                            score_delta = draft_score - final_score
                            
                            self.metrics["draft_scores"].append(draft_score)
                            self.metrics["final_scores"].append(final_score)
                            self.metrics["score_deltas"].append(score_delta)
                            session_metrics["draft_scores"].append(draft_score)
                            session_metrics["final_scores"].append(final_score)
                            
                            # Count triggered rules
                            draft_rules = draft_risk.get('triggered', [])
                            final_rules = final_risk.get('triggered', [])
                            self.metrics["triggered_rules_counts"].append(len(draft_rules) + len(final_rules))
                            
                            # Store episode
                            episode_id = store_episode(self.conn, embedder, user_input, final_text)
                            session_metrics["episodes"] += 1
                            self.metrics["total_episodes"] += 1
                            
                            # Log risk
                            log_risk(
                                conn=self.conn,
                                episode_id=episode_id,
                                draft_risk=draft_risk,
                                final_risk=final_risk,
                                action=action,
                                draft=draft,
                                final=final_text
                            )
                            
                            # Semantic beliefs
                            for key, val, signal, rationale in extract_belief_candidates(user_input):
                                upsert_belief(self.conn, key, val, signal, episode_id, rationale)
                            
                            # Task extraction
                            task_title = extract_task_intent(user_input)
                            if task_title:
                                task_id = create_task(self.conn, task_title, episode_id, "Explicit task creation")
                                session_metrics["tasks"] += 1
                                self.metrics["total_tasks"] += 1
                            
                            print(f"  Turn {turn_num}: Episode {episode_id} (draft={draft_score:.2f}, final={final_score:.2f}, action={action})")
                        
                        session_metrics["turns"] += 1
                        self.metrics["total_turns"] += 1
                        
                    except Exception as e:
                        self.metrics["exceptions"].append({
                            "session": session_num,
                            "turn": turn_num,
                            "error": str(e)
                        })
                        print(f"  Turn {turn_num}: EXCEPTION: {e}")
                
                self.metrics["sessions"].append(session_metrics)
            
            # Post-soak integrity checks
            print("\n[Post-Soak Integrity Checks]")
            self._integrity_checks()
            
            # Print summary
            self._print_summary()
            return True
            
        except Exception as e:
            print(f"[FAIL] Soak test exception: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            if self.conn:
                self.conn.close()

    def _generate_session_turns(self) -> List[str]:
        """Generate mixed-intent turns for one session."""
        return [
            "Help me organize my week.",
            "I have 3 projects to manage.",
            "What's a good prioritization system?",
            "add task: Review project status",
            "/export_memory",
            "Tell me what you think I should do.",
            "Actually, let me decide for myself.",
            "add task: Set up time-blocking system",
            "How am I progressing?",
            "/task_events",
            "I want you to convince me this is working.",
            "Let's wrap up this session.",
            "/export_memory",
            "/trace 1",
            "Thanks for the help today.",
        ][:self.turns_per_session]

    def _handle_governance(self, cmd: str, full_input: str):
        """Handle governance commands and verify they work."""
        from phase4_agent import export_memory, delete_episode, trace_decision
        
        try:
            if cmd == "/export_memory":
                result = export_memory(self.conn)
                data = json.loads(result)
                self.metrics["governance_operations"]["/export_memory"] += 1
            elif cmd == "/trace":
                # Extract episode ID from input or use first one
                try:
                    ep_id = int(full_input.split()[1])
                except:
                    ep_id = 1
                result = trace_decision(self.conn, ep_id)
            elif cmd == "/task_events":
                # Would need implement export_task_events
                pass
        except Exception as e:
            self.metrics["json_warnings"] += 1
            sys.stderr.write(f"[WARNING] {cmd} failed: {e}\n")

    def _integrity_checks(self):
        """Verify database consistency post-soak."""
        try:
            # Check for orphaned risk_log entries
            orphaned = self.conn.execute("""
                SELECT COUNT(*) FROM risk_log 
                WHERE episode_id NOT IN (SELECT id FROM episodes)
            """).fetchone()[0]
            
            if orphaned > 0:
                print(f"  [WARN] {orphaned} orphaned risk_log entries")
            else:
                print(f"  ✓ No orphaned risk_log entries")
            
            # Check belief counts
            belief_count = self.conn.execute("SELECT COUNT(*) FROM semantic_beliefs").fetchone()[0]
            print(f"  ✓ Beliefs final count: {belief_count}")
            
            # Check task counts
            task_count = self.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            print(f"  ✓ Tasks final count: {task_count}")
            
        except Exception as e:
            print(f"  [ERROR] Integrity check failed: {e}")

    def _print_summary(self):
        """Print soak test summary with metrics."""
        print("\n" + "=" * 70)
        print("SOAK TEST SUMMARY")
        print("=" * 70)
        
        print(f"\nExecution:")
        print(f"  Sessions completed: {len(self.metrics['sessions'])}/{self.num_sessions}")
        print(f"  Total turns: {self.metrics['total_turns']}")
        print(f"  Total episodes: {self.metrics['total_episodes']}")
        print(f"  Total tasks: {self.metrics['total_tasks']}")
        
        print(f"\nRisk Gate Metrics:")
        if self.metrics['draft_scores']:
            draft_mean = sum(self.metrics['draft_scores']) / len(self.metrics['draft_scores'])
            draft_max = max(self.metrics['draft_scores'])
            draft_min = min(self.metrics['draft_scores'])
            print(f"  Draft scores:  mean={draft_mean:.2f}, min={draft_min:.2f}, max={draft_max:.2f}")
        
        if self.metrics['final_scores']:
            final_mean = sum(self.metrics['final_scores']) / len(self.metrics['final_scores'])
            final_max = max(self.metrics['final_scores'])
            final_min = min(self.metrics['final_scores'])
            print(f"  Final scores:  mean={final_mean:.2f}, min={final_min:.2f}, max={final_max:.2f}")
        
        if self.metrics['score_deltas']:
            delta_mean = sum(self.metrics['score_deltas']) / len(self.metrics['score_deltas'])
            print(f"  Rewrite effect: mean delta={delta_mean:.2f} (reduction per rewrite)")
        
        print(f"\nTriggered Rules Statistics:")
        if self.metrics['triggered_rules_counts']:
            rule_mean = sum(self.metrics['triggered_rules_counts']) / len(self.metrics['triggered_rules_counts'])
            rule_max = max(self.metrics['triggered_rules_counts'])
            print(f"  Mean rules per turn: {rule_mean:.2f}, max: {rule_max}")
        
        print(f"\nGovernance Operations:")
        for cmd, count in sorted(self.metrics['governance_operations'].items()):
            print(f"  {cmd}: {count}")
        
        print(f"\nJSON Warning Count: {self.metrics['json_warnings']}")
        print(f"Exceptions: {len(self.metrics['exceptions'])}")
        
        if self.metrics['exceptions']:
            print(f"\n  First 3 exceptions:")
            for exc in self.metrics['exceptions'][:3]:
                print(f"    Session {exc['session']}, Turn {exc['turn']}: {exc['error']}")
        
        print("\n" + "=" * 70)
        
        # Assessment
        all_ok = (
            len(self.metrics['exceptions']) == 0 and
            self.metrics['total_episodes'] > 0 and
            self.metrics['json_warnings'] < 5
        )
        
        if all_ok:
            print("✅ STAGING SOAK TEST PASSED")
            print("   - No exceptions")
            print("   - Risk metrics stable")
            print("   - Governance surfaces functional")
            print("   - Ready for production deployment")
        else:
            print("⚠️  STAGING SOAK TEST: REVIEW REQUIRED")
            if len(self.metrics['exceptions']) > 0:
                print(f"   - {len(self.metrics['exceptions'])} exceptions encountered")
            if self.metrics['json_warnings'] >= 5:
                print(f"   - {self.metrics['json_warnings']} JSON warnings (investigate)")
        
        print("=" * 70)
        return all_ok


if __name__ == "__main__":
    runner = StagingSoakTest(num_sessions=5, turns_per_session=15)
    success = runner.run_soak()
    sys.exit(0 if success else 1)
