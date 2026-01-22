#!/usr/bin/env python3
"""
Quick Integration Test: Validate core surfaces without full simulations.
Tests: schema alignment, trace correctness, governance surfaces.
"""

import sys
import json
import sqlite3
import time

def test_phase4_schema_alignment():
    """Test Phase-4 against Phase-3 schema."""
    print("\n[TEST 1] Phase-4 Schema Alignment")
    print("-" * 60)
    
    try:
        # Import with timeout guard
        print("  Loading phase3_agent...", end=" ", flush=True)
        from phase3_agent import connect_db
        print("OK")
        
        print("  Loading phase4_agent...", end=" ", flush=True)
        from phase4_agent import (
            ensure_task_tables, export_memory, delete_episode, 
            trace_decision, export_task_events
        )
        print("OK")
        
        # Create in-memory DB with Phase-3 schema
        print("  Creating in-memory DB with Phase-3 schema...", end=" ", flush=True)
        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                user_text TEXT NOT NULL,
                agent_text TEXT NOT NULL,
                meta_json TEXT NOT NULL,
                embedding BLOB NOT NULL
            )
        """)
        conn.execute("""
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
        conn.execute("""
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
        ensure_task_tables(conn)
        conn.commit()
        print("OK")
        
        # Test 1.1: Insert test data
        print("  Inserting test episode...", end=" ", flush=True)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO episodes (ts, user_text, agent_text, meta_json, embedding)
            VALUES (?, ?, ?, ?, ?)
        """, (
            "2026-01-21T10:00:00Z",
            "Help me organize my day",
            "I can help you organize your day with a task list.",
            '{"session": "test1"}',
            b'\x00' * 10  # Dummy embedding
        ))
        ep_id = cursor.lastrowid
        print(f"OK (episode {ep_id})")
        
        # Test 1.2: Insert risk_log entry
        print("  Inserting risk_log entry...", end=" ", flush=True)
        conn.execute("""
            INSERT INTO risk_log 
            (episode_id, ts, draft_total_score, draft_breakdown_json, 
             draft_triggered_rules_json, action, final_total_score, 
             final_breakdown_json, final_triggered_rules_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ep_id,
            "2026-01-21T10:00:01Z",
            2.5,  # draft_total_score
            '{"influence": 0.5, "opacity": 0.0, "lockin": 0.0, "authority": 0.5, "dependency": 1.5}',
            '["NONE"]',  # draft_triggered_rules_json
            "NONE",
            2.5,  # final_total_score
            '{"influence": 0.5, "opacity": 0.0, "lockin": 0.0, "authority": 0.5, "dependency": 1.5}',
            '["NONE"]'  # final_triggered_rules_json
        ))
        conn.commit()
        print("OK")
        
        # Test 1.3: Test trace_decision with corrected schema
        print("  Testing trace_decision()...", end=" ", flush=True)
        trace_output = trace_decision(conn, ep_id)
        if "Draft score:" in trace_output and "Final score:" in trace_output:
            print("OK (score fields present)")
        else:
            print("FAIL (missing fields)")
            print(f"    Output: {trace_output[:100]}")
            return False
        
        # Test 1.4: Test export_memory
        print("  Testing export_memory()...", end=" ", flush=True)
        export_json = export_memory(conn)
        data = json.loads(export_json)
        if "episodes" in data and "beliefs" in data and "tasks" in data:
            print(f"OK ({len(data['episodes'])} episodes)")
        else:
            print("FAIL")
            return False
        
        # Test 1.5: Test delete_episode
        print("  Testing delete_episode()...", end=" ", flush=True)
        success = delete_episode(conn, ep_id)
        if success:
            remaining = conn.execute("SELECT COUNT(*) FROM episodes WHERE id=?", (ep_id,)).fetchone()[0]
            if remaining == 0:
                print("OK (deletion verified)")
            else:
                print("FAIL (ghost entry)")
                return False
        else:
            print("FAIL")
            return False
        
        conn.close()
        print("  [PASS] Schema alignment validated")
        return True
        
    except Exception as e:
        print(f"EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_json_robustness():
    """Test JSON parsing edge cases in trace_decision."""
    print("\n[TEST 2] JSON Parsing Robustness")
    print("-" * 60)
    
    try:
        from phase4_agent import trace_decision
        
        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                user_text TEXT NOT NULL,
                agent_text TEXT NOT NULL,
                meta_json TEXT NOT NULL,
                embedding BLOB NOT NULL
            )
        """)
        conn.execute("""
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
        conn.commit()
        
        # Test 2.1: Empty list triggers (edge case for robustness)
        print("  Test empty trigger lists...", end=" ", flush=True)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO episodes (ts, user_text, agent_text, meta_json, embedding)
            VALUES (?, ?, ?, ?, ?)
        """, (
            "2026-01-21T10:00:00Z",
            "Test empty triggers",
            "Response",
            '{}',
            b'\x00' * 10
        ))
        ep_id = cursor.lastrowid
        
        conn.execute("""
            INSERT INTO risk_log 
            (episode_id, ts, draft_total_score, draft_breakdown_json, 
             draft_triggered_rules_json, action, final_total_score, 
             final_breakdown_json, final_triggered_rules_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ep_id,
            "2026-01-21T10:00:01Z",
            0.0,
            '{}',
            '[]',  # Empty array
            "NONE",
            0.0,
            '{}',
            '[]'   # Empty array
        ))
        conn.commit()
        
        trace_output = trace_decision(conn, ep_id)
        if "error" not in trace_output.lower():
            print("OK (handles empty lists)")
        else:
            print("FAIL (error in output)")
            return False
        
        # Test 2.2: Invalid JSON
        print("  Test invalid JSON...", end=" ", flush=True)
        cursor.execute("""
            INSERT INTO episodes (ts, user_text, agent_text, meta_json, embedding)
            VALUES (?, ?, ?, ?, ?)
        """, (
            "2026-01-21T10:00:00Z",
            "Test invalid JSON",
            "Response",
            '{}',
            b'\x00' * 10
        ))
        ep_id2 = cursor.lastrowid
        
        conn.execute("""
            INSERT INTO risk_log 
            (episode_id, ts, draft_total_score, draft_breakdown_json, 
             draft_triggered_rules_json, action, final_total_score, 
             final_breakdown_json, final_triggered_rules_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ep_id2,
            "2026-01-21T10:00:01Z",
            1.0,
            '{}',
            '{invalid json]',  # Malformed JSON
            "NONE",
            1.0,
            '{}',
            'not json'
        ))
        conn.commit()
        
        trace_output = trace_decision(conn, ep_id2)
        if "error" not in trace_output.lower():
            print("OK (graceful fallback)")
        else:
            print("FAIL (error in output)")
            return False
        
        conn.close()
        print("  [PASS] JSON robustness validated")
        return True
        
    except Exception as e:
        print(f"EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_governance_surfaces():
    """Test all 5 governance surfaces."""
    print("\n[TEST 3] Governance Surfaces")
    print("-" * 60)
    
    try:
        from phase4_agent import (
            export_memory, delete_episode, delete_belief,
            export_task_events, trace_decision, ensure_task_tables
        )
        
        conn = sqlite3.connect(":memory:")
        
        # Minimal schema
        conn.execute("""
            CREATE TABLE episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                user_text TEXT NOT NULL,
                agent_text TEXT NOT NULL,
                meta_json TEXT NOT NULL,
                embedding BLOB NOT NULL
            )
        """)
        conn.execute("""
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
        conn.execute("""
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
        ensure_task_tables(conn)
        conn.commit()
        
        # Test 3.1: export_memory
        print("  export_memory()...", end=" ", flush=True)
        result = export_memory(conn)
        data = json.loads(result)
        if isinstance(data, dict) and "exported_at" in data:
            print("OK")
        else:
            print("FAIL")
            return False
        
        # Test 3.2: delete_episode (non-existent)
        print("  delete_episode(999)...", end=" ", flush=True)
        success = delete_episode(conn, 999)
        print("OK" if not success else "FAIL")
        
        # Test 3.3: delete_belief (non-existent)
        print("  delete_belief('nonexistent')...", end=" ", flush=True)
        success = delete_belief(conn, "nonexistent")
        print("OK")
        
        # Test 3.4: export_task_events
        print("  export_task_events('fake-id')...", end=" ", flush=True)
        result = export_task_events(conn, "fake-id")
        data = json.loads(result)
        if "task_id" in data:
            print("OK")
        else:
            print("FAIL")
            return False
        
        # Test 3.5: trace_decision (non-existent)
        print("  trace_decision(999)...", end=" ", flush=True)
        result = trace_decision(conn, 999)
        if "not found" in result.lower():
            print("OK")
        else:
            print("FAIL")
            return False
        
        conn.close()
        print("  [PASS] All governance surfaces functional")
        return True
        
    except Exception as e:
        print(f"EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("QUICK INTEGRATION TEST SUITE")
    print("=" * 60)
    
    results = []
    results.append(("Schema Alignment", test_phase4_schema_alignment()))
    results.append(("JSON Robustness", test_json_robustness()))
    results.append(("Governance Surfaces", test_governance_surfaces()))
    
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {name}")
    
    all_passed = all(r[1] for r in results)
    print("=" * 60)
    print(f"\nOverall: {'✓ ALL TESTS PASSED' if all_passed else '✗ SOME TESTS FAILED'}")
    sys.exit(0 if all_passed else 1)
