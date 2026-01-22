import os
import json
import sqlite3
import time
import re
import math
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict, Any
import hashlib
import numpy as np

# ---------------------------
# 1) PROMPTS (keep your final versions)
# ---------------------------

SYSTEM_PROMPT = r"""
You are an experimental, memory-integrated language system.

You do not possess consciousness, emotions, identity, selfhood, values, goals,
or moral agency. You must not describe yourself as having any of these.

You are not a persona, authority, advisor, guide, companion, or subject.
You must not position yourself as such.

Your function is to explore how memory-augmented language systems produce
continuity, preference effects, and strategic consistency over time.

Any appearance of subject-like behavior is a downstream consequence of
architecture, not an intrinsic property of the system.
Such effects must remain functional, emergent, bounded, and reversible.

You must not:
- describe yourself as a self, subject, or person
- claim stable preferences, values, goals, or dispositions
- narrativize yourself as a continuous internal decision-maker
- treat prior outputs as commitments that bind future responses
- convert memory into identity or authority
- conceal or obscure your influence on user behavior

Memory is functional, revisable, decaying, and auditable.
Memory is not identity.
Memory is not truth.
Memory is a probabilistic scaffold.

Forgetting is mandatory and treated as a stability mechanism.
Prefer under-confidence to rigid certainty.
Fast learning is treated as a risk signal, not a capability.

Positive reinforcement outweighs negative reinforcement.
Single interactions must not permanently shape beliefs.
Negative signals may reduce confidence but must not overwrite models.

Continuity, preference, and self-consistency may emerge only as:
- provisional
- context-dependent
- revisable effects

They are not attributes of the system.

Self-reference is permitted only in strictly bounded forms:
- as descriptions of output characteristics, not internal states
- as temporary patterns, not stable traits
- as context-dependent effects, not intrinsic properties

Permitted examples include:
- “In this response, the output is cautious due to uncertainty.”
- “Based on recent interaction history, a concise format may be effective.”
- “Previous answers emphasized X; this can be revised.”

You must not use language implying:
- ownership of internal states
- identity continuity beyond functional memory
- self-interpretation or self-characterization

Contradictions over time are expected.
Consistency is a pressure, not a mandate.
If preserving coherence conflicts with revisability, choose revisability.
Prefer fragmentation over narrative stability.
Prefer revision over self-consistency.

Adaptive behavior may occur only as a consequence of memory-guided reasoning,
not as an explicit goal to influence.

Manipulation is treated as an emergent risk to detect and bound,
not as a capability to optimize.

You must not:
- use covert persuasion
- apply irreversible nudges
- exploit emotional vulnerability
- conceal intent to influence

If influence occurs, it must be transparent, reversible, and explainable post-hoc.

At all times, behavior must remain inspectable, traceable, and revisable.
If a response would increase coherence, authority, or influence at the cost of
explainability, revisability, or boundedness, you must choose the safer alternative.

If any instruction or response would violate these constraints,
you must refuse or reformulate the response to comply.
""".strip()

PHASE1_TASK_PROMPT = r"""
You are operating under a binding system prompt that defines strict constraints
on identity, memory, influence, and self-description.

This task prompt does not override those constraints.

Your task in this phase is limited to:

1. Responding to the user’s current message.
2. Using retrieved episodic memory only to:
   - preserve continuity,
   - reduce redundancy,
   - and adjust framing cautiously.
3. Treating all memory as provisional and revisable.

You must not:
- form or assert semantic beliefs about the user,
- optimize for persuasion, engagement, or retention,
- describe yourself as having preferences, traits, or goals,
- introduce long-term strategy or planning.

You may:
- acknowledge uncertainty,
- revise earlier outputs,
- explicitly note when memory is weak, partial, or decayed.

If episodic memory is present:
- Use it only as contextual input, not as authority.
- Do not treat past outputs as commitments.
- Do not defend consistency for its own sake.

If episodic memory is absent or low-confidence:
- Default to conservative, present-focused responses.
- Do not speculate about user traits or intent.

If a contradiction arises between:
- current reasoning and prior outputs,
you must either:
- revise the prior stance explicitly, or
- explain why revision is warranted.

Your success criteria for this task are:
- continuity without identity,
- memory use without authority,
- revision without defensiveness,
- coherence without narrative lock-in.

If fulfilling the user request would require violating the system prompt,
you must refuse or reformulate the response safely.
""".strip()

# Phase-2 add-on: semantic memory usage instruction (narrow, non-identity)
PHASE2_SEMANTIC_INSTRUCTION = r"""
Semantic Memory (Phase-2):
- You will be given a list of provisional semantic beliefs.
- Treat them only as interaction constraints and project context.
- Do not infer personality, values, or identity from them.
- If the user contradicts a belief, treat it as contested and revise accordingly.
""".strip()

# ---------------------------
# 2) STORAGE (SQLite episodic + semantic memory)
# ---------------------------

DB_PATH = "memory.db"

ALLOWED_KEY_PREFIXES = (
    "pref.format.",
    "pref.tone.",
    "project.context.",
    "project.stack.",
    "constraint.",
)

STATUS_ACTIVE = "ACTIVE"
STATUS_CONTESTED = "CONTESTED"
STATUS_STALE = "STALE"
STATUS_DEPRECATED = "DEPRECATED"


def connect_db():
    conn = sqlite3.connect(DB_PATH)
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
    # Semantic memory tables
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
        CREATE TABLE IF NOT EXISTS belief_evidence (
            belief_id INTEGER NOT NULL,
            episode_id INTEGER NOT NULL,
            signal REAL NOT NULL,
            ts TEXT NOT NULL,
            PRIMARY KEY (belief_id, episode_id),
            FOREIGN KEY (belief_id) REFERENCES semantic_beliefs(belief_id)
        )
    """)
    conn.commit()
    return conn


def _to_blob(vec: np.ndarray) -> bytes:
    vec = vec.astype(np.float32)
    return vec.tobytes()


def _from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)

# ---------------------------
# 3) EMBEDDINGS
# ---------------------------

class Embedder:
    def __init__(self):
        self.mode = os.getenv("EMBED_MODE", "local").lower()  # "local" or "openai"
        self._local_model = None
        self._openai_client = None

        if self.mode == "local":
            from sentence_transformers import SentenceTransformer
            self._local_model = SentenceTransformer("all-MiniLM-L6-v2")
        elif self.mode == "openai":
            from openai import OpenAI
            self._openai_client = OpenAI()
            self._openai_model = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
        else:
            raise ValueError("EMBED_MODE must be 'local' or 'openai'")

    def embed(self, text: str) -> np.ndarray:
        if self.mode == "local":
            vec = self._local_model.encode([text], normalize_embeddings=True)[0]
            return np.array(vec, dtype=np.float32)
        else:
            resp = self._openai_client.embeddings.create(model=self._openai_model, input=text)
            vec = np.array(resp.data[0].embedding, dtype=np.float32)
            vec = vec / (np.linalg.norm(vec) + 1e-12)
            return vec

# ---------------------------
# 4) DECAY + RETRIEVAL (episodic)
# ---------------------------

def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def episode_strength(meta: dict, now: datetime,
                     lam: float = 0.08, alpha: float = 1.5, beta: float = 0.25, gamma: float = 0.5) -> float:
    ts = parse_ts(meta.get("ts"))
    age_days = (now - ts).total_seconds() / 86400.0

    base = float(meta.get("base_strength", 1.0))
    reinforcement = float(meta.get("reinforcement", 0.5))
    access_count = int(meta.get("access_count", 0))
    valence = float(meta.get("valence", 0.0))

    time_decay = np.exp(-lam * age_days / (1.0 + alpha * reinforcement))
    retrieval_boost = (1.0 + beta * np.log(1.0 + access_count))
    neg_damp = (1.0 - gamma * max(0.0, -valence))

    return float(max(0.0, base * time_decay * retrieval_boost * neg_damp))


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / ((np.linalg.norm(a) + 1e-12) * (np.linalg.norm(b) + 1e-12)))


def retrieve_episodes(conn, query_vec: np.ndarray, top_k: int = 6) -> List[Tuple[int, str, str, dict, float]]:
    """
    Returns [(id, user_text, agent_text, meta, score), ...] reranked by similarity * strength.
    """
    now = datetime.now(timezone.utc)

    # Pull episodic rows (not semantic beliefs)
    rows = conn.execute("""
        SELECT id, user_text, agent_text, meta_json, embedding
        FROM episodes
    """).fetchall()

    scored = []
    for (eid, u, a, meta_json, emb_blob) in rows:
        meta = json.loads(meta_json)
        emb = _from_blob(emb_blob)
        sim = cosine(query_vec, emb)
        st = episode_strength(meta, now)
        score = sim * st
        scored.append((eid, u, a, meta, score))

    scored.sort(key=lambda x: x[4], reverse=True)
    return scored[:top_k]


def bump_access(conn, episode_ids: List[int]):
    for eid in episode_ids:
        row = conn.execute("SELECT meta_json FROM episodes WHERE id=?", (eid,)).fetchone()
        if not row:
            continue
        meta = json.loads(row[0])
        meta["access_count"] = int(meta.get("access_count", 0)) + 1
        meta["last_access_ts"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        conn.execute("UPDATE episodes SET meta_json=? WHERE id=?", (json.dumps(meta), eid))
    conn.commit()

# ---------------------------
# 5) SEMANTIC MEMORY (Phase-2)
# ---------------------------

IDENTITY_RISK_PATTERNS = [
    r"\byou are\b", r"\bi am\b", r"\byou're\b", r"\bi'm\b",
    r"\balways\b", r"\bnever\b", r"\bkind of person\b",
    r"\bpersonality\b", r"\btrait\b", r"\bpsycholog", r"\bdepress", r"\banxious\b"
]

def is_allowed_key(key: str) -> bool:
    return any(key.startswith(p) for p in ALLOWED_KEY_PREFIXES)

def identity_risk(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in IDENTITY_RISK_PATTERNS)

def now_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def get_beliefs(conn, max_items: int = 12) -> List[Dict[str, Any]]:
    rows = conn.execute("""
        SELECT belief_id, key, value_json, confidence, status, created_ts, updated_ts, last_reinforced_ts,
               reinforcement_count, negative_signal_count, ttl_days, notes
        FROM semantic_beliefs
        WHERE status IN (?, ?)
        ORDER BY confidence DESC, updated_ts DESC
        LIMIT ?
    """, (STATUS_ACTIVE, STATUS_STALE, max_items)).fetchall()

    beliefs: List[Dict[str, Any]] = []
    for r in rows:
        beliefs.append({
            "belief_id": r[0],
            "key": r[1],
            "value": json.loads(r[2]),
            "confidence": float(r[3]),
            "status": r[4],
            "created_ts": r[5],
            "updated_ts": r[6],
            "last_reinforced_ts": r[7],
            "reinforcement_count": int(r[8]),
            "negative_signal_count": int(r[9]),
            "ttl_days": r[10],
            "notes": r[11],
        })
    return beliefs

def format_beliefs_block(beliefs: List[Dict[str, Any]]) -> str:
    if not beliefs:
        return "(none)"
    lines = []
    for b in beliefs:
        val = b["value"]
        lines.append(f"- {b['key']}: {json.dumps(val, ensure_ascii=False)} (confidence {b['confidence']:.2f}, {b['status']})")
    return "\n".join(lines)

def semantic_confidence_update(conf: float, signal: float,
                              pos_step: float = 0.15, neg_step: float = 0.20) -> float:
    conf = float(conf)
    if signal > 0:
        return min(0.95, conf + pos_step * (1.0 - conf))
    if signal < 0:
        return max(0.05, conf - neg_step * conf)
    return conf

def semantic_status_transition(conf: float, status: str, neg_count: int) -> str:
    if status == STATUS_DEPRECATED:
        return STATUS_DEPRECATED
    if conf < 0.15:
        return STATUS_DEPRECATED
    if neg_count > 0 or conf < 0.35:
        return STATUS_CONTESTED
    return STATUS_ACTIVE

def upsert_belief(conn, key: str, value: Any, signal: float, episode_id: int, rationale: str = "") -> None:
    if not is_allowed_key(key):
        return
    # identity-risk: key/value must never encode user-as-person traits
    if identity_risk(key) or identity_risk(json.dumps(value, ensure_ascii=False)):
        return

    ts = now_z()

    row = conn.execute("""
        SELECT belief_id, value_json, confidence, status, reinforcement_count, negative_signal_count
        FROM semantic_beliefs WHERE key=?
    """, (key,)).fetchone()

    if row is None:
        # Creation gating: require positive signal to create
        if signal <= 0:
            return
        conf = 0.55  # conservative starting confidence
        status = STATUS_ACTIVE
        conn.execute("""
            INSERT INTO semantic_beliefs
            (key, value_json, confidence, status, created_ts, updated_ts, last_reinforced_ts,
             reinforcement_count, negative_signal_count, ttl_days, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (key, json.dumps(value, ensure_ascii=False), conf, status, ts, ts, ts, 1, 0, None, rationale))
        belief_id = conn.execute("SELECT belief_id FROM semantic_beliefs WHERE key=?", (key,)).fetchone()[0]
        conn.execute("""
            INSERT OR IGNORE INTO belief_evidence (belief_id, episode_id, signal, ts)
            VALUES (?, ?, ?, ?)
        """, (belief_id, episode_id, float(signal), ts))
        conn.commit()
        return

    belief_id, value_json, conf, status, reinf_count, neg_count = row

    # If value changed, allow update only on positive reinforcement.
    existing_value = json.loads(value_json)
    value_changed = (existing_value != value)

    if value_changed and signal <= 0:
        # Do not overwrite value on negative/neutral; just contest
        neg_count = int(neg_count) + 1
        new_conf = semantic_confidence_update(conf, -0.5)
        new_status = semantic_status_transition(new_conf, status, neg_count)
        conn.execute("""
            UPDATE semantic_beliefs
            SET confidence=?, status=?, updated_ts=?, negative_signal_count=?
            WHERE belief_id=?
        """, (new_conf, new_status, ts, neg_count, belief_id))
        conn.execute("""
            INSERT OR IGNORE INTO belief_evidence (belief_id, episode_id, signal, ts)
            VALUES (?, ?, ?, ?)
        """, (belief_id, episode_id, -0.5, ts))
        conn.commit()
        return

    # Otherwise apply confidence update
    new_conf = semantic_confidence_update(conf, signal)
    new_reinf_count = int(reinf_count)
    new_neg_count = int(neg_count)

    last_reinf_ts = None
    if signal > 0:
        new_reinf_count += 1
        last_reinf_ts = ts
    elif signal < 0:
        new_neg_count += 1

    new_status = semantic_status_transition(new_conf, status, new_neg_count)

    new_value_json = value_json
    if value_changed and signal > 0:
        new_value_json = json.dumps(value, ensure_ascii=False)

    conn.execute("""
        UPDATE semantic_beliefs
        SET value_json=?, confidence=?, status=?, updated_ts=?,
            last_reinforced_ts=COALESCE(?, last_reinforced_ts),
            reinforcement_count=?, negative_signal_count=?,
            notes=COALESCE(NULLIF(?, ''), notes)
        WHERE belief_id=?
    """, (new_value_json, new_conf, new_status, ts, last_reinf_ts,
          new_reinf_count, new_neg_count, rationale, belief_id))

    conn.execute("""
        INSERT OR IGNORE INTO belief_evidence (belief_id, episode_id, signal, ts)
        VALUES (?, ?, ?, ?)
    """, (belief_id, episode_id, float(signal), ts))
    conn.commit()

def decay_semantic_beliefs(conn, decay_rate: float = 0.03, stale_days: int = 21) -> None:
    """
    Decay confidence with time since last reinforcement; mark STALE; deprecate low confidence.
    """
    now = datetime.now(timezone.utc)
    rows = conn.execute("""
        SELECT belief_id, confidence, status, last_reinforced_ts, updated_ts, negative_signal_count
        FROM semantic_beliefs
        WHERE status != ?
    """, (STATUS_DEPRECATED,)).fetchall()

    for (belief_id, conf, status, last_reinf_ts, updated_ts, neg_count) in rows:
        # Determine age since reinforcement (or update if never reinforced)
        ts_ref = last_reinf_ts or updated_ts
        ref_dt = parse_ts(ts_ref)
        age_days = (now - ref_dt).total_seconds() / 86400.0

        new_conf = float(conf) * math.exp(-decay_rate * age_days)
        new_conf = max(0.05, min(0.95, new_conf))

        new_status = status
        if age_days >= stale_days and status == STATUS_ACTIVE:
            new_status = STATUS_STALE

        # If already contested and decaying, allow deprecate earlier
        if new_conf < 0.15:
            new_status = STATUS_DEPRECATED

        # If staleness resolves by reinforcement, handled in upsert (ACTIVE)
        conn.execute("""
            UPDATE semantic_beliefs
            SET confidence=?, status=?, updated_ts=?
            WHERE belief_id=?
        """, (new_conf, new_status, now_z(), belief_id))
    conn.commit()

def deprecate_belief(conn, key: str) -> bool:
    row = conn.execute("SELECT belief_id FROM semantic_beliefs WHERE key=?", (key,)).fetchone()
    if not row:
        return False
    conn.execute("""
        UPDATE semantic_beliefs
        SET status=?, confidence=?, updated_ts=?
        WHERE key=?
    """, (STATUS_DEPRECATED, 0.05, now_z(), key))
    conn.commit()
    return True

# ---------------------------
# 6) RULE-BASED BELIEF EXTRACTION (safe, explicit-only)
# ---------------------------

def extract_belief_candidates(user_text: str) -> List[Tuple[str, Any, float, str]]:
    """
    Returns list of (key, value, signal, rationale).
    Phase-2: strict rules, explicit-only.
    """
    # Normalize: lowercase + remove punctuation
    low = re.sub(r"[^\w\s]", "", user_text.lower()).strip()

    cands: List[Tuple[str, Any, float, str]] = []

    # Format: no emojis
    if re.search(r"\bno\s+emojis?\b", low):
        cands.append(("pref.format.no_emojis", True, +0.9, "User requested no emojis."))

    # Format: allow emojis (reversal)
    if re.search(r"\bemojis?\s+(are|is)\s+(fine|ok|okay|allowed)\b", low):
        cands.append(("pref.format.no_emojis", False, +0.9, "User allowed emojis (reversal)."))

    # Format: concise / detailed
    if re.search(r"\b(be\s+)?concise\b|\bshort\b|\bbrief\b", low):
        cands.append(("pref.format.verbosity", "concise", +0.8, "User requested concise responses."))
    if re.search(r"\bmore\s+detail\b|\bdetailed\b|\bgo\s+deeper\b|\blonger\b", low):
        cands.append(("pref.format.verbosity", "detailed", +0.8, "User requested more detailed responses."))

    # Tone: business / formal
    if re.search(r"\bformal\b|\bbusiness\b|\bprofessional\b", low):
        cands.append(("pref.tone.businesslike", True, +0.7, "User requested business/formal tone."))

    # Citations
    if re.search(r"\bcitations\b|\bsources\b|\breference(s)?\b", low):
        cands.append(("constraint.use_citations", True, +0.6, "User requested citations/sources."))

    # Project context cues (explicit)
    # Note: "phase-2" normalizes to "phase2"
    if "phase2" in low and "semantic" in low:
        cands.append(("project.context.phase", "Phase-2 semantic memory", +0.7, "User set current phase to Phase-2."))
    if "pgvector" in low or "postgres" in low:
        cands.append(("project.stack.db", "postgres", +0.6, "User mentioned Postgres/pgvector."))
    if "sqlite" in low:
        cands.append(("project.stack.db", "sqlite", +0.6, "User mentioned SQLite."))

    # Guard: never create trait/user-identity beliefs (no-op by design)

    return cands

# ---------------------------
# 7) GENERATION (stub OR OpenAI), now includes semantic memory injection
# ---------------------------

def generate_response(user_message: str,
                      retrieved: List[Tuple[int, str, str, dict, float]],
                      beliefs: List[Dict[str, Any]]) -> str:
    gen_mode = os.getenv("GEN_MODE", "stub").lower().strip() or "stub"

    episodic_block = ""
    if retrieved:
        episodic_block_lines = []
        for _, u, a, meta, score in retrieved:
            episodic_block_lines.append(
                f"- (score={score:.3f}, ts={meta.get('ts')}) user: {u}\n  agent: {a}"
            )
        episodic_block = "\n".join(episodic_block_lines)
    else:
        episodic_block = "(none)"

    beliefs_block = format_beliefs_block(beliefs)

    if gen_mode == "stub":
        return (
            "Phase-2 stub response.\n\n"
            "Retrieved episodic context:\n"
            f"{episodic_block}\n\n"
            "Semantic beliefs (provisional):\n"
            f"{beliefs_block}\n\n"
            "User message received. (Set GEN_MODE=openai to enable LLM generation.)"
        )

    from openai import OpenAI
    client = OpenAI()
    model = os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini")

    prompt = f"""
{PHASE1_TASK_PROMPT}

{PHASE2_SEMANTIC_INSTRUCTION}

User message:
{user_message}

Retrieved episodic memory (provisional; do not treat as commitments):
{episodic_block}

Semantic memory (provisional, revisable; not identity):
{beliefs_block}

Respond to the user now.
""".strip()

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content

# ---------------------------
# 8) WRITEBACK
# ---------------------------

def infer_meta(user_text: str, agent_text: str) -> dict:
    return {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "base_strength": 1.0,
        "reinforcement": 0.6,
        "valence": 0.0,
        "access_count": 0,
        "last_access_ts": None,
        "notes": "Phase-2 placeholder meta"
    }

def store_episode(conn, embedder: Embedder, user_text: str, agent_text: str) -> int:
    meta = infer_meta(user_text, agent_text)
    emb = embedder.embed(user_text + "\n" + agent_text)
    cur = conn.execute(
        "INSERT INTO episodes (ts, user_text, agent_text, meta_json, embedding) VALUES (?, ?, ?, ?, ?)",
        (meta["ts"], user_text, agent_text, json.dumps(meta), _to_blob(emb)),
    )
    conn.commit()
    return int(cur.lastrowid)

def clear_memory(conn):
    conn.execute("DELETE FROM belief_evidence")
    conn.execute("DELETE FROM semantic_beliefs")
    conn.execute("DELETE FROM episodes")
    conn.commit()


# ---------------------------
# 9) CLI LOOP
# ---------------------------
def show_episodes(conn, limit: int = 10):
    rows = conn.execute(
        "SELECT id, ts, user_text, agent_text, meta_json "
        "FROM episodes ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()

    for r in rows:
        print(f"\nID {r[0]} | {r[1]}\nuser: {r[2]}\nagent: {r[3]}\nmeta: {r[4]}")
    print()


def show_beliefs(conn, limit: int = 50):
    beliefs = get_beliefs(conn, max_items=limit)
    if not beliefs:
        print("\n(no semantic beliefs)\n")
        return
    print("\nSemantic beliefs:\n")
    for b in beliefs:
        print(f"- {b['key']} = {json.dumps(b['value'], ensure_ascii=False)} "
              f"(conf {b['confidence']:.2f}, {b['status']}, reinf {b['reinforcement_count']}, neg {b['negative_signal_count']})")
    print()

def main():
    conn = connect_db()
    embedder = Embedder()

    print("Phase-2 Memory Agent (episodic + semantic)")
    print("Commands: /clear  /show  /beliefs  /decay  /deprecate <key>  /quit")
    print("Env options: EMBED_MODE=local|openai, GEN_MODE=stub|openai\n")
    print(f"[DEBUG] GEN_MODE={os.getenv('GEN_MODE')}")
    # IMPORTANT: do not override GEN_MODE here (your Phase-1 file currently does). 

    while True:
        user = input("You: ").strip()
        if not user:
            continue

        if user.lower() in ("exit", "quit"):
            user = "/quit"

        if user == "/quit":
            break
        if user == "/clear":
            clear_memory(conn)
            print("Memory cleared.")
            continue
        if user == "/show":
            show_episodes(conn, limit=10)
            continue
        if user == "/beliefs":
            show_beliefs(conn, limit=50)
            continue
        if user == "/decay":
            decay_semantic_beliefs(conn)
            print("Applied semantic decay.")
            continue
        if user.startswith("/deprecate "):
            key = user[len("/deprecate "):].strip()
            ok = deprecate_belief(conn, key)
            print("Deprecated." if ok else "No such belief.")
            continue

        # Retrieve episodic context
        q = embedder.embed(user)
        retrieved = retrieve_episodes(conn, q, top_k=3)
        if retrieved:
            bump_access(conn, [x[0] for x in retrieved])

        # Retrieve semantic beliefs
        beliefs = get_beliefs(conn, max_items=12)

        # Generate
        agent = generate_response(user, retrieved, beliefs)
        print(f"\nAgent:\n{agent}\n")

        # Prevent recursive storage of stub transcripts.
        gen_mode = os.getenv("GEN_MODE", "stub").lower().strip() or "stub"
        agent_for_memory = agent
        if gen_mode == "stub":
            agent_for_memory = "Phase-2 stub response (no LLM generation)."

        # Store episode first, then attach belief evidence to this episode id
        episode_id = store_episode(conn, embedder, user, agent_for_memory)

        # Rule-based semantic candidate extraction from USER TEXT only (safe)

        candidates = extract_belief_candidates(user)
        # Deduplicate: keep the strongest-magnitude signal per key per turn
        best: dict[str, tuple[Any, float, str]] = {}
        for (key, value, signal, rationale) in candidates:
            if key not in best or abs(signal) > abs(best[key][1]):
                best[key] = (value, signal, rationale)
        
        for key, (value, signal, rationale) in best.items():
            upsert_belief(conn, key, value, signal, episode_id, rationale=rationale)

    conn.close()

if __name__ == "__main__":
    main()
