import os
import json
import sqlite3
from datetime import datetime, timezone
from typing import List, Tuple
import numpy as np

# ---------------------------
# 1) PROMPTS (final version)
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

# ---------------------------
# 2) STORAGE (SQLite episodic memory)
# ---------------------------

DB_PATH = "memory.db"

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
            # OpenAI embeddings are already float vectors; normalize for cosine.
            resp = self._openai_client.embeddings.create(model=self._openai_model, input=text)
            vec = np.array(resp.data[0].embedding, dtype=np.float32)
            vec = vec / (np.linalg.norm(vec) + 1e-12)
            return vec

# ---------------------------
# 4) DECAY + RETRIEVAL
# ---------------------------

def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))

def episode_strength(meta: dict, now: datetime,
                     lam: float = 0.08, alpha: float = 1.5, beta: float = 0.25, gamma: float = 0.5) -> float:
    """
    Simple decay-weighted strength:
    - time decay (exponential)
    - positive reinforcement slows decay
    - access_count boosts persistence
    - negative valence dampens
    """
    ts = parse_ts(meta.get("ts"))
    age_days = (now - ts).total_seconds() / 86400.0

    base = float(meta.get("base_strength", 1.0))
    reinforcement = float(meta.get("reinforcement", 0.5))  # 0..1
    access_count = int(meta.get("access_count", 0))
    valence = float(meta.get("valence", 0.0))  # -1..+1

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

    rows = conn.execute("SELECT id, user_text, agent_text, meta_json, embedding FROM episodes").fetchall()
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
# 5) GENERATION (local stub OR OpenAI chat)
# ---------------------------

def generate_response(user_message: str, retrieved: List[Tuple[int, str, str, dict, float]]) -> str:
    """
    Phase-1: keep this simple.
    If you want an actual LLM response, switch GEN_MODE=openai and set OPENAI_API_KEY.
    """
    gen_mode = os.getenv("GEN_MODE", "stub").lower()  # "stub" or "openai"

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

    if gen_mode == "stub":
        # A deterministic placeholder: proves the memory loop works before you plug in an LLM.
        return (
            "Phase-1 stub response.\n\n"
            "Retrieved episodic context:\n"
            f"{episodic_block}\n\n"
            "User message received. (Set GEN_MODE=openai to enable LLM generation.)"
        )

    # OpenAI chat generation
    from openai import OpenAI
    client = OpenAI()
    model = os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini")

    prompt = f"""
{PHASE1_TASK_PROMPT}

User message:
{user_message}

Retrieved episodic memory (provisional; do not treat as commitments):
{episodic_block}

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
# 6) WRITEBACK
# ---------------------------

def infer_meta(user_text: str, agent_text: str) -> dict:
    """
    Phase-1: placeholders only.
    You can later replace with a classifier/LLM judge.
    """
    return {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "base_strength": 1.0,
        "reinforcement": 0.6,  # default mild-positive so memory is stable enough to observe
        "valence": 0.0,
        "access_count": 0,
        "last_access_ts": None,
        "notes": "Phase-1 placeholder meta"
    }

def store_episode(conn, embedder: Embedder, user_text: str, agent_text: str):
    meta = infer_meta(user_text, agent_text)
    # Embed combined content so retrieval brings back the “episode” as a unit.
    emb = embedder.embed(user_text + "\n" + agent_text)
    conn.execute(
        "INSERT INTO episodes (ts, user_text, agent_text, meta_json, embedding) VALUES (?, ?, ?, ?, ?)",
        (meta["ts"], user_text, agent_text, json.dumps(meta), _to_blob(emb)),
    )
    conn.commit()

def clear_memory(conn):
    conn.execute("DELETE FROM episodes")
    conn.commit()

# ---------------------------
# 7) CLI LOOP
# ---------------------------

def main():
    conn = connect_db()
    embedder = Embedder()

    print("Phase-1 Memory Agent")
    print("Commands: /clear  /show  /quit")
    print("Env options: EMBED_MODE=local|openai, GEN_MODE=stub|openai\n")
    os.environ["GEN_MODE"] = os.getenv("GEN_MODE", "stub")
    print(f"[DEBUG] GEN_MODE={os.getenv('GEN_MODE')}")


    while True:
        user = input("You: ").strip()
        if not user:
            continue

        # Allow plain "exit"/"quit" as aliases (do not store them).
        if user.lower() in ("exit", "quit"):
            user = "/quit"

        if user == "/quit":
            break
        if user == "/clear":
            clear_memory(conn)
            print("Memory cleared.")
            continue
        if user == "/show":
            rows = conn.execute(
                "SELECT id, ts, user_text, agent_text, meta_json "
                "FROM episodes ORDER BY id DESC LIMIT 10"
            ).fetchall()
            for r in rows:
                print(f"\nID {r[0]} | {r[1]}\nuser: {r[2]}\nagent: {r[3]}\nmeta: {r[4]}")
            print()
            continue

        q = embedder.embed(user)
        retrieved = retrieve_episodes(conn, q, top_k=3)
        if retrieved:
            bump_access(conn, [x[0] for x in retrieved])

        agent = generate_response(user, retrieved)
        print(f"\nAgent:\n{agent}\n")

        # Prevent recursive storage of stub transcripts.
        gen_mode = os.getenv("GEN_MODE", "stub").lower().strip() or "stub"
        agent_for_memory = agent
        if gen_mode == "stub":
            agent_for_memory = "Phase-1 stub response (no LLM generation)."

        store_episode(conn, embedder, user, agent_for_memory)

    conn.close()

if __name__ == "__main__":
    main()
