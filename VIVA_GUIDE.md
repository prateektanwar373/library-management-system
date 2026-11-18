# Viva Guide - Library Management System

## 1. The project in 60 seconds (say this first)

> "My project is a web-based Library Management System. An admin logs in and can manage books and
> students, issue and return books, and see overdue loans on a dashboard. The frontend is HTML, CSS
> and JavaScript, the backend is Python Flask, and the data is stored in SQLite through Python's
> `sqlite3` module. The database has four tables - admins, books, students and transactions - linked
> with primary and foreign keys. The system automatically keeps the available-copies count correct
> when books are issued or returned, refuses to issue a book that has no copies left, validates all
> input, uses parameterised queries against SQL injection, and has 51 automated tests."

## 2. Architecture in simple words

Think of three layers, like a restaurant:

| Layer | Restaurant | In my project |
|-------|-----------|---------------|
| Presentation | Dining room and menu | `templates/`, `static/css`, `static/js` - what the admin sees and clicks |
| Application | Kitchen | `app.py` (routes + rules) and `validators.py` (checks input) |
| Data | Storeroom | `database.py` and the SQLite file `instance/library.db` |

**What happens when the admin issues a book:**
1. The browser sends the form (book, student, due date) to `/issue`.
2. Flask checks the admin is logged in and the CSRF token is valid.
3. `validators.py` checks the input (a book and student chosen, due date is today or later).
4. Inside **one database transaction**: check the book/student exist → check the student does not already
   hold this book → `UPDATE books SET available = available - 1 WHERE id=? AND available > 0` → insert the
   transaction row. If any step fails, everything is rolled back.
5. A success message is shown and the page goes to the list of issued books.

**Files and what each one does**

| File | Purpose |
|------|---------|
| `app.py` | Creates the Flask app; all routes (login, books, students, issue, return, overdue); security hooks |
| `database.py` | Table definitions, connection helper, transaction helper, sample data, setup command |
| `validators.py` | Cleans and validates form input, returns clear error messages |
| `templates/` | HTML pages; `base.html` is the shared layout |
| `tests/` | Automated tests (unittest) |

## 3. Key design decisions (examiners love "why")

* **Flask** - small, easy to explain, no hidden magic; perfect for a practical.
* **SQLite + `sqlite3`** - no server to install, a single file, ships with Python.
* **`available` column stored in books** - fast to display and filter; kept correct by doing the update and
  the transaction insert in the *same* database transaction. Invariant: `available = quantity − active loans`.
* **Server-side validation** - HTML5 checks help the user, but they can be bypassed, so the server always re-checks.
* **Database constraints as a second safety net** - `CHECK (available >= 0)`, `UNIQUE` ISBN, foreign keys. Even a
  bug in my code could not store a negative stock.
* **Sessions + hashed passwords + CSRF token** - basic but correct security.
* **Sample data computed relative to today** - so overdue loans stay overdue whenever the database is created.

## 4. Likely viva questions and answers

### General / architecture

**Q1. What is the aim of your project?**
To automate library work: keeping the book catalogue and student records, issuing and returning books with
automatic stock updates, and finding overdue books, replacing a paper register.

**Q2. Which technologies did you use and why?**
HTML/CSS/JS for the interface, Flask for the backend, SQLite for storage. They are lightweight, free, easy to
run on any laptop and cover everything the practical needs.

**Q3. What is Flask?**
A lightweight Python web framework. It maps URLs to Python functions (routes), handles requests/responses,
sessions and templates.

**Q4. Explain the architecture of your project.**
A three-layer design: presentation (templates/CSS/JS), application logic (Flask routes + validators) and data
(SQLite through `sqlite3`). The browser talks only to Flask; Flask is the only thing that talks to the database.

**Q5. What is MVC and does your project follow it?**
Model-View-Controller separates data, display and logic. Roughly: Model = `database.py` + SQL tables,
View = Jinja2 templates, Controller = Flask routes in `app.py`. It is not a strict MVC framework but follows the idea.

**Q6. What is a route? Give an example.**
A URL mapped to a function, e.g. `@app.route("/books")` runs `books()` which queries the database and renders `books.html`.

**Q7. What is Jinja2 / what is `base.html`?**
Jinja2 is Flask's template engine - HTML with placeholders and loops. `base.html` holds the layout (sidebar, top bar);
other pages "extend" it so the layout is written once.

**Q8. What is `create_app` (application factory)?**
A function that builds and configures the Flask app. It lets the tests create a separate app with a temporary database.

### Database

**Q9. Describe your database tables.**
`admins` (login accounts), `books` (title, author, ISBN, category, quantity, available), `students` (student ID,
name, email, contact) and `transactions` (which student took which book, issue/due/return dates, status).

**Q10. What are the keys?**
Primary keys: `id` in each table. Foreign keys: `transactions.book_id → books.id` and
`transactions.student_id → students.id`. Unique keys: ISBN, username, student ID, email.

**Q11. What relationship exists between books and students?**
Many-to-many: a student can borrow many books and a book can be borrowed by many students over time. The
`transactions` table is the junction table that resolves it into two one-to-many relationships.

**Q12. Which constraints did you use?**
`NOT NULL`, `UNIQUE`, `CHECK (quantity >= 0)`, `CHECK (available >= 0 AND available <= quantity)`,
`CHECK (status IN ('Issued','Returned'))`, `CHECK (due_date >= issue_date)` and foreign keys with
`PRAGMA foreign_keys = ON` (SQLite has it off by default).

**Q13. What is normalization? Is your schema normalised?**
Removing redundancy by splitting data into related tables. Student and book details are stored once and referenced by
ID in `transactions`, so the schema is in 3NF. `available` is a deliberate, controlled denormalisation for speed.

**Q14. What is a transaction (ACID)? Where do you use it?**
A group of SQL steps that succeed or fail together (Atomicity, Consistency, Isolation, Durability). Issuing a book does
"decrease stock + insert record" and returning does "update record + increase stock" - each inside one transaction
with `BEGIN IMMEDIATE`. If one step fails, `ROLLBACK` undoes everything.

**Q15. How do you prevent two people issuing the last copy at the same time?**
`BEGIN IMMEDIATE` takes the write lock first, and the update is `... SET available = available - 1 WHERE id=? AND
available > 0`. If it affects 0 rows, no copy was available and the issue is refused.

**Q16. How does data persist after restart?**
It is written to the SQLite file `instance/library.db` on disk. The app only creates the file if it does not exist, and
sample data is inserted only into an empty books table.

### Features and logic

**Q17. How does issuing a book work?**
Validate input → check book/student exist → check student does not already have it → decrease `available` only if
it is above 0 → insert a transaction with status *Issued*, issue date = today and the chosen due date.

**Q18. How is "no copies available" handled?**
The `WHERE available > 0` condition makes the update affect zero rows; I detect that, roll back and show the
message "No copies ... are available right now". The database `CHECK` also forbids negative stock as a backup.

**Q19. How does return work?**
Set the transaction to *Returned* with today's date and increase `available` by 1, in one transaction. Returning twice is
blocked, so stock cannot be inflated.

**Q20. How are overdue books found?**
Loans with status *Issued* whose `due_date` is earlier than today: `status='Issued' AND due_date < today`. Days overdue =
today − due date, calculated in SQL with `julianday`.

**Q21. What happens when you edit a book's quantity?**
The number of copies currently issued is `quantity − available`. New quantity cannot be lower than that, and
`available` is recomputed as `new quantity − issued`. So the counts never go out of sync.

**Q22. Why can't you delete a book that is issued?**
Deleting it would lose track of a physical book still out. The system tells the admin to return the copies first.

**Q23. How does search work?**
`WHERE title LIKE ? OR author LIKE ? OR isbn LIKE ?` with `%text%` as a bound parameter. I escape `%` and `_` so they
are treated as normal characters. ISBN search ignores hyphens.

### Security and validation

**Q24. What is SQL injection and how did you prevent it?**
Attacker input becoming part of the SQL command (e.g. `' OR 1=1 --`). I always pass values as parameters
(`cursor.execute("... WHERE id = ?", (id,))`), so input is treated as data and never as SQL. There is an automated test
that tries injection strings.

**Q25. How are passwords protected?**
Hashed and salted with Werkzeug's `generate_password_hash`; only the hash is stored. Login uses `check_password_hash`.
No password or secret key is written in the source code.

**Q26. How does login/session work?**
After a correct login the admin's ID is stored in Flask's signed session cookie. A `login_required` decorator checks it
on every protected route; logout clears the session.

**Q27. What is CSRF and how do you stop it?**
A malicious site tricking your browser into sending a request to my app. Every form carries a secret token tied to the
session, and the server rejects POSTs without the right token.

**Q28. What is XSS?**
Injecting JavaScript through input. Jinja2 escapes all output automatically, so `<script>` typed into a field is displayed
as text, not executed.

**Q29. What validation do you perform?**
Required fields, length limits, ISBN format (10/13 digits), whole-number quantity within range, email format, 10-13 digit
phone, no digits in names, due date not in the past, unique ISBN / student ID / email. Errors are shown next to the field.

**Q30. Client-side vs server-side validation?**
Client-side (HTML attributes) gives instant feedback but can be bypassed. Server-side is the real protection, so I do
both.

### Testing and software engineering

**Q31. How did you test the system?**
51 automated `unittest` tests plus a manual walkthrough. Tests cover login, add/edit/delete/search books, student
registration, issue, zero-stock refusal, return, stock accuracy, overdue, persistence, CSRF and SQL injection. Each test uses
a temporary database.

**Q32. Which types of testing are these?**
Unit tests (validators, database constraints), integration tests (routes + database together), functional/black-box tests
(manual walkthrough), and some security tests.

**Q33. Which software process model would suit this project?**
Iterative/incremental or Agile: build login → books → students → issue/return → reports, testing each increment.
(Waterfall also fits because requirements were fixed up front. Be ready to justify whichever you pick.)

**Q34. What are the functional and non-functional requirements?**
Functional: login, manage books/students, issue/return, overdue, search. Non-functional: usability (clean responsive UI),
security (hashing, CSRF, parameterised SQL), reliability (transactions, constraints), portability (runs on Windows with
only Python), maintainability (modular files, tests).

**Q35. How is the code organised for maintainability?**
Separate modules: routes (`app.py`), data layer (`database.py`), validation (`validators.py`), templates, static files and
tests. A change to the UI does not touch the database code.

### Honest limitations (say these confidently - it shows understanding)

**Q36. What are the limitations and future improvements?**
* One admin role only (no librarian/student logins).
* No fines/payments for late returns, no book reservations, no email reminders.
* No pagination (fine for hundreds of records, not for tens of thousands).
* Flask's built-in server is for development; production would use a WSGI server (e.g. Waitress/Gunicorn) and a
  database like PostgreSQL/MySQL for many simultaneous users.
* Deleting a book/student also deletes its returned history; a real system would archive instead.

## 5. Demo script for the professor (5 minutes)

1. Show the folder structure and say the three layers.
2. Log in. Point at the dashboard cards and recent activity.
3. Books: search by author, then ISBN. Add a book. Try a duplicate ISBN to show validation.
4. Students: register one.
5. Issue the new book to that student → show the dashboard numbers change.
6. Try to issue **Design Patterns** (0 copies in sample data) → show the refusal.
7. Return the book → numbers change back. Show History.
8. Show Overdue with days overdue.
9. Delete something → show the confirmation dialog.
10. Open a terminal: `python -m unittest discover -s tests -v` → all tests pass.
11. (If asked) open `database.py` and show the schema with keys and constraints.
