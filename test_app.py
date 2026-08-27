import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

import app


def response_payload(product_name="เนื้อแดง (ไหล่)", net_weight_kg=0.090):
    text = json.dumps({"product_name": product_name, "net_weight_kg": net_weight_kg}, ensure_ascii=False)
    return {"output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}


class FakeHTTPResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class LabelReadingTests(unittest.TestCase):
    def setUp(self):
        os.environ["APP_TESTING"] = "1"

    def tearDown(self):
        os.environ.pop("APP_TESTING", None)

    def test_clear_label_is_accepted(self):
        result = app.parse_label_response(response_payload())
        self.assertTrue(result["ok"])
        self.assertEqual(result["name"], "เนื้อแดง (ไหล่)")
        self.assertAlmostEqual(result["weight"], 0.090)

    def test_only_missing_real_value_is_unclear(self):
        for name, weight in ((None, 0.090), ("เนื้อแดง (ไหล่)", None), ("", 0.090)):
            with self.subTest(name=name, weight=weight):
                result = app.parse_label_response(response_payload(name, weight))
                self.assertFalse(result["ok"])
                self.assertEqual(result["message"], "ภาพไม่ชัด กรุณาถ่ายรูปใหม่หรืออัปโหลดรูปใหม่")

    def test_request_schema_contains_only_two_label_fields(self):
        fake_response = FakeHTTPResponse(json.dumps(response_payload(), ensure_ascii=False).encode("utf-8"))
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "x"}, clear=False):
            with mock.patch("urllib.request.urlopen", return_value=fake_response) as mocked_open:
                result = app.read_label("data:image/png;base64,AA==")

        request = mocked_open.call_args.args[0]
        payload = json.loads(request.data)
        properties = payload["text"]["format"]["schema"]["properties"]
        self.assertEqual(set(properties), {"product_name", "net_weight_kg"})
        prompt = payload["input"][0]["content"][0]["text"]
        self.assertIn("กลับหัวหรือตะแคง", prompt)
        self.assertTrue(result["ok"])

    def test_401_and_429_are_not_reported_as_unclear_images(self):
        cases = ((401, "authentication_error"), (429, "rate_limit_error"))
        for status, expected_code in cases:
            with self.subTest(status=status):
                error = urllib.error.HTTPError("https://api.openai.com/v1/responses", status, "error", {}, None)
                with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "x"}, clear=False):
                    with mock.patch("urllib.request.urlopen", side_effect=error):
                        with self.assertRaises(app.VisionAPIError) as raised:
                            app.read_label("data:image/png;base64,AA==")
                self.assertEqual(raised.exception.code, expected_code)
                self.assertNotIn("ภาพไม่ชัด", raised.exception.message)

    def test_parse_error_is_distinct(self):
        malformed = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "not-json"}]}]}
        with self.assertRaises(app.VisionAPIError) as raised:
            app.parse_label_response(malformed)
        self.assertEqual(raised.exception.code, "parse_error")

    def test_read_label_endpoint_returns_detected_values(self):
        server = app.ExclusiveThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/api/read-label"
            body = json.dumps({"image": "data:image/png;base64,AA=="}).encode()
            request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with mock.patch("app.read_label", return_value={
                "ok": True, "name": "เนื้อแดง (ไหล่)", "weight": 0.090, "message": "อ่านฉลากสำเร็จ"
            }):
                with urllib.request.urlopen(request, timeout=3) as response:
                    result = json.load(response)
            self.assertTrue(result["ok"])
            self.assertEqual(result["name"], "เนื้อแดง (ไหล่)")
            self.assertAlmostEqual(result["weight"], 0.090)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_endpoint_preserves_api_error_status_and_code(self):
        server = app.ExclusiveThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/api/read-label"
            body = json.dumps({"image": "data:image/png;base64,AA=="}).encode()
            cases = ((401, "authentication_error"), (429, "rate_limit_error"), (502, "parse_error"))
            for status, code in cases:
                with self.subTest(status=status, code=code):
                    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
                    error = app.VisionAPIError(code, "ทดสอบข้อผิดพลาด", status)
                    with mock.patch("app.read_label", side_effect=error):
                        with self.assertRaises(urllib.error.HTTPError) as raised:
                            urllib.request.urlopen(request, timeout=3)
                    self.assertEqual(raised.exception.code, status)
                    response = json.loads(raised.exception.read())
                    self.assertEqual(response["error_code"], code)
                    self.assertNotIn("key", response)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_historical_report_filters_date_range_and_all_dates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.object(app, "DB", Path(temp_dir) / "history.db"):
                app.init_db()
                rows = [
                    ("2026-08-20", "บางบัวทอง", "หมูบด A", "เนื้อแดง", 1.0, "", "2026-08-20T08:00:00"),
                    ("2026-08-21", "บางบัวทอง", "หมูบด A", "เนื้อแดง", 2.0, "", "2026-08-21T08:00:00"),
                    ("2026-08-22", "ตรัง", "หมูรวมต้ม", "สามชั้น", 3.0, "", "2026-08-22T08:00:00"),
                ]
                with app.db() as connection:
                    connection.executemany(
                        "INSERT INTO records(tx_date,branch,category,product_name,weight_kg,image_data,created_at) VALUES(?,?,?,?,?,?,?)",
                        rows,
                    )

                server = app.ExclusiveThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    base_url = f"http://127.0.0.1:{server.server_address[1]}/api/report"
                    with urllib.request.urlopen(base_url + "?date_from=2026-08-20&date_to=2026-08-21", timeout=3) as response:
                        ranged = json.load(response)
                    with urllib.request.urlopen(base_url + "?all=1", timeout=3) as response:
                        all_dates = json.load(response)
                    self.assertEqual(len(ranged), 2)
                    self.assertEqual({row["tx_date"] for row in ranged}, {"2026-08-20", "2026-08-21"})
                    self.assertEqual(len(all_dates), 3)
                    self.assertEqual(all_dates[0]["tx_date"], "2026-08-22")
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)

    def test_record_endpoint_rejects_backdated_entry(self):
        server = app.ExclusiveThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/api/records"
            body = json.dumps({
                "date": "2000-01-01",
                "branch": "บางบัวทอง",
                "category": "หมูบด A",
                "items": [{"valid": True, "name": "เนื้อแดง", "weight": 1.0, "image": ""}],
            }, ensure_ascii=False).encode("utf-8")
            request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request, timeout=3)
            self.assertEqual(raised.exception.code, 400)
            response = json.loads(raised.exception.read())
            self.assertIn("ไม่อนุญาตให้เพิ่มรายการย้อนหลัง", response["message"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_unrelated_product_is_saved_and_summarized_under_selected_category(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.object(app, "DB", Path(temp_dir) / "category-grouping.db"):
                app.init_db()
                today = app.date.today().isoformat()
                payload = {
                    "date": today,
                    "branch": "บางบัวทอง",
                    "category": "หมูบด A",
                    "items": [{
                        "valid": True,
                        "name": "หมูสามชั้นบาง",
                        "weight": 2.39,
                        "image": "data:image/png;base64,AA==",
                    }],
                }
                server = app.ExclusiveThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    base_url = f"http://127.0.0.1:{server.server_address[1]}"
                    request = urllib.request.Request(
                        base_url + "/api/records",
                        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(request, timeout=3) as response:
                        saved_result = json.load(response)
                    report_url = base_url + "/api/report?date_from=" + today + "&date_to=" + today + "&category=" + urllib.parse.quote("หมูบด A")
                    with urllib.request.urlopen(report_url, timeout=3) as response:
                        summary = json.load(response)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)

                self.assertEqual(saved_result["saved"], 1)
                self.assertEqual(len(summary), 1)
                self.assertEqual(summary[0]["category"], "หมูบด A")
                self.assertEqual(summary[0]["product_name"], "หมูสามชั้นบาง")
                self.assertAlmostEqual(summary[0]["weight_kg"], 2.39)

    def test_competitor_prices_save_and_load_by_branch_and_date(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.object(app, "DB", Path(temp_dir) / "prices.db"):
                app.init_db()
                server = app.ExclusiveThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    base_url = f"http://127.0.0.1:{server.server_address[1]}"
                    payload = {
                        "date": "2026-08-25",
                        "branch": "บางบัวทอง",
                        "items": [{
                            "product_name": "เนื้อแดง",
                            "our_price": 150,
                            "competitor_1": 145,
                            "competitor_2": 148,
                            "competitor_3": 147,
                        }],
                    }
                    request = urllib.request.Request(
                        base_url + "/api/competitor-prices",
                        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(request, timeout=3) as response:
                        saved = json.load(response)
                    query = urllib.parse.urlencode({"date": payload["date"], "branch": payload["branch"]})
                    with urllib.request.urlopen(base_url + "/api/competitor-prices?" + query, timeout=3) as response:
                        loaded = json.load(response)
                    with urllib.request.urlopen(base_url + "/api/price-summary?" + query, timeout=3) as response:
                        summary = json.load(response)
                    history_query = urllib.parse.urlencode({"branch": payload["branch"], "product": "เนื้อแดง"})
                    with urllib.request.urlopen(base_url + "/api/price-history?" + history_query, timeout=3) as response:
                        history = json.load(response)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)

                self.assertEqual(saved["saved"], 1)
                self.assertEqual(len(loaded), 1)
                self.assertEqual(loaded[0]["product_name"], "เนื้อแดง")
                self.assertEqual(loaded[0]["our_price"], 150)
                self.assertEqual(min(loaded[0]["competitor_1"], loaded[0]["competitor_2"], loaded[0]["competitor_3"]), 145)
                self.assertEqual(summary[0]["branch"], "บางบัวทอง")
                self.assertEqual(summary[0]["product_name"], "เนื้อแดง")
                self.assertEqual(history[0]["price_date"], "2026-08-25")

    def test_login_and_manager_branch_permission(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.object(app, "DB", Path(temp_dir) / "auth.db"):
                app.init_db()
                server = app.ExclusiveThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                os.environ.pop("APP_TESTING", None)
                try:
                    base_url = f"http://127.0.0.1:{server.server_address[1]}"
                    login = urllib.request.Request(
                        base_url + "/api/login",
                        data=json.dumps({"username": "manager_trang", "password": "manager123"}).encode(),
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(login, timeout=3) as response:
                        cookie = response.headers["Set-Cookie"].split(";", 1)[0]
                    me = urllib.request.Request(base_url + "/api/me", headers={"Cookie": cookie})
                    with urllib.request.urlopen(me, timeout=3) as response:
                        profile = json.load(response)
                    forbidden_query = urllib.parse.urlencode({"date": "2026-08-25", "branch": "บางบัวทอง"})
                    forbidden = urllib.request.Request(
                        base_url + "/api/competitor-prices?" + forbidden_query,
                        headers={"Cookie": cookie},
                    )
                    with self.assertRaises(urllib.error.HTTPError) as raised:
                        urllib.request.urlopen(forbidden, timeout=3)
                finally:
                    os.environ["APP_TESTING"] = "1"
                    server.shutdown(); server.server_close(); thread.join(timeout=2)
                self.assertEqual(profile["role"], "manager")
                self.assertEqual(profile["branch"], "ตรัง")
                self.assertEqual(raised.exception.code, 403)

    def test_order_validation_rejects_negative_and_unknown_products(self):
        with self.assertRaisesRegex(ValueError, "ต้องไม่ติดลบ"):
            app.prepare_order_items({"items": [{"product_name": "เนื้อแดง", "quantity": -1, "unit": "กก."}]})
        with self.assertRaisesRegex(ValueError, "ชื่อสินค้าที่ไม่ถูกต้อง"):
            app.prepare_order_items({"items": [{"product_name": "สินค้าอื่น", "quantity": 1, "unit": "กก."}]})

    def test_order_endpoints_save_server_total_and_load_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.object(app, "DB", Path(temp_dir) / "orders.db"):
                app.init_db()
                server = app.ExclusiveThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    base_url = f"http://127.0.0.1:{server.server_address[1]}"
                    payload = {
                        "branch": "บางบัวทอง",
                        "note": "ขาหน้าขอน้ำหนักขาละ 1.70-1.90 กก.",
                        "total_weight": 99999,
                        "items": [
                            {"product_name": "เนื้อแดง", "quantity": 100, "unit": "กก."},
                            {"product_name": "สามชั้น", "quantity": 500, "unit": "กก."},
                            {"product_name": "ขาหน้า", "quantity": 100, "unit": "กก."},
                            {"product_name": "คากิ", "quantity": 0, "unit": "กก."},
                        ],
                    }
                    request = urllib.request.Request(
                        base_url + "/api/orders",
                        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(request, timeout=3) as response:
                        saved = json.load(response)
                    query = urllib.parse.urlencode({"branch": "บางบัวทอง", "date": app.date.today().isoformat()})
                    with urllib.request.urlopen(base_url + "/api/orders?" + query, timeout=3) as response:
                        history = json.load(response)
                    with urllib.request.urlopen(base_url + f"/api/orders/{saved['id']}", timeout=3) as response:
                        detail = json.load(response)
                    with urllib.request.urlopen(base_url + "/order.html", timeout=3) as response:
                        order_page = response.read().decode("utf-8")
                    with urllib.request.urlopen(base_url + "/order-history.html", timeout=3) as response:
                        history_page = response.read().decode("utf-8")
                finally:
                    server.shutdown(); server.server_close(); thread.join(timeout=2)
                self.assertEqual(saved["saved"], 3)
                self.assertEqual(saved["total_weight"], 700)
                self.assertEqual(history[0]["item_count"], 3)
                self.assertEqual(history[0]["ordered_by"], "test-admin")
                self.assertEqual(detail["total_weight"], 700)
                self.assertEqual([item["product_name"] for item in detail["items"]], ["เนื้อแดง", "สามชั้น", "ขาหน้า"])
                self.assertIn('id="orderRows"', order_page)
                self.assertIn('id="orderHistoryRows"', history_page)

    def test_manager_cannot_save_or_read_other_branch_orders(self):
        manager = {"username": "manager_trang", "role": "manager", "branch": "ตรัง"}
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.object(app, "DB", Path(temp_dir) / "manager-orders.db"):
                app.init_db()
                with mock.patch.object(app.Handler, "current_user", return_value=manager):
                    server = app.ExclusiveThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    try:
                        base_url = f"http://127.0.0.1:{server.server_address[1]}"
                        payload = {"branch": "บางบัวทอง", "items": [{"product_name": "เนื้อแดง", "quantity": 1, "unit": "กก."}]}
                        request = urllib.request.Request(base_url + "/api/orders", data=json.dumps(payload, ensure_ascii=False).encode(), headers={"Content-Type": "application/json"})
                        with self.assertRaises(urllib.error.HTTPError) as save_error:
                            urllib.request.urlopen(request, timeout=3)
                        with self.assertRaises(urllib.error.HTTPError) as read_error:
                            urllib.request.urlopen(base_url + "/api/orders?branch=" + urllib.parse.quote("บางบัวทอง"), timeout=3)
                    finally:
                        server.shutdown(); server.server_close(); thread.join(timeout=2)
                self.assertEqual(save_error.exception.code, 403)
                self.assertEqual(read_error.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
