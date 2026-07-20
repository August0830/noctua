"""
Batch import OpenCode sessions into EverOS memory.
Reads ~/.local/share/opencode/opencode.db, extracts text messages per session,
and POSTs them to local EverOS server.
"""
import json
import sqlite3
import sys
import urllib.request
import time
from pathlib import Path

EVEROS_URL = "http://127.0.0.1:8000"
DB_PATH = Path.home() / ".local/share/opencode/opencode.db"
CHECKPOINT_PATH = Path.home() / ".everos/.import_checkpoint.json"
USER_ID = "mengzhilu"
BATCH_SIZE = 25
MAX_RETRIES = 5


def get_sessions(db_path: Path, limit: int | None = None) -> list[dict]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    query = """
        SELECT id, title, directory, time_created
        FROM session
        ORDER BY time_created DESC
    """
    if limit:
        query += f" LIMIT {limit}"
    rows = conn.execute(query).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_text_messages(db_path: Path, session_id: str) -> list[dict]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    query = """
        SELECT
            m.id AS msg_id,
            json_extract(m.data, '$.role') AS role,
            json_extract(m.data, '$.time.created') AS created_ms,
            json_extract(m.data, '$.agent') AS agent
        FROM message m
        WHERE m.session_id = ?
        ORDER BY created_ms ASC
    """
    messages = conn.execute(query, (session_id,)).fetchall()

    results = []
    for msg in messages:
        msg_id = msg["msg_id"]
        role = msg["role"]
        created_ms = msg["created_ms"] or 0

        parts_query = """
            SELECT json_extract(data, '$.text') AS content
            FROM part
            WHERE message_id = ? AND json_extract(data, '$.type') = 'text'
        """
        parts = conn.execute(parts_query, (msg_id,)).fetchall()

        combined = " ".join(p["content"] for p in parts if p["content"])
        if combined.strip():
            results.append({
                "role": role,
                "content": combined.strip(),
                "timestamp_ms": int(created_ms),
            })

    conn.close()
    return results


def post_to_everos(session: dict, messages: list[dict]) -> bool:
    """Send messages in 50-msg batches with retry on failure."""
    session_id = f"oc-{session['id']}"
    overall_ok = True

    for batch_start in range(0, len(messages), BATCH_SIZE):
        batch = messages[batch_start:batch_start + BATCH_SIZE]
        everos_messages = []
        for m in batch:
            everos_role = "user" if m["role"] == "user" else "assistant"
            everos_messages.append({
                "sender_id": USER_ID,
                "role": everos_role,
                "timestamp": m["timestamp_ms"],
                "content": m["content"],
            })

        payload = json.dumps({
            "session_id": session_id,
            "app_id": "opencode",
            "project_id": "noctua",
            "messages": everos_messages,
        }).encode("utf-8")

        ok = False
        for attempt in range(MAX_RETRIES):
            try:
                req = urllib.request.Request(
                    f"{EVEROS_URL}/api/v1/memory/add",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=300) as resp:
                    result = json.loads(resp.read())
                    if result.get("error"):
                        print(f"  batch {batch_start//BATCH_SIZE+1}/{-( -len(messages)//BATCH_SIZE)} "
                              f"error (attempt {attempt+1}): {result['error']}")
                        time.sleep(2 ** attempt)
                        continue
                    ok = True
                    break
            except Exception as e:
                wait = 2 ** attempt
                print(f"  batch {batch_start//BATCH_SIZE+1} retry {attempt+1}/{MAX_RETRIES} "
                      f"after {wait}s: {e}")
                time.sleep(wait)

        if not ok:
            print(f"  batch FAILED after {MAX_RETRIES} retries")
            overall_ok = False

    return overall_ok


def main():
    print("Checking EverOS health...")
    try:
        with urllib.request.urlopen(f"{EVEROS_URL}/health", timeout=5) as resp:
            print(f"  EverOS: {json.loads(resp.read())}")
    except Exception as e:
        print(f"  EverOS not reachable: {e}")
        sys.exit(1)

    # Load checkpoint
    done_ids = set()
    if CHECKPOINT_PATH.exists():
        try:
            done_ids = set(json.loads(CHECKPOINT_PATH.read_text()))
            print(f"  Resume: {len(done_ids)} sessions already imported, skipping")
        except Exception:
            pass

    def save_checkpoint():
        CHECKPOINT_PATH.write_text(json.dumps(list(done_ids)))

    sessions = get_sessions(DB_PATH)
    print(f"\nFound {len(sessions)} sessions in OpenCode DB\n")

    imported = 0
    skipped = 0
    total_msgs = 0
    start_time = time.time()

    for i, s in enumerate(sessions):
        if s["id"] in done_ids:
            skipped += 1
            continue

        messages = get_text_messages(DB_PATH, s["id"])
        if not messages:
            done_ids.add(s["id"])
            save_checkpoint()
            skipped += 1
            continue

        ts = s["time_created"]
        date_str = time.strftime("%Y-%m-%d", time.gmtime(ts / 1000)) if ts else "?"
        title = s["title"][:60]
        directory = s.get("directory", "") or ""
        dir_short = directory.replace(str(Path.home()), "~") if directory else ""

        elapsed = time.time() - start_time
        remaining = len(sessions) - i - 1
        eta = (elapsed / (imported + 1)) * remaining if imported > 0 else 0
        print(f"[{i+1}/{len(sessions)}] {date_str} | {title}")
        print(f"  dir: {dir_short}  |  msgs: {len(messages)}  |  "
              f"elapsed: {elapsed:.0f}s  eta: {eta:.0f}s")

        if post_to_everos(s, messages):
            imported += 1
            total_msgs += len(messages)
            done_ids.add(s["id"])
            save_checkpoint()
        else:
            skipped += 1

        time.sleep(0.05)

    total_time = time.time() - start_time
    print(f"\n--- Done: {imported} new + {len(done_ids)} total ({total_msgs} msgs) in {total_time:.0f}s ---")
    print(f"    skipped/failed: {skipped}")
    print(f"    checkpoint: {CHECKPOINT_PATH}")
    print(f"\nMessages buffered. cascade watcher extracts in background.")


if __name__ == "__main__":
    main()
