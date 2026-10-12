"""Lightweight knowledge graph over SQLite + FTS5.

Documents are split into chunks (full-text indexed). Entities, relations and
mentions are written by the caller (an agent) with provenance back to a doc/chunk.
"""
import hashlib
import re
import sqlite3
import threading
from collections import deque
from contextlib import contextmanager
from pathlib import Path

TEXT_EXTS = {".txt", ".md", ".markdown", ".vtt", ".srt", ".csv", ".json", ".html", ".rst", ".log"}

SCHEMA = """
create table if not exists docs(
  id integer primary key, title text not null, kind text, source text unique,
  sha text, added text default current_timestamp);
create virtual table if not exists chunks using fts5(doc_id unindexed, seq unindexed, text);
create table if not exists entities(
  id integer primary key, name text not null unique collate nocase, type text, description text);
create table if not exists aliases(
  alias text primary key collate nocase, entity_id int not null references entities on delete cascade);
create table if not exists relations(
  id integer primary key,
  src int not null references entities on delete cascade, rel text not null,
  dst int not null references entities on delete cascade,
  doc_id int references docs on delete cascade, chunk_id int, evidence text not null default '',
  unique(src, rel, dst, doc_id, evidence));
create table if not exists mentions(
  entity_id int not null references entities on delete cascade,
  doc_id int not null references docs on delete cascade, chunk_id int, quote text not null default '',
  unique(entity_id, doc_id, quote));
create index if not exists rel_src on relations(src);
create index if not exists rel_dst on relations(dst);
create index if not exists men_doc on mentions(doc_id);
"""


def chunk(text, size=1500):
    """Split on line boundaries into ~size-char chunks; hard-split lines longer than size."""
    out, buf = [], ""
    for line in text.splitlines(keepends=True):
        for piece in [line[i:i + size] for i in range(0, len(line), size)] or [line]:
            if buf and len(buf) + len(piece) > size:
                out.append(buf)
                buf = ""
            buf += piece
    if buf.strip():
        out.append(buf)
    return out


def _fts_quote(q):
    """Fallback for queries that aren't valid FTS5 syntax: OR the bare words, bm25 ranks the rest."""
    return " OR ".join(f'"{w}"' for w in re.findall(r"\w+", q)) or '""'


class Graph:
    def __init__(self, path):
        self.db_path = str(path)
        self.db = sqlite3.connect(self.db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("pragma foreign_keys = on")
        self.db.execute("pragma journal_mode = wal")
        self.db.executescript(SCHEMA)
        # ponytail: one lock for the whole db, fine for one user; per-connection pool if it ever contends
        self.lock = threading.RLock()

    @contextmanager
    def tx(self):
        with self.lock, self.db:
            yield self.db

    # ---------- documents ----------

    def add_document(self, title, text, kind="document", source=None):
        sha = hashlib.sha256(text.encode()).hexdigest()
        source = source or f"text:{sha[:16]}"
        with self.tx() as db:
            old = db.execute("select id, sha from docs where source = ?", (source,)).fetchone()
            if old and old["sha"] == sha:
                return {"doc_id": old["id"], "status": "unchanged"}
            if old:  # content changed: drop old doc and the facts extracted from it
                self._delete_doc(db, old["id"])
            doc_id = db.execute("insert into docs(title, kind, source, sha) values (?,?,?,?)",
                                (title, kind, source, sha)).lastrowid
            parts = chunk(text)
            db.executemany("insert into chunks(doc_id, seq, text) values (?,?,?)",
                           [(doc_id, i, t) for i, t in enumerate(parts)])
        return {"doc_id": doc_id, "chunks": len(parts), "status": "replaced" if old else "added"}

    def _delete_doc(self, db, doc_id):
        db.execute("delete from chunks where doc_id = ?", (doc_id,))  # fts table, no FK cascade
        return db.execute("delete from docs where id = ?", (doc_id,)).rowcount  # cascades relations/mentions

    def delete_document(self, doc_id):
        """Delete a document, its chunks, and every relation/mention extracted from it."""
        with self.tx() as db:
            return {"deleted": bool(self._delete_doc(db, doc_id))}

    def ingest_path(self, path, kind="document"):
        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(p)
        files = [p] if p.is_file() else sorted(
            f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in TEXT_EXTS)
        return [{"file": str(f), **self.add_document(f.stem, f.read_text(errors="replace"), kind, str(f))}
                for f in files]

    def documents(self):
        with self.tx() as db:
            return [dict(r) for r in db.execute(
                "select d.id, d.title, d.kind, d.source, d.added,"
                " (select count(*) from chunks c where c.doc_id = d.id) chunks,"
                " (select count(distinct entity_id) from mentions m where m.doc_id = d.id) entities"
                " from docs d order by d.id")]

    def read_chunks(self, doc_id, start=0, count=5):
        with self.tx() as db:
            rows = db.execute("select rowid chunk_id, seq, text from chunks where doc_id = ? and seq >= ?"
                              " order by seq limit ?", (doc_id, start, count)).fetchall()
            total = db.execute("select count(*) from chunks where doc_id = ?", (doc_id,)).fetchone()[0]
        return {"doc_id": doc_id, "total_chunks": total, "chunks": [dict(r) for r in rows]}

    def search_text(self, query, limit=10, doc_id=None):
        sql = ("select c.rowid chunk_id, c.doc_id, d.title, c.seq,"
               " snippet(chunks, 2, '[', ']', '…', 32) snippet"
               " from chunks c join docs d on d.id = c.doc_id where chunks match ?"
               + (" and c.doc_id = ?" if doc_id else "") + " order by bm25(chunks) limit ?")
        args = lambda q: (q, doc_id, limit) if doc_id else (q, limit)
        with self.tx() as db:
            try:
                rows = db.execute(sql, args(query)).fetchall()
            except sqlite3.OperationalError:  # natural-language query isn't valid FTS syntax
                rows = db.execute(sql, args(_fts_quote(query))).fetchall()
        return [dict(r) for r in rows]

    # ---------- entities & facts ----------

    def _resolve(self, db, name):
        row = db.execute("select id from entities where name = ?", (name,)).fetchone() or \
            db.execute("select entity_id id from aliases where alias = ?", (name,)).fetchone()
        return row["id"] if row else None

    def _upsert_entity(self, db, name, type=None, description=None):
        name = name.strip()
        if not name:
            raise ValueError("entity name is empty")
        eid = self._resolve(db, name)
        if eid is None:
            return db.execute("insert into entities(name, type, description) values (?,?,?)",
                              (name, type, description)).lastrowid
        db.execute("update entities set type = coalesce(type, ?), description = coalesce(description, ?)"
                   " where id = ?", (type, description, eid))
        return eid

    def add_facts(self, doc_id=None, entities=(), relations=()):
        """entities: [{name, type?, description?, chunk_id?, quote?}]
        relations: [{source, relation, target, chunk_id?, evidence?}] (endpoints auto-created)."""
        added = {"entities": 0, "mentions": 0, "relations": 0}
        with self.tx() as db:
            if doc_id is not None and not db.execute("select 1 from docs where id = ?", (doc_id,)).fetchone():
                raise ValueError(f"no document {doc_id}")
            for e in entities:
                eid = self._upsert_entity(db, e["name"], e.get("type"), e.get("description"))
                added["entities"] += 1
                if doc_id is not None:
                    added["mentions"] += db.execute(
                        "insert or ignore into mentions values (?,?,?,?)",
                        (eid, doc_id, e.get("chunk_id"), e.get("quote") or "")).rowcount
            for r in relations:
                src, dst = self._upsert_entity(db, r["source"]), self._upsert_entity(db, r["target"])
                for eid in (src, dst):
                    if doc_id is not None:
                        db.execute("insert or ignore into mentions(entity_id, doc_id, chunk_id) values (?,?,?)",
                                   (eid, doc_id, r.get("chunk_id")))
                added["relations"] += db.execute(
                    "insert or ignore into relations(src, rel, dst, doc_id, chunk_id, evidence)"
                    " values (?,?,?,?,?,?)",
                    (src, r["relation"].strip().lower(), dst, doc_id, r.get("chunk_id"),
                     r.get("evidence") or "")).rowcount
        return added

    def search_entities(self, query="", type=None, limit=50):
        sql = ("select e.id, e.name, e.type, e.description,"
               " (select count(distinct doc_id) from mentions m where m.entity_id = e.id) docs,"
               " (select count(*) from relations r where r.src = e.id or r.dst = e.id) degree"
               " from entities e where (e.name like ?1 or e.description like ?1"
               "  or e.id in (select entity_id from aliases where alias like ?1))"
               + (" and e.type = ?3 collate nocase" if type else "") + " order by degree desc limit ?2")
        with self.tx() as db:
            return [dict(r) for r in db.execute(sql, (f"%{query}%", limit, type) if type else (f"%{query}%", limit))]

    def entity(self, name, limit=100):
        with self.tx() as db:
            eid = self._resolve(db, name)
            if eid is None:
                return None
            ent = dict(db.execute("select * from entities where id = ?", (eid,)).fetchone())
            ent["aliases"] = [r[0] for r in db.execute("select alias from aliases where entity_id = ?", (eid,))]
            ent["relations"] = [dict(r) for r in db.execute(
                "select r.id relation_id, s.name source, r.rel relation, t.name target, d.title doc, r.doc_id,"
                " r.chunk_id, r.evidence"
                " from relations r join entities s on s.id = r.src join entities t on t.id = r.dst"
                " left join docs d on d.id = r.doc_id where r.src = ?1 or r.dst = ?1 limit ?2", (eid, limit))]
            ent["mentioned_in"] = [dict(r) for r in db.execute(
                "select d.id doc_id, d.title, count(*) mentions,"
                " group_concat(nullif(m.quote, ''), ' | ') quotes"
                " from mentions m join docs d on d.id = m.doc_id where m.entity_id = ? group by d.id", (eid,))]
        return ent

    def merge_entities(self, keep, drop):
        with self.tx() as db:
            k, d = self._resolve(db, keep), self._resolve(db, drop)
            if k is None or d is None:
                raise ValueError(f"unknown entity: {keep if k is None else drop}")
            if k == d:
                return {"merged": False, "reason": "same entity"}
            dname = db.execute("select name from entities where id = ?", (d,)).fetchone()[0]
            for sql in ("update or ignore relations set src = ?1 where src = ?2",
                        "update or ignore relations set dst = ?1 where dst = ?2",
                        "update or ignore mentions set entity_id = ?1 where entity_id = ?2",
                        "update aliases set entity_id = ?1 where entity_id = ?2"):
                db.execute(sql, (k, d))
            db.execute("update entities set type = coalesce(type, (select type from entities where id = ?2)),"
                       " description = coalesce(description, (select description from entities where id = ?2))"
                       " where id = ?1", (k, d))
            db.execute("delete from entities where id = ?", (d,))  # cascades leftover duplicate rows
            db.execute("insert or replace into aliases values (?, ?)", (dname, k))
        return {"merged": True, "kept": keep, "alias_added": dname}

    def update_entity(self, name, new_name=None, type=None, description=None):
        """Overwrite the given fields. A rename keeps the old name as an alias."""
        with self.tx() as db:
            eid = self._resolve(db, name)
            if eid is None:
                raise ValueError(f"unknown entity: {name}")
            old = db.execute("select name from entities where id = ?", (eid,)).fetchone()[0]
            if new_name and new_name.strip() != old:
                new_name = new_name.strip()
                other = self._resolve(db, new_name)
                if other not in (None, eid):
                    raise ValueError(f"{new_name!r} already exists; use merge_entities")
                db.execute("delete from aliases where alias = ?", (new_name,))
                db.execute("update entities set name = ? where id = ?", (new_name, eid))
                if old.lower() != new_name.lower():
                    db.execute("insert or replace into aliases values (?, ?)", (old, eid))
            for col, val in (("type", type), ("description", description)):
                if val is not None:
                    db.execute(f"update entities set {col} = ? where id = ?", (val, eid))
            return dict(db.execute("select * from entities where id = ?", (eid,)).fetchone())

    def delete_entity(self, name):
        """Delete an entity with its aliases, mentions and every relation touching it."""
        with self.tx() as db:
            eid = self._resolve(db, name)
            if eid is None:
                raise ValueError(f"unknown entity: {name}")
            n = db.execute("select count(*) from relations where src = ?1 or dst = ?1", (eid,)).fetchone()[0]
            db.execute("delete from entities where id = ?", (eid,))
        return {"deleted": name, "relations_removed": n}

    def delete_relation(self, relation_id):
        """Delete one relation row (ids come from entity())."""
        with self.tx() as db:
            return {"deleted": bool(db.execute("delete from relations where id = ?", (relation_id,)).rowcount)}

    # ---------- traversal ----------

    def _edges(self, db, ids):
        q = ",".join("?" * len(ids))
        return db.execute(
            f"select r.src, s.name source, r.rel relation, r.dst, t.name target, d.title doc, r.evidence"
            f" from relations r join entities s on s.id = r.src join entities t on t.id = r.dst"
            f" left join docs d on d.id = r.doc_id where r.src in ({q}) or r.dst in ({q})",
            list(ids) * 2).fetchall()

    def neighbors(self, name, depth=1, max_edges=300):
        with self.tx() as db:
            start = self._resolve(db, name)
            if start is None:
                return None
            seen, frontier, edges = {start}, {start}, {}
            for _ in range(depth):
                nxt = set()
                for r in self._edges(db, frontier):
                    edges.setdefault((r["src"], r["relation"], r["dst"]), dict(r))
                    nxt |= {r["src"], r["dst"]} - seen
                seen |= nxt
                frontier = nxt
                if not frontier or len(edges) >= max_edges:
                    break
        out = [{k: v for k, v in e.items() if k not in ("src", "dst")} for e in edges.values()]
        return {"entity": name, "depth": depth, "edges": out[:max_edges], "truncated": len(out) > max_edges}

    def path(self, a, b, max_depth=4):
        """Shortest undirected path between two entities, as a list of edges."""
        with self.tx() as db:
            s, t = self._resolve(db, a), self._resolve(db, b)
            if s is None or t is None:
                raise ValueError(f"unknown entity: {a if s is None else b}")
            prev, frontier = {s: None}, [s]
            for _ in range(max_depth):
                if t in prev:
                    break
                nxt = []
                for r in self._edges(db, frontier):
                    for here, there in ((r["src"], r["dst"]), (r["dst"], r["src"])):
                        if here in prev and there not in prev:
                            prev[there] = (here, r)
                            nxt.append(there)
                frontier = nxt
                if not frontier:
                    break
        if t not in prev:
            return []
        hops, node = [], t
        while prev[node]:
            node, r = prev[node]
            hops.append({k: r[k] for k in ("source", "relation", "target", "doc", "evidence")})
        return hops[::-1]

    # ---------- analysis ----------

    def overview(self, top=20):
        with self.tx() as db:
            one = lambda sql: db.execute(sql).fetchone()[0]
            return {
                "documents": one("select count(*) from docs"),
                "chunks": one("select count(*) from chunks"),
                "entities": one("select count(*) from entities"),
                "relations": one("select count(*) from relations"),
                "entity_types": [dict(r) for r in db.execute(
                    "select coalesce(type, '?') type, count(*) n from entities group by 1 order by n desc")],
                "relation_types": [dict(r) for r in db.execute(
                    "select rel relation, count(*) n from relations group by 1 order by n desc limit ?", (top,))],
                "top_entities": [dict(r) for r in db.execute(
                    "select e.name, e.type, count(distinct m.doc_id) docs from entities e"
                    " join mentions m on m.entity_id = e.id group by e.id order by docs desc limit ?", (top,))],
            }

    def query(self, sql, limit=500):
        """Run read-only SQL against a separate read-only connection."""
        ro = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        ro.row_factory = sqlite3.Row
        try:
            cur = ro.execute(sql)
            return [dict(r) for r in cur.fetchmany(limit)]
        finally:
            ro.close()


if __name__ == "__main__":  # self-check
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        g = Graph(Path(d) / "t.db")
        assert chunk("a\n" * 10, size=4) == ["a\na\n"] * 5
        assert all(len(c) <= 10 for c in chunk("x" * 35, size=10))
        doc = g.add_document("Standup", "Alice: Bob owns the Atlas migration.\nBob: Atlas ships in March.\n",
                             "transcript", "standup.txt")
        assert doc["status"] == "added"
        assert g.add_document("Standup", "Alice: Bob owns the Atlas migration.\nBob: Atlas ships in March.\n",
                              source="standup.txt")["status"] == "unchanged"
        did = doc["doc_id"]
        g.add_facts(did, [{"name": "Alice", "type": "person"}, {"name": "Bob", "type": "person", "quote": "Bob owns"}],
                    [{"source": "Bob", "relation": "OWNS", "target": "Atlas", "evidence": "Bob owns the Atlas migration"},
                     {"source": "Atlas", "relation": "ships_in", "target": "March"}])
        assert g.search_text("atlas migration")[0]["doc_id"] == did
        assert g.search_text("Bob's \"migration")  # bad FTS syntax falls back to quoting
        assert [h["relation"] for h in g.path("Alice", "March")] == []  # Alice has no edges
        assert [h["relation"] for h in g.path("Bob", "March")] == ["owns", "ships_in"]
        assert len(g.neighbors("bob", depth=2)["edges"]) == 2
        g.add_facts(did, [{"name": "Robert"}], [{"source": "Robert", "relation": "owns", "target": "Atlas"}])
        g.merge_entities("Bob", "Robert")
        e = g.entity("robert")  # resolves through alias
        assert e["name"] == "Bob" and "Robert" in e["aliases"]
        assert len([r for r in e["relations"] if r["relation"] == "owns"]) == 2  # distinct evidence kept
        assert g.overview()["entities"] == 4
        assert g.query("select count(*) n from relations")[0]["n"] == 3
        try:
            g.query("delete from relations")
            raise AssertionError("query() must be read-only")
        except sqlite3.OperationalError:
            pass
        g.update_entity("Bob", new_name="Bob Smith", type="engineer")
        e = g.entity("bob")  # old name now an alias
        assert e["name"] == "Bob Smith" and e["type"] == "engineer" and {"Bob", "Robert"} <= set(e["aliases"])
        try:
            g.update_entity("Bob Smith", new_name="Atlas")
            raise AssertionError("rename onto existing entity must fail")
        except ValueError:
            pass
        assert g.delete_relation(e["relations"][0]["relation_id"])["deleted"]
        assert g.delete_entity("March")["relations_removed"] == 1
        assert g.entity("March") is None and g.query("select count(*) n from relations")[0]["n"] == 1
        g.add_document("Standup", "changed", source="standup.txt")  # replaced: old facts dropped
        assert g.query("select count(*) n from relations")[0]["n"] == 0
        other = g.add_document("Other", "Carol joins.", source="other.txt")["doc_id"]
        g.add_facts(other, relations=[{"source": "Carol", "relation": "joins", "target": "Atlas"}])
        assert g.delete_document(other)["deleted"] and not g.search_text("Carol")
        assert g.query("select count(*) n from relations")[0]["n"] == 0
    print("kg.py self-check ok")
