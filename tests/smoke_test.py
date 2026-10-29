"""Проганяє весь шлях покупця й адміна з фейковим Telegram (без мережі й токена)."""
import asyncio, sys, tempfile, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["BOT_TOKEN"] = "42:TEST"
os.environ["ADMIN_ID"] = "999"

import catalog, config, db
db.DB_PATH = Path(tempfile.mkdtemp()) / "test.db"
import bot as app

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Update, Message
from aiogram.methods import SendMessage, SendPhoto, EditMessageText, EditMessageCaption

sent = []
msg_id = [100]

class FakeSession(BaseSession):
    async def make_request(self, bot, method, timeout=None):
        sent.append(method)
        if isinstance(method, (SendMessage, SendPhoto, EditMessageText, EditMessageCaption)):
            msg_id[0] += 1
            return Message.model_validate({"message_id": msg_id[0], "date": 0,
                "chat": {"id": getattr(method, "chat_id", 1) or 1, "type": "private"},
                "text": getattr(method, "text", None) or getattr(method, "caption", None) or "x"})
        return True
    async def close(self): pass
    async def stream_content(self, *a, **k):
        yield b""

USER = {"id": 1, "is_bot": False, "first_name": "Тест", "username": "tester"}
CHAT = {"id": 1, "type": "private"}
uid = [0]

def msg(text=None, contact=None):
    uid[0] += 1
    m = {"message_id": uid[0], "date": 0, "chat": CHAT, "from": USER}
    if text: m["text"] = text
    if contact: m["contact"] = contact
    return Update.model_validate({"update_id": uid[0], "message": m})

def cb(data, photo=False):
    uid[0] += 1
    m = {"message_id": 5, "date": 0, "chat": CHAT, "from": {"id": 42, "is_bot": True, "first_name": "B"}}
    if photo:
        m["photo"] = [{"file_id": "f", "file_unique_id": "u", "width": 1, "height": 1}]
        m["caption"] = "x"
    else:
        m["text"] = "x"
    return Update.model_validate({"update_id": uid[0], "callback_query": {
        "id": str(uid[0]), "from": USER, "chat_instance": "x", "data": data, "message": m}})

def last_kb_data():
    for m in reversed(sent):
        rm = getattr(m, "reply_markup", None)
        if rm is not None and hasattr(rm, "inline_keyboard"):
            return [b.callback_data for row in rm.inline_keyboard for b in row]
    return []

async def main():
    assert catalog.load() == 9
    db.init_db()
    bot = Bot("42:TEST", session=FakeSession(), default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(app.router)

    async def step(u, label):
        n = len(sent)
        await dp.feed_update(bot, u)
        new = sent[n:]
        print(f"--- {label}: {[type(m).__name__ for m in new]}")
        for m in new:
            t = getattr(m, "text", None) or getattr(m, "caption", None)
            if t: print("   ", t.replace("\n", " | ")[:160])
        return new

    await step(msg("/start"), "start")
    await step(msg(app.BTN_CART), "empty cart")
    await step(msg(app.BTN_CATALOG), "catalog")
    await step(cb(last_kb_data()[0]), "category Кухня")
    new = await step(cb(last_kb_data()[0]), "product card")
    assert any(isinstance(m, SendPhoto) for m in new), "no photo card"
    plus = last_kb_data()[2]
    await step(cb(plus, photo=True), "qty +1")
    add = [d for d in last_kb_data() if d.startswith("add:")][0]
    assert add == "add:k1:2", add
    await step(cb(add, photo=True), "add 2 to cart")
    assert db.cart_qty(1, "k1") == 2
    await step(cb("prod:k1:0", photo=True), "qty below 1 (ignored)")

    # другий товар з іншої категорії
    await step(cb("cat:2", photo=True), "back to category Декор")
    await step(cb("prod:d1:1"), "candle card")
    await step(cb("add:d1:1", photo=True), "add candle")

    await step(cb("cart", photo=True), "open cart from card")
    await step(cb("cart:inc:d1"), "candle +1")
    await step(cb("cart:dec:k1"), "knives -1")
    assert db.cart_items(1) == [("k1", 1), ("d1", 2)], db.cart_items(1)

    # оформлення
    await step(cb("checkout"), "checkout")
    await step(msg("Олена"), "bad name")
    await step(msg("Олена Коваль"), "name")
    await step(msg("123"), "bad phone")
    await step(msg("+380 000 000 00 00"), "13 digits (bad)")
    assert app.normalize_phone("+380 67 123 45 67") == "+380671234567"
    assert app.normalize_phone("380671234567") == "+380671234567"
    await step(msg("067 123 45 67"), "phone without +38")
    await step(msg("Луцьк"), "city")
    await step(msg("відділення"), "bad branch")
    await step(msg("Відділення 12"), "branch")
    await step(cb("pay:cod"), "payment")
    new = await step(cb("confirm_order"), "confirm")
    admin = [m for m in new if getattr(m, "chat_id", None) == 999]
    assert admin and "1 270 грн" in admin[0].text, "admin not notified / wrong total"
    assert db.cart_items(1) == []
    order = db.get_order(1)
    assert order["branch"] == "№12" and order["total"] == 890 + 190 * 2
    assert order["phone"] == "+380671234567", order["phone"]

    await step(msg(app.BTN_ORDERS), "my orders")
    await step(msg(app.BTN_INFO), "info")

    # покупець не може позначити відправленим
    await step(cb("ship:1"), "ship by customer (ignored)")
    assert db.get_order(1)["status"] == "new"

    # адмін
    USER["id"] = 999
    new = await step(cb("ship:1"), "ship by admin")
    assert any(getattr(m, "chat_id", None) == 1 for m in new), "customer not notified"
    assert db.get_order(1)["status"] == "shipped"
    await step(msg("/orders"), "admin orders")
    await step(msg("/reload"), "admin reload")
    USER["id"] = 1
    await step(msg("/orders"), "non-admin orders (should be silent)")

    # скасування оформлення лишає кошик
    await step(cb("add:t1:1", photo=True), "add plaid")
    await step(cb("checkout"), "checkout again")
    await step(msg(app.BTN_ABORT), "abort")
    assert db.cart_items(1) == [("t1", 1)]

    await step(cb("pay:cod"), "stale payment button")
    print("ALL OK")

asyncio.run(main())
