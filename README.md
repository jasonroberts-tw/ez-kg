# ez-kg

Local knowledge graph (SQLite + FTS5) with an MCP server, for cross-document/transcript analysis with any MCP-capable agent.
The agent does the extraction: it reads chunks and writes entities/relations back with doc/chunk/quote provenance.

- `kg.py`: graph core, stdlib only. `python3 kg.py` runs the self-check.
- `server.py`: MCP wrapper (`mcp` 2.x, via uv inline deps). DB defaults to `./kg.db`; override with `KG_DB`.

## Hook up

To have an agent do it: give it [INSTALL.md](INSTALL.md).

stdio: register this command with your MCP client (most accept this JSON shape; use absolute paths):

```json
{ "mcpServers": { "kg": { "command": "uv", "args": ["run", "--script", "/path/to/ez-kg/server.py"] } } }
```

Or as a persistent local server shared by several clients, then register `http://127.0.0.1:8765/mcp` as a streamable HTTP server:

```bash
uv run --script /path/to/ez-kg/server.py --http
```

## Use

> Ingest ~/notes/transcripts as transcripts, extract people, projects, decisions and risks from each, then tell me which risks come up in more than one meeting and who raised them.

Tools: `ingest`, `ingest_text`, `list_documents`, `read_chunks`, `search_text`, `add_facts`, `search_entities`,
`entity`, `neighbors`, `path`, `merge_entities`, `update_entity`, `delete_entity`, `delete_relation`,
`delete_document`, `overview`, `query` (read-only SQL).
