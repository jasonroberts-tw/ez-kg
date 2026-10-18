# ez-kg

A local knowledge graph in one SQLite file, served over MCP (Model Context Protocol).
The connected agent does the extraction, so this repo holds only storage, search and traversal.

## Layout

- `kg.py` holds all logic in the `Graph` class.
- `server.py` exposes each `Graph` method as one MCP tool and keeps no logic of its own.
- The tool is deliberately two files. Grow them before adding a module.

## Rules

- `kg.py` stays standard library only, because `python3 kg.py` must run with no install.
- Dependencies go in the inline script block at the top of `server.py`, pinned to an exact version.
- `server.py` uses the `mcp` 2.x API (`MCPServer`), which differs from the 1.x `FastMCP` API. Check the docs for the pinned version before changing server code.
- Wrap every database access in `self.tx()`, because one lock guards the connection that HTTP mode shares across threads.
- `query()` opens a separate read-only connection. That connection is what makes the tool read-only, so keep `query()` off the main connection.
- Look up entities by name through `_resolve()`, because it matches case-insensitively and through aliases.
- Relations and mentions carry the `doc_id` they came from. Replacing or deleting a document deletes them by cascade, while entities survive.
- The `chunks` table is FTS5 (SQLite full-text search), which has no foreign keys. `_delete_doc()` deletes chunks by hand for that reason.
- The schema uses `create table if not exists` with no migrations. A column change will not reach an existing `kg.db`, so a schema change needs a migration step in `Graph.__init__`.
- `# ponytail:` comments mark deliberate shortcuts. Each one names its limit and the upgrade path.

## Testing

- The only test is the self-check at the bottom of `kg.py`. Run `python3 kg.py` and expect `kg.py self-check ok`.
- Every behaviour change in `kg.py` adds an assert to that self-check.
- `server.py` has no test. After changing it, run `uv run --script server.py --http` with `KG_DB` set to a scratch path, and confirm the server starts.

## Keep the docs in sync

Three audiences read this repo:

| File | Reader | Update when |
|---|---|---|
| `server.py` `instructions=` and tool docstrings | the agent using the graph at runtime | tools, tool behaviour or tables change |
| `INSTALL.md` | an agent installing the tool | setup, config or supported formats change |
| `README.md` | a human | tools or hook-up steps change |

The table list in `instructions=` must match `SCHEMA`, because agents write `query` SQL from that list.
A new ingest format touches `TEXT_EXTS`, `read_file()`, the `ingest` docstring and the ingest scope line in `INSTALL.md`.

## Release

Push a `v*` tag. CI then runs `package.ps1` and attaches `ez-kg.zip` to a GitHub release.
The zip holds every top-level `.py` and `.md` file except this one, so a new top-level file of either type ships to users.
