# Library Management System

A web-based Library Management System built for a Software Engineering practical.
Admins can manage books and students, issue and return books, track overdue loans and
see live statistics on a dashboard.

| Layer | Technology |
|-------|------------|
| Frontend | HTML, CSS, JavaScript (no frameworks, no CDN - works offline) |
| Backend | Python 3 + Flask |
| Database | SQLite, accessed through Python's built-in `sqlite3` module |

---

## 1. Project structure

```
library-management-system/
├── app.py                 Flask app: routes, business rules, security hooks
├── database.py            SQL schema, connection handling, sample data, setup command
├── validators.py          Input validation for books, students and the issue form
├── requirements.txt       Python dependencies (only Flask)
├── README.md              This file
├── VIVA_GUIDE.md          Architecture explanation + viva questions and answers
├── instance/              Created automatically: library.db (SQLite file), secret_key
├── templates/             Jinja2 HTML pages
│   ├── base.html          Layout: sidebar, top bar, toasts, confirm dialog
│   ├── login.html         Admin login page
│   ├── dashboard.html     Statistics cards + recent activity
│   ├── books.html / book_form.html          List+search / add+edit books
│   ├── students.html / student_form.html    List+search / register+edit students
│   ├── issue.html         Issue a book
│   ├── transactions.html  Return books + full issue/return history
│   ├── overdue.html       Overdue books
│   ├── error.html         404 / 400 / 500 pages
│   └── _macros.html, _icons.html, _flashes.html   Reusable template pieces
├── static/
│   ├── css/style.css      All styling (responsive)
│   └── js/app.js          Sidebar toggle, toasts, delete confirmation dialog
└── tests/
    ├── test_app.py        48 automated tests for all features
    └── test_startup.py    3 tests for first-run behaviour
```

---

## 2. Installation and running (Windows 11)

You need **Python 3.10 or newer** (check with `python --version`; install from python.org and
tick *"Add python.exe to PATH"* if the command is not found).

Open **PowerShell** (or Windows Terminal) and run these commands one at a time:

```powershell
# 1. Go to the project folder (adjust the path to where you unzipped it)
cd C:\Users\YourName\Desktop\library-management-system

# 2. Create and activate a virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Install the dependency
pip install -r requirements.txt

# 4. Create the database + admin account + sample data
python database.py

# 5. Start the server
python app.py
```

Then open **http://127.0.0.1:5000** in your browser and sign in.

**Notes**

* *Step 2 error "running scripts is disabled"?* Run
  `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` and repeat the activate line,
  or use Command Prompt instead and run `venv\Scripts\activate.bat`.
* *Step 4* asks you to choose an admin password (minimum 8 characters; typing is hidden).
  The username is `admin`. To skip the prompt:
  `python database.py --username admin --password YourPassword1`
* **Write your password down before the viva.** Forgot it? Reset it without losing data:
  `python database.py --no-seed --username admin --password NewPassword1`
* Stop the server with **Ctrl + C**.
* Port 5000 busy? `$env:PORT=5001; python app.py` and open `http://127.0.0.1:5001`.
* Start over with a fresh database (**deletes all data**): stop the server, then
  `python database.py --reset`.

No credentials are hard-coded in the source. The admin password is chosen by you at setup (or read
from the `LMS_ADMIN_PASSWORD` environment variable), is stored only as a salted hash, and the session
signing key is generated randomly on first run and saved to `instance/secret_key`.

---

## 3. Features

| Area | What it does |
|------|--------------|
| **Admin login** | Username + password, session-based. Every page except login requires it. Logout button in the sidebar. |
| **Dashboard** | Total books (copies), available books, currently issued, registered students, overdue count, and the 8 most recent issue/return events. |
| **Books** | Add, edit, delete, list. Search by title, author or ISBN; filter by category and availability. Stores ID, title, author, ISBN, category, quantity. |
| **Students** | Register, edit, delete, list, search. Stores student ID, name, email, contact number. |
| **Issue** | Choose a book and a student; issue date is today, due date defaults to +14 days. Refused when no copies are left. Available count drops by one. |
| **Return** | One click. Available count rises by one; transaction becomes *Returned* with the return date. |
| **History** | Every issue and return, searchable, filterable by status (issued / overdue / returned). |
| **Overdue** | Lists issued books past their due date with number of days overdue and a *Mark returned* button. |
| **Safety** | Validation with clear messages, confirmation dialog before every delete, success/error toast notifications, responsive layout (tables become cards on phones). |

**Business rules enforced** (in code *and*, where possible, by the database):

* A book cannot be issued when `available = 0` (checked atomically inside a database transaction).
* The same student cannot hold two copies of the same book at once.
* A returned transaction cannot be returned twice (so stock can never be inflated).
* A book or student with an active (not yet returned) loan cannot be deleted.
* Quantity cannot be lowered below the number of copies currently issued; *available* is recalculated automatically when quantity is edited.
* ISBNs and student IDs/emails are unique. Due dates must be today or later (maximum 90 days ahead).

> **Design decision:** deleting a book or student that has *only returned* history also deletes
> that history (`ON DELETE CASCADE`). This keeps the database consistent and the project simple; a
> real system might archive instead of delete.

---

## 4. Architecture

```
 Browser (HTML + CSS + JS)
        │  HTTP request (form POST / page GET)
        ▼
 ┌───────────────────────────── Flask (app.py) ─────────────────────────────┐
 │  Route  →  login_required  →  validators.py  →  business rules  →  render │
 └───────────────────────────────────┬──────────────────────────────────────┘
                                     │ parameterised SQL (sqlite3)
                                     ▼
                         database.py  →  instance/library.db (SQLite)
```

* **Presentation layer** - Jinja2 templates + CSS + JS.
* **Application layer** - Flask routes in `app.py`; `validators.py` cleans and checks input.
* **Data layer** - `database.py` holds the schema and connections; SQLite stores the data.

### Database schema

```
admins(id PK, username UNIQUE, password_hash, created_at)

books(id PK, title, author, isbn UNIQUE, category,
      quantity ≥ 0, available ≥ 0, CHECK available ≤ quantity)

students(id PK, student_id UNIQUE, name, email UNIQUE, contact)

transactions(id PK,
             book_id    FK → books.id,
             student_id FK → students.id,
             issue_date, due_date, return_date,
             status IN ('Issued','Returned'),
             CHECK due_date ≥ issue_date,
             CHECK status/return_date agree)

books 1 ──── * transactions * ──── 1 students
```

### Security measures

* Parameterised SQL everywhere (`?` / `:name` placeholders), never string-built values → prevents SQL injection.
* Passwords hashed with Werkzeug (PBKDF2/scrypt + salt); never stored or logged in plain text.
* CSRF token required on every POST form.
* Session is cleared on login and logout; cookies are `HttpOnly` + `SameSite=Lax`.
* Jinja2 auto-escapes output (prevents XSS); the "return" redirect only accepts local paths.

---

## 5. Testing

### Run the automated tests

```powershell
python -m unittest discover -s tests -v
```

Expected: `Ran 51 tests ... OK`. Tests use a temporary database, so your real data is never touched.

### Test cases and expected results

| ID | Feature | Action | Expected result | Automated test |
|----|---------|--------|-----------------|----------------|
| TC01 | Admin login | Valid username + password | Redirected to dashboard, "Welcome back" shown | `test_tc01_login_with_valid_credentials` |
| TC02 | Admin login | Wrong password | Stays on login, "Invalid username or password" | `test_tc02_...` |
| TC03 | Admin login | Unknown username | Rejected with the same message | `test_tc03_...` |
| TC04 | Admin login | Empty form | "Username is required" / "Password is required" | `test_tc04_...` |
| TC05 | Access control | Open any page without logging in | Redirected to login | `test_tc05_...` |
| TC06 | Logout | Click Log out | Session ended; pages redirect to login again | `test_tc06_...` |
| TC07 | Add book | Fill valid form | Book saved with available = quantity | `test_tc07_add_book` |
| TC08 | Add book | ISBN typed as `978-0-13-235088-4` | Stored as `9780132350884` | `test_tc08_...` |
| TC09 | Add book | Empty fields, bad ISBN, quantity "abc" | Error shown per field; nothing saved | `test_tc09_...` |
| TC10 | Add book | Duplicate ISBN | "ISBN already exists"; nothing saved | `test_tc10_...` |
| TC11 | Update book | Change title/category/quantity | Saved; available recalculated | `test_tc11_update_book` |
| TC12 | Search book | Search title, author, ISBN | Only matching books listed; no match → message | `test_tc12_search_book_by_title_author_and_isbn` |
| TC13 | Delete book | Confirm delete | Book removed from database | `test_tc13_delete_book` |
| TC14 | Register student | Valid form | Student saved | `test_tc14_register_student` |
| TC15 | Register student | Bad ID, digits in name, bad email/phone | Error per field; nothing saved | `test_tc15_...` |
| TC16 | Register student | Duplicate student ID / email | Friendly duplicate error | `test_tc16_...` |
| TC17 | Edit student | Change name/email/contact | Saved | `test_tc17_edit_student` |
| TC18 | Delete student | Confirm delete | Student removed | `test_tc18_delete_student` |
| TC19 | Issue book | Issue 1 of 2 copies | Available 2 → 1; transaction *Issued* with dates | `test_tc19_...` |
| TC20 | Issue book | Issue when 0 copies left | Error "No copies ... available"; available stays 0; no transaction created | `test_tc20_cannot_issue_when_stock_is_zero` |
| TC21 | Return book | Return an issued book | Available 1 → 2; status *Returned*; return date saved | `test_tc21_...` |
| TC22 | Return book | Return the same loan twice | "already returned"; stock unchanged | `test_tc22_...` |
| TC23 | Quantity accuracy | Several issues and returns | `available = quantity − active loans` always | `test_tc23_...` |
| TC24 | Delete rules | Delete book/student with active loan | "Cannot delete"; records kept | `test_tc24_...` |
| TC25 | Overdue | Loan past due date | Appears on Overdue page with days overdue | `test_tc25_overdue_books_are_listed` |
| TC26 | Dashboard | Open dashboard with sample data | Counts match the database | `test_tc26_...` |
| TC27 | Persistence | Restart the app on the same DB | Data still present | `test_tc27_...` |
| TC28 | Security | POST without CSRF token | Rejected (400) | `test_tc28_...` |

Extra tests cover SQL-injection attempts in search, filters, the issue-form validation rules, the
quantity-below-issued rule, the open-redirect guard, database CHECK/FOREIGN KEY constraints and
first-run secret-key creation.

### Manual walkthrough (about 5 minutes)

1. **Login** - wrong password → error toast; correct password → dashboard.
2. **Dashboard** - shows 40 books, 33 available, 7 issued, 8 students, 2 overdue (sample data).
3. **Books → Add book** - add *"Test Book"*, qty 1. Try the same ISBN again → duplicate error.
4. **Books** - search `clean`, then an author name, then an ISBN. Use the category / availability filters.
5. **Books → Edit** - change the quantity and save.
6. **Students → Register student** - add one; try an invalid email to see validation.
7. **Issue Book** - issue *Test Book* to your student. Dashboard: available −1, issued +1.
8. **Issue Book** - issue *Test Book* again to another student → error "No copies available".
   (Also try *Design Patterns*, which already has 0 copies in the sample data.)
9. **Return Books** - click *Return*. Dashboard: available +1.
10. **History** - issue and return both recorded; filter by *Returned*.
11. **Overdue** - sample data has 2 overdue loans with days overdue; click *Mark returned*.
12. **Delete** - delete *Test Book*: confirmation dialog appears, cancel once, then confirm.
13. **Restart** - stop with Ctrl+C, run `python app.py` again; everything is still there.
14. **Logout**.

---

## 6. Troubleshooting

| Problem | Fix |
|---------|-----|
| `python` not recognised | Reinstall Python and tick "Add to PATH", or try `py` instead of `python`. |
| `No module named flask` | Activate the virtual environment, then `pip install -r requirements.txt`. |
| Cannot log in | Reset the password: `python database.py --no-seed --username admin --password NewPassword1`. |
| "Security token missing or expired" | Reload the page (the session expired or cookies are blocked). |
| `--reset` fails with a permission error | Stop the running server first (Ctrl+C). |
