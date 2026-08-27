from __future__ import annotations

import json
import base64
import hashlib
import hmac
import os
import secrets
import socket
import sqlite3
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "processing.db"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "10000"))
APP_ENV = os.environ.get("APP_ENV", "development").lower()
AUTH_SECRET = os.environ.get("AUTH_SECRET", "local-development-secret-change-before-production")
BRANCHES = {"บางบัวทอง", "หลังสวน", "ตรัง"}
CATEGORIES = {
    "หมูบด A", "หมูบด B", "หมูบด 5", "หมูบดผสมไก่", "หมูอ้วนหมูบด(หมูบด6)",
    "ขาหน้าล้วน", "ขาหลังล้วน", "ขาหลังเลาะ", "คากิ", "คาตั้งกลม", "เครื่องในต้ม",
    "หมูรวมต้ม", "หมูแปรรูป", "ไก่บดA", "ไก่สับ", "ไก่รวมต้ม", "น่องไก่", "สะโพกไก่",
}
PORK_PROCESSING_PRODUCTS = ("แคปสะโพก", "หนังสัน", "มันแข็ง", "ปีกบน", "ปีกกลาง", "ปีกปลาย", "ปลายปีก", "เศษเนื้อ", "ชายหมูสามชั้น")
PRICE_PRODUCTS = {
    "เนื้อแดง", "สะโพก", "สามชั้น", "ซี่โครง", "ขาหน้า", "ขาหลัง", "สันนอก",
    "อกไก่", "น่องสะโพก",
}
ORDER_PRODUCTS = (
    "เนื้อแดง", "สะโพก", "สามชั้น", "สามชั้นบาง", "สามชั้นลอกหนัง", "ซี่โครง",
    "ซี่โครงอ่อน", "ซี่โครงแข็ง", "กระดูกอ่อน", "เอียวเล้ง", "ขาหน้า", "ขาหลัง",
    "สันนอก", "สันใน", "สันคอ", "หมูบด", "หนังหมู", "มันหมู", "ไส้หมู",
    "ไส้อ่อน", "ไส้ใหญ่", "ตับ", "หัวใจ", "ไต", "ม้าม", "ปอด", "กระเพาะหมู",
    "เซี่ยงจี้", "หัวหมู", "หูหมู", "แก้มหมู", "ลิ้นหมู", "หางหมู", "คากิ",
    "สะโพกติดหนัง", "คอหมูย่าง", "เศษเนื้อ", "เศษเนื้อใหญ่", "เนื้อแก้มหมู",
    "กระดูกอ่อน(โครงแก้ว)", "เล้งตัว", "เล้งปีก", "เล้งคอ", "เอ็นแก้ว", "คาตั้งกลม",
    "พอคช็อป", "ขาเลาะเผา", "แคปสะโพก", "มันคอ", "มันแดง", "มันแข็ง", "แดงแข็ง",
    "มันเปลว", "หนังสัน", "หนังต้ม", "ขั้วตับ", "ไส้ตันต้ม", "เครื่องในต้มรวม",
    "หมูรวมต้ม", "ไส้ขม", "หัวกลมเผา", "หน้ากากเผา", "หางหมู เล็ก", "หางหมูกลาง",
    "หางหมูจัมโบ้", "ตุ้มหมู", "เพดานหมู", "นมหมูย่าง", "หมูบดA", "หมูบดB",
    "หมูบด สูตร5", "หมูหมักนุ่ม", "หมูหมักงา", "หมูหมักพริกไทยดำ",
    "หมูหมักบาร์บีคิว", "หมูหมักหมาล่า",
    "ขั้วปอด", "คางหมู", "สามชั้นหนา", "ชายสามชั้น",
)
SELLING_PRODUCTS = {
    "หมู": ORDER_PRODUCTS,
    "ไก่": ("ไก่เนื้อล้วง(ตัว)","ไก่กลม(ตัว)","อกไก่","สันในไก่","หนังไก่(แผ่น)","มันเครื่องใน","น่อง+สะโพกไก่","น่องไก่","สะโพกไก่","เศษไก่ BL","เศษหนังBL","เศษไก่ BLK","ปีกเต็ม","ปีกบน","ปีกกลาง","ข้อไก่","ขายำ(เล็บมือนาง)","เอ็นแก้ว","กระดูกอ่อนไก่","เครื่องในผ่ารวม","ตับล้วน","ตับติดใจ","หัวใจไก่","ไก่สับ"),
}


def ai_is_configured():
    """Report whether the backend process received a non-empty key.

    Never return, log, or persist the key itself.
    """
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


@contextmanager
def db():
    if USE_POSTGRES:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("ติดตั้ง psycopg[binary] ก่อนใช้ PostgreSQL") from exc
        raw = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    else:
        raw = sqlite3.connect(DB)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys=ON")

    class Connection:
        def execute(self, sql, params=()):
            if USE_POSTGRES:
                sql = sql.replace("?", "%s")
            return raw.execute(sql, params)

        def executemany(self, sql, params):
            if USE_POSTGRES:
                sql = sql.replace("?", "%s")
            return raw.executemany(sql, params)

    try:
        yield Connection()
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def init_db():
    with db() as conn:
        id_column = "BIGSERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
        order_id_column = "BIGINT" if USE_POSTGRES else "INTEGER"
        conn.execute(f"""CREATE TABLE IF NOT EXISTS records(
            id {id_column},
            tx_date TEXT NOT NULL, branch TEXT NOT NULL, category TEXT NOT NULL,
            product_name TEXT NOT NULL, weight_kg REAL NOT NULL,
            image_data TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        )""")
        conn.execute(f"""CREATE TABLE IF NOT EXISTS competitor_prices(
            id {id_column},
            price_date TEXT NOT NULL, branch TEXT NOT NULL, product_name TEXT NOT NULL,
            our_price REAL, competitor_1 REAL, competitor_2 REAL, competitor_3 REAL,
            updated_at TEXT NOT NULL,
            UNIQUE(price_date, branch, product_name)
        )""")
        conn.execute(f"""CREATE TABLE IF NOT EXISTS users(
            id {id_column}, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
            role TEXT NOT NULL, branch TEXT, active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )""")
        conn.execute(f"""CREATE TABLE IF NOT EXISTS orders(
            id {id_column}, order_date DATE NOT NULL, branch TEXT NOT NULL,
            ordered_by TEXT NOT NULL, total_weight NUMERIC NOT NULL,
            note TEXT NOT NULL DEFAULT '', created_at TIMESTAMP NOT NULL
        )""")
        conn.execute(f"""CREATE TABLE IF NOT EXISTS order_items(
            id {id_column}, order_id {order_id_column} NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            product_name TEXT NOT NULL, quantity NUMERIC NOT NULL, unit TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL
        )""")
        conn.execute(f"""CREATE TABLE IF NOT EXISTS selling_prices(
            id {id_column}, product_category TEXT NOT NULL, product_name TEXT NOT NULL,
            purchase_cost NUMERIC(12,2) NOT NULL DEFAULT 0, transport_cost NUMERIC(12,2) NOT NULL DEFAULT 0,
            total_cost NUMERIC(12,2) NOT NULL DEFAULT 0, profit_percent NUMERIC(8,2) NOT NULL DEFAULT 0,
            profit_amount NUMERIC(12,2) NOT NULL DEFAULT 0, calculated_price NUMERIC(12,2) NOT NULL DEFAULT 0,
            recommended_price NUMERIC(12,2) NOT NULL DEFAULT 0, branch TEXT NOT NULL,
            updated_by TEXT NOT NULL, updated_at TIMESTAMP NOT NULL,
            UNIQUE(branch,product_category,product_name)
        )""")
        conn.execute(f"""CREATE TABLE IF NOT EXISTS selling_price_history(
            id {id_column}, product_category TEXT, product_name TEXT, purchase_cost NUMERIC(12,2),
            transport_cost NUMERIC(12,2), total_cost NUMERIC(12,2), profit_percent NUMERIC(8,2),
            calculated_price NUMERIC(12,2), recommended_price NUMERIC(12,2), branch TEXT,
            changed_by TEXT, created_at TIMESTAMP NOT NULL
        )""")
    seed_users()


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    rounds = 210_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return f"pbkdf2_sha256${rounds}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password, encoded):
    try:
        _name, rounds, salt, expected = encoded.split("$", 3)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.urlsafe_b64decode(salt), int(rounds))
        return hmac.compare_digest(base64.urlsafe_b64encode(actual).decode(), expected)
    except (ValueError, TypeError):
        return False


def seed_users():
    accounts = [
        ("admin", "ADMIN_PASSWORD", "admin123", "admin", None),
        ("manager_bangbuathong", "MANAGER_BANGBUATHONG_PASSWORD", "manager123", "manager", "บางบัวทอง"),
        ("manager_trang", "MANAGER_TRANG_PASSWORD", "manager123", "manager", "ตรัง"),
        ("manager_langsuan", "MANAGER_LANGSUAN_PASSWORD", "manager123", "manager", "หลังสวน"),
    ]
    with db() as conn:
        for username, env_name, default_password, role, branch in accounts:
            password = os.environ.get(env_name, default_password)
            exists = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO users(username,password_hash,role,branch,active,created_at) VALUES(?,?,?,?,?,?)",
                    (username, hash_password(password), role, branch, 1, datetime.now().isoformat(timespec="seconds")),
                )
            elif os.environ.get(env_name):
                conn.execute("UPDATE users SET password_hash=?,role=?,branch=?,active=1 WHERE username=?",
                             (hash_password(password), role, branch, username))


def create_session(user):
    payload = {"username": user["username"], "role": user["role"], "branch": user["branch"], "exp": int(time.time()) + 12 * 3600}
    encoded = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode().rstrip("=")
    signature = hmac.new(AUTH_SECRET.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def parse_session(token):
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(AUTH_SECRET.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected): return None
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        return payload if payload.get("exp", 0) > time.time() else None
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def effective_branch(user, requested, allow_all=False):
    if user["role"] == "admin":
        if requested == "ALL" and allow_all: return requested
        if requested in BRANCHES: return requested
    elif requested in (user["branch"], "ALL"):
        return user["branch"]
    raise PermissionError("ไม่มีสิทธิ์เข้าถึงสาขานี้")


def validate_production_config():
    if APP_ENV != "production": return
    required = ["DATABASE_URL", "AUTH_SECRET", "OPENAI_API_KEY", "ADMIN_PASSWORD",
                "MANAGER_BANGBUATHONG_PASSWORD", "MANAGER_TRANG_PASSWORD", "MANAGER_LANGSUAN_PASSWORD"]
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        raise RuntimeError("Production configuration missing: " + ", ".join(missing))
    if len(AUTH_SECRET) < 32:
        raise RuntimeError("AUTH_SECRET must contain at least 32 characters in Production")


def output_text(response):
    for item in response.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    return content.get("text", "")
    return ""


class VisionAPIError(Exception):
    def __init__(self, code, message, http_status=502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def parse_label_response(response):
    """Parse only the two requested label fields from a Responses API result."""
    raw_text = output_text(response)
    if not raw_text:
        raise VisionAPIError("parse_error", "AI ตอบกลับไม่ครบรูปแบบ กรุณาลองใหม่", 502)

    try:
        parsed = json.loads(raw_text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise VisionAPIError("parse_error", "AI ตอบกลับไม่ครบรูปแบบ กรุณาลองใหม่", 502) from exc

    if not isinstance(parsed, dict):
        raise VisionAPIError("parse_error", "AI ตอบกลับไม่ครบรูปแบบ กรุณาลองใหม่", 502)

    product_name = parsed.get("product_name")
    net_weight_kg = parsed.get("net_weight_kg")
    name = product_name.strip() if isinstance(product_name, str) else ""
    weight_is_number = isinstance(net_weight_kg, (int, float)) and not isinstance(net_weight_kg, bool)

    if not name or not weight_is_number or net_weight_kg <= 0:
        return {
            "ok": False,
            "name": "",
            "weight": None,
            "message": "ภาพไม่ชัด กรุณาถ่ายรูปใหม่หรืออัปโหลดรูปใหม่",
        }

    return {
        "ok": True,
        "name": name,
        "weight": float(net_weight_kg),
        "message": "อ่านฉลากสำเร็จ",
    }


def read_label(image_data):
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise VisionAPIError("ai_not_configured", "ยังไม่ได้ตั้งค่า AI กรุณาเปิดโปรแกรมผ่าน start.bat", 503)

    schema = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "product_name": {"type": ["string", "null"]},
            "net_weight_kg": {"type": ["number", "null"]},
        },
        "required": ["product_name", "net_weight_kg"],
    }
    payload = {
        "model": os.environ.get("OPENAI_VISION_MODEL", "gpt-4o"),
        "store": False,
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": (
                "อ่านฉลากสินค้าจากภาพและคืนเฉพาะชื่อสินค้า (product_name) กับน้ำหนักสุทธิ"
                "หน่วยกิโลกรัม (net_weight_kg) เท่านั้น ตัวอย่างชื่อ: เนื้อแดง (ไหล่) และตัวอย่าง"
                "น้ำหนัก: 0.090 กก. ให้พยายามอ่านข้อความแม้ฉลากกลับหัวหรือตะแคง โดยหมุนภาพ"
                f"ในใจได้ หากตรงกับรายการหมูแปรรูปให้ใช้ชื่อที่ตรงที่สุดจาก: {', '.join(PORK_PROCESSING_PRODUCTS)} "
                "ห้ามอ่านหรือใช้ราคา วันที่ผลิต วันหมดอายุ และบาร์โค้ด ถ้าระบุชื่อไม่ได้จริง"
                "ให้ product_name=null ถ้าระบุน้ำหนักเป็นตัวเลขไม่ได้จริงให้ net_weight_kg=null"
            )},
            {"type": "input_image", "image_url": image_data, "detail": "high"}
        ]}],
        "text": {"format": {"type": "json_schema", "name": "label", "strict": True, "schema": schema}}
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            response = json.load(res)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise VisionAPIError("authentication_error", "API key ไม่ถูกต้องหรือหมดอายุ กรุณาเปิดโปรแกรมใหม่และใส่ key ที่ถูกต้อง", 401) from exc
        if exc.code == 429:
            raise VisionAPIError("rate_limit_error", "โควตา AI ไม่เพียงพอหรือมีการเรียกใช้งานถี่เกินไป กรุณาตรวจ Billing แล้วลองใหม่", 429) from exc
        raise VisionAPIError("openai_api_error", f"บริการ AI ขัดข้อง (HTTP {exc.code}) กรุณาลองใหม่", 502) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise VisionAPIError("connection_error", "เชื่อมต่อบริการ AI ไม่สำเร็จ กรุณาตรวจอินเทอร์เน็ตแล้วลองใหม่", 502) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise VisionAPIError("parse_error", "อ่านผลตอบกลับจากบริการ AI ไม่สำเร็จ กรุณาลองใหม่", 502) from exc

    return parse_label_response(response)


def prepare_record_rows(data, current_date=None):
    """Validate a save request without comparing product names to categories.

    The selected category is grouping metadata only. Every valid AI-read product
    is saved under the category the user selected, regardless of its name.
    """
    branch = data.get("branch")
    category = data.get("category")
    tx_date = data.get("date")
    if branch not in BRANCHES or category not in CATEGORIES:
        raise ValueError("สาขาหรือหมวดไม่ถูกต้อง")
    datetime.strptime(tx_date, "%Y-%m-%d")
    if tx_date != (current_date or date.today().isoformat()):
        raise ValueError("ไม่อนุญาตให้เพิ่มรายการย้อนหลัง กรุณาบันทึกรายการของวันนี้เท่านั้น")

    rows = []
    created_at = datetime.now().isoformat(timespec="seconds")
    for item in data.get("items", []):
        name = str(item.get("name", "")).strip()
        weight = float(item.get("weight", 0))
        if item.get("valid") and name and weight > 0:
            rows.append((tx_date, branch, category, name, weight, str(item.get("image", "")), created_at))
    if not rows:
        raise ValueError("ไม่มีรายการที่ผ่านการตรวจสอบ")
    return rows


def prepare_order_items(data):
    rows = []
    for item in data.get("items", []):
        product_name = str(item.get("product_name", "")).strip()
        if product_name not in ORDER_PRODUCTS:
            raise ValueError("พบชื่อสินค้าที่ไม่ถูกต้อง")
        try:
            quantity = Decimal(str(item.get("quantity", 0) or 0))
        except (InvalidOperation, ValueError):
            raise ValueError("จำนวน/น้ำหนักต้องเป็นตัวเลข")
        if not quantity.is_finite() or quantity < 0:
            raise ValueError("จำนวน/น้ำหนักต้องไม่ติดลบ")
        unit = str(item.get("unit", "กก.")).strip()
        if unit != "กก.":
            raise ValueError("หน่วยสินค้าไม่ถูกต้อง")
        if quantity > 0:
            rows.append((product_name, quantity, unit))
    if not rows:
        raise ValueError("กรุณากรอกสินค้าอย่างน้อย 1 รายการที่มีน้ำหนักมากกว่า 0")
    return rows


def calculate_selling_price(item):
    category = str(item.get("product_category", "")).strip()
    product = str(item.get("product_name", "")).strip()
    if category not in SELLING_PRODUCTS or product not in SELLING_PRODUCTS[category]:
        raise ValueError("หมวดหรือรายการสินค้าไม่ถูกต้อง")
    values = []
    for key in ("purchase_cost", "transport_cost", "profit_percent"):
        try: value = Decimal(str(item.get(key, 0) or 0))
        except (InvalidOperation, ValueError): raise ValueError("ราคาและกำไรต้องเป็นตัวเลข")
        if not value.is_finite() or value < 0: raise ValueError("ราคาและกำไรต้องไม่ติดลบ")
        values.append(value)
    purchase, transport, profit_percent = values
    total = purchase + transport
    profit_amount = total * profit_percent / Decimal("100")
    calculated = total + profit_amount
    recommended = calculated.to_integral_value(rounding=ROUND_CEILING)
    if recommended < total: raise ValueError("ราคาขายแนะนำต้องไม่ต่ำกว่าต้นทุนรวม")
    return (category, product, purchase, transport, total, profit_percent, profit_amount, calculated, recommended)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_json(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        super().end_headers()

    def body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 30_000_000:
            raise ValueError("ข้อมูลมีขนาดใหญ่เกินไป")
        return json.loads(self.rfile.read(length) or b"{}")

    def current_user(self):
        if os.environ.get("APP_TESTING") == "1":
            return {"username": "test-admin", "role": "admin", "branch": None}
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        session = cookie.get("processing_session")
        return parse_session(session.value) if session else None

    def require_user(self):
        user = self.current_user()
        if not user:
            self.send_json({"message": "กรุณาเข้าสู่ระบบ"}, 401)
        return user

    def redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self):
        from urllib.parse import urlparse
        clean_path = urlparse(self.path).path
        if clean_path == "/api/status":
            self.send_json({"ai": ai_is_configured(), "date": date.today().isoformat(), "database": "PostgreSQL" if USE_POSTGRES else "SQLite"}); return
        if clean_path in ("/login.html", "/styles.css", "/overview.css", "/login.js") or clean_path.endswith((".css", ".js")):
            super().do_GET(); return
        user = self.current_user()
        if not user:
            if clean_path.startswith("/api/"):
                self.send_json({"message": "กรุณาเข้าสู่ระบบ"}, 401)
            else:
                self.redirect("/login.html")
            return
        if clean_path == "/api/me":
            self.send_json({"username": user["username"], "role": user["role"], "branch": user.get("branch")}); return
        if clean_path == "/api/product-catalog":
            self.send_json({"pork": list(ORDER_PRODUCTS)}); return
        if clean_path.startswith("/api/orders/"):
            try:
                order_id = int(clean_path.rsplit("/", 1)[1])
            except (TypeError, ValueError):
                self.send_json({"message": "รหัสคำสั่งซื้อไม่ถูกต้อง"}, 400); return
            with db() as conn:
                order = conn.execute(
                    "SELECT id,order_date,branch,ordered_by,total_weight,note,created_at FROM orders WHERE id=?",
                    (order_id,),
                ).fetchone()
                if not order:
                    self.send_json({"message": "ไม่พบคำสั่งซื้อ"}, 404); return
                try: effective_branch(user, order["branch"])
                except PermissionError as exc: self.send_json({"message": str(exc)}, 403); return
                items = [dict(row) for row in conn.execute(
                    "SELECT product_name,quantity,unit FROM order_items WHERE order_id=? ORDER BY id",
                    (order_id,),
                )]
            result = dict(order)
            result["order_date"] = str(result["order_date"])
            result["created_at"] = str(result["created_at"])
            result["total_weight"] = float(result["total_weight"])
            for item in items: item["quantity"] = float(item["quantity"])
            result["items"] = items
            self.send_json(result); return
        if clean_path == "/api/orders":
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            branch = q.get("branch", ["ALL" if user["role"] == "admin" else user.get("branch", "")])[0]
            order_date = q.get("date", [""])[0]
            try: branch = effective_branch(user, branch, allow_all=True)
            except PermissionError as exc: self.send_json({"message": str(exc)}, 403); return
            if order_date:
                try: datetime.strptime(order_date, "%Y-%m-%d")
                except ValueError: self.send_json({"message": "รูปแบบวันที่ไม่ถูกต้อง"}, 400); return
            sql = """SELECT o.id,o.order_date,o.branch,o.ordered_by,o.total_weight,o.note,o.created_at,
                COUNT(i.id) item_count FROM orders o LEFT JOIN order_items i ON i.order_id=o.id WHERE 1=1"""
            params = []
            if branch != "ALL": sql += " AND o.branch=?"; params.append(branch)
            if order_date: sql += " AND o.order_date=?"; params.append(order_date)
            sql += " GROUP BY o.id,o.order_date,o.branch,o.ordered_by,o.total_weight,o.note,o.created_at ORDER BY o.order_date DESC,o.id DESC"
            with db() as conn: rows = [dict(row) for row in conn.execute(sql, params)]
            for row in rows:
                row["order_date"] = str(row["order_date"])
                row["created_at"] = str(row["created_at"])
                row["total_weight"] = float(row["total_weight"])
            self.send_json(rows); return
        if clean_path in ("/api/selling-prices", "/api/selling-price-history"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            branch = q.get("branch", ["ALL" if user["role"] == "admin" else user.get("branch", "")])[0]
            category = q.get("category", [""])[0]
            product = q.get("product", [""])[0]
            history_date = q.get("date", [""])[0]
            try: branch = effective_branch(user, branch, allow_all=True)
            except PermissionError as exc: self.send_json({"message": str(exc)}, 403); return
            if category and category not in SELLING_PRODUCTS: self.send_json({"message": "หมวดสินค้าไม่ถูกต้อง"}, 400); return
            if history_date:
                try: datetime.strptime(history_date, "%Y-%m-%d")
                except ValueError: self.send_json({"message": "รูปแบบวันที่ไม่ถูกต้อง"}, 400); return
            table = "selling_price_history" if clean_path.endswith("history") else "selling_prices"
            sql = f"SELECT * FROM {table} WHERE 1=1"; params = []
            if branch != "ALL": sql += " AND branch=?"; params.append(branch)
            if category: sql += " AND product_category=?"; params.append(category)
            if product: sql += " AND product_name=?"; params.append(product)
            if history_date: sql += " AND DATE(created_at)=?"; params.append(history_date)
            sql += " ORDER BY " + ("created_at DESC,id DESC" if table.endswith("history") else "product_category,product_name")
            with db() as conn: rows = [dict(row) for row in conn.execute(sql, params)]
            numeric_fields=("purchase_cost","transport_cost","total_cost","profit_percent","profit_amount","calculated_price","recommended_price")
            for row in rows:
                for key in numeric_fields:
                    if key in row and row[key] is not None: row[key]=float(row[key])
                if "updated_at" in row: row["updated_at"]=str(row["updated_at"])
                if "created_at" in row: row["created_at"]=str(row["created_at"])
            self.send_json(rows); return
        if self.path.startswith("/api/price-history"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            branch = q.get("branch", [""])[0]
            product = q.get("product", [""])[0]
            try: branch = effective_branch(user, branch)
            except PermissionError as exc: self.send_json({"message": str(exc)}, 403); return
            if product not in PRICE_PRODUCTS:
                self.send_json({"message": "สาขาหรือสินค้าไม่ถูกต้อง"}, 400); return
            with db() as conn:
                rows = [dict(row) for row in conn.execute(
                    """SELECT price_date,our_price,competitor_1,competitor_2,competitor_3
                    FROM competitor_prices WHERE branch=? AND product_name=?
                    ORDER BY price_date DESC LIMIT 90""",
                    (branch, product),
                )]
            self.send_json(rows); return
        if self.path.startswith("/api/price-summary"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            price_date = q.get("date", [""])[0]
            branch = q.get("branch", ["ALL"])[0]
            try:
                datetime.strptime(price_date, "%Y-%m-%d")
            except ValueError:
                self.send_json({"message": "รูปแบบวันที่ไม่ถูกต้อง"}, 400); return
            try: branch = effective_branch(user, branch, allow_all=True)
            except PermissionError as exc: self.send_json({"message": str(exc)}, 403); return
            sql = """SELECT branch,product_name,our_price,competitor_1,competitor_2,competitor_3
                FROM competitor_prices WHERE price_date=?"""
            params = [price_date]
            if branch != "ALL":
                sql += " AND branch=?"; params.append(branch)
            sql += " ORDER BY branch,product_name"
            with db() as conn:
                rows = [dict(row) for row in conn.execute(sql, params)]
            self.send_json(rows); return
        if self.path.startswith("/api/competitor-prices"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            price_date = q.get("date", [""])[0]
            branch = q.get("branch", [""])[0]
            try:
                datetime.strptime(price_date, "%Y-%m-%d")
            except ValueError:
                self.send_json({"message": "รูปแบบวันที่ไม่ถูกต้อง"}, 400); return
            try: branch = effective_branch(user, branch)
            except PermissionError as exc: self.send_json({"message": str(exc)}, 403); return
            with db() as conn:
                rows = [dict(row) for row in conn.execute(
                    "SELECT product_name,our_price,competitor_1,competitor_2,competitor_3 FROM competitor_prices WHERE price_date=? AND branch=?",
                    (price_date, branch),
                )]
            self.send_json(rows); return
        if self.path.startswith("/api/report"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            show_all = q.get("all", ["0"])[0] == "1"
            date_from = q.get("date_from", q.get("date", [date.today().isoformat()]))[0]
            date_to = q.get("date_to", q.get("date", [date.today().isoformat()]))[0]
            branch = q.get("branch", ["ALL"])[0]
            category = q.get("category", ["ALL"])[0]
            try: branch = effective_branch(user, branch, allow_all=True)
            except PermissionError as exc: self.send_json({"message": str(exc)}, 403); return
            if not show_all:
                try:
                    datetime.strptime(date_from, "%Y-%m-%d")
                    datetime.strptime(date_to, "%Y-%m-%d")
                except ValueError:
                    self.send_json({"message": "รูปแบบวันที่ไม่ถูกต้อง"}, 400); return
                if date_from > date_to:
                    self.send_json({"message": "วันที่เริ่มต้นต้องไม่เกินวันที่สิ้นสุด"}, 400); return
            sql = "SELECT tx_date,branch,category,product_name,ROUND(SUM(weight_kg),3) weight_kg,COUNT(*) images FROM records WHERE 1=1"
            params = []
            if not show_all:
                sql += " AND tx_date BETWEEN ? AND ?"; params.extend([date_from, date_to])
            if branch != "ALL": sql += " AND branch=?"; params.append(branch)
            if category != "ALL": sql += " AND category=?"; params.append(category)
            sql += " GROUP BY tx_date,branch,category,product_name ORDER BY tx_date DESC,branch,category,product_name"
            with db() as conn: rows = [dict(x) for x in conn.execute(sql, params)]
            self.send_json(rows); return
        if self.path == "/": self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        try:
            data = self.body()
            if self.path == "/api/login":
                username = str(data.get("username", "")).strip()
                password = str(data.get("password", ""))
                with db() as conn:
                    user_row = conn.execute("SELECT username,password_hash,role,branch,active FROM users WHERE username=?", (username,)).fetchone()
                if not user_row or not user_row["active"] or not verify_password(password, user_row["password_hash"]):
                    self.send_json({"message": "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"}, 401); return
                token = create_session(user_row)
                self.send_response(200)
                self.send_header("Set-Cookie", f"processing_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200" + ("; Secure" if APP_ENV == "production" else ""))
                body = json.dumps({"ok": True}, ensure_ascii=False).encode()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body); return
            if self.path == "/api/logout":
                self.send_response(200)
                self.send_header("Set-Cookie", "processing_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
                self.send_header("Content-Length", "2")
                self.end_headers(); self.wfile.write(b"{}"); return
            user = self.require_user()
            if not user: return
            if self.path == "/api/read-label":
                image = str(data.get("image", ""))
                if not image.startswith("data:image/"):
                    self.send_json({"message": "ไฟล์ไม่ใช่รูปภาพ"}, 400); return
                try:
                    self.send_json(read_label(image))
                except VisionAPIError as exc:
                    self.send_json({"ok": False, "error_code": exc.code, "message": exc.message}, exc.http_status)
                return
            if self.path == "/api/records":
                data["branch"] = effective_branch(user, data.get("branch"))
                valid = prepare_record_rows(data)
                with db() as conn:
                    conn.executemany("INSERT INTO records(tx_date,branch,category,product_name,weight_kg,image_data,created_at) VALUES(?,?,?,?,?,?,?)", valid)
                self.send_json({"ok": True, "saved": len(valid)}); return
            if self.path == "/api/orders":
                branch = effective_branch(user, data.get("branch"))
                order_items = prepare_order_items(data)
                note = str(data.get("note", "")).strip()
                if len(note) > 2000:
                    raise ValueError("หมายเหตุยาวเกินไป")
                total_weight = sum((item[1] for item in order_items), Decimal("0"))
                now = datetime.now().isoformat(timespec="seconds")
                stored_total = total_weight if USE_POSTGRES else float(total_weight)
                with db() as conn:
                    order_id = conn.execute(
                        """INSERT INTO orders(order_date,branch,ordered_by,total_weight,note,created_at)
                        VALUES(?,?,?,?,?,?) RETURNING id""",
                        (date.today().isoformat(), branch, user["username"], stored_total, note, now),
                    ).fetchone()["id"]
                    conn.executemany(
                        """INSERT INTO order_items(order_id,product_name,quantity,unit,created_at)
                        VALUES(?,?,?,?,?)""",
                        [(order_id, product_name, quantity if USE_POSTGRES else float(quantity), unit, now)
                         for product_name, quantity, unit in order_items],
                    )
                self.send_json({"ok": True, "id": order_id, "saved": len(order_items), "total_weight": float(total_weight)}); return
            if self.path in ("/api/selling-prices", "/api/selling-prices/bulk"):
                branch = effective_branch(user, data.get("branch"))
                raw_items = data.get("items", []) if self.path.endswith("/bulk") else [data]
                if not raw_items: raise ValueError("ไม่มีรายการสำหรับบันทึก")
                calculated_items = [calculate_selling_price(item) for item in raw_items]
                now = datetime.now().isoformat(timespec="seconds")
                def stored(value): return value if USE_POSTGRES else float(value)
                with db() as conn:
                    for values in calculated_items:
                        category, product, purchase, transport, total, profit_percent, profit_amount, calculated, recommended = values
                        params = (category,product,stored(purchase),stored(transport),stored(total),stored(profit_percent),stored(profit_amount),stored(calculated),stored(recommended),branch,user["username"],now)
                        conn.execute("""INSERT INTO selling_prices(product_category,product_name,purchase_cost,transport_cost,total_cost,profit_percent,profit_amount,calculated_price,recommended_price,branch,updated_by,updated_at)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(branch,product_category,product_name) DO UPDATE SET
                            purchase_cost=excluded.purchase_cost,transport_cost=excluded.transport_cost,total_cost=excluded.total_cost,
                            profit_percent=excluded.profit_percent,profit_amount=excluded.profit_amount,calculated_price=excluded.calculated_price,
                            recommended_price=excluded.recommended_price,updated_by=excluded.updated_by,updated_at=excluded.updated_at""", params)
                        conn.execute("""INSERT INTO selling_price_history(product_category,product_name,purchase_cost,transport_cost,total_cost,profit_percent,calculated_price,recommended_price,branch,changed_by,created_at)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (category,product,stored(purchase),stored(transport),stored(total),stored(profit_percent),stored(calculated),stored(recommended),branch,user["username"],now))
                self.send_json({"ok":True,"saved":len(calculated_items)}); return
            if self.path == "/api/competitor-prices":
                price_date = data.get("date")
                branch = effective_branch(user, data.get("branch"))
                try:
                    datetime.strptime(price_date, "%Y-%m-%d")
                except (TypeError, ValueError):
                    raise ValueError("รูปแบบวันที่ไม่ถูกต้อง")
                if branch not in BRANCHES:
                    raise ValueError("สาขาไม่ถูกต้อง")

                saved_rows = []
                now = datetime.now().isoformat(timespec="seconds")
                for item in data.get("items", []):
                    product_name = str(item.get("product_name", "")).strip()
                    if product_name not in PRICE_PRODUCTS:
                        raise ValueError("พบชื่อสินค้าที่ไม่ถูกต้อง")
                    prices = []
                    for field in ("our_price", "competitor_1", "competitor_2", "competitor_3"):
                        value = item.get(field)
                        if value in (None, ""):
                            prices.append(None)
                        else:
                            number = float(value)
                            if number < 0:
                                raise ValueError("ราคาต้องไม่ติดลบ")
                            prices.append(number)
                    saved_rows.append((price_date, branch, product_name, *prices, now))

                if not saved_rows:
                    raise ValueError("ไม่มีรายการราคาสำหรับบันทึก")
                with db() as conn:
                    conn.executemany("""INSERT INTO competitor_prices(
                        price_date,branch,product_name,our_price,competitor_1,competitor_2,competitor_3,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(price_date,branch,product_name) DO UPDATE SET
                        our_price=excluded.our_price, competitor_1=excluded.competitor_1,
                        competitor_2=excluded.competitor_2, competitor_3=excluded.competitor_3,
                        updated_at=excluded.updated_at""", saved_rows)
                self.send_json({"ok": True, "saved": len(saved_rows)}); return
            self.send_json({"message": "ไม่พบ API"}, 404)
        except PermissionError as exc:
            self.send_json({"message": str(exc)}, 403)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_json({"message": str(exc)}, 400)


class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    """Prevent multiple Windows processes from sharing the same port."""

    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


if __name__ == "__main__":
    validate_production_config()
    init_db()
    server = ExclusiveThreadingHTTPServer((HOST, PORT), Handler)
    print(f"ระบบแปรรูปสินค้าพร้อมใช้งาน: http://localhost:{PORT}")
    print("กด Ctrl+C เพื่อปิดโปรแกรม")
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
