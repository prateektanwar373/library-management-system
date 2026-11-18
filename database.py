"""Database layer for the Library Management System.

Uses only Python's built-in ``sqlite3`` module. This file contains:

* the SQL schema (4 tables: admins, books, students, transactions)
* connection handling for Flask (one connection per request)
* a small ``transaction`` helper for all-or-nothing updates
* sample data so the dashboard is not empty on first launch
* a command line tool:  ``python database.py``  (initialise / reset the database)
"""
import argparse
import getpass
import os
import secrets
import sqlite3
import sys
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

from flask import current_app, g
from werkzeug.security import generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "instance" / "library.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS admins (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS books (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL CHECK (length(trim(title)) > 0),
    author     TEXT    NOT NULL CHECK (length(trim(author)) > 0),
    isbn       TEXT    NOT NULL UNIQUE,
    category   TEXT    NOT NULL CHECK (length(trim(category)) > 0),
    quantity   INTEGER NOT NULL CHECK (quantity >= 0),
    available  INTEGER NOT NULL CHECK (available >= 0),
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (available <= quantity)
);

CREATE TABLE IF NOT EXISTS students (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT    NOT NULL UNIQUE,
    name       TEXT    NOT NULL CHECK (length(trim(name)) > 0),
    email      TEXT    NOT NULL UNIQUE,
    contact    TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id     INTEGER NOT NULL REFERENCES books(id)    ON DELETE CASCADE,
    student_id  INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    issue_date  TEXT    NOT NULL,
    due_date    TEXT    NOT NULL,
    return_date TEXT,
    status      TEXT    NOT NULL DEFAULT 'Issued' CHECK (status IN ('Issued', 'Returned')),
    CHECK (due_date >= issue_date),
    CHECK ((status = 'Issued'   AND return_date IS NULL)
        OR (status = 'Returned' AND return_date IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_transactions_status  ON transactions(status);
CREATE INDEX IF NOT EXISTS idx_transactions_book    ON transactions(book_id);
CREATE INDEX IF NOT EXISTS idx_transactions_student ON transactions(student_id);
"""

# --------------------------------------------------------------------------
# Sample data (title, author, isbn, category, quantity)
# --------------------------------------------------------------------------
SAMPLE_BOOKS = [
    ("Clean Code", "Robert C. Martin", "9780132350884", "Programming", 4),
    ("The Pragmatic Programmer", "Andrew Hunt, David Thomas", "9780135957059", "Programming", 3),
    ("Introduction to Algorithms", "Thomas H. Cormen et al.", "9780262046305", "Algorithms", 5),
    ("Operating System Concepts", "Abraham Silberschatz et al.", "9781119800361", "Operating Systems", 4),
    ("Database System Concepts", "Abraham Silberschatz et al.", "9780078022159", "Databases", 3),
    ("Computer Networks", "Andrew S. Tanenbaum", "9780132126953", "Networking", 3),
    ("Software Engineering", "Ian Sommerville", "9780133943030", "Software Engineering", 5),
    ("Design Patterns", "Erich Gamma et al.", "9780201633610", "Software Engineering", 2),
    ("Artificial Intelligence: A Modern Approach", "Stuart Russell, Peter Norvig", "9780134610993", "Artificial Intelligence", 3),
    ("Fluent Python", "Luciano Ramalho", "9781492056355", "Programming", 2),
    ("Discrete Mathematics and Its Applications", "Kenneth H. Rosen", "9781259676512", "Mathematics", 4),
    ("The Alchemist", "Paulo Coelho", "9780062315007", "Fiction", 2),
]

# (student_id, name, email, contact)
SAMPLE_STUDENTS = [
    ("STU001", "Aarav Sharma", "aarav.sharma@example.com", "9876500001"),
    ("STU002", "Priya Verma", "priya.verma@example.com", "9876500002"),
    ("STU003", "Rohan Gupta", "rohan.gupta@example.com", "9876500003"),
    ("STU004", "Ananya Singh", "ananya.singh@example.com", "9876500004"),
    ("STU005", "Kabir Mehta", "kabir.mehta@example.com", "9876500005"),
    ("STU006", "Neha Kapoor", "neha.kapoor@example.com", "9876500006"),
    ("STU007", "Ishaan Malhotra", "ishaan.malhotra@example.com", "9876500007"),
    ("STU008", "Simran Kaur", "simran.kaur@example.com", "9876500008"),
]

# (book index, student index, issue offset, due offset, return offset or None)
# Offsets are in days relative to today, so "overdue" stays overdue whenever
# the database is created.
SAMPLE_TRANSACTIONS = [
    (0, 0, -20, -6, None),    # overdue
    (2, 1, -25, -11, -12),    # returned
    (3, 2, -5, 9, None),      # issued
    (6, 3, -3, 11, None),     # issued
    (7, 4, -18, -4, None),    # overdue (Design Patterns, copy 1 of 2)
    (1, 5, -10, 4, None),     # issued
    (9, 6, -30, -16, -20),    # returned
    (8, 1, -2, 12, None),     # issued
    (7, 2, -8, 6, None),      # issued (Design Patterns, copy 2 of 2 -> 0 left)
    (4, 7, -15, -1, -3),      # returned
]


# --------------------------------------------------------------------------
# Connections
# --------------------------------------------------------------------------
def connect(db_path):
    """Open a connection in autocommit mode with foreign keys enforced.

    ``isolation_level=None`` means Python never opens transactions behind our
    back; multi-step changes use the explicit ``transaction`` helper below.
    """
    conn = sqlite3.connect(str(db_path), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    """Return this request's connection (created on first use)."""
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_app(app):
    app.teardown_appcontext(close_db)


@contextmanager
def transaction(conn):
    """All-or-nothing block. ``BEGIN IMMEDIATE`` takes the write lock up front,
    so two simultaneous issues of the last copy cannot both succeed."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


# --------------------------------------------------------------------------
# Initialisation
# --------------------------------------------------------------------------
def seed_sample_data(conn, today=None):
    today = today or date.today()

    def day(offset):
        return None if offset is None else (today + timedelta(days=offset)).isoformat()

    with transaction(conn):
        book_ids = []
        for title, author, isbn, category, qty in SAMPLE_BOOKS:
            cur = conn.execute(
                "INSERT INTO books (title, author, isbn, category, quantity, available) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (title, author, isbn, category, qty, qty),
            )
            book_ids.append(cur.lastrowid)

        student_ids = []
        for sid, name, email, contact in SAMPLE_STUDENTS:
            cur = conn.execute(
                "INSERT INTO students (student_id, name, email, contact) VALUES (?, ?, ?, ?)",
                (sid, name, email, contact),
            )
            student_ids.append(cur.lastrowid)

        for b, s, issued, due, returned in SAMPLE_TRANSACTIONS:
            status = "Returned" if returned is not None else "Issued"
            conn.execute(
                "INSERT INTO transactions (book_id, student_id, issue_date, due_date, return_date, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (book_ids[b], student_ids[s], day(issued), day(due), day(returned), status),
            )
            if status == "Issued":
                conn.execute("UPDATE books SET available = available - 1 WHERE id = ?", (book_ids[b],))


def init_db(db_path=DEFAULT_DB_PATH, admin_username="admin", admin_password=None,
            seed=True, reset=False):
    """Create the tables, the admin account and (optionally) sample data.

    * ``reset=True`` deletes the existing database file first.
    * If ``admin_password`` is given the admin is created, or its password is
      replaced when the username already exists.
    * Sample data is only inserted when the books table is empty.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if reset and db_path.exists():
        db_path.unlink()

    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)

        if admin_password:
            password_hash = generate_password_hash(admin_password)
            existing = conn.execute(
                "SELECT id FROM admins WHERE username = ?", (admin_username,)
            ).fetchone()
            if existing:
                conn.execute("UPDATE admins SET password_hash = ? WHERE id = ?",
                             (password_hash, existing["id"]))
            else:
                conn.execute("INSERT INTO admins (username, password_hash) VALUES (?, ?)",
                             (admin_username, password_hash))
        elif conn.execute("SELECT 1 FROM admins LIMIT 1").fetchone() is None:
            raise ValueError("No admin account exists yet - an admin password is required.")

        seeded = False
        if seed and conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 0:
            seed_sample_data(conn)
            seeded = True
        return seeded
    finally:
        conn.close()


def resolve_admin_credentials(username=None, password=None, allow_prompt=True):
    """Work out the admin username/password without hard-coding any secret.

    Order: command-line value -> LMS_ADMIN_USER / LMS_ADMIN_PASSWORD env vars ->
    interactive hidden prompt -> randomly generated password (printed once).
    Returns ``(username, password, was_generated)``.
    """
    username = username or os.environ.get("LMS_ADMIN_USER") or "admin"
    password = password or os.environ.get("LMS_ADMIN_PASSWORD")
    generated = False

    if password:
        if len(password) < 8:
            raise ValueError("Admin password must be at least 8 characters.")
    elif allow_prompt and sys.stdin is not None and sys.stdin.isatty():
        while True:
            first = getpass.getpass(f"Choose a password for admin '{username}' (min 8 chars): ")
            if len(first) < 8:
                print("  Too short - use at least 8 characters.")
                continue
            if first != getpass.getpass("Repeat the password: "):
                print("  Passwords do not match, try again.")
                continue
            password = first
            break
    else:
        password = secrets.token_urlsafe(9)
        generated = True
    return username, password, generated


def bootstrap_if_missing(db_path):
    """Called by the app on startup: create a database if none exists yet."""
    username, password, generated = resolve_admin_credentials(allow_prompt=False)
    init_db(db_path, username, password)
    print("=" * 64)
    print(f" New database created at: {db_path}")
    print(f" Admin username : {username}")
    if generated:
        print(f" Admin password : {password}   (generated - note it down now)")
    else:
        print(" Admin password : taken from LMS_ADMIN_PASSWORD")
    print("=" * 64)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Initialise the Library Management System database.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="database file (default: instance/library.db)")
    parser.add_argument("--username", help="admin username (default: admin)")
    parser.add_argument("--password", help="admin password (omit to be prompted)")
    parser.add_argument("--reset", action="store_true", help="DELETE the existing database and start fresh")
    parser.add_argument("--no-seed", action="store_true", help="do not insert sample data")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    existing = db_path.exists() and not args.reset
    password_needed = not existing or args.password or args.username

    try:
        if password_needed:
            username, password, generated = resolve_admin_credentials(args.username, args.password)
        else:
            username, password, generated = "admin", None, False
        seeded = init_db(db_path, username, password, seed=not args.no_seed, reset=args.reset)
    except PermissionError:
        print("ERROR: could not replace the database file. Stop the running server (Ctrl+C) and try again.")
        return 1
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"Database ready: {db_path}")
    if password:
        print(f"Admin username: {username}")
        if generated:
            print(f"Admin password (generated, note it down): {password}")
    print("Sample data inserted." if seeded else "No sample data inserted (database already has books, or --no-seed used).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
