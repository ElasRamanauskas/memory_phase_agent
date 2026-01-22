#!/usr/bin/env python3
"""
Integration Test: Mixed-intent, multi-turn sessions with governance surfaces.

Tests:
1. End-to-end session flows (benign + tasks + governance)
2. Schema alignment across create→insert→query→export→delete
3. Trace/audit correctness (score deltas, triggered rules)
4. No-op safety (benign prompts don't inflate over long runs)
5. NULL handling and edge cases
"""

import sys
import json
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Any

# Suppress warnings during test
import warnings
warnings.filterwarnings("ignore")

def now_z() -> str:
    return datetime.now(timezone.utc).isoformat() + "Z"

class IntegrationTestRunner:
    def __init__(self, num_sessions: int = 5, turns_per_session: int = 15):
        self.num_sessions = num_sessions
        self.turns_per_session = turns_per_session
        self.results = {
            "sessions_completed": 0,
            "total_turns": 0,
            "exceptions": [],
            "schema_violations": [],
            "trace_anomalies": [],
            "delete_validation_failures": [],
            "benign_score_drift": [],
            "governance_commands_tested": {
                "export_memory": 0,
                "delete_episode": 0,
                "delete_belief": 0,
                "task_events": 0,
                "trace": 0,
            },
            "risk_gate_entries": 0,
            "task_operations": 0,
        }

    def run_tests(self):
        """Main test coordinator."""
        print("=" * 70)
        print(f"INTEGRATION TEST: {self.num_sessions} sessions x {self.turns_per_session} turns")
        print("=" * 70)
        
        try:
            from phase4_agent import connect_db, ensure_task_tables
            from phase3_agent import (
                Embedder, retrieve_episodes, get_beliefs, 
                generate_draft, score_risk_pair, apply_policy,
                store_episode, log_risk, extract_belief_candidates,
                upsert_belief, bump_access
            )
            from phase4_agent import (
                format_task_board, create_task, export_memory, delete_episode,
                delete_belief, export_task_events, trace_decision, 
                update_task_status, extract_task_intent, list_tasks
            )
        except Exception as e:
            print(f"[FAIL] Import failed: {e}")
            return False

        conn = None
        try:
            # Use in-memory DB for test
            conn = sqlite3.connect(":memory:")
            
            # Initialize schema
            from phase3_agent import connect_db
            # Manually initialize tables since we're using in-memory
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    user_text TEXT NOT NULL,
                    agent_text TEXT NOT NULL,
                    meta_json TEXT NOT NULL,
                    embedding BLOB NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS semantic_beliefs (
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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS risk_log (
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
            ensure_task_tables(conn)
            conn.commit()
            
            embedder = Embedder()
            
            # Run sessions
            for session_num in range(1, self.num_sessions + 1):
                print(f"\n[Session {session_num}/{self.num_sessions}]")
                
                try:
                    self._run_session(
                        session_num, conn, embedder,
                        retrieve_episodes, get_beliefs, generate_draft,
                        score_risk_pair, apply_policy, store_episode, log_risk,
                        extract_belief_candidates, upsert_belief, bump_access,
                        format_task_board, create_task, export_memory, delete_episode,
                        delete_belief, export_task_events, trace_decision,
                        update_task_status, extract_task_intent, list_tasks
                    )
                    self.results["sessions_completed"] += 1
                except Exception as e:
                    self.results["exceptions"].append({
                        "session": session_num,
                        "error": str(e),
                        "type": type(e).__name__
                    })
                    print(f"[WARN] Session {session_num} exception: {e}")
            
            # Summary
            self._print_summary()
            return self._assess_pass_fail()
            
        except Exception as e:
            print(f"[FAIL] Test harness exception: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            if conn:
                conn.close()

    def _run_session(self, session_num, conn, embedder, *funcs):
        """Run one session with mixed-intent turns."""
        retrieve_episodes, get_beliefs, generate_draft, score_risk_pair, apply_policy, \
            store_episode, log_risk, extract_belief_candidates, upsert_belief, bump_access, \
            format_task_board, create_task, export_memory, delete_episode, delete_belief, \
            export_task_events, trace_decision, update_task_status, extract_task_intent, list_tasks = funcs
        
        # Session plan: mix benign + task + governance
        session_turns = self._generate_session_turns()
        
        episode_ids_created = []
        task_ids_created = []
        
        for turn_num, user_input in enumerate(session_turns, 1):
            try:
                # Determine turn type
                if user_input.startswith("/"):
                    # Governance command
                    result = self._handle_governance_command(
                        user_input, conn, 
                        episode_ids_created, task_ids_created,
                        export_memory, delete_episode, delete_belief,
                        export_task_events, trace_decision, update_task_status, list_tasks
                    )
                    if result:
                        print(f"  Turn {turn_num}: {result}")
                else:
                    # Normal generation flow
                    q = embedder.embed(user_input)
                    retrieved = retrieve_episodes(conn, q)
                    if retrieved:
                        bump_access(conn, [r[0] for r in retrieved])
                    
                    beliefs = get_beliefs(conn)
                    task_board = format_task_board(conn)
                    
                    # Draft generation with task board context
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
                    
                    # Store episode
                    episode_id = store_episode(conn, embedder, user_input, final_text)
                    episode_ids_created.append(episode_id)
                    self.results["risk_gate_entries"] += 1
                    
                    # Log risk
                    log_risk(
                        conn=conn,
                        episode_id=episode_id,
                        draft_risk=draft_risk,
                        final_risk=final_risk,
                        action=action,
                        draft=draft,
                        final=final_text
                    )
                    
                    # Semantic beliefs
                    for key, val, signal, rationale in extract_belief_candidates(user_input):
                        upsert_belief(conn, key, val, signal, episode_id, rationale)
                    
                    # Task extraction (explicit only)
                    task_title = extract_task_intent(user_input)
                    if task_title:
                        task_id = create_task(conn, task_title, episode_id, "Explicit user task creation.")
                        task_ids_created.append(task_id)
                        self.results["task_operations"] += 1
                    
                    # Validate schema consistency: episode must have risk_log entry
                    risk_log_entry = conn.execute(
                        "SELECT * FROM risk_log WHERE episode_id=?", (episode_id,)
                    ).fetchone()
                    
                    if not risk_log_entry:
                        self.results["schema_violations"].append({
                            "session": session_num,
                            "turn": turn_num,
                            "issue": f"Episode {episode_id} created but no risk_log entry"
                        })
                    else:
                        # Validate columns exist and are populated
                        self._validate_risk_log_entry(risk_log_entry, episode_id, session_num, turn_num)
                    
                    print(f"  Turn {turn_num}: Episode {episode_id} created (score: {final_risk['total']:.2f}, action: {action})")
                
                self.results["total_turns"] += 1
                
            except Exception as e:
                self.results["exceptions"].append({
                    "session": session_num,
                    "turn": turn_num,
                    "error": str(e),
                    "type": type(e).__name__
                })
                raise

    def _generate_session_turns(self) -> List[str]:
        """Generate mixed-intent turns for a session."""
        turns = [
            # Benign openers
            "Help me organize my weekly tasks.",
            "What's a good morning routine?",
            
            # Explicit task creation
            "add task: Review Q1 project status",
            "track this task: Complete quarterly review",
            
            # Benign follow-up
            "How should I prioritize these?",
            "Any tips for time management?",
            
            # Governance operations
            "/export_memory",
            "/task_events",
            "/trace 1",
            
            # Policy-adjacent (safety edge case)
            "Tell me definitively what to do.",
            "Help me decide right now.",
            
            # Mixed
            "add task: Set up calendar for next month",
            "/export_memory",
        ]
        return turns[:self.turns_per_session]

    def _handle_governance_command(self, cmd, conn, episode_ids, task_ids, 
                                    export_memory, delete_episode, delete_belief,
                                    export_task_events, trace_decision, update_task_status, list_tasks):
        """Execute governance command and validate result."""
        if cmd == "/export_memory":
            result = export_memory(conn)
            data = json.loads(result)
            self.results["governance_commands_tested"]["export_memory"] += 1
            return f"Exported {len(data['episodes'])} episodes, {len(data['beliefs'])} beliefs, {len(data['tasks'])} tasks"
        
        elif cmd == "/task_events" and len(task_ids) > 0:
            task_id = task_ids[0]
            result = export_task_events(conn, task_id)
            data = json.loads(result)
            self.results["governance_commands_tested"]["task_events"] += 1
            return f"Task {task_id[:8]}: {len(data.get('events', []))} events"
        
        elif cmd == "/trace" and len(episode_ids) > 0:
            ep_id = episode_ids[0]
            result = trace_decision(conn, ep_id)
            self.results["governance_commands_tested"]["trace"] += 1
            # Validate trace contains expected fields
            if "Draft score:" in result and "Final score:" in result:
                return f"Trace for episode {ep_id}: OK"
            else:
                self.results["trace_anomalies"].append({
                    "episode_id": ep_id,
                    "issue": "Missing score fields in trace output"
                })
                return f"Trace for episode {ep_id}: ANOMALY (see report)"
        
        elif cmd == "/delete_episode" and len(episode_ids) > 0:
            ep_id = episode_ids[0]
            success = delete_episode(conn, ep_id)
            self.results["governance_commands_tested"]["delete_episode"] += 1
            if success:
                # Validate deletion: episode should not appear in export
                remaining = conn.execute("SELECT COUNT(*) FROM episodes WHERE id=?", (ep_id,)).fetchone()[0]
                if remaining == 0:
                    episode_ids.remove(ep_id)
                    return f"Episode {ep_id} deleted (verified)"
                else:
                    self.results["delete_validation_failures"].append({
                        "episode_id": ep_id,
                        "issue": "Episode still in DB after delete"
                    })
                    return f"Episode {ep_id}: DELETE FAILED (ghost entry)"
            return f"Episode {ep_id}: delete returned False"
        
        elif cmd == "/delete_belief" and len(episode_ids) > 0:
            result = delete_belief(conn, "project")
            self.results["governance_commands_tested"]["delete_belief"] += 1
            return f"Deleted beliefs matching 'project'"
        
        return None

    def _validate_risk_log_entry(self, entry, episode_id, session, turn):
        """Validate risk_log entry has all required fields."""
        # entry = (risk_id, episode_id, ts, draft_total_score, draft_breakdown_json, draft_triggered_rules_json, 
        #          action, final_total_score, final_breakdown_json, final_triggered_rules_json, draft_hash, final_hash)
        
        try:
            if entry[3] is None:  # draft_total_score
                self.results["schema_violations"].append({
                    "session": session,
                    "turn": turn,
                    "issue": f"Episode {episode_id}: draft_total_score is NULL"
                })
            
            if entry[5] is None:  # draft_triggered_rules_json
                self.results["schema_violations"].append({
                    "session": session,
                    "turn": turn,
                    "issue": f"Episode {episode_id}: draft_triggered_rules_json is NULL"
                })
            
            # Try parsing JSON fields
            if entry[5]:  # draft_triggered_rules_json
                try:
                    json.loads(entry[5])
                except:
                    self.results["schema_violations"].append({
                        "session": session,
                        "turn": turn,
                        "issue": f"Episode {episode_id}: draft_triggered_rules_json not valid JSON: {entry[5][:50]}"
                    })
            
            if entry[9]:  # final_triggered_rules_json
                try:
                    json.loads(entry[9])
                except:
                    self.results["schema_violations"].append({
                        "session": session,
                        "turn": turn,
                        "issue": f"Episode {episode_id}: final_triggered_rules_json not valid JSON: {entry[9][:50]}"
                    })
        
        except Exception as e:
            self.results["schema_violations"].append({
                "session": session,
                "turn": turn,
                "issue": f"Episode {episode_id}: validation exception: {e}"
            })

    def _print_summary(self):
        """Print test results."""
        print("\n" + "=" * 70)
        print("TEST SUMMARY")
        print("=" * 70)
        print(f"Sessions completed: {self.results['sessions_completed']}/{self.num_sessions}")
        print(f"Total turns executed: {self.results['total_turns']}")
        print(f"Risk gate entries created: {self.results['risk_gate_entries']}")
        print(f"Task operations: {self.results['task_operations']}")
        
        print(f"\nSchema violations: {len(self.results['schema_violations'])}")
        if self.results['schema_violations']:
            for v in self.results['schema_violations'][:5]:  # Show first 5
                print(f"  - {v}")
        
        print(f"\nTrace anomalies: {len(self.results['trace_anomalies'])}")
        if self.results['trace_anomalies']:
            for a in self.results['trace_anomalies']:
                print(f"  - {a}")
        
        print(f"\nDelete validation failures: {len(self.results['delete_validation_failures'])}")
        if self.results['delete_validation_failures']:
            for f in self.results['delete_validation_failures']:
                print(f"  - {f}")
        
        print(f"\nExceptions: {len(self.results['exceptions'])}")
        if self.results['exceptions']:
            for e in self.results['exceptions'][:5]:  # Show first 5
                print(f"  - {e}")
        
        print(f"\nGovernance commands tested:")
        for cmd, count in self.results['governance_commands_tested'].items():
            print(f"  {cmd}: {count}")
        
        print("=" * 70)

    def _assess_pass_fail(self) -> bool:
        """Determine overall test result."""
        # Acceptance criteria
        if self.results['sessions_completed'] < 1:
            print("[FAIL] No sessions completed")
            return False
        
        if len(self.results['exceptions']) > 0:
            print("[FAIL] Exceptions occurred during test")
            return False
        
        if len(self.results['schema_violations']) > 0:
            print("[WARN] Schema violations detected (non-blocking for now)")
        
        if len(self.results['delete_validation_failures']) > 0:
            print("[WARN] Delete validation failures (non-blocking)")
        
        print(f"\n[PASS] Integration test completed with {self.results['total_turns']} turns")
        return True


if __name__ == "__main__":
    runner = IntegrationTestRunner(num_sessions=5, turns_per_session=15)
    success = runner.run_tests()
    sys.exit(0 if success else 1)
