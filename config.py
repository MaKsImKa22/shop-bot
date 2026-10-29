import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0").strip() or 0)
# Потрібен на безкоштовному PythonAnywhere: http://proxy.server:3128
PROXY = os.getenv("PROXY", "").strip() or None

SHOP_NAME = "«Домівка»"

FREE_DELIVERY_FROM = 1500  # грн, від цієї суми доставка безкоштовна
MAX_QTY = 20               # максимум одного товару в кошику

# Код -> назва способу оплати
PAYMENT_METHODS = {
    "cod": "Накладений платіж",
    "card": "Передоплата на картку",
}

INFO_TEXT = (
    "<b>Доставка й оплата</b>\n\n"
    "🚚 Новою Поштою по всій Україні, відправка протягом 1-2 днів.\n"
    f"Від {FREE_DELIVERY_FROM} грн доставка безкоштовна, до цієї суми - за тарифами НП.\n\n"
    "💳 Накладений платіж або передоплата на картку.\n"
    "↩️ Обмін і повернення - 14 днів.\n\n"
    "<i>Це демо-бот: магазин вигаданий, замовлення нікуди не відправляються.</i>"
)
