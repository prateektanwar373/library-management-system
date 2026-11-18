"""Automated tests for the Library Management System.

Run from the project folder with:
    python -m unittest discover -s tests -v

Each test starts with a brand-new temporary database, so tests never touch
your real data in instance/library.db.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database  # noqa: E402
import validators  # noqa: E402
from app import create_app  # noqa: E402

ADMIN_USER = "testadmin"
ADMIN_PASS = "Str0ngTestPass!"


def iso(offset_days=0):
    return (date.today() + timedelta(days=offset_days)).isoformat()


class BaseTestCase(unittest.TestCase):
    """Creates a temp database + Flask test client for every test."""

    seed = False
    csrf = False

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "test.db")
        database.init_db(self.db_path, ADMIN_USER, ADMIN_PASS, seed=self.seed)
        self.app = create_app({
            "TESTING": True,
            "DATABASE": self.db_path,
            "SECRET_KEY": "test-secret",
            "CSRF_ENABLED": self.csrf,
        })
        self.client = self.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- helpers ----
    def login(self, username=ADMIN_USER, password=ADMIN_PASS, follow=True):
        return self.client.post("/login", data={"username": username, "password": password},
                                follow_redirects=follow)

    def query(self, sql, params=()):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def add_book(self, title="Clean Code", author="Robert C. Martin", isbn="9780132350884",
                 category="Programming", quantity=2):
        return self.client.post("/books/add", data={
            "title": title, "author": author, "isbn": isbn,
            "category": category, "quantity": str(quantity)}, follow_redirects=True)

    def add_student(self, student_id="STU100", name="Test Student",
                    email="test.student@example.com", contact="9876543210"):
        return self.client.post("/students/add", data={
            "student_id": student_id, "name": name, "email": email, "contact": contact},
            follow_redirects=True)

    def issue(self, book_id=1, student_id=1, due=None):
        return self.client.post("/issue", data={
            "book_id": str(book_id), "student_id": str(student_id),
            "due_date": due or iso(14)}, follow_redirects=True)

    def book(self, book_id=1):
        return self.query("SELECT * FROM books WHERE id = ?", (book_id,))[0]

    def prepare_one_book_one_student(self, quantity=2):
        self.login()
        self.add_book(quantity=quantity)
        self.add_student()


# ===========================================================================
class TestAdminLogin(BaseTestCase):
    def test_tc01_login_with_valid_credentials(self):
        resp = self.login()
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Dashboard", resp.data)
        self.assertIn(b"Welcome back", resp.data)

    def test_tc02_login_with_wrong_password_is_rejected(self):
        resp = self.login(password="wrong-password")
        self.assertEqual(resp.status_code, 401)
        self.assertIn(b"Invalid username or password", resp.data)

    def test_tc03_login_with_unknown_user_is_rejected(self):
        resp = self.login(username="nobody")
        self.assertEqual(resp.status_code, 401)

    def test_tc04_empty_login_form_shows_validation_errors(self):
        resp = self.login(username="", password="")
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"Username is required", resp.data)
        self.assertIn(b"Password is required", resp.data)

    def test_tc05_pages_require_login(self):
        for url in ("/", "/books", "/students", "/issue", "/transactions", "/overdue"):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302, url)
            self.assertIn("/login", resp.headers["Location"], url)

    def test_tc06_logout_ends_the_session(self):
        self.login()
        resp = self.client.post("/logout", follow_redirects=True)
        self.assertIn(b"logged out", resp.data)
        self.assertEqual(self.client.get("/books").status_code, 302)

    def test_password_is_stored_hashed_not_plain(self):
        stored = self.query("SELECT password_hash FROM admins")[0]["password_hash"]
        self.assertNotEqual(stored, ADMIN_PASS)
        self.assertNotIn(ADMIN_PASS, stored)


class TestBookManagement(BaseTestCase):
    def test_tc07_add_book(self):
        self.login()
        resp = self.add_book()
        self.assertIn(b"was added", resp.data)
        row = self.book()
        self.assertEqual((row["title"], row["quantity"], row["available"]), ("Clean Code", 2, 2))

    def test_tc08_add_book_with_hyphenated_isbn_is_normalised(self):
        self.login()
        self.add_book(isbn="978-0-13-235088-4")
        self.assertEqual(self.book()["isbn"], "9780132350884")

    def test_tc09_add_book_validation_errors(self):
        self.login()
        resp = self.client.post("/books/add", data={
            "title": "", "author": "", "isbn": "123", "category": "", "quantity": "abc"})
        self.assertEqual(resp.status_code, 400)
        for text in (b"Title is required", b"Author is required", b"ISBN must be",
                     b"Category is required", b"Quantity must be a whole number"):
            self.assertIn(text, resp.data)
        self.assertEqual(self.query("SELECT COUNT(*) AS n FROM books")[0]["n"], 0)

    def test_tc10_duplicate_isbn_is_rejected(self):
        self.login()
        self.add_book()
        resp = self.add_book(title="Another Title")
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"ISBN already exists", resp.data)
        self.assertEqual(self.query("SELECT COUNT(*) AS n FROM books")[0]["n"], 1)

    def test_tc11_update_book(self):
        self.login()
        self.add_book()
        resp = self.client.post("/books/1/edit", data={
            "title": "Clean Code (2nd copy)", "author": "Robert C. Martin",
            "isbn": "9780132350884", "category": "Software Engineering", "quantity": "5"},
            follow_redirects=True)
        self.assertIn(b"was updated", resp.data)
        row = self.book()
        self.assertEqual((row["title"], row["category"], row["quantity"], row["available"]),
                         ("Clean Code (2nd copy)", "Software Engineering", 5, 5))

    def test_tc12_search_book_by_title_author_and_isbn(self):
        self.login()
        self.add_book(title="Clean Code", author="Robert C. Martin", isbn="9780132350884")
        self.add_book(title="Fluent Python", author="Luciano Ramalho", isbn="9781492056355")
        by_title = self.client.get("/books?q=clean").data
        self.assertIn(b"Clean Code", by_title)
        self.assertNotIn(b"Fluent Python", by_title)
        by_author = self.client.get("/books?q=ramalho").data
        self.assertIn(b"Fluent Python", by_author)
        self.assertNotIn(b"Clean Code", by_author)
        by_isbn = self.client.get("/books?q=978-1-49-205635-5").data
        self.assertIn(b"Fluent Python", by_isbn)
        self.assertNotIn(b"Clean Code", by_isbn)
        self.assertIn(b"No books match", self.client.get("/books?q=zzzzzz").data)

    def test_filter_books_by_category_and_availability(self):
        self.login()
        self.add_book(title="Clean Code", isbn="9780132350884", category="Programming", quantity=1)
        self.add_book(title="The Alchemist", author="Paulo Coelho", isbn="9780062315007", category="Fiction")
        self.add_student()
        self.issue(book_id=1)  # Clean Code now has 0 available
        by_cat = self.client.get("/books?category=Fiction").data
        self.assertIn(b"The Alchemist", by_cat)
        self.assertNotIn(b"Clean Code", by_cat)
        out = self.client.get("/books?availability=out").data
        self.assertIn(b"Clean Code", out)
        self.assertNotIn(b"The Alchemist", out)

    def test_search_is_safe_against_sql_injection(self):
        self.login()
        self.add_book()
        resp = self.client.get("/books?q=' OR 1=1 --")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"No books match", resp.data)
        resp = self.client.get("/books?q='; DROP TABLE books; --")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.query("SELECT COUNT(*) AS n FROM books")[0]["n"], 1)

    def test_tc13_delete_book(self):
        self.login()
        self.add_book()
        resp = self.client.post("/books/1/delete", follow_redirects=True)
        self.assertIn(b"was deleted", resp.data)
        self.assertEqual(self.query("SELECT COUNT(*) AS n FROM books")[0]["n"], 0)

    def test_delete_page_has_confirmation_prompt(self):
        self.login()
        self.add_book()
        html = self.client.get("/books").data
        self.assertIn(b"data-confirm=", html)

    def test_edit_or_delete_missing_book_returns_404(self):
        self.login()
        self.assertEqual(self.client.get("/books/999/edit").status_code, 404)
        self.assertEqual(self.client.post("/books/999/delete").status_code, 404)


class TestStudentManagement(BaseTestCase):
    def test_tc14_register_student(self):
        self.login()
        resp = self.add_student()
        self.assertIn(b"was registered", resp.data)
        row = self.query("SELECT * FROM students")[0]
        self.assertEqual((row["student_id"], row["name"]), ("STU100", "Test Student"))

    def test_tc15_student_validation_errors(self):
        self.login()
        resp = self.client.post("/students/add", data={
            "student_id": "!", "name": "A1", "email": "not-an-email", "contact": "12"})
        self.assertEqual(resp.status_code, 400)
        for text in (b"Student ID must be", b"Name must not contain digits",
                     b"valid email", b"Contact number must be"):
            self.assertIn(text, resp.data)

    def test_tc16_duplicate_student_id_and_email_rejected(self):
        self.login()
        self.add_student()
        resp = self.add_student(name="Someone Else", email="other@example.com")
        self.assertIn(b"student ID is already registered", resp.data)
        resp = self.add_student(student_id="STU200", name="Someone Else")
        self.assertIn(b"email address is already registered", resp.data)
        self.assertEqual(self.query("SELECT COUNT(*) AS n FROM students")[0]["n"], 1)

    def test_tc17_edit_student(self):
        self.login()
        self.add_student()
        resp = self.client.post("/students/1/edit", data={
            "student_id": "STU100", "name": "Renamed Student",
            "email": "renamed@example.com", "contact": "9123456780"}, follow_redirects=True)
        self.assertIn(b"was updated", resp.data)
        self.assertEqual(self.query("SELECT name FROM students")[0]["name"], "Renamed Student")

    def test_search_students(self):
        self.login()
        self.add_student()
        self.add_student(student_id="STU101", name="Zara Khan", email="zara@example.com")
        data = self.client.get("/students?q=zara").data
        self.assertIn(b"Zara Khan", data)
        self.assertNotIn(b"Test Student", data)

    def test_tc18_delete_student(self):
        self.login()
        self.add_student()
        resp = self.client.post("/students/1/delete", follow_redirects=True)
        self.assertIn(b"was deleted", resp.data)
        self.assertEqual(self.query("SELECT COUNT(*) AS n FROM students")[0]["n"], 0)


class TestIssueAndReturn(BaseTestCase):
    def test_tc19_issue_book_decreases_available_and_records_dates(self):
        self.prepare_one_book_one_student(quantity=2)
        resp = self.issue(due=iso(10))
        self.assertIn(b"was issued to", resp.data)
        self.assertEqual(self.book()["available"], 1)
        tx = self.query("SELECT * FROM transactions")[0]
        self.assertEqual((tx["status"], tx["issue_date"], tx["due_date"], tx["return_date"]),
                         ("Issued", iso(0), iso(10), None))

    def test_tc20_cannot_issue_when_stock_is_zero(self):
        self.login()
        self.add_book(quantity=1)
        self.add_student()
        self.add_student(student_id="STU101", name="Second Student", email="second@example.com")
        self.issue(book_id=1, student_id=1)
        self.assertEqual(self.book()["available"], 0)

        resp = self.issue(book_id=1, student_id=2)
        self.assertEqual(resp.status_code, 409)
        self.assertIn(b"No copies of", resp.data)
        self.assertEqual(self.book()["available"], 0)  # never goes negative
        self.assertEqual(self.query("SELECT COUNT(*) AS n FROM transactions")[0]["n"], 1)

    def test_same_student_cannot_hold_two_copies_of_same_book(self):
        self.prepare_one_book_one_student(quantity=3)
        self.issue()
        resp = self.issue()
        self.assertEqual(resp.status_code, 409)
        self.assertIn(b"already has a copy", resp.data)
        self.assertEqual(self.book()["available"], 2)

    def test_issue_validation_errors(self):
        self.prepare_one_book_one_student()
        resp = self.client.post("/issue", data={"book_id": "", "student_id": "", "due_date": ""})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"Please select a book", resp.data)
        self.assertIn(b"Please select a student", resp.data)
        resp = self.issue(due=iso(-1))
        self.assertIn(b"cannot be in the past", resp.data)
        resp = self.issue(due=iso(365))
        self.assertIn(b"days from today", resp.data)
        resp = self.issue(book_id=999)
        self.assertIn(b"does not exist", resp.data)
        self.assertEqual(self.book()["available"], 2)

    def test_tc21_return_book_increases_available_and_updates_status(self):
        self.prepare_one_book_one_student(quantity=2)
        self.issue()
        self.assertEqual(self.book()["available"], 1)
        resp = self.client.post("/return/1", follow_redirects=True)
        self.assertIn(b"returned by", resp.data)
        self.assertEqual(self.book()["available"], 2)
        tx = self.query("SELECT * FROM transactions")[0]
        self.assertEqual((tx["status"], tx["return_date"]), ("Returned", iso(0)))

    def test_tc22_returning_twice_does_not_inflate_stock(self):
        self.prepare_one_book_one_student(quantity=2)
        self.issue()
        self.client.post("/return/1")
        resp = self.client.post("/return/1", follow_redirects=True)
        self.assertIn(b"already been returned", resp.data)
        self.assertEqual(self.book()["available"], 2)

    def test_tc23_available_quantity_stays_correct_over_many_operations(self):
        self.login()
        self.add_book(quantity=3)
        for i in range(1, 4):
            self.add_student(student_id=f"STU30{i}", name=f"Student Number{'ABC'[i-1]}",
                             email=f"s{i}@example.com")
        for student in (1, 2, 3):
            self.issue(book_id=1, student_id=student)
        self.assertEqual(self.book()["available"], 0)
        self.client.post("/return/2")
        self.assertEqual(self.book()["available"], 1)
        self.issue(book_id=1, student_id=2)
        self.assertEqual(self.book()["available"], 0)
        # invariant: available == quantity - active loans
        active = self.query("SELECT COUNT(*) AS n FROM transactions WHERE status='Issued'")[0]["n"]
        self.assertEqual(self.book()["available"], self.book()["quantity"] - active)

    def test_history_shows_issue_and_return(self):
        self.prepare_one_book_one_student()
        self.issue()
        self.client.post("/return/1")
        self.issue()
        html = self.client.get("/transactions").data
        self.assertIn(b"Returned", html)
        self.assertIn(b"Issued", html)
        returned_only = self.client.get("/transactions?status=returned").data
        self.assertIn(b"Returned", returned_only)
        self.assertEqual(self.client.get("/transactions?status=issued").data.count(b">Return</button>"), 1)

    def test_edit_quantity_cannot_drop_below_issued_copies(self):
        self.prepare_one_book_one_student(quantity=3)
        self.issue()
        resp = self.client.post("/books/1/edit", data={
            "title": "Clean Code", "author": "Robert C. Martin", "isbn": "9780132350884",
            "category": "Programming", "quantity": "0"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"currently issued", resp.data)
        self.assertEqual(self.book()["quantity"], 3)
        # raising the quantity keeps available consistent: 5 total - 1 issued = 4
        self.client.post("/books/1/edit", data={
            "title": "Clean Code", "author": "Robert C. Martin", "isbn": "9780132350884",
            "category": "Programming", "quantity": "5"})
        self.assertEqual((self.book()["quantity"], self.book()["available"]), (5, 4))

    def test_tc24_cannot_delete_book_or_student_with_active_loan(self):
        self.prepare_one_book_one_student()
        self.issue()
        resp = self.client.post("/books/1/delete", follow_redirects=True)
        self.assertIn(b"Cannot delete", resp.data)
        resp = self.client.post("/students/1/delete", follow_redirects=True)
        self.assertIn(b"Cannot delete", resp.data)
        self.assertEqual(self.query("SELECT COUNT(*) AS n FROM books")[0]["n"], 1)
        self.assertEqual(self.query("SELECT COUNT(*) AS n FROM students")[0]["n"], 1)
        # after returning, deletion works
        self.client.post("/return/1")
        resp = self.client.post("/books/1/delete", follow_redirects=True)
        self.assertIn(b"was deleted", resp.data)

    def test_tc25_overdue_books_are_listed(self):
        self.prepare_one_book_one_student(quantity=2)
        self.issue()
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE transactions SET issue_date = ?, due_date = ? WHERE id = 1",
                     (iso(-20), iso(-5)))
        conn.commit()
        conn.close()
        html = self.client.get("/overdue").data
        self.assertIn(b"Clean Code", html)
        self.assertIn(b">5</span>", html)  # 5 days overdue
        self.assertIn(b"Overdue", self.client.get("/transactions").data)
        self.assertIn(b"Clean Code", self.client.get("/transactions?status=overdue").data)

    def test_not_overdue_when_due_in_future(self):
        self.prepare_one_book_one_student()
        self.issue(due=iso(7))
        self.assertIn(b"Nothing is overdue", self.client.get("/overdue").data)


class TestDashboard(BaseTestCase):
    seed = True

    def test_tc26_dashboard_shows_seeded_statistics(self):
        self.login()
        html = self.client.get("/").data.decode()
        total = self.query("SELECT SUM(quantity) AS n FROM books")[0]["n"]
        avail = self.query("SELECT SUM(available) AS n FROM books")[0]["n"]
        issued = self.query("SELECT COUNT(*) AS n FROM transactions WHERE status='Issued'")[0]["n"]
        students = self.query("SELECT COUNT(*) AS n FROM students")[0]["n"]
        for value in (total, avail, issued, students):
            self.assertIn(f'<p class="stat-value">{value}</p>', html)
        self.assertIn("Recent activity", html)
        self.assertIn("issued to", html)
        self.assertIn("returned by", html)

    def test_seed_data_is_consistent(self):
        rows = self.query("""
            SELECT b.id, b.quantity, b.available,
                   (SELECT COUNT(*) FROM transactions t WHERE t.book_id = b.id AND t.status='Issued') AS active
            FROM books b""")
        self.assertGreaterEqual(len(rows), 10)
        for r in rows:
            self.assertEqual(r["available"], r["quantity"] - r["active"])
        overdue = self.query("SELECT COUNT(*) AS n FROM transactions WHERE status='Issued' AND due_date < ?",
                             (iso(0),))[0]["n"]
        self.assertGreaterEqual(overdue, 1)
        self.assertEqual(self.query("SELECT COUNT(*) AS n FROM books WHERE available = 0")[0]["n"] >= 1, True)

    def test_every_page_renders_for_logged_in_admin(self):
        self.login()
        for url in ("/", "/books", "/books/add", "/books/1/edit", "/students", "/students/add",
                    "/students/1/edit", "/issue", "/issue?book_id=1", "/transactions",
                    "/transactions?status=issued", "/overdue"):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertEqual(self.client.get("/nope").status_code, 404)


class TestPersistence(BaseTestCase):
    def test_tc27_data_survives_application_restart(self):
        self.login()
        self.add_book()
        self.add_student()
        self.issue()
        # "restart": build a completely new app object on the same database file
        restarted = create_app({"TESTING": True, "DATABASE": self.db_path,
                                "SECRET_KEY": "test-secret", "CSRF_ENABLED": False})
        client = restarted.test_client()
        client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASS})
        self.assertIn(b"Clean Code", client.get("/books").data)
        self.assertIn(b"Test Student", client.get("/students").data)
        self.assertEqual(client.get("/transactions?status=issued").data.count(b">Return</button>"), 1)


class TestSecurity(BaseTestCase):
    csrf = True

    def test_tc28_post_without_csrf_token_is_rejected(self):
        resp = self.client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASS})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"Security token", resp.data)

    def test_login_works_with_valid_csrf_token(self):
        page = self.client.get("/login").data.decode()
        marker = 'name="csrf_token" value="'
        token = page.split(marker)[1].split('"')[0]
        resp = self.client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASS,
                                                "csrf_token": token}, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Welcome back", resp.data)

    def test_open_redirect_is_blocked_on_return(self):
        # use a non-CSRF client for the logic check
        client = create_app({"TESTING": True, "DATABASE": self.db_path, "SECRET_KEY": "x",
                             "CSRF_ENABLED": False}).test_client()
        client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASS})
        client.post("/books/add", data={"title": "T", "author": "A", "isbn": "9780132350884",
                                        "category": "C", "quantity": "1"})
        client.post("/students/add", data={"student_id": "S01", "name": "Some One",
                                           "email": "a@b.co", "contact": "9876543210"})
        client.post("/issue", data={"book_id": "1", "student_id": "1", "due_date": iso(5)})
        resp = client.post("/return/1", data={"next": "https://evil.example/"})
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn("evil.example", resp.headers["Location"])


class TestValidators(unittest.TestCase):
    def test_isbn_normalisation_and_formats(self):
        self.assertEqual(validators.normalize_isbn(" 978-0-13-235088-4 "), "9780132350884")
        self.assertEqual(validators.normalize_isbn("0-306-40615-x"), "030640615X")
        for ok in ("9780132350884", "0306406152", "030640615X"):
            _, errors = validators.validate_book(
                {"title": "t", "author": "a", "isbn": ok, "category": "c", "quantity": "1"})
            self.assertNotIn("isbn", errors, ok)
        for bad in ("", "12345", "97801323508", "ABCDEFGHIJ"):
            _, errors = validators.validate_book(
                {"title": "t", "author": "a", "isbn": bad, "category": "c", "quantity": "1"})
            self.assertIn("isbn", errors, bad)

    def test_quantity_limits(self):
        base = {"title": "t", "author": "a", "isbn": "9780132350884", "category": "c"}
        self.assertIn("quantity", validators.validate_book({**base, "quantity": "-1"})[1])
        self.assertIn("quantity", validators.validate_book({**base, "quantity": "1001"})[1])
        self.assertIn("quantity", validators.validate_book({**base, "quantity": "2.5"})[1])
        self.assertEqual(validators.validate_book({**base, "quantity": "10"})[1], {})

    def test_student_fields_are_normalised(self):
        data, errors = validators.validate_student({
            "student_id": " stu001 ", "name": " Priya ", "email": " Priya@Example.COM ",
            "contact": "98765-43210"})
        self.assertEqual(errors, {})
        self.assertEqual((data["student_id"], data["email"], data["contact"]),
                         ("STU001", "priya@example.com", "9876543210"))


class TestDatabaseSetup(unittest.TestCase):
    def test_schema_constraints_are_enforced_by_the_database_itself(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "t.db")
            database.init_db(path, "admin", "password123", seed=True)
            conn = database.connect(path)
            with self.assertRaises(sqlite3.IntegrityError):   # duplicate ISBN
                conn.execute("INSERT INTO books (title, author, isbn, category, quantity, available) "
                             "VALUES ('x','y','9780132350884','z',1,1)")
            with self.assertRaises(sqlite3.IntegrityError):   # available > quantity
                conn.execute("INSERT INTO books (title, author, isbn, category, quantity, available) "
                             "VALUES ('x','y','1111111111','z',1,2)")
            with self.assertRaises(sqlite3.IntegrityError):   # negative stock
                conn.execute("UPDATE books SET available = -1 WHERE id = 1")
            with self.assertRaises(sqlite3.IntegrityError):   # foreign key to a missing book
                conn.execute("INSERT INTO transactions (book_id, student_id, issue_date, due_date) "
                             "VALUES (9999, 1, '2026-01-01', '2026-01-10')")
            conn.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_init_db_does_not_reseed_existing_data(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "t.db")
            self.assertTrue(database.init_db(path, "admin", "password123", seed=True))
            self.assertFalse(database.init_db(path, "admin", "password123", seed=True))
            conn = database.connect(path)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM books").fetchone()[0], len(database.SAMPLE_BOOKS))
            conn.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
