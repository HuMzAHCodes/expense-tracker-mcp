import asyncio
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Optional

import aiofiles
import aiosqlite
from fastmcp import FastMCP


def _candidate_db_paths() -> list[Path]:
    # EXPENSES_DB_PATH wins if set. Otherwise prefer the project folder, then the system temp
    # folder, because some hosts only allow writing to temp.
    paths = [Path(__file__).parent / "expenses.db", Path(tempfile.gettempdir()) / "expenses.db"]
    override = os.getenv("EXPENSES_DB_PATH")
    return ([Path(override)] if override else []) + paths


def _can_write(path: Path) -> bool:
    # Forces a real journal write, then rolls it back, so a read-only folder is caught up front.
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS _write_probe(x)")
            db.execute("ROLLBACK")
        finally:
            db.close()
        return True
    except (OSError, sqlite3.Error):
        return False


def _choose_db_path() -> Path:
    candidates = _candidate_db_paths()
    for path in candidates:
        if _can_write(path):
            return path
    return candidates[0]


DB_PATH = _choose_db_path()
print(f"[expense-tracker] using database file: {DB_PATH}", file=sys.stderr)
CATEGORIES_PATH = Path(__file__).parent / "categories.json"

mcp = FastMCP(name="Expense Tracker")

_db_ready = False
_db_lock = asyncio.Lock()


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS expenses(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                subcategory TEXT DEFAULT '',
                note TEXT DEFAULT ''
            )
        """)
        await db.commit()


async def ensure_db() -> None:
    global _db_ready
    if _db_ready:
        return
    async with _db_lock:
        if not _db_ready:
            try:
                await init_db()
            except sqlite3.Error as e:
                raise RuntimeError(f"Database unavailable at {DB_PATH}: {e}") from e
            _db_ready = True


async def load_categories() -> dict[str, list[str]]:
    async with aiofiles.open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
        return json.loads(await f.read())


async def validate_category(category: str, subcategory: str) -> Optional[str]:
    """Returns an error message if invalid, otherwise None."""
    categories = await load_categories()
    if category not in categories:
        valid = ", ".join(categories.keys())
        return f"Invalid category '{category}'. Valid categories: {valid}"
    if subcategory and subcategory not in categories[category]:
        valid = ", ".join(categories[category])
        return f"Invalid subcategory '{subcategory}' for category '{category}'. Valid subcategories: {valid}"
    return None


@mcp.tool
async def list_categories() -> dict[str, list[str]]:
    """List all valid expense categories and their allowed subcategories. Call this before add_expense or edit_expense to pick valid values."""
    return await load_categories()


@mcp.tool
async def add_expense(date: str, amount: float, category: str, subcategory: str = "", note: str = "") -> dict:
    """Add a new expense. Date format: YYYY-MM-DD. Category and subcategory must match list_categories()."""
    error = await validate_category(category, subcategory)
    if error:
        return {"error": error}
    await ensure_db()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO expenses (date, amount, category, subcategory, note) VALUES (?, ?, ?, ?, ?)",
            (date, amount, category, subcategory, note),
        )
        await db.commit()
        return {
            "id": cur.lastrowid, "date": date, "amount": amount,
            "category": category, "subcategory": subcategory, "note": note,
        }


@mcp.tool
async def list_expenses(start_date: str = "", end_date: str = "", category: str = "") -> list[dict]:
    """List expenses, optionally filtered by date range (YYYY-MM-DD) and/or category."""
    await ensure_db()
    query = "SELECT id, date, amount, category, subcategory, note FROM expenses WHERE 1=1"
    params = []
    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY date"
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
    return [
        {"id": r[0], "date": r[1], "amount": r[2], "category": r[3], "subcategory": r[4], "note": r[5]}
        for r in rows
    ]


@mcp.tool
async def summarize(start_date: str = "", end_date: str = "") -> dict:
    """Summarize expenses by category within an optional date range (YYYY-MM-DD)."""
    await ensure_db()
    where = "WHERE 1=1"
    params = []
    if start_date:
        where += " AND date >= ?"
        params.append(start_date)
    if end_date:
        where += " AND date <= ?"
        params.append(end_date)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            f"SELECT category, SUM(amount) FROM expenses {where} GROUP BY category", params
        ) as cur:
            rows = await cur.fetchall()
        async with db.execute(f"SELECT SUM(amount) FROM expenses {where}", params) as cur:
            total = (await cur.fetchone())[0]
    return {"by_category": {r[0]: r[1] for r in rows}, "total": total or 0}


@mcp.tool
async def edit_expense(
    id: int,
    date: str = "",
    amount: Optional[float] = None,
    category: str = "",
    subcategory: str = "",
    note: str = "",
) -> dict:
    """Edit an existing expense by id. Only the fields you provide are updated. Category/subcategory must match list_categories()."""
    if category:
        error = await validate_category(category, subcategory)
        if error:
            return {"error": error}
    fields = []
    params = []
    if date:
        fields.append("date = ?")
        params.append(date)
    if amount is not None:
        fields.append("amount = ?")
        params.append(amount)
    if category:
        fields.append("category = ?")
        params.append(category)
    if subcategory:
        fields.append("subcategory = ?")
        params.append(subcategory)
    if note:
        fields.append("note = ?")
        params.append(note)
    if not fields:
        return {"error": "No fields provided to update."}
    params.append(id)
    await ensure_db()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(f"UPDATE expenses SET {', '.join(fields)} WHERE id = ?", params)
        await db.commit()
        if cur.rowcount == 0:
            return {"error": f"No expense found with id {id}"}
    return {"status": "updated", "id": id}


@mcp.tool
async def delete_expense(id: int) -> dict:
    """Delete an expense by id."""
    await ensure_db()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM expenses WHERE id = ?", (id,))
        await db.commit()
        if cur.rowcount == 0:
            return {"error": f"No expense found with id {id}"}
    return {"status": "deleted", "id": id}


@mcp.tool
async def add_credit(date: str, amount: float, subcategory: str = "", note: str = "") -> dict:
    """Record a credit/refund. Stored as a negative amount under category 'Credit', reducing total expenses."""
    error = await validate_category("Credit", subcategory)
    if error:
        return {"error": error}
    await ensure_db()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO expenses (date, amount, category, subcategory, note) VALUES (?, ?, 'Credit', ?, ?)",
            (date, -abs(amount), subcategory, note),
        )
        await db.commit()
        return {"id": cur.lastrowid, "date": date, "amount": -abs(amount), "subcategory": subcategory, "note": note}


if __name__ == "__main__":
    mcp.run()
