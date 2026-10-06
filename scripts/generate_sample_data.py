"""Generate messy, realistic sample data for a fictional startup.

Two raw sources, the way a real customer would hand them over:
  * data/raw/stripe_payments.csv  -> card payments (amounts in minor units, unix timestamps,
                                     mixed currencies, failed and refunded payments)
  * data/raw/bank_transactions.csv -> Swedish bank export (semicolon separated, comma decimals,
                                     mixed date formats, duplicate rows, Stripe payouts that
                                     would double count revenue if not removed)

The company "Nordlys Analytics AB" is fictional.
"""

import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

random.seed(42)
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

MONTHS = [(2026, m) for m in range(1, 10)]  # Jan to Sep 2026


def stripe_payments():
    rows = []
    customers = 18
    pid = 1000
    for year, month in MONTHS:
        customers += random.randint(1, 4)  # the business grows a little every month
        for c in range(customers):
            pid += 1
            day = random.randint(1, 27)
            ts = datetime(year, month, day, random.randint(8, 20), tzinfo=timezone.utc)
            if c % 5 == 0:
                currency, amount = "eur", random.choice([39900, 49900])  # EUR customers
            else:
                currency, amount = "sek", random.choice([450000, 520000, 600000])
            status = random.choices(["succeeded", "failed", "refunded"], [92, 5, 3])[0]
            rows.append({
                "id": f"py_{pid}",
                "created": int(ts.timestamp()),
                "amount": amount,  # minor units: 450000 = 4 500,00 SEK
                "currency": currency if random.random() > 0.1 else currency.upper(),
                "status": status,
                "customer": f"cus_{c:03d}",
            })
    with open(RAW / "stripe_payments.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    return rows


def swedish_amount(value: float) -> str:
    """-12345.5 -> '-12 345,50' (Swedish bank style)."""
    sign = "-" if value < 0 else ""
    whole, dec = f"{abs(value):.2f}".split(".")
    whole = f"{int(whole):,}".replace(",", " ")
    return f"{sign}{whole},{dec}"


def mixed_date(d: datetime) -> str:
    """Banks are not always consistent about date formats."""
    return d.strftime("%Y-%m-%d") if random.random() > 0.2 else d.strftime("%d/%m/%Y")


def bank_transactions():
    rows = []
    for year, month in MONTHS:
        headcount = 4 + (month // 3)
        fixed = [
            (25, "LÖN LÖNEUTBETALNING", -42000 * headcount),
            (1, "HYRA KONTOR SVEAVÄGEN", -28000),
            (5, "AWS EMEA", -random.uniform(9000, 16000)),
            (6, "GOOGLE WORKSPACE", -1890),
            (8, "FIGMA INC", -1450),
            (12, "OPENAI API", -random.uniform(2500, 6000)),
            (15, "ANTHROPIC API", -random.uniform(3000, 7000)),
            (18, "FORTNOX AB", -799),
            (20, "LINKEDIN ADS", -random.uniform(5000, 12000)),
        ]
        for day, text, amount in fixed:
            rows.append((datetime(year, month, day), text, round(amount, 2)))
        # a few one-off purchases, some of which our rules will not recognise
        for _ in range(random.randint(1, 3)):
            text = random.choice(["SL ACCESS", "WEBHALLEN", "ESPRESSO HOUSE", "CLAS OHLSON"])
            rows.append((datetime(year, month, random.randint(1, 27)), text,
                         -round(random.uniform(150, 4500), 2)))
        # Stripe pays out to the bank: this is NOT new revenue
        rows.append((datetime(year, month, 28), "STRIPE PAYOUT", round(random.uniform(80000, 140000), 2)))

    out = []
    for d, text, amount in rows:
        out.append([mixed_date(d), text, swedish_amount(amount)])
        if random.random() < 0.04:  # the export sometimes duplicates a row
            out.append([mixed_date(d), text, swedish_amount(amount)])
    with open(RAW / "bank_transactions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Datum", "Text", "Belopp"])
        w.writerows(out)


if __name__ == "__main__":
    stripe_payments()
    bank_transactions()
    print(f"Sample data written to {RAW}")
