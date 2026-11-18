"""Library Management System - Flask application (routes and business rules).

Run with:  python app.py
"""
import hmac
import os
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import (Flask, abort, flash, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash

import database
import validators
from database import get_db, transaction

DEFAULT_LOAN_DAYS = 14
MAX_LOAN_DAYS = 90

BOOK_UNIQUE = {"books.isbn": ("isbn", "A book with this ISBN already exists.")}
STUDENT_UNIQUE = {
    "students.student_id": ("student_id", "This student ID is already registered."),
    "students.email": ("email", "This email address is already registered."),
}


class BusinessError(Exception):
    """A rule of the library was broken (e.g. no copies left)."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def get_secret_key(instance_dir):
    """Secret key for signing session cookies: env var, else a random key that
    is generated once and stored in instance/secret_key (never in the code)."""
    env_key = os.environ.get("LMS_SECRET_KEY")
    if env_key:
        return env_key
    key_file = Path(instance_dir) / "secret_key"
    if key_file.exists():
        return key_file.read_text().strip()
    key = secrets.token_hex(32)
    key_file.write_text(key)
    return key


def like_pattern(text):
    """Turn user text into a safe LIKE pattern (escape % _ and backslash)."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def unique_violations(exc, mapping):
    """Translate a UNIQUE constraint failure into friendly per-field errors."""
    message = str(exc)
    errors = {col_field: text for column, (col_field, text) in mapping.items() if column in message}
    if not errors:
        raise exc
    return errors


def today():
    return date.today()


def safe_next(default):
    """Only allow redirects to paths inside this site."""
    target = request.form.get("next", "")
    if target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return default


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "admin_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def fetch_transactions(db, today_date, status="", q="", order="t.id DESC"):
    """Transactions joined with book + student, with overdue info computed in SQL.
    Only fixed SQL fragments are concatenated; every value is a bound parameter."""
    sql = """
        SELECT t.id, t.issue_date, t.due_date, t.return_date, t.status,
               b.id AS book_id, b.title, b.isbn,
               s.id AS student_pk, s.student_id AS roll_no, s.name AS student_name, s.contact,
               CASE WHEN t.status = 'Issued' AND t.due_date < :today THEN 1 ELSE 0 END AS is_overdue,
               CASE WHEN t.status = 'Issued' AND t.due_date < :today
                    THEN CAST(julianday(:today) - julianday(t.due_date) AS INTEGER)
                    ELSE 0 END AS days_overdue
        FROM transactions t
        JOIN books b    ON b.id = t.book_id
        JOIN students s ON s.id = t.student_id
        WHERE 1 = 1
    """
    params = {"today": today_date.isoformat()}
    if status == "issued":
        sql += " AND t.status = 'Issued'"
    elif status == "returned":
        sql += " AND t.status = 'Returned'"
    elif status == "overdue":
        sql += " AND t.status = 'Issued' AND t.due_date < :today"
    if q:
        sql += (" AND (b.title LIKE :q ESCAPE '\\' OR s.name LIKE :q ESCAPE '\\'"
                " OR s.student_id LIKE :q ESCAPE '\\')")
        params["q"] = like_pattern(q)
    sql += f" ORDER BY {order}"  # `order` is chosen from fixed values in this file only
    return db.execute(sql, params).fetchall()


# --------------------------------------------------------------------------
# Application factory
# --------------------------------------------------------------------------
def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        DATABASE=str(database.DEFAULT_DB_PATH),
        CSRF_ENABLED=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    if test_config:
        app.config.update(test_config)

    db_path = Path(app.config["DATABASE"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if not app.config.get("SECRET_KEY"):  # Flask defaults it to None, so test for "empty"
        app.config["SECRET_KEY"] = get_secret_key(db_path.parent)
    if not db_path.exists():
        database.bootstrap_if_missing(db_path)

    database.init_app(app)
    register_security(app)
    register_filters(app)
    register_routes(app)
    register_error_handlers(app)
    return app


def register_security(app):
    def csrf_token():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_hex(16)
        return session["_csrf"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def csrf_protect():
        if not app.config["CSRF_ENABLED"] or request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return
        expected = session.get("_csrf", "")
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        if not expected or not sent or not hmac.compare_digest(expected, sent):
            abort(400, "Security token missing or expired. Please reload the page and try again.")

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Cache-Control", "no-store")
        return response


def register_filters(app):
    @app.template_filter("pretty_date")
    def pretty_date(value):
        if not value:
            return "-"
        try:
            return datetime.strptime(value, "%Y-%m-%d").strftime("%d %b %Y")
        except ValueError:
            return value


def register_error_handlers(app):
    def render_error(code, title, message):
        return render_template("error.html", code=code, title=title, message=message), code

    @app.errorhandler(400)
    def bad_request(err):
        return render_error(400, "Request rejected", getattr(err, "description", "Bad request."))

    @app.errorhandler(404)
    def not_found(_err):
        return render_error(404, "Page not found", "The page or record you asked for does not exist.")

    @app.errorhandler(405)
    def not_allowed(_err):
        return render_error(405, "Method not allowed", "That action is not allowed on this page.")

    @app.errorhandler(500)
    def server_error(_err):
        return render_error(500, "Something went wrong",
                            "An unexpected error occurred. Your data has not been changed.")


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
def register_routes(app):

    # ----- Authentication -------------------------------------------------
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if "admin_id" in session:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            errors = {}
            if not username:
                errors["username"] = "Username is required."
            if not password:
                errors["password"] = "Password is required."
            if errors:
                return render_template("login.html", errors=errors, username=username), 400

            admin = get_db().execute(
                "SELECT id, username, password_hash FROM admins WHERE username = ?", (username,)
            ).fetchone()
            if admin is None or not check_password_hash(admin["password_hash"], password):
                flash("Invalid username or password.", "error")
                return render_template("login.html", errors={}, username=username), 401

            session.clear()  # drop any old session data before logging in
            session.permanent = True
            session["admin_id"] = admin["id"]
            session["admin_name"] = admin["username"]
            flash(f"Welcome back, {admin['username']}!", "success")
            return redirect(url_for("dashboard"))
        return render_template("login.html", errors={}, username="")

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        flash("You have been logged out.", "info")
        return redirect(url_for("login"))

    # ----- Dashboard ------------------------------------------------------
    @app.route("/")
    @login_required
    def dashboard():
        db = get_db()
        today_iso = today().isoformat()
        books = db.execute(
            "SELECT COUNT(*) AS titles, COALESCE(SUM(quantity), 0) AS copies, "
            "COALESCE(SUM(available), 0) AS available FROM books"
        ).fetchone()
        issued = db.execute("SELECT COUNT(*) FROM transactions WHERE status = 'Issued'").fetchone()[0]
        students = db.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        overdue = db.execute(
            "SELECT COUNT(*) FROM transactions WHERE status = 'Issued' AND due_date < ?", (today_iso,)
        ).fetchone()[0]
        recent = db.execute(
            """
            SELECT * FROM (
                SELECT t.id, 'Issued' AS action, t.issue_date AS event_date, b.title, s.name AS student_name
                FROM transactions t JOIN books b ON b.id = t.book_id JOIN students s ON s.id = t.student_id
                UNION ALL
                SELECT t.id, 'Returned', t.return_date, b.title, s.name
                FROM transactions t JOIN books b ON b.id = t.book_id JOIN students s ON s.id = t.student_id
                WHERE t.status = 'Returned'
            ) ORDER BY event_date DESC, id DESC LIMIT 8
            """
        ).fetchall()
        stats = {
            "titles": books["titles"], "total_books": books["copies"],
            "available": books["available"], "issued": issued,
            "students": students, "overdue": overdue,
        }
        return render_template("dashboard.html", stats=stats, recent=recent)

    # ----- Books ----------------------------------------------------------
    def category_list(db):
        return [r["category"] for r in db.execute("SELECT DISTINCT category FROM books ORDER BY category")]

    @app.route("/books")
    @login_required
    def books():
        db = get_db()
        q = request.args.get("q", "").strip()
        category = request.args.get("category", "").strip()
        availability = request.args.get("availability", "").strip()

        sql = "SELECT id, title, author, isbn, category, quantity, available FROM books WHERE 1 = 1"
        params = {}
        if q:
            sql += (" AND (title LIKE :q ESCAPE '\\' OR author LIKE :q ESCAPE '\\'"
                    " OR isbn LIKE :isbn ESCAPE '\\')")
            params["q"] = like_pattern(q)
            params["isbn"] = like_pattern(validators.normalize_isbn(q) or q)
        if category:
            sql += " AND category = :category"
            params["category"] = category
        if availability == "available":
            sql += " AND available > 0"
        elif availability == "out":
            sql += " AND available = 0"
        sql += " ORDER BY title COLLATE NOCASE"

        rows = db.execute(sql, params).fetchall()
        return render_template("books.html", books=rows, q=q, category=category,
                               availability=availability, categories=category_list(db))

    @app.route("/books/add", methods=["GET", "POST"])
    @login_required
    def add_book():
        db = get_db()
        if request.method == "POST":
            data, errors = validators.validate_book(request.form)
            if not errors:
                try:
                    db.execute(
                        "INSERT INTO books (title, author, isbn, category, quantity, available) "
                        "VALUES (:title, :author, :isbn, :category, :quantity, :quantity)", data)
                except sqlite3.IntegrityError as exc:
                    errors = unique_violations(exc, BOOK_UNIQUE)
                else:
                    flash(f"Book \"{data['title']}\" was added.", "success")
                    return redirect(url_for("books"))
            flash("Please fix the highlighted errors.", "error")
            return render_template("book_form.html", book=None, form=request.form, errors=errors,
                                   categories=category_list(db)), 400
        return render_template("book_form.html", book=None, form={"quantity": 1}, errors={},
                               categories=category_list(db))

    @app.route("/books/<int:book_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_book(book_id):
        db = get_db()
        book = db.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        if book is None:
            abort(404)
        issued_count = book["quantity"] - book["available"]

        if request.method == "POST":
            data, errors = validators.validate_book(request.form, min_quantity=issued_count)
            if not errors:
                data["id"] = book_id
                data["available"] = data["quantity"] - issued_count
                try:
                    db.execute(
                        "UPDATE books SET title = :title, author = :author, isbn = :isbn, "
                        "category = :category, quantity = :quantity, available = :available "
                        "WHERE id = :id", data)
                except sqlite3.IntegrityError as exc:
                    errors = unique_violations(exc, BOOK_UNIQUE)
                else:
                    flash(f"Book \"{data['title']}\" was updated.", "success")
                    return redirect(url_for("books"))
            flash("Please fix the highlighted errors.", "error")
            return render_template("book_form.html", book=book, form=request.form, errors=errors,
                                   issued_count=issued_count, categories=category_list(db)), 400
        return render_template("book_form.html", book=book, form=dict(book), errors={},
                               issued_count=issued_count, categories=category_list(db))

    @app.route("/books/<int:book_id>/delete", methods=["POST"])
    @login_required
    def delete_book(book_id):
        db = get_db()
        with transaction(db):
            book = db.execute("SELECT id, title FROM books WHERE id = ?", (book_id,)).fetchone()
            if book is None:
                abort(404)
            active = db.execute(
                "SELECT COUNT(*) FROM transactions WHERE book_id = ? AND status = 'Issued'", (book_id,)
            ).fetchone()[0]
            if active:
                flash(f"Cannot delete \"{book['title']}\": {active} cop{'y is' if active == 1 else 'ies are'} "
                      "currently issued. Return them first.", "error")
                return redirect(url_for("books"))
            db.execute("DELETE FROM books WHERE id = ?", (book_id,))
        flash(f"Book \"{book['title']}\" was deleted.", "success")
        return redirect(url_for("books"))

    # ----- Students -------------------------------------------------------
    @app.route("/students")
    @login_required
    def students():
        db = get_db()
        q = request.args.get("q", "").strip()
        sql = ("SELECT s.id, s.student_id, s.name, s.email, s.contact, "
               "(SELECT COUNT(*) FROM transactions t WHERE t.student_id = s.id AND t.status = 'Issued') AS active_loans "
               "FROM students s WHERE 1 = 1")
        params = {}
        if q:
            sql += (" AND (s.name LIKE :q ESCAPE '\\' OR s.student_id LIKE :q ESCAPE '\\'"
                    " OR s.email LIKE :q ESCAPE '\\' OR s.contact LIKE :q ESCAPE '\\')")
            params["q"] = like_pattern(q)
        sql += " ORDER BY s.name COLLATE NOCASE"
        return render_template("students.html", students=db.execute(sql, params).fetchall(), q=q)

    @app.route("/students/add", methods=["GET", "POST"])
    @login_required
    def add_student():
        db = get_db()
        if request.method == "POST":
            data, errors = validators.validate_student(request.form)
            if not errors:
                try:
                    db.execute(
                        "INSERT INTO students (student_id, name, email, contact) "
                        "VALUES (:student_id, :name, :email, :contact)", data)
                except sqlite3.IntegrityError as exc:
                    errors = unique_violations(exc, STUDENT_UNIQUE)
                else:
                    flash(f"Student {data['name']} was registered.", "success")
                    return redirect(url_for("students"))
            flash("Please fix the highlighted errors.", "error")
            return render_template("student_form.html", student=None, form=request.form, errors=errors), 400
        return render_template("student_form.html", student=None, form={}, errors={})

    @app.route("/students/<int:pk>/edit", methods=["GET", "POST"])
    @login_required
    def edit_student(pk):
        db = get_db()
        student = db.execute("SELECT * FROM students WHERE id = ?", (pk,)).fetchone()
        if student is None:
            abort(404)
        if request.method == "POST":
            data, errors = validators.validate_student(request.form)
            if not errors:
                data["id"] = pk
                try:
                    db.execute(
                        "UPDATE students SET student_id = :student_id, name = :name, "
                        "email = :email, contact = :contact WHERE id = :id", data)
                except sqlite3.IntegrityError as exc:
                    errors = unique_violations(exc, STUDENT_UNIQUE)
                else:
                    flash(f"Student {data['name']} was updated.", "success")
                    return redirect(url_for("students"))
            flash("Please fix the highlighted errors.", "error")
            return render_template("student_form.html", student=student, form=request.form, errors=errors), 400
        return render_template("student_form.html", student=student, form=dict(student), errors={})

    @app.route("/students/<int:pk>/delete", methods=["POST"])
    @login_required
    def delete_student(pk):
        db = get_db()
        with transaction(db):
            student = db.execute("SELECT id, name FROM students WHERE id = ?", (pk,)).fetchone()
            if student is None:
                abort(404)
            active = db.execute(
                "SELECT COUNT(*) FROM transactions WHERE student_id = ? AND status = 'Issued'", (pk,)
            ).fetchone()[0]
            if active:
                flash(f"Cannot delete {student['name']}: {active} book{' is' if active == 1 else 's are'} "
                      "still issued to this student. Return them first.", "error")
                return redirect(url_for("students"))
            db.execute("DELETE FROM students WHERE id = ?", (pk,))
        flash(f"Student {student['name']} was deleted.", "success")
        return redirect(url_for("students"))

    # ----- Issue / Return -------------------------------------------------
    def render_issue_form(form, errors, status=200):
        db = get_db()
        t = today()
        books_list = db.execute(
            "SELECT id, title, author, available FROM books ORDER BY title COLLATE NOCASE").fetchall()
        students_list = db.execute(
            "SELECT id, student_id, name FROM students ORDER BY name COLLATE NOCASE").fetchall()
        return render_template(
            "issue.html", books=books_list, students=students_list, form=form, errors=errors,
            today=t.isoformat(), max_due=(t + timedelta(days=MAX_LOAN_DAYS)).isoformat(),
            default_due=(t + timedelta(days=DEFAULT_LOAN_DAYS)).isoformat(),
        ), status

    @app.route("/issue", methods=["GET", "POST"])
    @login_required
    def issue_book():
        if request.method == "GET":
            return render_issue_form({"book_id": request.args.get("book_id", "")}, {})

        db = get_db()
        t = today()
        data, errors = validators.validate_issue(request.form, t, MAX_LOAN_DAYS)
        if errors:
            flash("Please fix the highlighted errors.", "error")
            return render_issue_form(request.form, errors, 400)

        try:
            with transaction(db):
                book = db.execute("SELECT id, title FROM books WHERE id = ?", (data["book_id"],)).fetchone()
                student = db.execute("SELECT id, name FROM students WHERE id = ?", (data["student_id"],)).fetchone()
                if book is None:
                    raise BusinessError("The selected book does not exist.", 400)
                if student is None:
                    raise BusinessError("The selected student does not exist.", 400)
                already = db.execute(
                    "SELECT 1 FROM transactions WHERE book_id = ? AND student_id = ? AND status = 'Issued'",
                    (book["id"], student["id"])).fetchone()
                if already:
                    raise BusinessError(f"{student['name']} already has a copy of \"{book['title']}\" issued.", 409)
                # Atomic stock check + decrement: the WHERE clause refuses to go below zero.
                updated = db.execute(
                    "UPDATE books SET available = available - 1 WHERE id = ? AND available > 0", (book["id"],))
                if updated.rowcount == 0:
                    raise BusinessError(f"No copies of \"{book['title']}\" are available right now.", 409)
                db.execute(
                    "INSERT INTO transactions (book_id, student_id, issue_date, due_date, status) "
                    "VALUES (?, ?, ?, ?, 'Issued')",
                    (book["id"], student["id"], t.isoformat(), data["due_date"]))
        except BusinessError as exc:
            flash(exc.message, "error")
            return render_issue_form(request.form, {}, exc.status)

        flash(f"\"{book['title']}\" was issued to {student['name']}. Due on "
              f"{datetime.strptime(data['due_date'], '%Y-%m-%d').strftime('%d %b %Y')}.", "success")
        return redirect(url_for("transactions", status="issued"))

    @app.route("/return/<int:tx_id>", methods=["POST"])
    @login_required
    def return_book(tx_id):
        db = get_db()
        fallback = url_for("transactions", status="issued")
        with transaction(db):
            tx = db.execute(
                "SELECT t.id, t.book_id, t.status, b.title, s.name AS student_name "
                "FROM transactions t JOIN books b ON b.id = t.book_id JOIN students s ON s.id = t.student_id "
                "WHERE t.id = ?", (tx_id,)).fetchone()
            if tx is None:
                abort(404)
            if tx["status"] == "Returned":
                flash("That book has already been returned.", "warning")
                return redirect(safe_next(fallback))
            db.execute("UPDATE transactions SET status = 'Returned', return_date = ? WHERE id = ?",
                       (today().isoformat(), tx_id))
            db.execute("UPDATE books SET available = available + 1 WHERE id = ?", (tx["book_id"],))
        flash(f"\"{tx['title']}\" returned by {tx['student_name']}.", "success")
        return redirect(safe_next(fallback))

    @app.route("/transactions")
    @login_required
    def transactions():
        status = request.args.get("status", "").strip().lower()
        if status not in ("issued", "returned", "overdue"):
            status = ""
        q = request.args.get("q", "").strip()
        rows = fetch_transactions(get_db(), today(), status, q)
        return render_template("transactions.html", rows=rows, status=status, q=q)

    @app.route("/overdue")
    @login_required
    def overdue():
        rows = fetch_transactions(get_db(), today(), status="overdue", order="t.due_date ASC, t.id ASC")
        return render_template("overdue.html", rows=rows)


# --------------------------------------------------------------------------
if __name__ == "__main__":
    application = create_app()
    application.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("LMS_DEBUG") == "1",
    )
