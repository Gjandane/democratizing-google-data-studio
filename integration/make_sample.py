"""Generate samples/ecommerce_sales.csv, the seeded demo dataset (seed 42, 2,000 orders).

    uv run --project integration python integration/make_sample.py           # write the file
    uv run --project integration python integration/make_sample.py --check   # exit 1 unless it matches

One row per order (one product each), dated 2026-01-01 to 2026-09-30, sorted by date with
sequential order IDs. Money is computed in integer cents, so the output is byte-stable.
"""

import argparse
import csv
import datetime as dt
import hashlib
import io
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples" / "ecommerce_sales.csv"

SEED = 42
ROWS = 2000
START = dt.date(2026, 1, 1)
END = dt.date(2026, 9, 30)
COLUMNS = ["order_id", "order_date", "region", "country", "category", "product_name",
           "customer_segment", "quantity", "unit_price", "revenue"]

# region -> (weight, [(country, weight)])
REGIONS = {
    "APAC": (40, [("Philippines", 30), ("Japan", 20), ("Singapore", 15), ("Australia", 20),
                  ("India", 15)]),
    "EMEA": (30, [("Germany", 30), ("United Kingdom", 25), ("France", 20), ("Netherlands", 15),
                  ("South Africa", 10)]),
    "AMER": (30, [("United States", 50), ("Canada", 20), ("Brazil", 15), ("Mexico", 15)]),
}

# category -> (weight, [(product, list price in cents)])
CATEGORIES = {
    "Electronics": (30, [("Wireless Mouse", 2499), ("Mechanical Keyboard", 8900),
                         ("USB-C Hub", 3999), ("Noise-Cancelling Headphones", 19900),
                         ("Webcam", 5950)]),
    "Home": (25, [("Desk Lamp", 3950), ("Coffee Grinder", 4900), ("Throw Blanket", 3499),
                  ("Ceramic Mug Set", 2200), ("Air Purifier", 14900)]),
    "Apparel": (25, [("Hoodie", 4500), ("Running Shoes", 9500), ("Rain Jacket", 7900),
                     ("Wool Socks", 1800), ("Baseball Cap", 2150)]),
    "Office": (20, [("Notebook Set", 1250), ("Ergonomic Chair", 24900), ("Monitor Stand", 4400),
                    ("Gel Pens", 899), ("Desk Organizer", 2799)]),
}

# segment -> (weight, min quantity, max quantity)
SEGMENTS = {"Consumer": (60, 1, 3), "SMB": (30, 1, 6), "Enterprise": (10, 5, 20)}

DISCOUNT_RATE = 0.12   # share of orders sold at 10% off


def _pick(rng, weighted):
    """One key of a {key: (weight, ...)} dict, or one item of a [(item, weight)] list."""
    if isinstance(weighted, dict):
        keys = list(weighted)
        return rng.choices(keys, weights=[weighted[k][0] for k in keys])[0]
    return rng.choices([i for i, _ in weighted], weights=[w for _, w in weighted])[0]


def _money(cents):
    return f"{cents // 100}.{cents % 100:02d}"


def build_rows():
    rng = random.Random(SEED)
    span = (END - START).days
    days = [START + dt.timedelta(days=i) for i in range(span + 1)]
    # Gentle growth over the period, quieter weekends: a trend line worth charting.
    day_weights = [(1 + 0.5 * i / span) * (0.75 if d.weekday() >= 5 else 1.0)
                   for i, d in enumerate(days)]
    rows = []
    for _ in range(ROWS):
        order_date = rng.choices(days, weights=day_weights)[0]
        region = _pick(rng, REGIONS)
        country = _pick(rng, REGIONS[region][1])
        category = _pick(rng, CATEGORIES)
        product, list_cents = rng.choice(CATEGORIES[category][1])
        segment = _pick(rng, SEGMENTS)
        _, qmin, qmax = SEGMENTS[segment]
        quantity = rng.randint(qmin, qmax)
        unit_cents = list_cents
        if rng.random() < DISCOUNT_RATE:
            unit_cents = (list_cents * 90 + 50) // 100   # 10% off, rounded half up
        rows.append([order_date, region, country, category, product, segment, quantity,
                     unit_cents, quantity * unit_cents])
    rows.sort(key=lambda r: r[0])   # stable: same-day orders keep generation order
    return [[f"O-{n:05d}", r[0].isoformat(), *r[1:6], str(r[6]), _money(r[7]), _money(r[8])]
            for n, r in enumerate(rows, start=1)]


def render_csv():
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(COLUMNS)
    writer.writerows(build_rows())
    return buf.getvalue().encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="regenerate in memory and compare with the committed file")
    args = parser.parse_args()
    data = render_csv()
    digest = hashlib.sha256(data).hexdigest()[:16]
    rel = OUT.relative_to(ROOT).as_posix()
    if args.check:
        if not OUT.exists():
            print(f"FAIL {rel} is missing; run make_sample.py without --check")
            return 1
        if OUT.read_bytes() != data:
            print(f"FAIL {rel} differs from the seed {SEED} output; regenerate it "
                  f"(expected sha256 {digest}...)")
            return 1
        print(f"PASS {rel} is byte-identical to the seed {SEED} output "
              f"({ROWS} rows, sha256 {digest}...)")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(data)
    print(f"wrote {rel}: {ROWS} rows, {len(data)} bytes, sha256 {digest}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
