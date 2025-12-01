from flask import Flask, render_template, redirect, url_for, request, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import stripe
import re
from dotenv import load_dotenv
import os
from functools import wraps
from datetime import datetime

# --- Load environment variables ---
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or "temporary_secret_for_testing"

# --- Stripe config ---
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")

DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")

# --- Utility: DB connection per request ---
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

# --- PASSWORD STRENGTH CHECK ---
def password_is_strong(password):
    return (
        len(password) >= 8
        and re.search(r"[A-Z]", password)
        and re.search(r"[a-z]", password)
        and re.search(r"[0-9]", password)
        and re.search(r"[!@#$%^&*(),.?\":{}|<>]", password)
    )

# --- LOGIN REQUIRED DECORATOR ---
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

# --- INITIALIZE DATABASE ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # users table
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    # products table
    c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL,
            stock INTEGER NOT NULL DEFAULT 0,
            image_url TEXT,
            category TEXT
        )
    """)

    # orders table
    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            total REAL NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # order_items table
    c.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER,
            product_name TEXT,
            unit_price REAL,
            quantity INTEGER,
            FOREIGN KEY(order_id) REFERENCES orders(id)
        )
    """)

    conn.commit()
    conn.close()

# Run DB initialization
init_db()

# --- HOME PAGE ---
@app.route("/")
def main():
    user = session.get("user")
    return render_template("main_page.html", user=user, pub_key=PUBLISHABLE_KEY)

# --- REGISTER ---
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        if not password_is_strong(password):
            flash("Password must be at least 8 characters long and include upper/lowercase letters, numbers, and symbols.", "danger")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(password)

        try:
            conn = get_db()
            c = conn.cursor()
            c.execute("INSERT INTO users (email, password) VALUES (?, ?)", (email, hashed_password))
            conn.commit()
            flash("Account created successfully!", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Email already registered!", "danger")
            return redirect(url_for("register"))

    return render_template("register_page.html")

# --- LOGIN ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if "user" in session:
        return redirect(url_for("main"))

    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT password FROM users WHERE email = ?", (email,))
        result = c.fetchone()

        if result and check_password_hash(result["password"], password):
            session["user"] = email
            flash("Logged in successfully!", "success")
            return redirect(url_for("main"))
        else:
            flash("Invalid email or password!", "danger")
            return redirect(url_for("login"))

    return render_template("login_page.html")

# --- LOGOUT ---
@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Logged out successfully!", "success")
    return redirect(url_for("main"))

# --- ADD TO CART ---
@app.route("/add-to-cart/<product_name>/<float:price>")
@login_required
def add_to_cart(product_name, price):
    cart = session.get("cart", [])

    for item in cart:
        if "quantity" not in item:
            item["quantity"] = 1

    for item in cart:
        if item["name"] == product_name:
            item["quantity"] += 1
            break
    else:
        cart.append({"name": product_name, "price": price, "quantity": 1})

    session["cart"] = cart
    flash(f"{product_name} added to cart!", "success")
    return redirect(request.referrer or url_for("main"))

# --- PRODUCT PAGES ---
@app.route("/graphics-cards")
@login_required
def graphics_cards():
    return render_template("graphics_cards.html")

@app.route("/processors")
@login_required
def processors():
    return render_template("processors.html")

@app.route("/motherboards")
@login_required
def motherboards():
    return render_template("motherboards.html")

@app.route("/ram")
@login_required
def ram():
    return render_template("ram.html")

@app.route("/ssd")
@login_required
def ssd():
    return render_template("ssd.html")

@app.route("/power-supply")
@login_required
def power_supply():
    return render_template("power_supply.html")

@app.route("/pc-cases")
@login_required
def pc_cases():
    return render_template("pc_cases.html")

@app.route("/cooling-fan")
@login_required
def coolingfan():
    return render_template("coolingfan.html")

# --- CART PAGE ---
@app.route("/cart")
@login_required
def cart():
    cart_items = session.get("cart", [])
    total = sum(item["price"] * item["quantity"] for item in cart_items)
    return render_template("cart.html", cart_items=cart_items, total=total)

# --- STRIPE CHECKOUT SESSION ---
@app.route("/checkout", methods=["POST"])
@login_required
def checkout():
    cart_items = session.get("cart", [])
    if not cart_items:
        flash("Your cart is empty!", "warning")
        return redirect(url_for("cart"))

    session_items = []
    for item in cart_items:
        session_items.append({
            'price_data': {
                'currency': 'usd',
                'product_data': {'name': item['name']},
                'unit_amount': int(item['price'] * 100),
            },
            'quantity': item['quantity'],
        })

    checkout_session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=session_items,
        mode='payment',
        success_url=url_for('success', _external=True),
        cancel_url=url_for('cart', _external=True),
        customer_email=session.get("user")
    )

    return redirect(checkout_session.url, code=303)

# --- SUCCESS / CANCEL ---
@app.route("/success")
@login_required
def success():
    cart_items = session.pop("cart", [])
    if cart_items:
        total = sum(item["price"] * item["quantity"] for item in cart_items)
        conn = get_db()
        c = conn.cursor()
        now = datetime.utcnow().isoformat()
        c.execute("INSERT INTO orders (user_email, total, created_at) VALUES (?, ?, ?)", (session.get("user"), total, now))
        order_id = c.lastrowid

        for item in cart_items:
            c.execute("SELECT id FROM products WHERE name = ?", (item["name"],))
            p = c.fetchone()
            product_id = p["id"] if p else None
            unit_price = item["price"]
            c.execute("INSERT INTO order_items (order_id, product_id, product_name, unit_price, quantity) VALUES (?, ?, ?, ?, ?)",
                      (order_id, product_id, item["name"], unit_price, item["quantity"]))
            if p:
                c.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (item["quantity"], product_id))

        conn.commit()
    return render_template("success.html")

@app.route("/cancel")
@login_required
def cancel():
    flash("Payment canceled.", "warning")
    return redirect(url_for("cart"))

# --- PRODUCT DETAIL PAGE ---
@app.route("/product/<int:product_id>")
def product_detail(product_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM products WHERE id=?", (product_id,))
    p = c.fetchone()
    if not p:
        flash("Product not found.", "warning")
        return redirect(url_for("main"))
    return render_template("product_detail.html", product=p)

# --- RUN APP ---
if __name__ == "__main__":
    app.run(debug=True)
