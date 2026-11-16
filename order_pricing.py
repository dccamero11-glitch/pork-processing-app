"""Shared ordering prices and immutable billing snapshots."""
import json
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def initialize(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS order_catalog_prices(
        product_name TEXT PRIMARY KEY, unit_price NUMERIC NOT NULL,
        updated_by TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS order_billing(
        order_id BIGINT PRIMARY KEY, invoice_number TEXT NOT NULL,
        total_amount NUMERIC NOT NULL, snapshot TEXT NOT NULL)""")


def money(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or result > 100000000:
            raise ValueError()
        return result.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('ราคาต้องเป็นตัวเลขตั้งแต่ 0 ถึง 100,000,000 บาท')


def prices(conn):
    return [dict(product_name=r['product_name'], unit_price=float(r['unit_price']),
                 updated_by=r['updated_by'], updated_at=r['updated_at'])
            for r in conn.execute('SELECT * FROM order_catalog_prices ORDER BY product_name')]


def save_prices(conn, data, user, allowed, now):
    if user.get('role') != 'admin':
        raise PermissionError('เฉพาะแอดมินเท่านั้นที่แก้ไขราคาได้')
    rows = data.get('items')
    if not isinstance(rows, list) or not rows or len(rows) > 1000:
        raise ValueError('กรุณาระบุรายการราคา')
    # Optimistic version check prevents overwriting another admin's edits.
    current = prices(conn)
    if data.get('version') != version(current):
        raise ValueError('ราคาถูกแก้ไขโดยผู้ใช้อื่น กรุณาโหลดหน้าใหม่ก่อนบันทึก')
    seen = set()
    for row in rows:
        name = row.get('product_name')
        if name not in allowed or name in seen:
            raise ValueError('ชื่อสินค้าไม่ถูกต้องหรือซ้ำกัน')
        seen.add(name)
        value = row.get('unit_price')
        if value in (None, ''):
            conn.execute('DELETE FROM order_catalog_prices WHERE product_name=?', (name,))
        else:
            conn.execute('''INSERT INTO order_catalog_prices(product_name,unit_price,updated_by,updated_at)
                VALUES(?,?,?,?) ON CONFLICT(product_name) DO UPDATE SET
                unit_price=excluded.unit_price,updated_by=excluded.updated_by,updated_at=excluded.updated_at''',
                         (name, str(money(value)), user['username'], now))


def version(rows):
    import hashlib
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def billing(conn, order_id):
    row = conn.execute('SELECT snapshot FROM order_billing WHERE order_id=?', (order_id,)).fetchone()
    return json.loads(row['snapshot']) if row else None


def save_billing(conn, order_id, data, items, now):
    fields = {'invoice_number': 100, 'branch_name': 200, 'address': 2000,
              'contact': 150, 'phone': 40, 'tax_id': 30, 'sender': 150,
              'receiver': 150, 'sent_date': 10, 'received_date': 10}
    raw = data.get('billing', {})
    if not isinstance(raw, dict):
        raise ValueError('ข้อมูลหัวบิลไม่ถูกต้อง')
    result = {}
    for key, limit in fields.items():
        value = str(raw.get(key, '')).strip()
        if len(value) > limit:
            raise ValueError('ข้อมูลหัวบิลยาวเกินกำหนด')
        result[key] = value
    for key in ('sent_date', 'received_date'):
        if result[key]:
            try:
                date.fromisoformat(result[key])
            except ValueError:
                raise ValueError('รูปแบบวันที่ส่งหรือรับสินค้าไม่ถูกต้อง')
    if not result['invoice_number'] or not result['address'] or not result['branch_name']:
        raise ValueError('กรุณากรอกเลขที่ใบสั่งซื้อ/ใบวางบิล ชื่อสาขา และที่อยู่')
    quoted = data.get('quoted_prices')
    if not isinstance(quoted, dict):
        raise ValueError('กรุณาโหลดราคาสินค้าก่อนบันทึก')
    current = {r['product_name']: money(r['unit_price']) for r in prices(conn)}
    detail = []
    for name, quantity, unit in items:
        if name not in current:
            raise ValueError('ยังไม่ได้กำหนดราคา: ' + name)
        price = current[name]
        if name not in quoted or money(quoted[name]) != price:
            raise ValueError('ราคาสินค้าเปลี่ยน กรุณาโหลดราคาใหม่และตรวจสอบยอดก่อนยืนยัน')
        line = (quantity * price).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        detail.append(dict(product_name=name, quantity=float(quantity), unit=unit,
                           unit_price=float(price), line_total=float(line)))
    total = sum((Decimal(str(r['line_total'])) for r in detail), Decimal('0'))
    result.update(items=detail, total_amount=float(total), saved_at=now)
    conn.execute('INSERT INTO order_billing(order_id,invoice_number,total_amount,snapshot) VALUES(?,?,?,?)',
                 (order_id, result['invoice_number'], str(total), json.dumps(result, ensure_ascii=False)))
    return result
