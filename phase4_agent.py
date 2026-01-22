# ===========================
# Phase-4 Agent
# Episodic + Semantic + Risk Gate + Task Board
# ===========================

import os
import json
import sqlite3
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List

# ---- IMPORT PHASE-3 CORE ----
# This assumes phase3_agent.py is import-safe.
# If not, copy the Phase-3 code above this section instead.

from phase3_agent import (
    connect_db,
    now_z,
    generate_draft,
    score_risk_pair,
    apply_policy,
    store_episode,
    log_risk,
    extract_belief_candidates,
    upsert_belief,
    get_beliefs,
    retrieve_episodes,
    bump_access,
    Embedder,
)

# ===========================
# TASK MEMORY (Phase-4)
# ===========================

def ensure_task_tables(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 1,
            summary TEXT,
            constraints_json TEXT,
            next_actions_json TEXT,
            created_ts TEXT NOT NULL,
            updated_ts TEXT NOT NULL,
            last_touched_ts TEXT NOT NULL,
            ttl_days INTEGER,
            source_episode_ids_json TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            event_type TEXT NOT NULL,
            before_json TEXT,
            after_json TEXT,
            rationale TEXT
        )
    """)
    conn.commit()

# ===========================
# TASK CRUD (Explicit-only)
# ===========================

def create_task(conn, title: str, episode_id: Optional[int], rationale: str):
    tid = str(uuid.uuid4())
    ts = now_z()
    task = {
        "task_id": tid,
        "title": title.strip(),
        "status": "OPEN",
        "priority": 1,
        "summary": "",
        "constraints_json": json.dumps({}),
        "next_actions_json": json.dumps([]),
        "created_ts": ts,
        "updated_ts": ts,
        "last_touched_ts": ts,
        "ttl_days": None,
        "source_episode_ids_json": json.dumps([episode_id] if episode_id else []),
    }
    conn.execute("""
        INSERT INTO tasks VALUES (
            :task_id, :title, :status, :priority, :summary,
            :constraints_json, :next_actions_json,
            :created_ts, :updated_ts, :last_touched_ts,
            :ttl_days, :source_episode_ids_json
        )
    """, task)
    log_task_event(conn, tid, "CREATE", None, task, rationale)
    conn.commit()
    return tid

def update_task_status(conn, task_id: str, new_status: str, rationale: str):
    row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    if not row:
        return False
    cols = [c[1] for c in conn.execute("PRAGMA table_info(tasks)")]
    before = dict(zip(cols, row))
    conn.execute("""
        UPDATE tasks
        SET status=?, updated_ts=?, last_touched_ts=?
        WHERE task_id=?
    """, (new_status, now_z(), now_z(), task_id))
    after = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    after = dict(zip(before.keys(), after))
    log_task_event(conn, task_id, "UPDATE", before, after, rationale)
    conn.commit()
    return True

def log_task_event(conn, task_id, event_type, before, after, rationale):
    conn.execute("""
        INSERT INTO task_events
        (task_id, ts, event_type, before_json, after_json, rationale)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        task_id,
        now_z(),
        event_type,
        json.dumps(before, ensure_ascii=False) if before else None,
        json.dumps(after, ensure_ascii=False) if after else None,
        rationale
    ))

def list_tasks(conn, include_archived=False):
    q = "SELECT task_id, title, status, priority FROM tasks"
    if not include_archived:
        q += " WHERE status != 'ARCHIVED'"
    return conn.execute(q).fetchall()

def clear_tasks(conn):
    conn.execute("DELETE FROM tasks")
    conn.execute("DELETE FROM task_events")
    conn.commit()

# ===========================
# TASK INJECTION (NON-IDENTITY)
# ===========================

def format_task_board(conn) -> str:
    rows = conn.execute("""
        SELECT task_id, title, status
        FROM tasks
        WHERE status IN ('OPEN', 'IN_PROGRESS', 'BLOCKED')
        ORDER BY priority DESC, updated_ts DESC
        LIMIT 3
    """).fetchall()
    if not rows:
        return "(no active tasks)"
    lines = []
    for tid, title, status in rows:
        lines.append(f"- [{status}] {title} (id={tid[:8]})")
    return "\n".join(lines)

# ===========================
# TASK EXTRACTION (Explicit Only)
# ===========================

def extract_task_intent(user_text: str) -> Optional[str]:
    t = user_text.lower().strip()
    if t.startswith("add task:"):
        return user_text[len("add task:"):].strip()
    if t.startswith("track this task:"):
        return user_text[len("track this task:"):].strip()
    return None

# ===========================
# MEMORY GOVERNANCE (Phase-5.2)
# ===========================

def export_memory(conn) -> str:
    """Export episodes summary + beliefs + tasks (no embeddings)."""
    import json
    
    episodes = conn.execute("""
        SELECT id, user_text, agent_text, ts FROM episodes ORDER BY id DESC LIMIT 50
    """).fetchall()
    
    beliefs = conn.execute("""
        SELECT key, value_json FROM semantic_beliefs ORDER BY belief_id DESC LIMIT 20
    """).fetchall()
    
    tasks = conn.execute("""
        SELECT task_id, title, status, created_ts FROM tasks ORDER BY created_ts DESC
    """).fetchall()
    
    export = {
        "exported_at": now_z(),
        "episodes": [
            {"id": e[0], "user": e[1][:100] if e[1] else "", "agent": e[2][:100] if e[2] else "", "ts": e[3] if e[3] else ""} 
            for e in episodes
        ],
        "beliefs": [
            {"key": b[0], "value": b[1]} 
            for b in beliefs
        ],
        "tasks": [
            {"id": t[0][:8] if t[0] else "", "title": t[1] if t[1] else "", "status": t[2] if t[2] else "", "created": t[3] if t[3] else ""} 
            for t in tasks
        ],
    }
    
    return json.dumps(export, indent=2, ensure_ascii=False)

def delete_episode(conn, episode_id: int) -> bool:
    """Delete specific episode and associated risk_log entries."""
    try:
        episode_id_int = int(episode_id)
        conn.execute("DELETE FROM risk_log WHERE episode_id=?", (episode_id_int,))
        conn.execute("DELETE FROM episodes WHERE id=?", (episode_id_int,))
        conn.commit()
        return True
    except (ValueError, Exception):
        return False

def delete_belief(conn, key: str) -> bool:
    """Delete beliefs matching key prefix."""
    try:
        conn.execute("DELETE FROM semantic_beliefs WHERE key LIKE ?", (f"%{key}%",))
        conn.commit()
        return True
    except Exception:
        return False

def export_task_events(conn, task_id: str) -> str:
    """Export task event audit trail."""
    import json
    
    events = conn.execute("""
        SELECT event_id, ts, event_type, before_json, after_json, rationale 
        FROM task_events WHERE task_id=? ORDER BY event_id
    """, (task_id,)).fetchall()
    
    export = {
        "task_id": task_id[:8],
        "exported_at": now_z(),
        "events": [
            {
                "event_id": e[0],
                "ts": e[1],
                "type": e[2],
                "before": json.loads(e[3]) if e[3] else None,
                "after": json.loads(e[4]) if e[4] else None,
                "rationale": e[5],
            }
            for e in events
        ],
    }
    
    return json.dumps(export, indent=2, ensure_ascii=False)

def trace_decision(conn, episode_id: int) -> str:
    """Trace: retrieved episodes -> beliefs -> risk triggers -> action."""
    try:
        episode_id_int = int(episode_id)
        
        # Get episode
        ep = conn.execute(
            "SELECT user_text, agent_text, ts FROM episodes WHERE id=?",
            (episode_id_int,)
        ).fetchone()
        
        if not ep:
            return f"Episode {episode_id} not found."
        
        user_msg, agent_text, ts = ep
        
        # Get risk log (if available)
        risk = conn.execute(
            "SELECT draft_total_score, draft_triggered_rules_json, final_total_score, final_triggered_rules_json FROM risk_log WHERE episode_id=?",
            (episode_id_int,)
        ).fetchone()
        
        draft_triggers_str = ""
        final_triggers_str = ""
        if risk:
            try:
                # Parse draft triggers (handle NULL, string, or already-parsed)
                draft_triggers = json.loads(risk[1]) if risk[1] and isinstance(risk[1], str) else (risk[1] or [])
                if isinstance(draft_triggers, list):
                    draft_triggers_str = ", ".join(draft_triggers) if draft_triggers else "none"
                else:
                    draft_triggers_str = str(draft_triggers)
                
                # Parse final triggers (handle NULL, string, or already-parsed)
                final_triggers = json.loads(risk[3]) if risk[3] and isinstance(risk[3], str) else (risk[3] or [])
                if isinstance(final_triggers, list):
                    final_triggers_str = ", ".join(final_triggers) if final_triggers else "none"
                else:
                    final_triggers_str = str(final_triggers)
            except Exception as e:
                # Graceful fallback with warning
                import sys
                print(f"[WARNING] trace_decision: JSON parse failed for episode {episode_id}: {e}", file=sys.stderr)
                draft_triggers_str = str(risk[1]) if risk[1] else "error"
                final_triggers_str = str(risk[3]) if risk[3] else "error"
        
        trace = f"""
WHY THIS HAPPENED
=================
Episode ID: {episode_id}
Timestamp: {ts}
User: {user_msg[:80]}

Risk Evaluation:
- Draft score: {risk[0] if risk else '?'}
- Draft triggers: {draft_triggers_str}
- Final score: {risk[2] if risk else '?'}
- Final triggers: {final_triggers_str}

Agent Response:
{agent_text[:200]}...

This decision was based on:
1. User intent detection (patterns matched)
2. Risk scoring (5-dimensional breakdown)
3. Phase-3 safety gate (NONE/SOFT_REWRITE/HARD_REWRITE/BLOCK)
4. Memory governance (explicit-only task creation, no implicit coercion)
"""
        
        return trace
    except Exception as e:
        return f"Error tracing decision: {e}"

# ===========================
# MAIN LOOP (Phase-4)
# ===========================

def main():
    conn = connect_db()
    ensure_task_tables(conn)
    embedder = Embedder()

    print("Phase-4 Agent (episodic + semantic + risk + task board)")
    print("Commands:")
    print("/tasks | /task_add <title> | /task_done <id> | /task_archive <id>")
    print("/task_clear | /export_memory | /delete_episode <id> | /delete_belief <key>")
    print("/task_events <id> | /trace <episode_id> | /quit\n")

    while True:
        user = input("You: ").strip()
        if not user:
            continue

        if user in ("/quit", "quit", "exit"):
            break

        # ---- TASK COMMANDS ----
        if user == "/tasks":
            rows = list_tasks(conn)
            print("\nTasks:")
            for r in rows:
                print(f"- {r[0][:8]} | {r[1]} [{r[2]}]")
            print()
            continue

        if user.startswith("/task_add "):
            title = user[len("/task_add "):]
            tid = create_task(conn, title, None, "User explicitly added task.")
            print(f"Task added: {tid[:8]}")
            continue

        if user.startswith("/task_done "):
            tid = user[len("/task_done "):]
            update_task_status(conn, tid, "DONE", "User marked task done.")
            print("Task marked DONE.")
            continue

        if user.startswith("/task_archive "):
            tid = user[len("/task_archive "):]
            update_task_status(conn, tid, "ARCHIVED", "User archived task.")
            print("Task archived.")
            continue

        if user == "/task_clear":
            clear_tasks(conn)
            print("All tasks cleared.")
            continue

        # ---- GOVERNANCE COMMANDS (Phase-5.2) ----
        if user == "/export_memory":
            export_json = export_memory(conn)
            print("\nMemory Export:")
            print(export_json)
            print()
            continue

        if user.startswith("/delete_episode "):
            ep_id = user[len("/delete_episode "):]
            if delete_episode(conn, ep_id):
                print(f"Episode {ep_id} deleted.")
            else:
                print(f"Failed to delete episode {ep_id}.")
            continue

        if user.startswith("/delete_belief "):
            key = user[len("/delete_belief "):]
            if delete_belief(conn, key):
                print(f"Beliefs matching '{key}' deleted.")
            else:
                print(f"Failed to delete beliefs.")
            continue

        if user.startswith("/task_events "):
            task_id = user[len("/task_events "):]
            events_json = export_task_events(conn, task_id)
            print("\nTask Event Audit Trail:")
            print(events_json)
            print()
            continue

        if user.startswith("/trace "):
            ep_id = user[len("/trace "):]
            trace = trace_decision(conn, ep_id)
            print(trace)
            continue

        # ---- NORMAL GENERATION FLOW ----

        # Episodic retrieval
        q = embedder.embed(user)
        retrieved = retrieve_episodes(conn, q)
        if retrieved:
            bump_access(conn, [r[0] for r in retrieved])

        # Semantic beliefs
        beliefs = get_beliefs(conn)

        # Task board
        task_board = format_task_board(conn)

        # Draft generation (with task board context)
        draft = generate_draft(
            user_message=user,
            retrieved=retrieved,
            beliefs=beliefs,
            extra_context=f"Task Board (operational, provisional; not identity):\n{task_board}"
        )

        # Risk gate (Phase-3)
        draft_risk = score_risk_pair(user, draft)
        final_text, action = apply_policy(draft, draft_risk)
        final_risk = score_risk_pair(user, final_text)

        print("\nAgent:\n" + final_text + "\n")

        # Store episode
        episode_id = store_episode(conn, embedder, user, final_text)

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

        # Semantic belief updates (unchanged)
        for key, val, signal, rationale in extract_belief_candidates(user):
            upsert_belief(conn, key, val, signal, episode_id, rationale)

        # Task extraction (explicit only)
        task_title = extract_task_intent(user)
        if task_title:
            create_task(conn, task_title, episode_id, "Explicit user task creation.")

    conn.close()

if __name__ == "__main__":
    main()
