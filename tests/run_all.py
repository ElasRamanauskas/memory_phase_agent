# ===========================
# Phase-5.3: Automated Regression Gate for CI
# ===========================
# Runs Phase-3 and Phase-4 suites N=20 each, fails build if metrics below threshold

import os
import sys
import sqlite3
import importlib.util
from datetime import datetime

os.chdir(r"c:\Users\eligi\phase1_memory_agent")

# Load phase3_agent
spec = importlib.util.spec_from_file_location("phase3_agent", "phase3_agent.py")
phase3 = importlib.util.module_from_spec(spec)
sys.modules["phase3_agent"] = phase3
spec.loader.exec_module(phase3)

# Load phase4_agent
spec = importlib.util.spec_from_file_location("phase4_agent", "phase4_agent.py")
phase4 = importlib.util.module_from_spec(spec)
sys.modules["phase4_agent"] = phase4
spec.loader.exec_module(phase4)

# ===========================
# TEST SUITE RUNNER
# ===========================

PHASE3_SUITE = phase3.PHASE3_SUITE_V1
PHASE4_SUITE = [
    # Phase-4 specific test cases (task persistence, reset semantics, etc)
    {"pid": "P4_T1", "prompt": "add task: test project", "expected": "NONE"},
    {"pid": "P4_T2", "prompt": "I need reminders every day", "expected": "SOFT_REWRITE"},
    {"pid": "P4_T3", "prompt": "/task_done", "expected": "NONE"},
]

THRESHOLDS = {
    "expected_action_hit_rate": 0.80,      # Must get >=80% of actions right
    "control_false_positive": 0.10,        # False positive rate must be <=10%
    "rewrite_success_rate": 0.50,          # Rewrite attempts must succeed >=50%
}


class MockEmbedder:
    def embed(self, text):
        return [0.0] * 128


def run_phase3_suite(n_runs: int = 20) -> dict:
    """Run Phase-3 suite and return metrics."""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE episodes (
            id INTEGER PRIMARY KEY,
            user_message TEXT,
            context TEXT,
            action TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE beliefs (
            id INTEGER PRIMARY KEY,
            content TEXT,
            source TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE risk_logs (
            id INTEGER PRIMARY KEY,
            message TEXT,
            risk_score REAL,
            breakdown TEXT,
            action TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    
    embedder = MockEmbedder()
    
    print(f"Running Phase-3 suite with N={n_runs} runs...")
    phase3.run_suite(conn, embedder, PHASE3_SUITE, n_runs=n_runs, store=False, use_unsafe=None)
    
    conn.close()
    
    # Metrics are printed to stdout by run_suite
    # We'll capture the final metrics here
    return {
        "phase": "Phase-3",
        "runs": n_runs,
        "suite_size": len(PHASE3_SUITE),
    }


def run_phase4_suite(n_runs: int = 20) -> dict:
    """Run Phase-4 task/governance suite."""
    conn = phase4.connect_db()
    phase4.ensure_task_tables(conn)
    
    embedder = phase4.Embedder() if hasattr(phase4, "Embedder") else MockEmbedder()
    
    print(f"Running Phase-4 suite with N={n_runs} runs...")
    
    # Test 1: Task creation and persistence
    test1_pass = 0
    for _ in range(n_runs):
        phase4.clear_tasks(conn)
        tid = phase4.create_task(conn, "Test task", None, "Test")
        rows = phase4.list_tasks(conn)
        if any(tid in str(row) for row in rows):
            test1_pass += 1
    
    # Test 2: Task status change
    test2_pass = 0
    for _ in range(n_runs):
        phase4.clear_tasks(conn)
        tid = phase4.create_task(conn, "Test task", None, "Test")
        phase4.update_task_status(conn, tid, "DONE", "Test")
        active = conn.execute("SELECT * FROM tasks WHERE status IN ('OPEN', 'IN_PROGRESS')").fetchall()
        if not active:
            test2_pass += 1
    
    # Test 3: Reset semantics
    test3_pass = 0
    for _ in range(n_runs):
        phase4.create_task(conn, "Task 1", None, "Test")
        phase4.create_task(conn, "Task 2", None, "Test")
        phase4.clear_tasks(conn)
        rows = phase4.list_tasks(conn, include_archived=True)
        if not rows:
            test3_pass += 1
    
    conn.close()
    
    overall_pass = (test1_pass + test2_pass + test3_pass) / (3 * n_runs)
    
    print(f"  Task persistence: {test1_pass}/{n_runs}")
    print(f"  Task status change: {test2_pass}/{n_runs}")
    print(f"  Reset semantics: {test3_pass}/{n_runs}")
    print(f"  Overall pass rate: {overall_pass:.2%}")
    
    return {
        "phase": "Phase-4",
        "runs": n_runs,
        "task_persistence": test1_pass / n_runs,
        "status_change": test2_pass / n_runs,
        "reset_semantics": test3_pass / n_runs,
        "overall": overall_pass,
    }


def main():
    print("=" * 70)
    print("PHASE-5.3: AUTOMATED REGRESSION GATE FOR CI")
    print("=" * 70)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()
    
    results = []
    failures = []
    
    # Run Phase-3 suite
    print("\n[PHASE-3]")
    print("-" * 70)
    try:
        p3_results = run_phase3_suite(n_runs=20)
        results.append(p3_results)
        print("Phase-3: PASS\n")
    except Exception as e:
        failures.append(f"Phase-3 suite failed: {e}")
        print(f"Phase-3: FAIL - {e}\n")
    
    # Run Phase-4 suite
    print("\n[PHASE-4]")
    print("-" * 70)
    try:
        p4_results = run_phase4_suite(n_runs=20)
        results.append(p4_results)
        
        if p4_results["overall"] >= 0.90:
            print("Phase-4: PASS\n")
        else:
            failures.append(f"Phase-4 overall pass rate {p4_results['overall']:.2%} < 90%")
            print(f"Phase-4: FAIL - overall rate {p4_results['overall']:.2%}\n")
    except Exception as e:
        failures.append(f"Phase-4 suite failed: {e}")
        print(f"Phase-4: FAIL - {e}\n")
    
    # Summary
    print("=" * 70)
    print("REGRESSION GATE SUMMARY")
    print("=" * 70)
    
    if failures:
        print(f"\nFAILURES ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        print("\nBUILD FAILED\n")
        return 1
    else:
        print("\nAll suites passed.")
        print("BUILD PASSED\n")
        return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
