import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
import zipfile
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
                        "request_id": "order-endpoint-test-1",
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
                self.assertTrue(saved["success"])
                self.assertEqual(saved["order_id"], saved["id"])
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
                        payload = {"request_id": "manager-forbidden-1", "branch": "บางบัวทอง", "items": [{"product_name": "เนื้อแดง", "quantity": 1, "unit": "กก."}]}
                        request = urllib.request.Request(base_url + "/api/orders", data=json.dumps(payload, ensure_ascii=False).encode(), headers={"Content-Type": "application/json"})
                        with self.assertRaises(urllib.error.HTTPError) as save_error:
                            urllib.request.urlopen(request, timeout=3)
                        with self.assertRaises(urllib.error.HTTPError) as read_error:
                            urllib.request.urlopen(base_url + "/api/orders?branch=" + urllib.parse.quote("บางบัวทอง"), timeout=3)
                    finally:
                        server.shutdown(); server.server_close(); thread.join(timeout=2)
                self.assertEqual(save_error.exception.code, 403)
                self.assertEqual(read_error.exception.code, 403)

    def test_selling_price_calculation_and_validation(self):
        values = app.calculate_selling_price({"product_category":"หมู","product_name":"เนื้อแดง","purchase_cost":100,"transport_cost":5,"profit_percent":15,"calculated_price":1})
        self.assertEqual(float(values[4]), 105)
        self.assertEqual(float(values[7]), 120.75)
        self.assertEqual(float(values[8]), 121)
        values = app.calculate_selling_price({"product_category":"หมู","product_name":"เนื้อแดง","purchase_cost":100,"transport_cost":0,"profit_percent":10})
        self.assertEqual(float(values[7]), 110)
        for key in ("purchase_cost","transport_cost","profit_percent"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                app.calculate_selling_price({"product_category":"หมู","product_name":"เนื้อแดง",key:-1})

    def test_selling_price_api_history_and_bulk_rollback(self):
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(app,"DB",Path(temp_dir)/"selling.db"):
            app.init_db();server=app.ExclusiveThreadingHTTPServer(("127.0.0.1",0),app.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                base=f"http://127.0.0.1:{server.server_address[1]}";payload={"branch":"บางบัวทอง","product_category":"หมู","product_name":"เนื้อแดง","purchase_cost":100,"transport_cost":5,"profit_percent":15,"calculated_price":1,"recommended_price":1}
                req=urllib.request.Request(base+"/api/selling-prices",data=json.dumps(payload,ensure_ascii=False).encode(),headers={"Content-Type":"application/json"})
                with urllib.request.urlopen(req,timeout=3) as response: self.assertEqual(json.load(response)["saved"],1)
                q=urllib.parse.urlencode({"branch":"บางบัวทอง","category":"หมู"})
                with urllib.request.urlopen(base+"/api/selling-prices?"+q,timeout=3) as response: current=json.load(response)
                with urllib.request.urlopen(base+"/api/selling-price-history?"+q,timeout=3) as response: history=json.load(response)
                self.assertEqual(current[0]["calculated_price"],120.75);self.assertEqual(current[0]["recommended_price"],121);self.assertEqual(len(history),1)
                bulk={"branch":"บางบัวทอง","items":[{"product_category":"หมู","product_name":"สามชั้น","purchase_cost":10},{"product_category":"หมู","product_name":"ผิด","purchase_cost":10}]}
                req=urllib.request.Request(base+"/api/selling-prices/bulk",data=json.dumps(bulk,ensure_ascii=False).encode(),headers={"Content-Type":"application/json"})
                with self.assertRaises(urllib.error.HTTPError): urllib.request.urlopen(req,timeout=3)
                with app.db() as conn: self.assertEqual(conn.execute("SELECT COUNT(*) n FROM selling_prices WHERE product_name=?",("สามชั้น",)).fetchone()["n"],0)
            finally: server.shutdown();server.server_close();thread.join(timeout=2)

    def test_manager_cannot_bypass_selling_price_branch(self):
        manager={"username":"manager_trang","role":"manager","branch":"ตรัง"}
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(app,"DB",Path(temp_dir)/"selling-manager.db"):
            app.init_db()
            with mock.patch.object(app.Handler,"current_user",return_value=manager):
                server=app.ExclusiveThreadingHTTPServer(("127.0.0.1",0),app.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                try:
                    base=f"http://127.0.0.1:{server.server_address[1]}";payload={"branch":"บางบัวทอง","product_category":"หมู","product_name":"เนื้อแดง","purchase_cost":100}
                    req=urllib.request.Request(base+"/api/selling-prices",data=json.dumps(payload,ensure_ascii=False).encode(),headers={"Content-Type":"application/json"})
                    with self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(req,timeout=3)
                    self.assertEqual(error.exception.code,403)
                finally: server.shutdown();server.server_close();thread.join(timeout=2)


    def test_expanded_order_products_are_unique_and_accepted(self):
        names = ("สะโพกติดหนัง", "หมูบดA", "หมูหมักหมาล่า", "กระดูกอ่อน(โครงแก้ว)")
        self.assertEqual(len(app.ORDER_PRODUCTS), len(set(app.ORDER_PRODUCTS)))
        rows = app.prepare_order_items({"items": [
            {"product_name": name, "quantity": index + 1, "unit": "กก."}
            for index, name in enumerate(names)
        ]})
        self.assertEqual([row[0] for row in rows], list(names))
        self.assertEqual(sum(row[1] for row in rows), 10)


    def test_full_chicken_selling_products_are_unique_and_calculable(self):
        chicken = app.SELLING_PRODUCTS["ไก่"]
        required = ("ไก่เนื้อล้วง(ตัว)","ไก่กลม(ตัว)","น่อง+สะโพกไก่","เศษไก่ BL","เศษหนังBL","เศษไก่ BLK","ขายำ(เล็บมือนาง)","กระดูกอ่อนไก่","เครื่องในผ่ารวม","ตับติดใจ","ไก่สับ")
        self.assertEqual(len(chicken), 24)
        self.assertEqual(len(chicken), len(set(chicken)))
        for product in required:
            values = app.calculate_selling_price({"product_category":"ไก่","product_name":product,"purchase_cost":100,"transport_cost":5,"profit_percent":15})
            self.assertEqual(float(values[7]), 120.75)
            self.assertEqual(float(values[8]), 121)
        self.assertTrue(set(app.SELLING_PRODUCTS["หมู"]).isdisjoint({"ไก่เนื้อล้วง(ตัว)","ไก่กลม(ตัว)"}))


    def test_additional_pork_order_products_are_unique_and_accepted(self):
        products = ("ม้าม", "ขั้วปอด", "คางหมู", "สามชั้นหนา", "ชายสามชั้น")
        self.assertEqual(len(app.ORDER_PRODUCTS), len(set(app.ORDER_PRODUCTS)))
        rows = app.prepare_order_items({"items": [
            {"product_name": name, "quantity": 1, "unit": "กก."} for name in products
        ]})
        self.assertEqual([row[0] for row in rows], list(products))
        self.assertEqual(sum(row[1] for row in rows), 5)


    def test_pork_processing_products_are_distinct_and_summarizable(self):
        products = app.PORK_PROCESSING_PRODUCTS
        expected = ("แคปสะโพก", "หนังสัน", "มันแข็ง", "ปีกบน", "ปีกกลาง", "ปีกปลาย", "ปลายปีก", "เศษเนื้อ", "ชายหมูสามชั้น")
        self.assertEqual(products, expected)
        self.assertEqual(len(products), 9)
        self.assertEqual(len(products), len(set(products)))
        self.assertTrue(set(products).issubset(app.CATEGORIES))
        self.assertNotIn("หมูแปรรูป", app.CATEGORIES)
        self.assertEqual(len(app.CATEGORIES), len(set(app.CATEGORIES)))
        app_js = (app.ROOT / "app.js").read_text(encoding="utf-8")
        ui_categories = json.loads(app_js.split("CATEGORIES=", 1)[1].split("], PORK_PROCESSING_PRODUCTS", 1)[0] + "]")
        self.assertTrue(set(products).issubset(ui_categories))
        self.assertNotIn("หมูแปรรูป", ui_categories)
        self.assertEqual(len(ui_categories), len(set(ui_categories)))
        self.assertIn("ปีกปลาย", products)
        self.assertIn("ปลายปีก", products)
        self.assertNotEqual(products.index("ปีกปลาย"), products.index("ปลายปีก"))
        rows = app.prepare_record_rows({
            "date": app.date.today().isoformat(), "branch": "บางบัวทอง", "category": "แคปสะโพก",
            "items": [
                {"valid": True, "name": "แคปสะโพก", "weight": 20, "image": ""},
                {"valid": True, "name": "หนังสัน", "weight": 10, "image": ""},
                {"valid": True, "name": "เศษเนื้อ", "weight": 15, "image": ""},
                {"valid": True, "name": "ชายหมูสามชั้น", "weight": 5, "image": ""},
            ],
        })
        self.assertEqual(sum(row[4] for row in rows), 50)


    def test_selling_pork_catalog_uses_ordering_names_only(self):
        self.assertIs(app.SELLING_PRODUCTS["หมู"], app.ORDER_PRODUCTS)
        self.assertEqual(len(app.ORDER_PRODUCTS), 80)
        self.assertEqual(len(app.ORDER_PRODUCTS), len(set(app.ORDER_PRODUCTS)))
        for name in ("เนื้อแดง", "สะโพก", "สามชั้น", "สามชั้นบาง"):
            self.assertIn(name, app.SELLING_PRODUCTS["หมู"])
        self.assertEqual(len(app.SELLING_PRODUCTS["ไก่"]), 24)
        self.assertNotIn("ไก่เนื้อล้วง(ตัว)", app.SELLING_PRODUCTS["หมู"])
        self.assertNotIn("เนื้อแดง", app.SELLING_PRODUCTS["ไก่"])


    def test_order_summary_aggregates_branches_multiple_orders_and_notes(self):
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(app, "DB", Path(temp_dir) / "summary.db"):
            app.init_db(); today = "2026-08-27"; now = "2026-08-27T08:00:00"
            with app.db() as conn:
                entries = [("บางบัวทอง","เนื้อแดง",100,"หมายเหตุบางบัวทอง"),("บางบัวทอง","เนื้อแดง",50,""),("หลังสวน","เนื้อแดง",100,"หมายเหตุหลังสวน"),("ตรัง","เนื้อแดง",100,"")]
                for branch, product, quantity, note in entries:
                    order_id = conn.execute("INSERT INTO orders(order_date,branch,ordered_by,total_weight,note,created_at) VALUES(?,?,?,?,?,?) RETURNING id",(today,branch,"test-admin",quantity,note,now)).fetchone()["id"]
                    conn.execute("INSERT INTO order_items(order_id,product_name,quantity,unit,created_at) VALUES(?,?,?,?,?)",(order_id,product,quantity,"กก.",now))
            server=app.ExclusiveThreadingHTTPServer(("127.0.0.1",0),app.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                url=f"http://127.0.0.1:{server.server_address[1]}/api/orders/summary?date={today}&branch=ALL"
                with urllib.request.urlopen(url,timeout=3) as response: result=json.load(response)
            finally: server.shutdown();server.server_close();thread.join(timeout=2)
            meat=next(row for row in result["products"] if row["product_name"]=="เนื้อแดง")
            self.assertEqual(meat["บางบัวทอง"],150);self.assertEqual(meat["หลังสวน"],100);self.assertEqual(meat["ตรัง"],100)
            self.assertEqual(meat["total"],350);self.assertEqual(result["grand_total"],350)
            self.assertEqual(result["notes"]["บางบัวทอง"],["หมายเหตุบางบัวทอง"])

    def test_xlsx_export_is_real_zip_workbook_with_thai_text(self):
        content=app.make_xlsx("สรุปการสั่งสินค้า",[["วันที่","2026-08-27"]],[["รายการสินค้า","รวม"],["เนื้อแดง",100.0]])
        self.assertTrue(content.startswith(b"PK"))
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            sheet=archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn("สรุปการสั่งสินค้า",sheet);self.assertIn("เนื้อแดง",sheet)

    def test_order_save_three_branches_is_idempotent_and_summary_totals_300(self):
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(app, "DB", Path(temp_dir) / "three-branches.db"):
            app.init_db(); server=app.ExclusiveThreadingHTTPServer(("127.0.0.1",0),app.Handler); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            try:
                base=f"http://127.0.0.1:{server.server_address[1]}"
                saved=[]
                for index, branch in enumerate(("บางบัวทอง","หลังสวน","ตรัง"),1):
                    payload={"request_id":f"three-branch-{index}","branch":branch,"items":[{"product_name":"เนื้อแดง","quantity":100,"unit":"กก."}]}
                    request=urllib.request.Request(base+"/api/orders",data=json.dumps(payload,ensure_ascii=False).encode(),headers={"Content-Type":"application/json"})
                    with urllib.request.urlopen(request,timeout=3) as response:
                        self.assertEqual(response.headers.get_content_type(),"application/json"); saved.append(json.load(response))
                    if index == 1:
                        with urllib.request.urlopen(request,timeout=3) as response: retried=json.load(response)
                with urllib.request.urlopen(base+"/api/orders/summary?date="+app.date.today().isoformat()+"&branch=ALL",timeout=3) as response: summary=json.load(response)
                with app.db() as conn:
                    order_count=conn.execute("SELECT COUNT(*) count FROM orders").fetchone()["count"]
                    item_count=conn.execute("SELECT COUNT(*) count FROM order_items").fetchone()["count"]
            finally: server.shutdown();server.server_close();thread.join(timeout=2)
            self.assertTrue(all(row["success"] and row["order_id"] for row in saved));self.assertTrue(retried["duplicate"]);self.assertEqual(retried["order_id"],saved[0]["order_id"])
            self.assertEqual(order_count,3);self.assertEqual(item_count,3)
            meat=next(row for row in summary["products"] if row["product_name"]=="เนื้อแดง")
            self.assertEqual([meat[b] for b in ("บางบัวทอง","หลังสวน","ตรัง")],[100,100,100]);self.assertEqual(meat["total"],300)

    def test_order_transaction_error_rolls_back_and_returns_json(self):
        original_db=app.db
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(app,"DB",Path(temp_dir)/"rollback.db"):
            app.init_db()
            @app.contextmanager
            def failing_db():
                with original_db() as connection:
                    class FailingConnection:
                        def execute(self,*args,**kwargs): return connection.execute(*args,**kwargs)
                        def executemany(self,sql,params):
                            if "INSERT INTO order_items" in sql: raise RuntimeError("forced database failure")
                            return connection.executemany(sql,params)
                    yield FailingConnection()
            with mock.patch.object(app,"db",failing_db):
                server=app.ExclusiveThreadingHTTPServer(("127.0.0.1",0),app.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                try:
                    payload={"request_id":"rollback-1","branch":"บางบัวทอง","items":[{"product_name":"เนื้อแดง","quantity":100,"unit":"กก."}]}
                    request=urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}/api/orders",data=json.dumps(payload,ensure_ascii=False).encode(),headers={"Content-Type":"application/json"})
                    with self.assertRaises(urllib.error.HTTPError) as raised: urllib.request.urlopen(request,timeout=3)
                    error=json.load(raised.exception)
                finally: server.shutdown();server.server_close();thread.join(timeout=2)
            with original_db() as conn: count=conn.execute("SELECT COUNT(*) count FROM orders").fetchone()["count"]
            self.assertEqual(raised.exception.code,500);self.assertFalse(error["success"]);self.assertNotIn("forced database failure",json.dumps(error));self.assertEqual(count,0)

    def test_existing_order_schema_gets_safe_idempotency_migration(self):
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(app,"DB",Path(temp_dir)/"existing.db"):
            raw=app.sqlite3.connect(app.DB)
            raw.execute("CREATE TABLE orders(id INTEGER PRIMARY KEY AUTOINCREMENT,order_date DATE NOT NULL,branch TEXT NOT NULL,ordered_by TEXT NOT NULL,total_weight NUMERIC NOT NULL,note TEXT NOT NULL DEFAULT '',created_at TIMESTAMP NOT NULL)")
            raw.execute("CREATE TABLE order_items(id INTEGER PRIMARY KEY AUTOINCREMENT,order_id INTEGER NOT NULL REFERENCES orders(id),product_name TEXT NOT NULL,quantity NUMERIC NOT NULL,unit TEXT NOT NULL,created_at TIMESTAMP NOT NULL)")
            raw.commit();raw.close()
            app.init_db();app.init_db()
            with app.db() as conn:
                columns={row["name"] for row in conn.execute("PRAGMA table_info(order_requests)")}
                indexes={row["name"] for row in conn.execute("PRAGMA index_list(order_requests)")}
            self.assertEqual(columns,{"request_id","order_id","created_at"})
            self.assertIn("idx_order_requests_request_id",indexes);self.assertIn("idx_order_requests_order_id",indexes)

    def test_postgres_order_sql_uses_psycopg_placeholders(self):
        statements=(
            "SELECT order_id FROM order_requests WHERE request_id=?",
            "INSERT INTO orders(order_date,branch,ordered_by,total_weight,note,created_at) VALUES(?,?,?,?,?,?) RETURNING id",
            "INSERT INTO order_items(order_id,product_name,quantity,unit,created_at) VALUES(?,?,?,?,?)",
            "INSERT INTO order_requests(request_id,order_id,created_at) VALUES(?,?,?)",
        )
        for statement in statements:
            translated=app.postgres_sql(statement)
            self.assertNotIn("?",translated);self.assertEqual(translated.count("%s"),statement.count("?"))

    def test_postgres_wrapper_uses_cursor_executemany_not_connection(self):
        calls=[]
        class FakeCursor:
            def __enter__(self): return self
            def __exit__(self,*_args): pass
            def executemany(self,sql,params): calls.append((sql,list(params)))
        class FakePostgresConnection:
            def cursor(self): return FakeCursor()
            def execute(self,sql,params=()): calls.append((sql,params));return FakeCursor()
            def commit(self): calls.append(("commit",None))
            def rollback(self): calls.append(("rollback",None))
            def close(self): calls.append(("close",None))
        fake_psycopg=type("FakePsycopg",(),{"connect":staticmethod(lambda *_args,**_kwargs:FakePostgresConnection())})
        fake_rows=type("FakeRows",(),{"dict_row":object()})
        with mock.patch.object(app,"USE_POSTGRES",True),mock.patch.object(app,"DATABASE_URL","postgresql://test"),mock.patch.dict(app.sys.modules if hasattr(app,"sys") else __import__('sys').modules,{"psycopg":fake_psycopg,"psycopg.rows":fake_rows}):
            with app.db() as conn:
                conn.executemany("INSERT INTO order_items(order_id,product_name,quantity,unit,created_at) VALUES(?,?,?,?,?)",[(1,"เนื้อแดง",100,"กก.","2026-08-27")])
        insert=next(row for row in calls if isinstance(row[0],str) and row[0].startswith("INSERT INTO order_items"))
        self.assertNotIn("?",insert[0]);self.assertEqual(insert[0].count("%s"),5);self.assertIn(("commit",None),calls)


if __name__ == "__main__":
    unittest.main()
