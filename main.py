import json
import sqlite3
from pathlib import Path
from typing import Optional
from fastmcp import FastMCP

DB_PATH = Path(__file__).parent / "expenses.db"
CATEGORIES_PATH = Path(__file__).parent / "categories.json"

mcp = FastMCP(name="Expense Tracker")


def init_db():
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS expenses(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                subcategory TEXT DEFAULT '',
                note TEXT DEFAULT ''
            )
        """)


def load_categories() -> dict[str, list[str]]:
    with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


init_db()


def validate_category(category: str, subcategory: str) -> Optional[str]:
    """Returns an error message if invalid, otherwise None."""
    categories = load_categories()
    if category not in categories:
        valid = ", ".join(categories.keys())
        return f"Invalid category '{category}'. Valid categories: {valid}"
    if subcategory and subcategory not in categories[category]:
        valid = ", ".join(categories[category])
        return f"Invalid subcategory '{subcategory}' for category '{category}'. Valid subcategories: {valid}"
    return None


@mcp.tool
def list_categories() -> dict[str, list[str]]:
    """List all valid expense categories and their allowed subcategories. Call this before add_expense or edit_expense to pick valid values."""
    return load_categories()


@mcp.tool
def add_expense(date: str, amount: float, category: str, subcategory: str = "", note: str = "") -> dict:
    """Add a new expense. Date format: YYYY-MM-DD. Category and subcategory must match list_categories()."""
    error = validate_category(category, subcategory)
    if error:
        return {"error": error}
    with sqlite3.connect(DB_PATH) as c:
        cur = c.execute(
            "INSERT INTO expenses (date, amount, category, subcategory, note) VALUES (?, ?, ?, ?, ?)",
            (date, amount, category, subcategory, note),
        )
        return {
            "id": cur.lastrowid, "date": date, "amount": amount,
            "category": category, "subcategory": subcategory, "note": note,
        }


@mcp.tool
def list_expenses(start_date: str = "", end_date: str = "", category: str = "") -> list[dict]:
    """List expenses, optionally filtered by date range (YYYY-MM-DD) and/or category."""
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
    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute(query, params).fetchall()
    return [
        {"id": r[0], "date": r[1], "amount": r[2], "category": r[3], "subcategory": r[4], "note": r[5]}
        for r in rows
    ]


@mcp.tool
def summarize(start_date: str = "", end_date: str = "") -> dict:
    """Summarize expenses by category within an optional date range (YYYY-MM-DD)."""
    where = "WHERE 1=1"
    params = []
    if start_date:
        where += " AND date >= ?"
        params.append(start_date)
    if end_date:
        where += " AND date <= ?"
        params.append(end_date)
    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute(f"SELECT category, SUM(amount) FROM expenses {where} GROUP BY category", params).fetchall()
        total = c.execute(f"SELECT SUM(amount) FROM expenses {where}", params).fetchone()[0]
    return {"by_category": {r[0]: r[1] for r in rows}, "total": total or 0}


@mcp.tool
def edit_expense(
    id: int,
    date: str = "",
    amount: Optional[float] = None,
    category: str = "",
    subcategory: str = "",
    note: str = "",
) -> dict:
    """Edit an existing expense by id. Only the fields you provide are updated. Category/subcategory must match list_categories()."""
    if category:
        error = validate_category(category, subcategory)
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
    with sqlite3.connect(DB_PATH) as c:
        cur = c.execute(f"UPDATE expenses SET {', '.join(fields)} WHERE id = ?", params)
        if cur.rowcount == 0:
            return {"error": f"No expense found with id {id}"}
    return {"status": "updated", "id": id}


@mcp.tool
def delete_expense(id: int) -> dict:
    """Delete an expense by id."""
    with sqlite3.connect(DB_PATH) as c:
        cur = c.execute("DELETE FROM expenses WHERE id = ?", (id,))
        if cur.rowcount == 0:
            return {"error": f"No expense found with id {id}"}
    return {"status": "deleted", "id": id}


@mcp.tool
def add_credit(date: str, amount: float, subcategory: str = "", note: str = "") -> dict:
    """Record a credit/refund. Stored as a negative amount under category 'Credit', reducing total expenses."""
    error = validate_category("Credit", subcategory)
    if error:
        return {"error": error}
    with sqlite3.connect(DB_PATH) as c:
        cur = c.execute(
            "INSERT INTO expenses (date, amount, category, subcategory, note) VALUES (?, ?, 'Credit', ?, ?)",
            (date, -abs(amount), subcategory, note),
        )
        return {"id": cur.lastrowid, "date": date, "amount": -abs(amount), "subcategory": subcategory, "note": note}


if __name__ == "__main__":
    mcp.run()
