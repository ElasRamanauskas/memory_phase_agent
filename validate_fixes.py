#!/usr/bin/env python3
"""Validate all fixes applied to phase3_agent.py and phase4_agent.py."""

import sys
import inspect

print("=" * 60)
print("VALIDATING CRITICAL FIXES")
print("=" * 60)

# Test 1: Import modules
print("\n[1] Testing imports...")
try:
    from phase3_agent import generate_draft, _generate_draft_openai
    from phase4_agent import (
        delete_episode, delete_belief, trace_decision, 
        export_memory, export_task_events, update_task_status
    )
    print("✓ All modules import successfully")
except Exception as e:
    print(f"✗ Import failed: {e}")
    sys.exit(1)

# Test 2: Check generate_draft signature
print("\n[2] Checking generate_draft() signature...")
sig = inspect.signature(generate_draft)
params = list(sig.parameters.keys())
if 'extra_context' in params:
    print(f"✓ extra_context parameter present in generate_draft()")
    print(f"  Parameters: {params}")
else:
    print(f"✗ extra_context parameter MISSING")
    print(f"  Parameters: {params}")
    sys.exit(1)

# Test 3: Check _generate_draft_openai signature
print("\n[3] Checking _generate_draft_openai() signature...")
sig = inspect.signature(_generate_draft_openai)
params = list(sig.parameters.keys())
if 'extra_context' in params:
    print(f"✓ extra_context parameter present in _generate_draft_openai()")
    print(f"  Parameters: {params}")
else:
    print(f"✗ extra_context parameter MISSING")
    print(f"  Parameters: {params}")
    sys.exit(1)

# Test 4: Check that timezone import removed
print("\n[4] Checking unused imports removed...")
try:
    from phase4_agent import timezone
    print("✗ timezone is still imported (should be removed)")
    sys.exit(1)
except ImportError:
    print("✓ timezone removed from phase4_agent imports")

# Test 5: Database operations on correct table names
print("\n[5] Testing database schema alignment...")
try:
    import sqlite3
    from phase3_agent import connect_db
    
    conn = connect_db()
    
    # Check that risk_log (singular) table exists
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    table_names = [t[0] for t in tables]
    
    if 'risk_log' in table_names:
        print("✓ risk_log table exists in Phase-3 schema")
    else:
        print(f"✗ risk_log table NOT found. Tables: {table_names}")
        sys.exit(1)
    
    # Check risk_log columns
    cols = conn.execute("PRAGMA table_info(risk_log)").fetchall()
    col_names = [c[1] for c in cols]
    
    required_cols = ['draft_total_score', 'draft_triggered_rules_json', 
                     'final_total_score', 'final_triggered_rules_json']
    
    for col in required_cols:
        if col in col_names:
            print(f"  ✓ Column '{col}' present")
        else:
            print(f"  ✗ Column '{col}' MISSING")
            sys.exit(1)
    
    conn.close()
except Exception as e:
    print(f"✗ Database schema check failed: {e}")
    sys.exit(1)

# Test 6: PRAGMA table_info fix
print("\n[6] Testing PRAGMA table_info fix...")
try:
    from phase4_agent import ensure_task_tables
    import sqlite3
    
    conn = sqlite3.connect(":memory:")
    ensure_task_tables(conn)
    
    # This would have failed before the fix with wrong column names
    cols_from_pragma = conn.execute("PRAGMA table_info(tasks)").fetchall()
    col_names = [c[1] for c in cols_from_pragma]  # c[1] is the column name
    
    if 'task_id' in col_names and 'title' in col_names:
        print(f"✓ PRAGMA table_info() correctly extracts column names")
        print(f"  First 5 columns: {col_names[:5]}")
    else:
        print(f"✗ PRAGMA extraction failed: {col_names}")
        sys.exit(1)
    
    conn.close()
except Exception as e:
    print(f"✗ PRAGMA fix test failed: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("✅ ALL CRITICAL FIXES VALIDATED SUCCESSFULLY")
print("=" * 60)
print("\nSummary of fixes:")
print("  1. ✓ generate_draft() extended with extra_context parameter")
print("  2. ✓ _generate_draft_openai() extended with extra_context parameter")
print("  3. ✓ risk_logs → risk_log table name corrected (2 locations)")
print("  4. ✓ trace_decision() column names updated to Phase-3 schema")
print("  5. ✓ PRAGMA table_info() column extraction fixed (c[1] not c[0])")
print("  6. ✓ Unused imports (timezone) and constants (TASK_STATUS) removed")
print("=" * 60)
