from flask import Flask, render_template, redirect, url_for, request, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import stripe
import re
from dotenv import load_dotenv
import os
from functools import wraps

# --- Load environment variables ---
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or "temporary_secret_for_testing"

# --- Stripe config ---
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")

DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")

# ----------------------------
# PASSWORD STRENGTH CHECK
# ----------------------------
def password_is_strong(password):
    return (
        len(password) >= 8
        and re.search(r"[A-Z]", password)
        and re.search(r"[a-z]", password)
        and re.search(r"[0-9]", password)
        and re.search(r"[!@#$%^&*(),.?\":{}|<>]", password)
    )

# ----------------------------
# LOGIN REQUIRED
# ----------------------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

# ----------------------------
# ADMIN REQUIRED
# ----------------------------
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            flash("You must log in.", "danger")
            return redirect(url_for("login"))

        email = session["user"]
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT role FROM users WHERE email = ?", (email,))
            role = c.fetchone()

        if not role or role[0] != "admin":
            flash("Access denied. Admins only.", "danger")
            return redirect(url_for("main"))

        return f(*args, **kwargs)
    return decorated

# ----------------------------
# INITIALIZE DATABASE
# ----------------------------
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT DEFAULT 'user'
            )
        """)

        # OPTIONAL: Create default admin automatically
        c.execute("SELECT * FROM users WHERE email = 'admin@shop.com'")
        if not c.fetchone():
            c.execute("""
                INSERT INTO users (email, password, role)
                VALUES (?, ?, 'admin')
            """, ("admin@shop.com", generate_password_hash("Admin123!")))
            print("Default admin created: admin@shop.com / Admin123!")

        conn.commit()

init_db()

# ----------------------------
# HOME PAGE
# ----------------------------
@app.route("/")
def main():
    return render_template("main_page.html", pub_key=PUBLISHABLE_KEY, user=session.get("user"))

# ----------------------------
# REGISTER
# ----------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        if not password_is_strong(password):
            flash("Weak password. Use uppercase, lowercase, digits & symbols.", "danger")
            return redirect(url_for("register"))

        hashed = generate_password_hash(password)

        try:
            with sqlite3.connect(DB_PATH) as conn:
                c = conn.cursor()
                c.execute("INSERT INTO users (email, password) VALUES (?, ?)", (email, hashed))
                conn.commit()
        except sqlite3.IntegrityError:
            flash("Email already exists.", "danger")
            return redirect(url_for("register"))

        flash("Account created!", "success")
        return redirect(url_for("login"))

    return render_template("register_page.html")

# ----------------------------
# LOGIN
# ----------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if "user" in session:
        return redirect(url_for("main"))

    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT password, role FROM users WHERE email = ?", (email,))
            user = c.fetchone()

        if user and check_password_hash(user[0], password):
            session["user"] = email
            flash(f"Logged in as {email} ({user[1]})", "success")
            return redirect(url_for("main"))

        flash("Invalid email or password.", "danger")
        return redirect(url_for("login"))

    return render_template("login_page.html")

# ----------------------------
# LOGOUT
# ----------------------------
@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Logged out.", "success")
    return redirect(url_for("main"))

# ----------------------------
# ADMIN PANEL
# ----------------------------
@app.route("/admin")
@admin_required
def admin_dashboard():
    return render_template("admin/admin_dashboard.html")

@app.route("/admin/products")
@admin_required
def admin_products():
    return render_template("admin/products.html")

@app.route("/admin/orders")
@admin_required
def admin_orders():
    return render_template("admin/orders.html")

@app.route("/admin/users")
@admin_required
def admin_users():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT id, email, role FROM users")
        users = c.fetchall()
    return render_template("admin/users.html", users=users)

# ----------------------------
# RUN APP
# ----------------------------
if __name__ == "__main__":
    app.run(debug=True)
