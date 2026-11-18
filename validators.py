"""Input validation helpers.

Every function takes the raw submitted form (any mapping with ``.get``) and
returns ``(clean_data, errors)``. ``errors`` is a dict of ``field -> message``;
when it is empty the cleaned data is safe to use.
"""
import re
from datetime import date

MAX_QUANTITY = 1000

ISBN_RE = re.compile(r"^(?:\d{13}|\d{9}[\dX])$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
STUDENT_ID_RE = re.compile(r"^[A-Z0-9-]{3,20}$")
CONTACT_RE = re.compile(r"^\+?\d{10,13}$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _text(form, key):
    return (form.get(key) or "").strip()


def normalize_isbn(raw):
    """Remove spaces/hyphens and upper-case (so 978-0-13-235088-4 == 9780132350884)."""
    return re.sub(r"[\s-]", "", raw or "").upper()


def parse_int(raw):
    """Return an int, or None when the text is not a whole number."""
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def validate_book(form, min_quantity=0):
    errors = {}
    title = _text(form, "title")
    author = _text(form, "author")
    category = _text(form, "category")
    isbn = normalize_isbn(form.get("isbn"))
    quantity = parse_int(form.get("quantity"))

    if not title:
        errors["title"] = "Title is required."
    elif len(title) > 200:
        errors["title"] = "Title must be 200 characters or fewer."

    if not author:
        errors["author"] = "Author is required."
    elif len(author) > 150:
        errors["author"] = "Author must be 150 characters or fewer."

    if not isbn:
        errors["isbn"] = "ISBN is required."
    elif not ISBN_RE.match(isbn):
        errors["isbn"] = "ISBN must be 10 or 13 digits (hyphens allowed; a final X is allowed for ISBN-10)."

    if not category:
        errors["category"] = "Category is required."
    elif len(category) > 60:
        errors["category"] = "Category must be 60 characters or fewer."

    if quantity is None:
        errors["quantity"] = "Quantity must be a whole number."
    elif quantity < min_quantity:
        if min_quantity > 0:
            errors["quantity"] = (
                f"Quantity cannot be lower than the {min_quantity} cop"
                f"{'y' if min_quantity == 1 else 'ies'} currently issued."
            )
        else:
            errors["quantity"] = "Quantity cannot be negative."
    elif quantity > MAX_QUANTITY:
        errors["quantity"] = f"Quantity cannot be more than {MAX_QUANTITY}."

    data = {
        "title": title,
        "author": author,
        "isbn": isbn,
        "category": category,
        "quantity": quantity,
    }
    return data, errors


def validate_student(form):
    errors = {}
    student_id = _text(form, "student_id").upper()
    name = _text(form, "name")
    email = _text(form, "email").lower()
    contact = re.sub(r"[\s-]", "", _text(form, "contact"))

    if not student_id:
        errors["student_id"] = "Student ID is required."
    elif not STUDENT_ID_RE.match(student_id):
        errors["student_id"] = "Student ID must be 3-20 characters: letters, digits or hyphens."

    if not name:
        errors["name"] = "Name is required."
    elif len(name) < 2 or len(name) > 100:
        errors["name"] = "Name must be between 2 and 100 characters."
    elif any(ch.isdigit() for ch in name):
        errors["name"] = "Name must not contain digits."

    if not email:
        errors["email"] = "Email is required."
    elif len(email) > 120 or not EMAIL_RE.match(email):
        errors["email"] = "Enter a valid email address."

    if not contact:
        errors["contact"] = "Contact number is required."
    elif not CONTACT_RE.match(contact):
        errors["contact"] = "Contact number must be 10-13 digits (optional leading +)."

    data = {"student_id": student_id, "name": name, "email": email, "contact": contact}
    return data, errors


def validate_issue(form, today, max_days):
    """Validate the issue form. ``today`` is a ``datetime.date``."""
    errors = {}
    book_id = parse_int(form.get("book_id"))
    student_id = parse_int(form.get("student_id"))
    due_raw = _text(form, "due_date")
    due_date = None

    if book_id is None:
        errors["book_id"] = "Please select a book."
    if student_id is None:
        errors["student_id"] = "Please select a student."

    if not due_raw:
        errors["due_date"] = "Due date is required."
    elif not ISO_DATE_RE.match(due_raw):
        errors["due_date"] = "Due date must be a valid date."
    else:
        try:
            due_date = date.fromisoformat(due_raw)
        except ValueError:
            errors["due_date"] = "Due date must be a valid date."
        else:
            if due_date < today:
                errors["due_date"] = "Due date cannot be in the past."
            elif (due_date - today).days > max_days:
                errors["due_date"] = f"Due date cannot be more than {max_days} days from today."

    data = {
        "book_id": book_id,
        "student_id": student_id,
        "due_date": due_date.isoformat() if due_date and "due_date" not in errors else None,
    }
    return data, errors
