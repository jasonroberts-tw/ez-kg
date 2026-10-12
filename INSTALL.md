# Install ez-kg

You are installing **ez-kg** for the user: a local knowledge graph (one SQLite file with full-text search) wrapped in an MCP server. The user ingests documents and transcripts; Claude reads them in chunks, records entities and relations with a citable quote, then analyses across documents with graph and search tools. The server sends its own usage instructions to the client on connect, so the user's Claude knows the workflow once it's hooked up.

Files, all in the repo directory (the folder holding this file):

- `kg.py`: the graph core, standard library only.
- `server.py`: the MCP server. It declares its `mcp` dependency inline, so `uv run --script` installs it on first launch.
- `kg.db`: the graph data, created on first run next to `server.py`. Set the `KG_DB` environment variable to keep it somewhere else.

## Steps

1. **Locate.** Resolve the repo directory to an absolute path (`REPO`) and the absolute path of `uv` (`UV`, from `command -v uv`). Use these absolute paths in every config below, because GUI clients like Claude Desktop launch with a minimal `PATH`. Done when both paths exist. If `uv` is missing, ask the user to install it (https://docs.astral.sh/uv/) and wait.

2. **Self-check.** Run `python3 REPO/kg.py` (Python 3.11 or newer). Done when it prints `kg.py self-check ok`.

3. **Ask the user** which clients to connect: Claude Code, Claude Desktop, or both. Also ask whether they want stdio (the default: each client starts its own server process) or one persistent HTTP server shared by several clients. Both modes work on the same `kg.db`.

4. **Connect** each chosen client:

   - **Claude Code, stdio:**
     ```
     claude mcp add kg -s user -- UV run --script REPO/server.py
     ```
   - **Claude Code, HTTP:** start the server with `UV run --script REPO/server.py --http` (it listens on `127.0.0.1:8765`; add `--port N` to change that), keep it running, then:
     ```
     claude mcp add kg -s user --transport http http://127.0.0.1:8765/mcp
     ```
   - **Claude Desktop:** merge this entry into `mcpServers` in `claude_desktop_config.json`, keeping every existing server. The file is at `~/Library/Application Support/Claude/` on macOS and `%APPDATA%\Claude\` on Windows.
     ```json
     "kg": { "command": "UV", "args": ["run", "--script", "REPO/server.py"] }
     ```
     For a different data location, add `"env": { "KG_DB": "/abs/path/kg.db" }`. The user then fully quits and reopens Claude Desktop.

   To edit Claude Code config files directly rather than through `claude mcp`, use the directory named by `CLAUDE_CONFIG_DIR`, or `~/.claude` when that variable is unset.

5. **Verify.** For Claude Code, run `claude mcp list`. Done when `kg` shows as connected. For Claude Desktop, done when the user sees the `kg` tools in a new chat. On the first launch, `uv` downloads the `mcp` package, so a slow first connect is normal.

6. **Report** the paths used, the clients connected, where `kg.db` lives, and one example prompt to try:
   > Ingest ~/path/to/transcripts as transcripts, extract people, projects, decisions and risks, then tell me which risks come up in more than one meeting and who raised them.

## Troubleshooting

- **Server fails to start in Claude Desktop:** a relative `uv` or a relative repo path is the usual cause. Swap in the absolute paths from step 1.
- **HTTP client can't connect:** the `--http` server must already be running. Check with `curl -s http://127.0.0.1:8765/mcp`; any response means it's up.
- **Ingest scope:** only text formats are read (.txt .md .vtt .srt .csv .json .html .rst .log). Convert PDF and .docx files to text first, or pass the text to the `ingest_text` tool.
