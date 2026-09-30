"""Structured store (SQLite, stdlib). Tables:
  documents(url, domain, type, title, text, ...)   one row per page, latest extracted text
  chunks(doc_url, i, text, emb) + chunks_fts       ~800-char passages; emb = float32 vector (null if no embed model)
  claims(run, id, url, text, kind, ...)            every claim every run extracted, with its task links
search(): vector cosine when a query vector is given, else FTS5 BM25."""
import array, json, math, sqlite3, threading, time
from .paths import DATA

PATH = DATA / "store.db"
_lock = threading.Lock()
_con = None
SCHEMA = """
create table if not exists documents(url text primary key, domain text, type text, title text, text text, text_hash text,
  via text, indexed_at real);
create table if not exists chunks(id integer primary key, doc_url text, i int, text text, emb blob);
create index if not exists chunks_doc on chunks(doc_url);
create virtual table if not exists chunks_fts using fts5(text, content='chunks', content_rowid='id');
create table if not exists claims(run text, id text, url text, text text, kind text, epistemic text, sentiment int,
  prices text, tasks text, query text, created real, primary key(run, id));
"""


def con():
    global _con
    if _con is None:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        _con = sqlite3.connect(PATH, check_same_thread=False)
        _con.row_factory = sqlite3.Row
        _con.executescript(SCHEMA)
    return _con


def chunk(text, size=800):
    out, cur = [], ""
    for p in (p.strip() for p in text.split("\n")):
        if not p:
            continue
        if cur and len(cur) + len(p) > size:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n{p}" if cur else p
    return out + [cur] if cur else out


def needs_index(url, text_hash):
    r = con().execute("select text_hash from documents where url=?", (url,)).fetchone()
    return not r or r[0] != text_hash


def put_document(doc: dict, chunks: list[str], embs: list | None):
    """doc: url, domain, type, title, text, text_hash, via. Replaces the doc's previous chunks."""
    with _lock, con() as c:
        c.execute("insert or replace into documents values(:url,:domain,:type,:title,:text,:text_hash,:via,:t)", {**doc, "t": time.time()})
        for rid, txt in c.execute("select id, text from chunks where doc_url=?", (doc["url"],)).fetchall():
            c.execute("insert into chunks_fts(chunks_fts, rowid, text) values('delete', ?, ?)", (rid, txt))
        c.execute("delete from chunks where doc_url=?", (doc["url"],))
        for i, t in enumerate(chunks):
            e = array.array("f", embs[i]).tobytes() if embs else None
            rid = c.execute("insert into chunks(doc_url, i, text, emb) values(?,?,?,?)", (doc["url"], i, t, e)).lastrowid
            c.execute("insert into chunks_fts(rowid, text) values(?,?)", (rid, t))


def put_claims(run, query, claims: list[dict]):
    with _lock, con() as c:
        c.executemany("insert or replace into claims values(?,?,?,?,?,?,?,?,?,?,?)",
                      [(run, x["id"], x["url"], x["text"], x["kind"], x["epistemic"], x["sentiment"], json.dumps(x["prices"]),
                        json.dumps(x["tasks"]), query, time.time()) for x in claims])


def _row(r, score):
    return {"url": r["doc_url"], "title": r["title"], "domain": r["domain"], "type": r["type"], "text": r["text"], "score": round(score, 4)}


def search(q: str, k=10, qvec=None):
    c = con()
    if qvec:
        # ponytail: brute-force cosine in Python, fine to ~100k chunks; switch to sqlite-vec beyond that
        qn = math.sqrt(sum(x * x for x in qvec)) or 1
        scored = []
        for r in c.execute("select c.doc_url, c.text, c.emb, d.title, d.domain, d.type from chunks c "
                           "join documents d on d.url=c.doc_url where c.emb is not null"):
            v = array.array("f", r["emb"])
            scored.append((sum(a * b for a, b in zip(qvec, v)) / (qn * (math.sqrt(sum(x * x for x in v)) or 1)), r))
        scored.sort(key=lambda x: -x[0])
        return [_row(r, s) for s, r in scored[:k]]
    terms = " OR ".join('"' + w + '"' for w in q.replace('"', " ").split() if len(w) > 2)
    if not terms:
        return []
    rows = c.execute("select c.doc_url, c.text, d.title, d.domain, d.type, bm25(chunks_fts) s from chunks_fts "
                     "join chunks c on c.id=chunks_fts.rowid join documents d on d.url=c.doc_url "
                     "where chunks_fts match ? order by s limit ?", (terms, k)).fetchall()
    return [_row(r, -r["s"]) for r in rows]


def claims(q="", kind="", k=50):
    sql, args = "select * from claims where 1", []
    if q:
        sql += " and text like ?"
        args.append(f"%{q}%")
    if kind:
        sql += " and kind=?"
        args.append(kind)
    return [dict(r) for r in con().execute(sql + " order by created desc limit ?", (*args, k))]


def stats():
    c = con()
    def n(sql): return c.execute(sql).fetchone()[0]
    return {"documents": n("select count(*) from documents"), "chunks": n("select count(*) from chunks"),
            "embedded_chunks": n("select count(*) from chunks where emb is not null"), "claims": n("select count(*) from claims"),
            "runs": n("select count(distinct run) from claims"), "path": str(PATH)}


if __name__ == "__main__":
    import tempfile, pathlib
    PATH = pathlib.Path(tempfile.mkdtemp()) / "t.db"
    assert chunk("a" * 500 + "\n" + "b" * 500 + "\nc") == ["a" * 500, "b" * 500 + "\nc"]
    d = {"url": "u", "domain": "d", "type": "news", "title": "t", "text": "x", "text_hash": "h", "via": "direct"}
    put_document(d, ["scooter rental prices in Bengaluru", "weather report"], [[1, 0], [0, 1]])
    put_document(d, ["scooter rental prices in Bengaluru", "weather report"], [[1, 0], [0, 1]])   # re-index replaces
    assert stats()["chunks"] == 2 and not needs_index("u", "h") and needs_index("u", "h2")
    assert search("scooter prices")[0]["text"].startswith("scooter")
    assert search("", qvec=[0.9, 0.1])[0]["text"].startswith("scooter")
    put_claims("r1", "q", [{"id": "c1", "url": "u", "text": "Rent is 1499", "kind": "fact", "epistemic": "reported",
                            "sentiment": 0, "prices": [], "tasks": ["t1"]}])
    assert claims("Rent")[0]["id"] == "c1"
    print("store self-check ok")
