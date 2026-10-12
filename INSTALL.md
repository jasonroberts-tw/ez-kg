# Install ez-kg

You are installing **ez-kg** for the user: a local knowledge graph (one SQLite file with full-text search) wrapped in an MCP server. The user ingests documents and transcripts; the agent reads them in chunks, records entities and relations with a citable quote, then analyses across documents with graph and search tools. The server sends its own usage instructions to the client on connect, so any agent connected to it knows the workflow.

Files, all in the repo directory (the folder holding this file):

- `kg.py`: the graph core, standard library only.
- `server.py`: the MCP server. It declares its `mcp` dependency inline, so `uv run --script` installs it on first launch.
- `kg.db`: the graph data, created on first run next to `server.py`. Set the `KG_DB` environment variable to keep it somewhere else.

## Steps

1. **Locate.** Resolve the repo directory to an absolute path (`REPO`) and the absolute path of `uv` (`UV`, from `command -v uv`). Use these absolute paths in every config below, because GUI clients often launch servers with a minimal `PATH`. Done when both paths exist. If `uv` is missing, ask the user to install it (https://docs.astral.sh/uv/) and wait.

2. **Self-check.** Run `python3 REPO/kg.py` (Python 3.11 or newer). Done when it prints `kg.py self-check ok`.

3. **Ask the user** which MCP clients to connect (the agent harness you are running in, a desktop chat app, an IDE, or several). Also ask whether they want stdio (the default: each client starts its own server process) or one persistent HTTP server shared by several clients. Both modes work on the same `kg.db`.

4. **Connect** each chosen client using that client's own way of registering MCP servers: its CLI command if it has one, otherwise its config file. When editing a config file, merge the new entry and keep every existing server. Name the server `kg`.

   - **stdio:** command `UV`, args `["run", "--script", "REPO/server.py"]`. Many clients use this JSON shape; adapt the keys to the client's format:
     ```json
     { "mcpServers": { "kg": { "command": "UV", "args": ["run", "--script", "REPO/server.py"] } } }
     ```
     For a different data location, add `"env": { "KG_DB": "/abs/path/kg.db" }`.
   - **HTTP:** start the server with `UV run --script REPO/server.py --http` (it listens on `127.0.0.1:8765`; add `--port N` to change that) and keep it running. Then register the streamable HTTP URL `http://127.0.0.1:8765/mcp` in each client.

   GUI clients usually load MCP config only at startup, so the user may need to fully quit and reopen them.

5. **Verify.** Done when each client lists `kg` as connected (its MCP list command or settings view) or its tools appear in a new session. On the first launch, `uv` downloads the `mcp` package, so a slow first connect is normal.

6. **Report** the paths used, the clients connected, where `kg.db` lives, and one example prompt to try:
   > Ingest ~/path/to/transcripts as transcripts, extract people, projects, decisions and risks, then tell me which risks come up in more than one meeting and who raised them.

## Troubleshooting

- **Server fails to start in a GUI client:** a relative `uv` or a relative repo path is the usual cause. Swap in the absolute paths from step 1.
- **HTTP client can't connect:** the `--http` server must already be running. Check with `curl -s http://127.0.0.1:8765/mcp`; any response means it's up.
- **Ingest scope:** text formats (.txt .md .vtt .srt .csv .json .html .rst .log) and .docx are read. Convert PDF files to text first, or pass the text to the `ingest_text` tool.
