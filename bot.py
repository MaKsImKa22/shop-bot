import asyncio
import logging
import re
from html import escape

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import catalog
import config
import db

router = Router()

BTN_CATALOG = "🛍 Каталог"
BTN_CART = "🛒 Кошик"
BTN_ORDERS = "📦 Мої замовлення"
BTN_INFO = "ℹ️ Доставка й оплата"
BTN_ABORT = "✖️ Скасувати"

STATUS_LABELS = {"new": "🕐 Нове", "shipped": "📦 Відправлено"}


class Checkout(StatesGroup):
    name = State()
    phone = State()
    city = State()
    branch = State()
    payment = State()
    confirm = State()


class CatCb(CallbackData, prefix="cat"):
    idx: int


class ProdCb(CallbackData, prefix="prod"):
    pid: str
    qty: int = 1


class AddCb(CallbackData, prefix="add"):
    pid: str
    qty: int


class CartCb(CallbackData, prefix="cart"):
    action: str  # inc / dec / del
    pid: str


class PayCb(CallbackData, prefix="pay"):
    method: str


class ShipCb(CallbackData, prefix="ship"):
    order_id: int


# ---------- допоміжне ----------

def money(amount):
    return f"{amount:,}".replace(",", " ") + " грн"


def cart_lines(user_id):
    """Товари з кошика, які ще є в каталозі: список (product, qty) і сума."""
    lines = []
    for pid, qty in db.cart_items(user_id):
        product = catalog.get(pid)
        if product:
            lines.append((product, qty))
    return lines, sum(p.price * q for p, q in lines)


def delivery_note(total):
    if total >= config.FREE_DELIVERY_FROM:
        return "🚚 Доставка безкоштовна"
    return f"🚚 До безкоштовної доставки ще {money(config.FREE_DELIVERY_FROM - total)}"


def items_text(items):
    return "\n".join(f"• {escape(name)} × {qty} = {money(price * qty)}" for name, qty, price in items)


def order_text(order_id, data, items, total):
    header = f"<b>Замовлення #{order_id}</b>\n\n" if order_id else ""
    return header + (
        f"{items_text(items)}\n"
        f"<b>Разом: {money(total)}</b>\n\n"
        f"👤 {escape(data['name'])}\n"
        f"📱 {escape(data['phone'])}\n"
        f"📍 {escape(data['city'])}, Нова Пошта {escape(data['branch'])}\n"
        f"💳 {escape(config.PAYMENT_METHODS[data['payment']])}"
    )


async def notify_admin(bot, text, reply_markup=None):
    if not config.ADMIN_ID:
        return
    try:
        await bot.send_message(config.ADMIN_ID, text, reply_markup=reply_markup)
    except Exception:
        logging.exception("Не вдалося надіслати повідомлення адміну")


async def show(callback, text, reply_markup=None):
    """Показує текстовий екран замість поточного повідомлення.

    Картку товару (фото) редагувати в текст не можна, тому її видаляємо і шлемо нове.
    """
    if callback.message.photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=reply_markup)
    else:
        await callback.message.edit_text(text, reply_markup=reply_markup)


# ---------- клавіатури ----------

def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CATALOG), KeyboardButton(text=BTN_CART)],
            [KeyboardButton(text=BTN_ORDERS), KeyboardButton(text=BTN_INFO)],
        ],
        resize_keyboard=True,
    )


def abort_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_ABORT)]], resize_keyboard=True
    )


def phone_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Надіслати мій номер", request_contact=True)],
            [KeyboardButton(text=BTN_ABORT)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def categories_kb():
    kb = InlineKeyboardBuilder()
    for i, name in enumerate(catalog.categories()):
        kb.button(text=name, callback_data=CatCb(idx=i))
    kb.adjust(1)
    return kb.as_markup()


def products_kb(products):
    kb = InlineKeyboardBuilder()
    for p in products:
        kb.button(text=f"{p.name} - {money(p.price)}", callback_data=ProdCb(pid=p.id))
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text="⬅️ Категорії", callback_data="cats"))
    return kb.as_markup()


def product_caption(p):
    return f"<b>{escape(p.name)}</b>\n{escape(p.description)}\n\n💰 {money(p.price)}"


def product_kb(p, qty, in_cart):
    kb = InlineKeyboardBuilder()
    kb.button(text="➖", callback_data=ProdCb(pid=p.id, qty=qty - 1))
    kb.button(text=f"{qty} шт", callback_data="noop")
    kb.button(text="➕", callback_data=ProdCb(pid=p.id, qty=qty + 1))
    kb.button(text=f"🛒 Додати - {money(p.price * qty)}", callback_data=AddCb(pid=p.id, qty=qty))
    if in_cart:
        kb.button(text=f"✅ У кошику {in_cart} шт - перейти", callback_data="cart")
    idx = catalog.categories().index(p.category)
    kb.button(text="⬅️ До категорії", callback_data=CatCb(idx=idx))
    kb.adjust(3, 1)
    return kb.as_markup()


def cart_view(user_id):
    lines, total = cart_lines(user_id)
    kb = InlineKeyboardBuilder()
    if not lines:
        kb.button(text="🛍 До каталогу", callback_data="cats")
        return "🛒 Кошик порожній. Загляньте в каталог 🙂", kb.as_markup()

    text = ["<b>🛒 Ваш кошик</b>\n"]
    for p, qty in lines:
        text.append(f"• {escape(p.name)}\n   {qty} × {money(p.price)} = {money(p.price * qty)}")
        short = p.name if len(p.name) <= 16 else p.name[:15] + "…"
        kb.row(
            InlineKeyboardButton(text="➖", callback_data=CartCb(action="dec", pid=p.id).pack()),
            InlineKeyboardButton(text=f"{short} ×{qty}", callback_data="noop"),
            InlineKeyboardButton(text="➕", callback_data=CartCb(action="inc", pid=p.id).pack()),
            InlineKeyboardButton(text="❌", callback_data=CartCb(action="del", pid=p.id).pack()),
        )
    text.append(f"\n<b>Разом: {money(total)}</b>\n{delivery_note(total)}")
    kb.row(InlineKeyboardButton(text="✅ Оформити замовлення", callback_data="checkout"))
    kb.row(
        InlineKeyboardButton(text="🗑 Очистити", callback_data="clear_cart"),
        InlineKeyboardButton(text="🛍 Каталог", callback_data="cats"),
    )
    return "\n".join(text), kb.as_markup()


def payment_kb():
    kb = InlineKeyboardBuilder()
    for code, name in config.PAYMENT_METHODS.items():
        kb.button(text=name, callback_data=PayCb(method=code))
    kb.button(text=BTN_ABORT, callback_data="abort")
    kb.adjust(1)
    return kb.as_markup()


def confirm_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Підтвердити замовлення", callback_data="confirm_order")
    kb.button(text=BTN_ABORT, callback_data="abort")
    kb.adjust(1)
    return kb.as_markup()


# ---------- загальні команди й меню ----------

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"Привіт, {escape(message.from_user.first_name)}! 👋\n"
        f"Це магазин товарів для дому {config.SHOP_NAME}.\n\n"
        "Обирайте товари в каталозі, складайте кошик і оформлюйте доставку Новою Поштою.",
        reply_markup=main_menu(),
    )


@router.message(Command("myid"))
async def cmd_myid(message: Message):
    await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")


@router.message(F.text == BTN_CATALOG)
async def menu_catalog(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Оберіть категорію:", reply_markup=categories_kb())


@router.message(F.text == BTN_CART)
async def menu_cart(message: Message, state: FSMContext):
    await state.clear()
    text, kb = cart_view(message.from_user.id)
    await message.answer(text, reply_markup=kb)


@router.message(F.text == BTN_ORDERS)
async def menu_orders(message: Message, state: FSMContext):
    await state.clear()
    orders = db.user_orders(message.from_user.id)
    if not orders:
        await message.answer("У вас поки немає замовлень.")
        return
    lines = ["<b>Ваші замовлення</b>\n"]
    for o in orders:
        lines.append(
            f"#{o['id']} від {o['created_at'][:10]} - {money(o['total'])} - "
            f"{STATUS_LABELS.get(o['status'], o['status'])}"
        )
    await message.answer("\n".join(lines))


@router.message(F.text == BTN_INFO)
async def menu_info(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(config.INFO_TEXT)


@router.message(F.text == BTN_ABORT)
async def text_abort(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Оформлення скасовано. Товари лишились у кошику.", reply_markup=main_menu())


@router.callback_query(F.data == "abort")
async def cb_abort(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Оформлення скасовано. Товари лишились у кошику.")
    await callback.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()


# ---------- каталог ----------

@router.callback_query(F.data == "cats")
async def cb_categories(callback: CallbackQuery):
    await show(callback, "Оберіть категорію:", categories_kb())
    await callback.answer()


@router.callback_query(CatCb.filter())
async def cb_category(callback: CallbackQuery, callback_data: CatCb):
    cats = catalog.categories()
    if not 0 <= callback_data.idx < len(cats):
        await callback.answer("Категорію не знайдено", show_alert=True)
        return
    name = cats[callback_data.idx]
    await show(callback, f"<b>{escape(name)}</b>\nОберіть товар:", products_kb(catalog.in_category(name)))
    await callback.answer()


@router.callback_query(ProdCb.filter())
async def cb_product(callback: CallbackQuery, callback_data: ProdCb):
    p = catalog.get(callback_data.pid)
    if p is None:
        await callback.answer("Цього товару вже немає", show_alert=True)
        return
    qty = callback_data.qty
    if qty < 1:
        await callback.answer("Мінімум 1 шт")
        return
    if qty > config.MAX_QTY:
        await callback.answer(f"Максимум {config.MAX_QTY} шт")
        return

    kb = product_kb(p, qty, db.cart_qty(callback.from_user.id, p.id))
    if callback.message.photo:
        # та сама картка, змінилась кількість
        await callback.message.edit_caption(caption=product_caption(p), reply_markup=kb)
    else:
        try:
            await callback.message.delete()
        except Exception:
            pass
        photo = catalog.photo_path(p)
        if photo:
            await callback.message.answer_photo(FSInputFile(photo), caption=product_caption(p), reply_markup=kb)
        else:
            await callback.message.answer(product_caption(p), reply_markup=kb)
    await callback.answer()


@router.callback_query(AddCb.filter())
async def cb_add(callback: CallbackQuery, callback_data: AddCb):
    p = catalog.get(callback_data.pid)
    if p is None:
        await callback.answer("Цього товару вже немає", show_alert=True)
        return
    user_id = callback.from_user.id
    in_cart = min(db.cart_qty(user_id, p.id) + callback_data.qty, config.MAX_QTY)
    db.cart_set(user_id, p.id, in_cart)
    await callback.answer(f"Додано в кошик: {p.name} × {callback_data.qty}")
    await callback.message.edit_reply_markup(reply_markup=product_kb(p, callback_data.qty, in_cart))


# ---------- кошик ----------

@router.callback_query(F.data == "cart")
async def cb_cart(callback: CallbackQuery):
    text, kb = cart_view(callback.from_user.id)
    await show(callback, text, kb)
    await callback.answer()


@router.callback_query(CartCb.filter())
async def cb_cart_change(callback: CallbackQuery, callback_data: CartCb):
    user_id = callback.from_user.id
    qty = db.cart_qty(user_id, callback_data.pid)
    if callback_data.action == "inc":
        if qty >= config.MAX_QTY:
            await callback.answer(f"Максимум {config.MAX_QTY} шт")
            return
        qty += 1
    elif callback_data.action == "dec":
        qty -= 1
    else:
        qty = 0
    db.cart_set(user_id, callback_data.pid, qty)
    text, kb = cart_view(user_id)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "clear_cart")
async def cb_clear_cart(callback: CallbackQuery):
    db.cart_clear(callback.from_user.id)
    text, kb = cart_view(callback.from_user.id)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer("Кошик очищено")


# ---------- оформлення ----------

@router.callback_query(F.data == "checkout")
async def cb_checkout(callback: CallbackQuery, state: FSMContext):
    lines, total = cart_lines(callback.from_user.id)
    if not lines:
        await callback.answer("Кошик порожній", show_alert=True)
        return
    await state.set_state(Checkout.name)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "<b>Оформлення замовлення</b>\n\n"
        "Крок 1 з 4. Ім'я та прізвище отримувача (як у паспорті, для Нової Пошти):",
        reply_markup=abort_kb(),
    )
    await callback.answer()


@router.message(Checkout.name, F.text)
async def got_name(message: Message, state: FSMContext):
    name = " ".join(message.text.split())
    if len(name.split()) < 2 or len(name) > 60 or re.search(r"[\d@/]", name):
        await message.answer("Напишіть ім'я та прізвище, наприклад: Олена Коваль")
        return
    await state.update_data(name=name)
    await state.set_state(Checkout.phone)
    await message.answer(
        "Крок 2 з 4. Номер телефону. Натисніть кнопку нижче або напишіть вручну.",
        reply_markup=phone_kb(),
    )


async def save_phone(message: Message, state: FSMContext, phone):
    await state.update_data(phone=phone)
    await state.set_state(Checkout.city)
    await message.answer("Крок 3 з 4. Місто або село доставки:", reply_markup=abort_kb())


@router.message(Checkout.phone, F.contact)
async def got_contact(message: Message, state: FSMContext):
    await save_phone(message, state, message.contact.phone_number)


@router.message(Checkout.phone, F.text)
async def got_phone_text(message: Message, state: FSMContext):
    phone = re.sub(r"[^\d+]", "", message.text)
    if not re.fullmatch(r"\+?\d{10,13}", phone):
        await message.answer("Не схоже на номер 🤔 Напишіть у форматі +380XXXXXXXXX або натисніть кнопку.")
        return
    await save_phone(message, state, phone)


@router.message(Checkout.city, F.text)
async def got_city(message: Message, state: FSMContext):
    city = " ".join(message.text.split())
    if not 2 <= len(city) <= 50 or re.search(r"\d", city):
        await message.answer("Напишіть назву населеного пункту, наприклад: Луцьк")
        return
    await state.update_data(city=city)
    await state.set_state(Checkout.branch)
    await message.answer("Крок 4 з 4. Номер відділення або поштомату Нової Пошти:")


@router.message(Checkout.branch, F.text)
async def got_branch(message: Message, state: FSMContext):
    number = re.search(r"\d{1,5}", message.text)
    if not number:
        await message.answer("Напишіть номер відділення цифрами, наприклад: 12")
        return
    await state.update_data(branch=f"№{number.group()}")
    await state.set_state(Checkout.payment)
    await message.answer("Майже готово 👇", reply_markup=main_menu())
    await message.answer("Оберіть спосіб оплати:", reply_markup=payment_kb())


@router.callback_query(Checkout.payment, PayCb.filter(F.method.in_(config.PAYMENT_METHODS)))
async def got_payment(callback: CallbackQuery, callback_data: PayCb, state: FSMContext):
    await state.update_data(payment=callback_data.method)
    await state.set_state(Checkout.confirm)
    data = await state.get_data()
    lines, total = cart_lines(callback.from_user.id)
    items = [(p.name, q, p.price) for p, q in lines]
    await callback.message.edit_text(
        "Перевірте замовлення 👇\n\n" + order_text(None, data, items, total) + f"\n\n{delivery_note(total)}",
        reply_markup=confirm_kb(),
    )
    await callback.answer()


@router.callback_query(Checkout.confirm, F.data == "confirm_order")
async def confirm_order(callback: CallbackQuery, state: FSMContext, bot: Bot):
    user = callback.from_user
    lines, total = cart_lines(user.id)
    if not lines:
        await state.clear()
        await callback.message.edit_text("Кошик порожній, замовлення не створено.")
        await callback.answer()
        return

    data = await state.get_data()
    items = [[p.name, q, p.price] for p, q in lines]
    order_id = db.create_order(
        user.id, data["name"], data["phone"], data["city"], data["branch"],
        data["payment"], items, total,
    )
    db.cart_clear(user.id)
    await state.clear()

    await callback.message.edit_text(
        f"✅ <b>Замовлення #{order_id} прийнято!</b>\n\n"
        "Менеджер зв'яжеться з вами для підтвердження. "
        f"Статус можна подивитись у меню «{BTN_ORDERS}»."
    )
    await callback.answer()

    username = f" (@{escape(user.username)})" if user.username else ""
    kb = InlineKeyboardBuilder()
    kb.button(text="📦 Позначити відправленим", callback_data=ShipCb(order_id=order_id))
    await notify_admin(
        bot,
        "🆕 " + order_text(order_id, data, items, total) + f"\n\nTelegram: {escape(user.full_name)}{username}",
        kb.as_markup(),
    )


# ---------- адмін ----------

@router.callback_query(ShipCb.filter())
async def cb_ship(callback: CallbackQuery, callback_data: ShipCb, bot: Bot):
    if callback.from_user.id != config.ADMIN_ID:
        await callback.answer()
        return
    order = db.get_order(callback_data.order_id)
    if order is None or order["status"] == "shipped":
        await callback.answer("Вже відправлено або не знайдено")
        return
    db.set_status(order["id"], "shipped")
    await callback.message.edit_text(callback.message.html_text + "\n\n📦 <b>Відправлено</b>")
    await callback.answer("Покупця сповіщено")
    try:
        await bot.send_message(
            order["user_id"],
            f"📦 Замовлення #{order['id']} відправлено! Чекайте SMS від Нової Пошти.",
        )
    except Exception:
        logging.exception("Не вдалося сповістити покупця")


@router.message(Command("orders"), F.from_user.id == config.ADMIN_ID)
async def admin_orders(message: Message):
    orders = db.recent_orders()
    if not orders:
        await message.answer("Замовлень поки немає.")
        return
    lines = ["<b>Останні замовлення</b>\n"]
    for o in orders:
        lines.append(
            f"#{o['id']} {o['created_at']} - {money(o['total'])} - {STATUS_LABELS.get(o['status'], o['status'])}\n"
            f"   {escape(o['name'])}, {escape(o['phone'])}, {escape(o['city'])} {escape(o['branch'])}"
        )
    await message.answer("\n".join(lines))


@router.message(Command("reload"), F.from_user.id == config.ADMIN_ID)
async def admin_reload(message: Message):
    try:
        count = catalog.load()
    except Exception as e:
        await message.answer(f"Не вдалося прочитати products.csv: {escape(str(e))}")
        return
    await message.answer(f"Каталог оновлено: {count} товарів.")


# ---------- застарілі кнопки ----------

@router.callback_query()
async def stale_button(callback: CallbackQuery):
    await callback.answer("Ця кнопка вже не активна. Почніть заново через меню 🙂", show_alert=True)


async def main():
    logging.basicConfig(level=logging.INFO)
    if not config.BOT_TOKEN:
        raise SystemExit("Не знайдено BOT_TOKEN. Створіть файл .env за зразком .env.example")

    catalog.load()
    db.init_db()
    session = AiohttpSession(proxy=config.PROXY) if config.PROXY else None
    bot = Bot(
        config.BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
