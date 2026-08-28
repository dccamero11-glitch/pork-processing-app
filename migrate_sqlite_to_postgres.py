"""One-time, non-destructive migration from processing.db to DATABASE_URL."""
import os
import sqlite3
from pathlib import Path

if not os.environ.get("DATABASE_URL", "").startswith(("postgres://", "postgresql://")):
    raise SystemExit("Set DATABASE_URL to the destination PostgreSQL database first")

import app

source_path = Path(__file__).resolve().parent / "processing.db"
if not source_path.exists():
    raise SystemExit(f"SQLite source not found: {source_path}")

app.init_db()
source = sqlite3.connect(source_path)
source.row_factory = sqlite3.Row

with app.db() as destination:
    existing = destination.execute("SELECT COUNT(*) AS count FROM records").fetchone()["count"]
    existing_prices = destination.execute("SELECT COUNT(*) AS count FROM competitor_prices").fetchone()["count"]
    if existing or existing_prices:
        raise SystemExit("Destination is not empty; migration stopped to prevent duplicate data")
    records = [tuple(row) for row in source.execute("SELECT tx_date,branch,category,product_name,weight_kg,image_data,created_at FROM records")]
    prices = [tuple(row) for row in source.execute("SELECT price_date,branch,product_name,our_price,competitor_1,competitor_2,competitor_3,updated_at FROM competitor_prices")]
    destination.executemany("INSERT INTO records(tx_date,branch,category,product_name,weight_kg,image_data,created_at) VALUES(?,?,?,?,?,?,?)", records)
    destination.executemany("INSERT INTO competitor_prices(price_date,branch,product_name,our_price,competitor_1,competitor_2,competitor_3,updated_at) VALUES(?,?,?,?,?,?,?,?)", prices)

source.close()
print(f"Migrated {len(records)} processing records and {len(prices)} price records to PostgreSQL")
