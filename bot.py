# UzPay bot: приём заказов, пополнение баланса бота в XTR, выдача подарков и Premium.
# Установка: pip install pyTelegramBotAPI requests
import html, sqlite3, threading, time, requests, telebot
from telebot import types

TOKEN = "8876134883:AAEY_8oHwqOfdZJobzjZaMxNb2eKVvjLFk8"
ADMIN_ID = 8836465969                    # ваш числовой ID (узнать у @userinfobot)
SHOP_URL = "https://uzpay751-lang.github.io/UzPaay/"
SUPPORT = "https://t.me/ygbag"
CARD, CARD_NAME = "5614 6828 7736 3459", "R.B"
RATE = 195                                # сум за 1 ★

STARS = [50, 100, 250, 500, 1000, 2500]
# месяцы: (сколько ★ спишется с бота, цена для клиента в сум)
PREM = {3: (1000, 169000), 6: (1500, 229000), 12: (2500, 389000)}
GIFTS = [("🧸", "Мишка", 15), ("🌹", "Роза", 25), ("🎁", "Подарок", 25),
         ("🎂", "Торт", 50), ("💐", "Букет", 50), ("🚀", "Ракета", 50),
         ("🍾", "Шампанское", 50), ("🏆", "Кубок", 100),
         ("💍", "Кольцо", 100), ("💎", "Алмаз", 100)]

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
db = sqlite3.connect("uzpay.db", check_same_thread=False)
lock = threading.Lock()
db.executescript("""
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT);
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, buyer INTEGER,
  target TEXT, kind TEXT, idx INTEGER, price INTEGER, status TEXT, ts INTEGER);""")
waiting = {}      # user_id -> order_id (ждём чек)
_gifts = {"t": 0, "d": []}


def q(sql, *a, fetch=False):
    with lock:
        cur = db.execute(sql, a)
        db.commit()
        return cur.fetchall() if fetch else cur


def api(method, **params):
    """Прямой вызов Bot API (для sendGift, giftPremiumSubscription, getMyStarBalance)."""
    return requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}",
                         json=params, timeout=30).json()


def money(n):
    return f"{n:,}".replace(",", " ")


def item(kind, i):
    if kind == "s":
        return f"⭐ {STARS[i]} Stars", STARS[i] * RATE
    if kind == "p":
        m = list(PREM)[i]
        return f"💎 Premium · {m} мес.", PREM[m][1]
    e, n, c = GIFTS[i]
    return f"{e} {n} ({c} ★)", c * RATE


# ---------- меню клиента ----------
def main_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("⭐ Stars", callback_data="k:s"),
           types.InlineKeyboardButton("💎 Premium", callback_data="k:p"))
    kb.add(types.InlineKeyboardButton("🎁 Подарки", callback_data="k:g"))
    kb.add(types.InlineKeyboardButton("🚀 Открыть магазин", url=SHOP_URL))
    kb.add(types.InlineKeyboardButton("💬 Поддержка", url=SUPPORT))
    return kb


def catalog_kb(kind):
    n = {"s": len(STARS), "p": len(PREM), "g": len(GIFTS)}[kind]
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(*[types.InlineKeyboardButton(f"{item(kind, i)[0]} · {money(item(kind, i)[1])}",
                                        callback_data=f"buy:{kind}:{i}") for i in range(n)])
    kb.add(types.InlineKeyboardButton("‹ Назад", callback_data="home"))
    return kb


def new_order(u, kind, idx, target=None):
    me = (u.username or "").lower()
    if not target or target.lstrip("@").lower() == me:
        target = f"id:{u.id}"
    else:
        target = "@" + target.lstrip("@")
    price = item(kind, idx)[1]
    cur = q("INSERT INTO orders(buyer,target,kind,idx,price,status,ts) VALUES(?,?,?,?,?,?,?)",
            u.id, target, kind, idx, price, "new", int(time.time()))
    return cur.lastrowid


def show_payment(chat, oid):
    _, buyer, target, kind, idx, price, *_ = q("SELECT * FROM orders WHERE id=?", oid, fetch=True)[0]
    who = "вам" if target.startswith("id:") else html.escape(target)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅ Я оплатил", callback_data=f"paid:{oid}"))
    kb.add(types.InlineKeyboardButton("✖ Отмена", callback_data="home"))
    bot.send_message(chat,
        f"🧾 <b>Заказ №{oid}</b>\n{item(kind, idx)[0]}\nПолучатель: {who}\n"
        f"К оплате: <b>{money(price)} сум</b>\n\n"
        f"UzCard: <code>{CARD}</code> ({CARD_NAME})\n\n"
        "Переведите точную сумму и нажмите «Я оплатил», затем отправьте скриншот чека.",
        reply_markup=kb)


@bot.message_handler(commands=["start"])
def start(m):
    u = m.from_user
    q("INSERT OR REPLACE INTO users(id,username) VALUES(?,?)", u.id, (u.username or "").lower())
    parts = m.text.split(maxsplit=1)
    if len(parts) == 2:                         # ссылка из приложения: s-2-username
        try:
            kind, idx, target = parts[1].split("-", 2)
            if kind in "spg" and int(idx) >= 0:
                item(kind, int(idx))
                return show_payment(m.chat.id, new_order(u, kind, int(idx), target))
        except Exception:
            pass
    bot.send_message(m.chat.id,
        f"👋 Привет, <b>{html.escape(u.first_name or 'друг')}</b>!\n\n"
        "Добро пожаловать в <b>UzPay</b> — твой надёжный магазин.\n"
        "⭐ Stars · 💎 Premium · 🎁 Подарки\n\nВыбери, что купить:",
        reply_markup=main_kb())


@bot.callback_query_handler(func=lambda c: True)
def buttons(c):
    d, u = c.data, c.from_user
    chat, msg = c.message.chat.id, c.message.message_id
    bot.answer_callback_query(c.id)
    if d == "home":
        bot.edit_message_text("Выбери, что купить:", chat, msg, reply_markup=main_kb())
    elif d.startswith("k:"):
        bot.edit_message_text("Выберите вариант:", chat, msg, reply_markup=catalog_kb(d[2]))
    elif d.startswith("buy:"):
        _, k, i = d.split(":")
        show_payment(chat, new_order(u, k, int(i)))
    elif d.startswith("paid:"):
        waiting[u.id] = int(d[5:])
        bot.send_message(chat, "📸 Отправьте скриншот или фото чека одним сообщением.")
    elif d.startswith(("ok:", "no:")) and u.id == ADMIN_ID:
        decide(d[:2], int(d[3:]), chat)


@bot.message_handler(content_types=["photo", "document"])
def receipt(m):
    oid = waiting.pop(m.from_user.id, None)
    if not oid:
        return
    q("UPDATE orders SET status='review' WHERE id=?", oid)
    row = q("SELECT * FROM orders WHERE id=?", oid, fetch=True)[0]
    _, buyer, target, kind, idx, price, *_ = row
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅ Принять", callback_data=f"ok:{oid}"),
           types.InlineKeyboardButton("❌ Отклонить", callback_data=f"no:{oid}"))
    bot.forward_message(ADMIN_ID, m.chat.id, m.message_id)
    bot.send_message(ADMIN_ID,
        f"🆕 Заказ №{oid}\n{item(kind, idx)[0]}\nСумма: {money(price)} сум\n"
        f"Покупатель: <code>{buyer}</code> @{html.escape(m.from_user.username or '-')}\n"
        f"Получатель: {html.escape(target)}", reply_markup=kb)
    bot.reply_to(m, "✅ Чек получен. Заказ проверяется, мы сообщим о результате.")


# ---------- выдача ----------
def gift_id(emoji, cost):
    if time.time() - _gifts["t"] > 600:
        r = api("getAvailableGifts")
        _gifts["d"] = r.get("result", {}).get("gifts", [])
        _gifts["t"] = time.time()
    for g in _gifts["d"]:
        if g.get("star_count") == cost and g.get("sticker", {}).get("emoji") == emoji:
            return g["id"]


def resolve(target):
    if target.startswith("id:"):
        return int(target[3:])
    r = q("SELECT id FROM users WHERE username=?", target.lstrip("@").lower(), fetch=True)
    return r[0][0] if r else None


def decide(act, oid, admin_chat):
    row = q("SELECT * FROM orders WHERE id=?", oid, fetch=True)
    if not row or row[0][6] not in ("review", "error"):
        return bot.send_message(admin_chat, "Заказ уже обработан.")
    _, buyer, target, kind, idx, price, *_ = row[0]
    if act == "no":
        q("UPDATE orders SET status='rejected' WHERE id=?", oid)
        bot.send_message(buyer, f"❌ Заказ №{oid} отклонён. Вопросы: {SUPPORT}")
        return bot.send_message(admin_chat, f"Заказ №{oid} отклонён.")
    if kind == "s":     # Bot API не умеет отправлять «голые» Stars пользователю
        q("UPDATE orders SET status='manual' WHERE id=?", oid)
        bot.send_message(buyer, f"✅ Заказ №{oid} принят. Stars будут отправлены вручную в ближайшее время.")
        return bot.send_message(admin_chat,
            f"⚠️ №{oid}: отправьте <b>{STARS[idx]} Stars</b> вручную → {html.escape(target)}")
    uid = resolve(target)
    if not uid:
        return bot.send_message(admin_chat, f"№{oid}: получатель {html.escape(target)} не запускал бота. "
                                            "Попросите его нажать /start и повторите.")
    if kind == "p":
        m = list(PREM)[idx]
        r = api("giftPremiumSubscription", user_id=uid, month_count=m, star_count=PREM[m][0])
    else:
        e, _, cost = GIFTS[idx]
        gid = gift_id(e, cost)
        if not gid:
            return bot.send_message(admin_chat, f"№{oid}: подарок {e} сейчас недоступен в Telegram.")
        r = api("sendGift", user_id=uid, gift_id=gid)
    if r.get("ok"):
        q("UPDATE orders SET status='done' WHERE id=?", oid)
        bot.send_message(admin_chat, f"✅ №{oid} выдан.")
        bot.send_message(buyer, f"🎉 Заказ №{oid} выполнен! Спасибо за покупку в UzPay.")
    else:
        q("UPDATE orders SET status='error' WHERE id=?", oid)
        bot.send_message(admin_chat, f"⚠️ №{oid} не выдан: {r.get('description')}\n"
                                     "Если не хватает звёзд — пополните: /topup 1000")


# ---------- админ ----------
def admin_only(m):
    return m.from_user.id == ADMIN_ID


@bot.message_handler(commands=["balance"], func=admin_only)
def balance(m):
    r = api("getMyStarBalance")
    amt = (r.get("result") or {}).get("amount") if r.get("ok") else None
    bot.send_message(m.chat.id, f"⭐ Баланс бота: <b>{amt}</b>" if amt is not None
                     else f"Ошибка: {r.get('description')}")


@bot.message_handler(commands=["topup"], func=admin_only)
def topup(m):
    try:
        n = int(m.text.split()[1])
        assert n > 0
    except Exception:
        return bot.send_message(m.chat.id, "Использование: /topup 1000")
    bot.send_invoice(m.chat.id, "Пополнение баланса бота", f"{n} Stars на баланс UzPay",
                     f"topup:{n}", provider_token="", currency="XTR",
                     prices=[types.LabeledPrice("Stars", n)])


@bot.pre_checkout_query_handler(func=lambda p: True)
def pre_checkout(p):
    bot.answer_pre_checkout_query(p.id, ok=p.from_user.id == ADMIN_ID,
                                  error_message="Недоступно")


@bot.message_handler(content_types=["successful_payment"])
def paid_ok(m):
    n = m.successful_payment.total_amount
    bot.send_message(m.chat.id, f"✅ Баланс бота пополнен на <b>{n} ★</b>. Проверить: /balance")


@bot.message_handler(commands=["orders"], func=admin_only)
def orders(m):
    rows = q("SELECT id,kind,idx,price,status FROM orders WHERE status IN ('review','error','manual') "
             "ORDER BY id DESC LIMIT 15", fetch=True)
    bot.send_message(m.chat.id, "\n".join(
        f"№{i} · {item(k, x)[0]} · {money(p)} сум · {s}" for i, k, x, p, s in rows) or "Нет активных заказов")


@bot.message_handler(commands=["admin"], func=admin_only)
def admin(m):
    bot.send_message(m.chat.id, "🔐 <b>Админ</b>\n/balance — баланс бота ★\n"
                                "/topup N — пополнить баланс бота звёздами (XTR)\n"
                                "/orders — активные заказы")


bot.infinity_polling(skip_pending=True)
