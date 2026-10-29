"""Каталог товарів з products.csv - його можна правити в Excel або Google Таблицях."""
import csv
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).parent
CSV_PATH = BASE_DIR / "products.csv"
PHOTOS_DIR = BASE_DIR / "photos"


@dataclass(frozen=True)
class Product:
    id: str
    category: str
    name: str
    price: int
    description: str
    photo: str


_products = {}


def load():
    """Перечитує products.csv. Повертає кількість товарів."""
    products = {}
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            pid = (row.get("id") or "").strip()
            if not pid:
                continue
            products[pid] = Product(
                id=pid,
                category=row["category"].strip(),
                name=row["name"].strip(),
                price=int(row["price"]),
                description=(row.get("description") or "").strip(),
                photo=(row.get("photo") or "").strip(),
            )
    _products.clear()
    _products.update(products)
    return len(products)


def categories():
    return list(dict.fromkeys(p.category for p in _products.values()))


def in_category(category):
    return [p for p in _products.values() if p.category == category]


def get(pid):
    return _products.get(pid)


def photo_path(product):
    if not product.photo:
        return None
    path = PHOTOS_DIR / product.photo
    return path if path.exists() else None
