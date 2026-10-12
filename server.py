# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp==2.3.0"]
# ///
"""MCP server exposing the knowledge graph. stdio by default; --http for a local server."""
import argparse
import os
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from kg import Graph

g = Graph(os.environ.get("KG_DB") or Path(__file__).with_name("kg.db"))

mcp = MCPServer("knowledge-graph", instructions="""\
A local knowledge graph built from documents and transcripts.
Workflow:
1. `ingest` files/folders (or `ingest_text`). Re-ingesting an unchanged file is a no-op.
2. `read_chunks` to read a document; extract people, orgs, projects, topics, decisions, claims, dates.
3. Before adding, `search_entities` to reuse existing canonical names (avoid duplicates).
4. `add_facts` with doc_id, chunk_id and a short verbatim quote/evidence so every fact is citable.
   Use short lowercase verb-phrase relations (works_at, decided, disagrees_with, mentions, owns).
5. Analyse with `entity`, `neighbors`, `path`, `search_text`, `overview`, and read-only `query` (SQL).
   Tables: docs, chunks(fts5: rowid, doc_id, seq, text), entities, aliases, relations(src, rel, dst,
   doc_id, chunk_id, evidence), mentions(entity_id, doc_id, chunk_id, quote).
6. Fix mistakes: `merge_entities` (same thing, dropped name becomes alias), `update_entity`,
   `delete_relation` (ids from `entity`), `delete_entity`, `delete_document`.
Cite doc titles and evidence quotes when reporting findings.""")


@mcp.tool()
def ingest(path: str, kind: str = "document") -> list[dict]:
    """Ingest a text file or every text file under a folder (.txt .md .vtt .srt .csv .json .html ...).
    kind: free label, e.g. 'transcript', 'report', 'email'."""
    return g.ingest_path(path, kind)


@mcp.tool()
def ingest_text(title: str, text: str, kind: str = "document", source: str | None = None) -> dict:
    """Ingest raw text (e.g. pasted notes or a transcript fetched from another tool).
    source: stable id (URL, meeting id) so re-ingesting replaces instead of duplicating."""
    return g.add_document(title, text, kind, source)


@mcp.tool()
def list_documents() -> list[dict]:
    """All documents with chunk and extracted-entity counts (0 entities = not yet extracted)."""
    return g.documents()


@mcp.tool()
def read_chunks(doc_id: int, start: int = 0, count: int = 5) -> dict:
    """Read a document's chunks in order, starting at chunk seq `start`."""
    return g.read_chunks(doc_id, start, count)


@mcp.tool()
def search_text(query: str, limit: int = 10, doc_id: int | None = None) -> list[dict]:
    """Full-text search over chunks (SQLite FTS5 syntax: "exact phrase", AND, OR, NOT, prefix*).
    Returns chunk ids with snippets, best match first."""
    return g.search_text(query, limit, doc_id)


@mcp.tool()
def add_facts(doc_id: int | None = None, entities: list[dict[str, Any]] = [],
              relations: list[dict[str, Any]] = []) -> dict:
    """Record extracted knowledge with provenance.
    entities: [{"name", "type"?, "description"?, "chunk_id"?, "quote"?}]
    relations: [{"source", "relation", "target", "chunk_id"?, "evidence"?}]; endpoints auto-created.
    Names resolve case-insensitively and through aliases."""
    return g.add_facts(doc_id, entities, relations)


@mcp.tool()
def search_entities(query: str = "", type: str | None = None, limit: int = 50) -> list[dict]:
    """Find entities by name/alias/description substring, optionally by type. Sorted by degree."""
    return g.search_entities(query, type, limit)


@mcp.tool()
def entity(name: str) -> dict:
    """An entity's details, aliases, all relations with evidence, and the documents mentioning it."""
    return g.entity(name) or {"error": f"no entity named {name!r}"}


@mcp.tool()
def neighbors(name: str, depth: int = 1) -> dict:
    """Edges within `depth` hops of an entity (both directions)."""
    return g.neighbors(name, depth) or {"error": f"no entity named {name!r}"}


@mcp.tool()
def path(source: str, target: str, max_depth: int = 4) -> list[dict]:
    """Shortest chain of relations connecting two entities (empty if none within max_depth)."""
    return g.path(source, target, max_depth)


@mcp.tool()
def merge_entities(keep: str, drop: str) -> dict:
    """Merge `drop` into `keep`: relations and mentions move over, `drop` becomes an alias."""
    return g.merge_entities(keep, drop)


@mcp.tool()
def update_entity(name: str, new_name: str | None = None, type: str | None = None,
                  description: str | None = None) -> dict:
    """Rename or overwrite an entity's type/description. A rename keeps the old name as an alias.
    Fails if new_name is another existing entity (use merge_entities)."""
    return g.update_entity(name, new_name, type, description)


@mcp.tool()
def delete_entity(name: str) -> dict:
    """Delete an entity and all its relations, mentions and aliases."""
    return g.delete_entity(name)


@mcp.tool()
def delete_relation(relation_id: int) -> dict:
    """Delete one relation by id (ids are in `entity` output). To change a relation, delete and re-add."""
    return g.delete_relation(relation_id)


@mcp.tool()
def delete_document(doc_id: int) -> dict:
    """Delete a document, its chunks, and all relations/mentions extracted from it. Entities remain."""
    return g.delete_document(doc_id)


@mcp.tool()
def overview(top: int = 20) -> dict:
    """Counts, entity/relation type distribution, and entities appearing in the most documents."""
    return g.overview(top)


@mcp.tool()
def query(sql: str) -> list[dict]:
    """Read-only SQL for ad-hoc analysis (max 500 rows). See server instructions for tables."""
    return g.query(sql)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    if a.http:
        mcp.run("streamable-http", host="127.0.0.1", port=a.port)
    else:
        mcp.run()
