"""SQL execution tool wrapped as a LangChain @tool."""

import json
import sqlite3
from typing import Any
from langchain_core.tools import tool

from db.init_db import DB_PATH


@tool
def execute_sql_query(query: str) -> str:
    """
    Execute a read-only SQL query against the operation_metrics database
    and return results as a JSON string.

    Args:
        query: A valid SQL SELECT statement.

    Returns:
        JSON-encoded list of row dicts, or an explicit error message string.
    """
    query_stripped: str = query.strip().upper()
    if not query_stripped.startswith("SELECT"):
        return json.dumps(
            {"error": "Only SELECT queries are allowed."},
            ensure_ascii=False,
        )

    try:
        conn: sqlite3.Connection = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor: sqlite3.Cursor = conn.cursor()
        cursor.execute(query)
        rows: list[sqlite3.Row] = cursor.fetchall()
        result: list[dict[str, Any]] = [dict(r) for r in rows]
        conn.close()
        return json.dumps(result, ensure_ascii=False, default=str)
    except sqlite3.OperationalError as e:
        error_msg: str = f"SQL syntax error: {e}"
        return json.dumps({"error": error_msg}, ensure_ascii=False)
    except sqlite3.DatabaseError as e:
        error_msg: str = f"Database error: {e}"
        return json.dumps({"error": error_msg}, ensure_ascii=False)
    except Exception as e:
        error_msg: str = f"Unexpected error: {e}"
        return json.dumps({"error": error_msg}, ensure_ascii=False)
