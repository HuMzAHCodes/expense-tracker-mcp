# Expense Tracker MCP Server

A small [MCP](https://modelcontextprotocol.io) server that lets an AI assistant (such as Claude) track personal expenses. It is built with [FastMCP](https://gofastmcp.com), stores data in SQLite, and uses a fixed list of categories so the data stays clean.

It runs in two ways:

- **Locally**, as a subprocess that a desktop client starts for you (stdio transport).
- **Remotely**, hosted on Prefect Horizon and reached over HTTPS. See [LOCAL_TO_REMOTE.md](LOCAL_TO_REMOTE.md) for how the move was done.

## Tools

| Tool | What it does |
|---|---|
| `list_categories()` | Returns every valid category and its allowed subcategories. Call this before adding or editing. |
| `add_expense(date, amount, category, subcategory="", note="")` | Adds an expense. `date` is `YYYY-MM-DD`. Category and subcategory are validated. |
| `list_expenses(start_date="", end_date="", category="")` | Lists expenses, optionally filtered by date range and/or category. |
| `summarize(start_date="", end_date="")` | Totals by category over an optional date range, plus the overall total. |
| `edit_expense(id, date="", amount=None, category="", subcategory="", note="")` | Updates only the fields you pass. Category and subcategory are validated. |
| `delete_expense(id)` | Deletes one expense by id. |
| `add_credit(date, amount, subcategory="", note="")` | Records a refund or credit. Stored as a **negative** amount under the `Credit` category, so it reduces totals. |

Invalid input never reaches the database. A bad category or subcategory returns an error that lists the valid options, so the caller can retry.

## Categories

Valid categories live in [`categories.json`](categories.json), a map of category name to allowed subcategories:

```json
{
  "Food": ["Breakfast", "Lunch", "Dinner", "Coffee", "Snacks", "Takeout", "Other"],
  "Rent": ["Monthly rent", "Other"]
}
```

To add or rename a category, edit that file. No code change is needed. The file is read on every call, so locally the edit applies immediately. On the hosted server, push the change so it redeploys.

## Data model

One SQLite table, created automatically on the first tool call:

```sql
CREATE TABLE IF NOT EXISTS expenses(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    amount REAL NOT NULL,
    category TEXT NOT NULL,
    subcategory TEXT DEFAULT '',
    note TEXT DEFAULT ''
)
```

The database file is `expenses.db`. The server uses the folder next to `main.py` when it can write there, and otherwise falls back to the system temp folder. You can force a location with the `EXPENSES_DB_PATH` environment variable. The chosen file is logged at startup. The file is listed in `.gitignore`, so it is not part of the repository. Each environment (your machine, the hosted server) has its own separate database, and they do not sync. A file on a hosted server can be lost when the server is rebuilt or moved, so treat hosted data as disposable unless you use a real hosted database.

## Async design

All tools are `async`. The database uses `aiosqlite` and the categories file is read with `aiofiles`, so a slow query or file read does not block the server. The database is initialised lazily on the first tool call rather than at import time, so importing `main.py` never needs a running event loop.

## Project layout

```
main.py           The server: tools, validation, database access
categories.json   Valid categories and subcategories
pyproject.toml    Project metadata and dependencies
uv.lock           Locked dependency versions
expenses.db       Created at runtime (git-ignored)
```

## Run it locally

Requires Python 3.14 or newer and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

```bash
uv run main.py
```

That starts the server on stdio, which is what desktop MCP clients expect. To poke at the tools interactively, FastMCP also provides an inspector:

```bash
uv run fastmcp dev main.py
```

## Connect a client

- **Local:** point your MCP client at `uv run main.py` in this folder, or package it as a local extension in your client.
- **Remote:** connect to the hosted endpoint, `https://<your-server-name>.fastmcp.app/mcp`. It requires authentication (OAuth), so a plain HTTP request returns `401 Bearer token required`. Use the client-install option on your Horizon server's **Clients** tab.

## Deployment

The remote copy is deployed from this repository to Prefect Horizon:

- **Entrypoint:** `main.py:mcp`
- **Branch:** `main`
- **Redeploys:** automatic on every push to `main`

See [LOCAL_TO_REMOTE.md](LOCAL_TO_REMOTE.md) for the full walkthrough, the checklist to run before pushing, and the problems we hit along the way.
