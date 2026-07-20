"""
Retry specific failed sessions with aggressive batching and pauses.
"""
import json, sqlite3, time, urllib.request
from pathlib import Path

EVEROS_URL = "http://127.0.0.1:8000"
DB_PATH = Path.home() / ".local/share/opencode/opencode.db"
CKPT_PATH = Path.home() / ".everos/.import_checkpoint.json"
USER_ID = "mengzhilu"

done = set(json.loads(CKPT_PATH.read_text()))

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT id, title FROM session ORDER BY time_created DESC").fetchall()
conn.close()

failed = [dict(r) for r in rows if r["id"] not in done]
print(f"{len(failed)} failed: {[s['title'][:50] for s in failed]}")

for s in failed:
    print(f"\n[{s['title'][:60]}]")
    # Get messages
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    msgs = conn.execute("""
        SELECT m.id, json_extract(m.data,'$.role') as role,
               json_extract(m.data,'$.time.created') as created
        FROM message m WHERE m.session_id=? ORDER BY created ASC
    """, (s["id"],)).fetchall()

    texts = []
    for msg in msgs:
        parts = conn.execute(
            "SELECT json_extract(data,'$.text') as content FROM part "
            "WHERE message_id=? AND json_extract(data,'$.type')='text'",
            (msg["id"],)
        ).fetchall()
        combined = " ".join(p["content"] for p in parts if p["content"])
        if combined.strip():
            texts.append({
                "sender_id": USER_ID,
                "role": "user" if msg["role"] == "user" else "assistant",
                "timestamp": int(msg["created"] or 0),
                "content": combined.strip(),
            })
    conn.close()

    print(f"  total msgs: {len(texts)}")

    # Send in batches of 10 with 2 second pauses
    BATCH = 10
    session_id = f"oc-{s['id']}"
    ok = True
    for i in range(0, len(texts), BATCH):
        batch = texts[i:i+BATCH]
        payload = json.dumps({
            "session_id": session_id,
            "app_id": "opencode",
            "project_id": "noctua",
            "messages": batch,
        }).encode()

        for attempt in range(5):
            try:
                req = urllib.request.Request(
                    f"{EVEROS_URL}/api/v1/memory/add",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=60) as resp:
                    r = json.loads(resp.read())
                    if r.get("error"):
                        raise Exception(r["error"])
                    print(f"  batch {i//BATCH+1}/{-(-len(texts)//BATCH)} OK")
                    break
            except Exception as e:
                wait = 3 * (attempt + 1)
                if attempt < 4:
                    print(f"  batch {i//BATCH+1} retry {attempt+1} in {wait}s")
                    time.sleep(wait)
                else:
                    print(f"  batch {i//BATCH+1} FAILED: {e}")
                    ok = False
        if ok:
            time.sleep(1.5)
        else:
            break

    if ok:
        done.add(s["id"])
        CKPT_PATH.write_text(json.dumps(list(done)))
        print(f"  SAVED")
    else:
        print(f"  SKIPPED (partial failure)")

print(f"\nFinal: {len(done)}/{len(rows)} in checkpoint")
