from __future__ import annotations

import json
import os
import socket
import sqlite3
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import date, datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "processing.db"
HOST, PORT = "0.0.0.0", int(os.environ.get("PORT", "8088"))
BRANCHES = {"บางบัวทอง", "หลังสวน", "ตรัง"}
CATEGORIES = {
    "หมูบด A", "หมูบด B", "หมูบด 5", "หมูบดผสมไก่", "หมูอ้วนหมูบด(หมูบด6)",
    "ขาหน้าล้วน", "ขาหลังล้วน", "ขาหลังเลาะ", "คากิ", "คาตั้งกลม", "เครื่องในต้ม",
    "หมูรวมต้ม", "ไก่บดA", "ไก่สับ", "ไก่รวมต้ม", "น่องไก่", "สะโพกไก่",
}


def ai_is_configured():
    """Report whether the backend process received a non-empty key.

    Never return, log, or persist the key itself.
    """
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


@contextmanager
def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS records(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tx_date TEXT NOT NULL, branch TEXT NOT NULL, category TEXT NOT NULL,
            product_name TEXT NOT NULL, weight_kg REAL NOT NULL,
            image_data TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        )""")


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
                "ในใจได้ ห้ามอ่านหรือใช้ราคา วันที่ผลิต วันหมดอายุ และบาร์โค้ด ถ้าระบุชื่อไม่ได้จริง"
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

    def do_GET(self):
        if self.path.startswith("/api/report"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            show_all = q.get("all", ["0"])[0] == "1"
            date_from = q.get("date_from", q.get("date", [date.today().isoformat()]))[0]
            date_to = q.get("date_to", q.get("date", [date.today().isoformat()]))[0]
            branch = q.get("branch", ["ALL"])[0]
            category = q.get("category", ["ALL"])[0]
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
        if self.path == "/api/status":
            self.send_json({"ai": ai_is_configured(), "date": date.today().isoformat()}); return
        if self.path == "/": self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        try:
            data = self.body()
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
                valid = prepare_record_rows(data)
                with db() as conn:
                    conn.executemany("INSERT INTO records(tx_date,branch,category,product_name,weight_kg,image_data,created_at) VALUES(?,?,?,?,?,?,?)", valid)
                self.send_json({"ok": True, "saved": len(valid)}); return
            self.send_json({"message": "ไม่พบ API"}, 404)
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
    init_db()
    server = ExclusiveThreadingHTTPServer((HOST, PORT), Handler)
    print(f"ระบบแปรรูปสินค้าพร้อมใช้งาน: http://localhost:{PORT}")
    print("กด Ctrl+C เพื่อปิดโปรแกรม")
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
