# Moving a Local MCP Server to a Remote One

A checklist and field notes from taking this expense tracker from "runs on my laptop" to "hosted on Prefect Horizon". It covers what to change in the code, how to deploy, how to connect a client, and how to check it worked.

Some things below were **observed** on this project rather than documented guarantees. They are marked as such.

## 1. Local vs remote: what actually changes

| | Local | Remote |
|---|---|---|
| How it runs | Your client starts it as a subprocess | A host runs it and serves it over HTTPS |
| Transport | stdio | Streamable HTTP at `/mcp` |
| Auth | None needed | OAuth required |
| Data | Files on your machine | Files (or databases) on the host |
| Updates | Restart the server | Push to Git, host redeploys |

Your tool code stays the same. What changes is where it runs, how clients reach it, and where its data lives.

## 2. Make the code deploy-ready

Work through this before you push.

- [ ] **The server object is at module level** and has a stable name, e.g. `mcp = FastMCP(name="Expense Tracker")`. The host imports `main.py:mcp`.
- [ ] **Dependencies are declared**, not just installed in your venv. Use `uv add <package>` so `pyproject.toml` and `uv.lock` are updated. The host builds from these files.
- [ ] **`requires-python` matches** the Python you developed against.
- [ ] **No absolute local paths.** Build file paths from `Path(__file__).parent`, never from `C:/Users/...`.
- [ ] **Nothing runs at import that needs an event loop.** Do not call `asyncio.run(...)` at module level. Initialise lazily on the first tool call instead. This project does that for its database.
- [ ] **No secrets in the repo.** API keys go in environment variables. Check your host's server settings for where to set them. Never commit a `.env` file.
- [ ] **`.gitignore` covers** `.venv/`, `__pycache__/`, `.env`, and any runtime database.
- [ ] **Remove local-only files.** A local extension `manifest.json` pointing at your machine's paths does nothing on the host and only leaks your folder layout.
- [ ] **Test in-process first.** FastMCP's `Client(mcp)` can call every tool without a network, which catches most bugs before you deploy.

### Sync or async?

Sync tools also work remotely. This project moved to `async def` tools with `aiosqlite` and `aiofiles` so that database and file access never block the server's event loop while other requests are waiting. Remember to `await db.commit()` after writes, because `aiosqlite` does not auto-commit the way `with sqlite3.connect(...)` does.

## 3. Put the code on GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/<you>/<repo>.git
git branch -M main
git push -u origin main
```

Run `git status` before committing and look at what you are about to publish. This project's first push included a local manifest and a database file that were better left out.

## 4. Deploy on Prefect Horizon

Horizon is the new name for FastMCP Cloud, at [horizon.prefect.io](https://horizon.prefect.io).

1. Sign in with GitHub.
2. Authorize Horizon for the repository. Choosing **Only select repositories** is safer than granting access to everything.
3. From the Registry page, click **+ Add server**.
4. Choose **Hosted** (build and publish your own MCP), not External or Remix.
5. Pick the repository and the `main` branch.
6. Set the **entrypoint** to `main.py:mcp` (file name, colon, variable name).
7. Click **Deploy**. Horizon clones the repo, installs from `pyproject.toml` and `uv.lock`, and starts it.

Your endpoint is `https://<server-name>.fastmcp.app/mcp`. It always points at the latest production deployment. **Every push to `main` triggers a new deployment**, and the Deployments page shows each commit hash with a status. Wait for your newest commit to read **Live** before testing.

## 5. Connect a client

The endpoint requires authentication. A plain request returns:

```
HTTP/1.1 401 Unauthorized
{"error":"invalid_request","error_description":"Bearer token required"}
```

That is the server working correctly, not a bug.

To connect Claude Desktop:

1. On the server's **Clients** tab in Horizon, click **Add to Claude Desktop**. This downloads a `.mcpb` file.
2. Do not double-click it in File Explorer. Windows may show an unrelated "How do you want to open this file?" dialog.
3. Open Claude Desktop, then **Settings, Extensions**. The extension appears under installed extensions.

Horizon handles the OAuth sign-in for you.

## 6. Verify it worked

Do all of these. Each one catches something different.

1. **Dashboard:** your latest commit hash shows **Live**.
2. **Auth check:** `curl` the endpoint and confirm you get the `401` above. That proves it is up and protected.
3. **Read test:** call a read-only tool such as `list_categories` or `list_expenses`.
4. **Write test:** add a clearly labelled test row, check it, then delete it. Use notes like `TEST - safe to delete`.
5. **Validation test:** send a bad category and confirm you get the error, not a database row.

Clean up test data afterwards so you do not leave junk on a live server.

## 7. Things to watch for

**Local and remote data are separate copies.** Adding an expense locally does not add it remotely, and vice versa. Decide which one is your real one.

**Two servers with the same tool names.** If you keep the local extension enabled next to the remote one, both expose `add_expense`, `list_expenses`, and so on. Clients may show two near-identical tool sets. Disable the local one while testing the remote so you know which you are hitting.

**Runtime data and Git.** If a database file is tracked in Git, a stray `git add .` can commit your local copy over the deployed one. Add it to `.gitignore` and untrack it with `git rm --cached <file>`, which removes it from the repo but keeps your local file.

**Persistence of the SQLite file (observed, not guaranteed).** On this project the hosted database kept its rows and its `AUTOINCREMENT` counter across two redeploys, including one after the file was removed from the repo. We saw ids continue past a deleted row instead of restarting. Do not rely on that. Hosting platforms can reset local files when they rebuild or move a server. For data you cannot afford to lose, use a hosted database instead of a file on the server.

**Optional arguments and some clients (observed).** With one client we used, tools with optional arguments rejected calls that left them out, with an "expected nonoptional" validation error. Passing the arguments explicitly, using empty strings for the unused ones, worked. It came from the client-side validator, not the Python server. If a client behaves this way, pass every argument.

**Redeploys take a few minutes.** A test right after a push may still hit the previous build. Check the dashboard for your commit before concluding anything.

## 8. Sharing access

The endpoint uses OAuth tied to your Horizon organisation. To let someone else connect:

1. Open the server dashboard, then **Members** under **Access**, and invite them.
2. They accept and sign in to Horizon with their own account.
3. They use the **Clients** tab to install it in their own client.

They connect to the same live server and the same data, not a copy. Turning authentication off would let anyone with the URL connect, so only do that briefly for a demo.

## 9. Quick reference

```bash
# Local run
uv sync
uv run main.py

# Ship a change
git add <files>
git commit -m "Describe the change"
git push origin main
# then wait for the commit to show Live in Horizon

# Stop tracking a file but keep it on disk
git rm --cached <file>
```
