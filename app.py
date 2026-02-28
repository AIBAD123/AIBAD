from flask import Flask, render_template, request, redirect, session, url_for
import sqlite3
import numpy as np
from sklearn.linear_model import LinearRegression
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

app = Flask(__name__)
app.secret_key = "super_secret_key_123"

DB = "data.db"

init_db() 

# ================= DATABASE =================
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    # ===== USERS =====
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT
    )
    """)

    # ===== PRODUCTS =====
    c.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        name TEXT,
        shelf_life INTEGER,
        import_price REAL,
        sell_price REAL,
        stock INTEGER DEFAULT 0
    )
    """)

    # ===== BATCHES =====
    c.execute("""
    CREATE TABLE IF NOT EXISTS batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        product_id INTEGER,
        month INTEGER,
        quantity INTEGER
    )
    """)

    # ===== SALES =====
    c.execute("""
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        product_id INTEGER,
        month INTEGER,
        quantity INTEGER
    )
    """)

    conn.commit()
    conn.close()


# ================= UTIL =================
def get_connection():
    return sqlite3.connect(DB)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function


def calculate_stock(product_id):
    conn = get_connection()
    c = conn.cursor()

    user_id = session.get("user_id")
    if not user_id:
        return 0
    c.execute("SELECT SUM(quantity) FROM batches WHERE product_id=? AND user_id=?",
          (product_id, user_id))
    total_import = c.fetchone()[0] or 0

    c.execute("SELECT SUM(quantity) FROM sales WHERE product_id=? AND user_id=?",
          (product_id, user_id))
    total_sales = c.fetchone()[0] or 0

    conn.close()
    return total_import - total_sales


# ================= AUTH =================

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = generate_password_hash(request.form["password"])

        conn = get_connection()
        c = conn.cursor()

        try:
            c.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, password)
            )
            conn.commit()
            return redirect("/login")

        except sqlite3.IntegrityError:
            return "Tài khoản đã tồn tại!"

        except Exception as e:
            return f"Lỗi hệ thống: {e}"

        finally:
            conn.close()

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT id, username, password FROM users WHERE username=?", (username,))
        user = c.fetchone()
        conn.close()

        if user is None:
            return "Tài khoản không tồn tại"

        stored_password = user[2]

        if check_password_hash(stored_password, password):
            session["user"] = user[1]
            session["user_id"] = user[0]
            return redirect("/dashboard")
        else:
            return "Sai mật khẩu"

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ================= ROUTES =================

@app.route("/")
def home():
    return redirect("/login")


# -------- SẢN PHẨM --------
@app.route("/san_pham", methods=["GET", "POST"])
@login_required
def san_pham():

    conn = get_connection()
    c = conn.cursor()

    if request.method == "POST":
        name = request.form.get("name")
        shelf_life = request.form.get("shelf_life")
        import_price = request.form.get("import_price")
        sell_price = request.form.get("sell_price")

        # Kiểm tra bắt buộc (trừ hạn sử dụng)
        if not name or not import_price or not sell_price:
            user_id = session["user_id"]
            c.execute("SELECT * FROM products WHERE user_id=?", (user_id,))
            products_raw = c.fetchall()

            products = []
            for p in products_raw:
                products.append({
                    "id": p[0],
                    "name": p[2],
                    "shelf_life": p[3],
                    "import_price": p[4],
                    "sell_price": p[5],
                    "stock": calculate_stock(p[0])
                })

            return render_template("san_pham.html",
                                   products=products,
                                   error="Vui lòng nhập đầy đủ thông tin!")

        try:
            import_price = float(import_price)
            sell_price = float(sell_price)
            shelf_life = int(shelf_life) if shelf_life else None
        except ValueError:
            return render_template("san_pham.html",
                                   products=[],
                                   error="Dữ liệu không hợp lệ!")

        user_id = session["user_id"]

        c.execute("""
            INSERT INTO products (user_id, name, shelf_life, import_price, sell_price)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, name, shelf_life, import_price, sell_price))

        conn.commit()

    # Lấy sản phẩm
    user_id = session["user_id"]
    c.execute("SELECT * FROM products WHERE user_id=?", (user_id,))
    products_raw = c.fetchall()

    products = []

    for p in products_raw:
        stock = calculate_stock(p[0])  # p[0] = product_id

        products.append({
            "id": p[0],
            "name": p[2],
            "shelf_life": p[3],
            "import_price": p[4],
            "sell_price": p[5],
            "stock": stock
        })

    conn.close()

    return render_template("san_pham.html", products=products)


# -------- NHẬP HÀNG --------
@app.route("/nhap_hang", methods=["GET", "POST"])
@login_required
def nhap_hang():

    conn = get_connection()
    c = conn.cursor()
    user_id = session["user_id"]

    # LẤY PRODUCTS TRƯỚC
    c.execute("SELECT * FROM products WHERE user_id=?", (user_id,))
    products = c.fetchall()

    if request.method == "POST":
        product_id = request.form.get("product_id")
        month = request.form.get("month")
        quantity = request.form.get("quantity")

        if not product_id or not month or not quantity:
            return render_template("nhap_hang.html",
                                   products=products,
                                   error="Vui lòng nhập đầy đủ thông tin!")

        try:
            product_id = int(product_id)
            month = int(month)
            quantity = int(quantity)
        except ValueError:
            return render_template("nhap_hang.html",
                                   products=products,
                                   error="Dữ liệu không hợp lệ!")

        c.execute("""
            INSERT INTO batches (user_id, product_id, month, quantity)
            VALUES (?, ?, ?, ?)
        """, (user_id, product_id, month, quantity))
        conn.commit()

    conn.close()
    return render_template("nhap_hang.html", products=products)


# -------- BÁN HÀNG --------
@app.route("/ban_hang", methods=["GET", "POST"])
@login_required
def ban_hang():

    conn = get_connection()
    c = conn.cursor()
    user_id = session["user_id"]

    # Lấy danh sách sản phẩm
    c.execute("SELECT * FROM products WHERE user_id=?", (user_id,))
    products = c.fetchall()

    if request.method == "POST":
        product_id = request.form.get("product_id")
        month = request.form.get("month")
        quantity = request.form.get("quantity")

        if not product_id or not month or not quantity:
            conn.close()
            return render_template("ban_hang.html",
                                   products=products,
                                   error="Vui lòng nhập đầy đủ thông tin!")

        try:
            product_id = int(product_id)
            month = int(month)
            quantity = int(quantity)
        except ValueError:
            conn.close()
            return render_template("ban_hang.html",
                                   products=products,
                                   error="Dữ liệu không hợp lệ!")

        # Kiểm tra tồn kho
        current_stock = calculate_stock(product_id)

        if quantity > current_stock:
            conn.close()
            return render_template("ban_hang.html",
                                   products=products,
                                   error="Không đủ hàng trong kho!")

        # Thêm vào bảng sales
        c.execute("""
            INSERT INTO sales (user_id, product_id, month, quantity)
            VALUES (?, ?, ?, ?)
        """, (user_id, product_id, month, quantity))

        conn.commit()
        conn.close()
        return redirect("/dashboard")

    conn.close()
    return render_template("ban_hang.html", products=products)


# -------- DASHBOARD + AI --------
@app.route("/dashboard")
@login_required
def dashboard():

    conn = get_connection()
    c = conn.cursor()

    # ===== Lấy danh sách sản phẩm =====
    user_id = session.get("user_id")
    if not user_id:
        return redirect("/login")
    c.execute("SELECT id FROM products WHERE user_id=?", (user_id,))
    product_ids = c.fetchall()

    total_stock = 0
    for p in product_ids:
        total_stock += calculate_stock(p[0])

    # ===== DOANH THU THEO THÁNG =====
    c.execute("""
        SELECT s.month, SUM(s.quantity * p.sell_price)
        FROM sales s
        JOIN products p ON s.product_id = p.id
        WHERE s.user_id=?
        GROUP BY s.month
        ORDER BY s.month
    """, (user_id,))
    revenue_data = c.fetchall()

    months = [r[0] for r in revenue_data] if revenue_data else []
    revenues = [r[1] for r in revenue_data] if revenue_data else []

    # ===== LỢI NHUẬN THÁNG GẦN NHẤT =====
    profit = 0
    last_month = None

    if months:
        last_month = months[-1]

        c.execute("""
            SELECT SUM(s.quantity * (p.sell_price - p.import_price))
            FROM sales s
            JOIN products p ON s.product_id = p.id
            WHERE s.month=?
        """, (last_month,))
        profit = c.fetchone()[0] or 0

    # ===== AI NÂNG CẤP =====
    alerts = []
    top_product = None

    for p in product_ids:
        product_id = p[0]

        c.execute("SELECT name FROM products WHERE id=?", (product_id,))
        name = c.fetchone()[0]

        stock = calculate_stock(product_id)

        c.execute("SELECT month, quantity FROM sales WHERE product_id=? ORDER BY month", (product_id,))
        data = c.fetchall()

        if len(data) >= 2:
            months_data = np.array([d[0] for d in data]).reshape(-1, 1)
            quantities = np.array([d[1] for d in data])

            model = LinearRegression()
            model.fit(months_data, quantities)

            next_month = months_data.max() + 1
            predicted = model.predict([[next_month]])[0]

            # Tăng / giảm
            growth = quantities[-1] - quantities[-2]

            if growth > 0:
                alerts.append(f"📈 {name} đang tăng trưởng tốt (+{growth})")

            if growth < 0:
                alerts.append(f"📉 {name} đang có xu hướng giảm")

            # Cảnh báo tồn kho
            if predicted > stock:
                alerts.append(f"⚠ {name} có nguy cơ hết hàng tháng tới")

                suggest_import = int(predicted - stock)
                alerts.append(f"📦 Nên nhập thêm khoảng {suggest_import} sản phẩm {name}")

            # Tìm sản phẩm mạnh nhất
            if top_product is None or predicted > top_product[1]:
                top_product = (name, predicted)

    conn.close()

    return render_template(
        "dashboard.html",
        total_stock=total_stock,
        revenues=revenues,
        months=months,
        profit=profit,
        last_month=last_month,
        alerts=alerts,
        top_product=top_product,
        product_count=len(product_ids)
    )


if __name__ == "__main__":
    app.run()
