import hashlib
import hmac
import json
import os
import time
from contextlib import contextmanager
from typing import Optional
from urllib.parse import parse_qsl

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

load_dotenv()

BOT_TOKEN = os.environ["8876134883:AAEY_8oHwqOfdZJobzjZaMxNb2eKVvjLFk8"]
ADMIN_KEY = os.environ["201354321BR"]
DATABASE_URL = os.environ["postgresql://u6552_b7fuieyr:JzGvGfkaSyoYqQr4UBN6aCT2kuyUIvR7@87.106.101.66:6432/uzpay_bi6nzs"]
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "https://uzpay751-lang.github.io")

# Цены хранятся ТОЛЬКО на сервере. Измени под себя (сумма в сумах).
PRODUCTS = {
    "stars_50": {"title": "50 Stars", "price": 15000},
    "stars_100": {"title": "100 Stars", "price": 28000},
    "stars_500": {"title": "500 Stars", "price": 135000},
    "premium_3m": {"title": "Telegram Premium 3 мес", "price": 190000},
    "premium_6m": {"title": "Telegram Premium 6 мес", "price": 250000},
    "premium_12m": {"title": "Telegram Premium 12 мес", "price": 430000},
}

app = FastAPI(title="UzPaay API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- БАЗА ДАННЫХ ----------
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY,               -- Telegram user id
    username TEXT,
    first_name TEXT,
    balance BIGINT NOT NULL DEFAULT 0,
    created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    product TEXT NOT NULL,
    recipient TEXT,                      -- @username получателя Stars/Premium
    amount BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | paid | completed | cancelled
    created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS payments (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    order_id BIGINT REFERENCES orders(id),
    amount BIGINT NOT NULL,
    type TEXT NOT NULL,                  -- topup | order_external | order_balance
    note TEXT,
    created_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);
"""


pool = ConnectionPool(
    DATABASE_URL,
    min_size=1,
    max_size=5,
    kwargs={"row_factory": dict_row, "prepare_threshold": None},
    open=True,
)


@contextmanager
def db():
    # commit при успехе, rollback при ошибке (делает сам пул)
    with pool.connection() as conn:
        yield conn


with db() as _c:
    _c.execute(SCHEMA)


# ---------- ПРОВЕРКА TELEGRAM initData ----------
def validate_init_data(init_data: str, max_age: int = 86400) -> dict:
    data = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = data.pop("hash", None)
    if not received_hash:
        raise HTTPException(401, "No hash")
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received_hash):
        raise HTTPException(401, "Bad signature")
    if time.time() - int(data.get("auth_date", 0)) > max_age:
        raise HTTPException(401, "initData expired")
    return json.loads(data["user"])


def current_user(x_init_data: str = Header(default="")) -> int:
    if not x_init_data:
        raise HTTPException(401, "Open the app inside Telegram")
    u = validate_init_data(x_init_data)
    with db() as c:
        c.execute(
            """INSERT INTO users (id, username, first_name, created_at)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT(id) DO UPDATE SET
                 username = excluded.username,
                 first_name = excluded.first_name""",
            (u["id"], u.get("username"), u.get("first_name"), int(time.time())),
        )
    return u["id"]


def admin_only(x_admin_key: str = Header(default="")):
    if not hmac.compare_digest(x_admin_key, ADMIN_KEY):
        raise HTTPException(403, "Forbidden")


# ---------- API ДЛЯ MINI APP ----------
class OrderIn(BaseModel):
    product: str
    recipient: Optional[str] = None


@app.get("/api/products")
def products():
    return [{"id": k, **v} for k, v in PRODUCTS.items()]


@app.get("/api/me")
def me(uid: int = Depends(current_user)):
    with db() as c:
        row = c.execute("SELECT * FROM users WHERE id = %s", (uid,)).fetchone()
    return dict(row)


@app.post("/api/orders")
def create_order(body: OrderIn, uid: int = Depends(current_user)):
    product = PRODUCTS.get(body.product)
    if not product:
        raise HTTPException(400, "Unknown product")
    recipient = (body.recipient or "").strip().lstrip("@")[:64] or None
    with db() as c:
        order = c.execute(
            "INSERT INTO orders (user_id, product, recipient, amount, created_at) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING *",
            (uid, body.product, recipient, product["price"], int(time.time())),
        ).fetchone()
    return dict(order)


@app.get("/api/orders")
def my_orders(uid: int = Depends(current_user)):
    with db() as c:
        rows = c.execute(
            "SELECT * FROM orders WHERE user_id = %s ORDER BY id DESC LIMIT 50", (uid,)
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/payments")
def my_payments(uid: int = Depends(current_user)):
    with db() as c:
        rows = c.execute(
            "SELECT * FROM payments WHERE user_id = %s ORDER BY id DESC LIMIT 50", (uid,)
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/orders/{order_id}/pay-balance")
def pay_with_balance(order_id: int, uid: int = Depends(current_user)):
    with db() as c:
        order = c.execute(
            "SELECT * FROM orders WHERE id = %s AND user_id = %s", (order_id, uid)
        ).fetchone()
        if not order:
            raise HTTPException(404, "Order not found")
        if order["status"] != "pending":
            raise HTTPException(400, "Order is not pending")
        # атомарное списание: не уйдёт в минус даже при двойном клике
        cur = c.execute(
            "UPDATE users SET balance = balance - %s WHERE id = %s AND balance >= %s",
            (order["amount"], uid, order["amount"]),
        )
        if cur.rowcount == 0:
            raise HTTPException(400, "Insufficient balance")
        c.execute("UPDATE orders SET status = 'paid' WHERE id = %s", (order_id,))
        c.execute(
            "INSERT INTO payments (user_id, order_id, amount, type, created_at) VALUES (%s,%s,%s,%s,%s)",
            (uid, order_id, -order["amount"], "order_balance", int(time.time())),
        )
    return {"ok": True}


# ---------- АДМИН (ты сам, через заголовок X-Admin-Key) ----------
class TopupIn(BaseModel):
    amount: int
    note: Optional[str] = None


@app.get("/admin/orders", dependencies=[Depends(admin_only)])
def admin_orders(status: str = "pending"):
    with db() as c:
        rows = c.execute(
            "SELECT * FROM orders WHERE status = %s ORDER BY id DESC LIMIT 100", (status,)
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/admin/orders/{order_id}/confirm", dependencies=[Depends(admin_only)])
def admin_confirm(order_id: int):
    """Ты получил оплату вручную (карта/перевод) -> помечаешь заказ оплаченным."""
    with db() as c:
        order = c.execute("SELECT * FROM orders WHERE id = %s", (order_id,)).fetchone()
        if not order:
            raise HTTPException(404, "Order not found")
        if order["status"] != "pending":
            raise HTTPException(400, "Order is not pending")
        c.execute("UPDATE orders SET status = 'paid' WHERE id = %s", (order_id,))
        c.execute(
            "INSERT INTO payments (user_id, order_id, amount, type, created_at) VALUES (%s,%s,%s,%s,%s)",
            (order["user_id"], order_id, order["amount"], "order_external", int(time.time())),
        )
    return {"ok": True}


@app.post("/admin/orders/{order_id}/complete", dependencies=[Depends(admin_only)])
def admin_complete(order_id: int):
    """Ты выдал Stars/Premium -> заказ выполнен."""
    with db() as c:
        cur = c.execute(
            "UPDATE orders SET status = 'completed' WHERE id = %s AND status = 'paid'",
            (order_id,),
        )
        if cur.rowcount == 0:
            raise HTTPException(400, "Order must be 'paid'")
    return {"ok": True}


@app.post("/admin/users/{user_id}/topup", dependencies=[Depends(admin_only)])
def admin_topup(user_id: int, body: TopupIn):
    if body.amount <= 0:
        raise HTTPException(400, "Amount must be positive")
    with db() as c:
        cur = c.execute(
            "UPDATE users SET balance = balance + %s WHERE id = %s", (body.amount, user_id)
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "User not found")
        c.execute(
            "INSERT INTO payments (user_id, amount, type, note, created_at) VALUES (%s,%s,%s,%s,%s)",
            (user_id, body.amount, "topup", body.note, int(time.time())),
        )
    return {"ok": True}


@app.get("/")
def health():
    return {"status": "ok"}
