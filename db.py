import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).with_name("shop.db")


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(_connect()) as conn, conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cart (
                user_id INTEGER NOT NULL,
                product_id TEXT NOT NULL,
                qty INTEGER NOT NULL,
                PRIMARY KEY (user_id, product_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                city TEXT NOT NULL,
                branch TEXT NOT NULL,
                payment TEXT NOT NULL,
                items TEXT NOT NULL,
                total INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'new',
                created_at TEXT NOT NULL
            )
            """
        )


# ---------- кошик ----------

def cart_items(user_id):
    """Список (product_id, qty) у порядку додавання."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT product_id, qty FROM cart WHERE user_id = ? ORDER BY rowid", (user_id,)
        )
        return [(row["product_id"], row["qty"]) for row in rows]


def cart_qty(user_id, product_id):
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT qty FROM cart WHERE user_id = ? AND product_id = ?", (user_id, product_id)
        ).fetchone()
        return row["qty"] if row else 0


def cart_set(user_id, product_id, qty):
    """Ставить кількість товару; 0 або менше - прибирає з кошика."""
    with closing(_connect()) as conn, conn:
        if qty <= 0:
            conn.execute(
                "DELETE FROM cart WHERE user_id = ? AND product_id = ?", (user_id, product_id)
            )
        else:
            conn.execute(
                "INSERT INTO cart (user_id, product_id, qty) VALUES (?, ?, ?) "
                "ON CONFLICT (user_id, product_id) DO UPDATE SET qty = excluded.qty",
                (user_id, product_id, qty),
            )


def cart_clear(user_id):
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM cart WHERE user_id = ?", (user_id,))


# ---------- замовлення ----------

def create_order(user_id, name, phone, city, branch, payment, items, total):
    """items - список [назва, кількість, ціна]. Повертає номер замовлення."""
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO orders (user_id, name, phone, city, branch, payment, items, total, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id, name, phone, city, branch, payment,
                json.dumps(items, ensure_ascii=False), total,
                datetime.now().strftime("%Y-%m-%d %H:%M"),
            ),
        )
        return cur.lastrowid


def get_order(order_id):
    with closing(_connect()) as conn:
        return conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()


def order_items(order):
    return json.loads(order["items"])


def set_status(order_id, status):
    with closing(_connect()) as conn, conn:
        conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))


def user_orders(user_id, limit=5):
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)
        ).fetchall()


def recent_orders(limit=10):
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
