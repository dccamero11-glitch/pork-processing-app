from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8-sig")

old = '''                counts = {}
                for row in query_all(
                    """SELECT product_code, actual_quantity, system_quantity, variance
                       FROM stock_counts
                       WHERE stock_date = ? AND branch = ?""",
                    (stock_date, branch),
                ):
                    counts[str(row["product_code"])] = row
'''

new = '''                counts = {}
                for row in query_all(
                    """SELECT product_code, actual_quantity, system_quantity, variance
                       FROM stock_counts
                       WHERE stock_date = ? AND branch = ?""",
                    (stock_date, branch),
                ):
                    counts[str(row["product_code"])] = {
                        "actual_quantity": float(row["actual_quantity"] or 0),
                        "system_quantity": float(row["system_quantity"] or 0),
                        "variance": float(row["variance"] or 0),
                    }
'''

if old not in s:
    raise SystemExit("STOP: expected stock count GET block not found")

s = s.replace(old, new, 1)
p.write_text(s, encoding="utf-8")

print("OK: stock count GET persistence fix installed")
