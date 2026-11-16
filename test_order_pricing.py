import json
import os
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch
import app
import order_pricing


class PricingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_db = Path(__file__).parent / 'pricing-test.db'
        cls.env = patch.dict(os.environ, {'APP_TESTING': '1'})
        cls.env.start()
        cls.database = patch.object(app, 'DB', cls.test_db)
        cls.database.start()
        app.init_db()
        app.init_db()  # repeatable additive schema
        cls.server = app.ExclusiveThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = 'http://127.0.0.1:' + str(cls.server.server_address[1])

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.database.stop()
        cls.env.stop()
        cls.test_db.unlink(missing_ok=True)

    def request(self, path, payload=None):
        req = urllib.request.Request(self.url + path,
              data=json.dumps(payload).encode() if payload is not None else None,
              headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as r:
            return r.code, json.load(r)

    def set_prices(self, items):
        _, current = self.request('/api/order-prices')
        return self.request('/api/order-prices', {'version': current['version'], 'items': items})

    def payload(self, request_id):
        return {'request_id': request_id, 'branch': 'บางบัวทอง', 'note': '<note>ส่งเช้า',
                'billing': {'invoice_number': 'PO-001', 'branch_name': 'บางบัวทอง',
                            'address': '123 ถนนตัวอย่าง', 'sender': 'ผู้ส่ง', 'receiver': 'ผู้รับ',
                            'sent_date': '2026-11-16'},
                'quoted_prices': {'เนื้อแดง': 125, 'อกA': 65},
                'items': [{'product_name': 'เนื้อแดง', 'quantity': 1.25, 'unit': 'กก.'},
                          {'product_name': 'อกA', 'quantity': 2.5, 'unit': 'กก.'}]}

    def test_transaction_snapshot_and_idempotency(self):
        self.assertEqual(self.set_prices([{'product_name': 'เนื้อแดง', 'unit_price': 125},
                                          {'product_name': 'อกA', 'unit_price': 65}])[0], 200)
        payload = self.payload('snapshot-test')
        status, saved = self.request('/api/orders', payload)
        self.assertEqual(status, 201, saved)
        self.assertEqual(saved['total_weight'], 3.75)
        _, order = self.request('/api/orders/' + str(saved['order_id']))
        self.assertEqual(order['billing']['total_amount'], 318.75)
        self.assertEqual(order['billing']['address'], '123 ถนนตัวอย่าง')
        self.assertEqual(len(order['billing']['items']), 2)
        self.set_prices([{'product_name': 'อกA', 'unit_price': 99}])
        status, again = self.request('/api/orders', payload)
        self.assertEqual(status, 200)
        self.assertEqual(saved['order_id'], again['order_id'])
        _, old = self.request('/api/orders/' + str(saved['order_id']))
        self.assertEqual(old['billing']['total_amount'], 318.75)
        _, history = self.request('/api/orders?invoice=PO-001')
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['invoice_number'], 'PO-001')
        self.assertEqual(history[0]['total_amount'], 318.75)
        self.assertEqual(self.request('/api/orders?invoice=NO-MATCH')[1], [])
        with patch.object(app.Handler, 'current_user', return_value={'username': 'm', 'role': 'manager', 'branch': 'ตรัง'}):
            self.assertEqual(self.request('/api/orders?branch=' + urllib.parse.quote('ตรัง'))[1], [])
            self.assertEqual(self.request('/api/orders/' + str(saved['order_id']))[0], 403)
        payload['request_id'] = 'stale-price-test'
        self.assertEqual(self.request('/api/orders', payload)[0], 400)
        with app.db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) AS n FROM orders').fetchone()['n'], 1)

    def test_permissions_validation_and_missing_price(self):
        with patch.object(app.Handler, 'current_user', return_value={'username': 'm', 'role': 'manager', 'branch': 'ตรัง'}):
            self.assertEqual(self.request('/api/order-prices', {'items': []})[0], 403)
            self.assertEqual(self.request('/api/orders', self.payload('wrong-branch'))[0], 403)
        with patch.object(app.Handler, 'current_user', return_value=None):
            self.assertEqual(self.request('/api/order-prices')[0], 401)
        for value in ('NaN', '-1', 'Infinity'):
            self.assertEqual(self.set_prices([{'product_name': 'อกA', 'unit_price': value}])[0], 400)
        self.set_prices([{'product_name': 'เนื้อแดง', 'unit_price': None}])
        self.assertEqual(self.request('/api/orders', self.payload('missing-price'))[0], 400)
        payload = self.payload('missing-address')
        payload['billing']['address'] = ''
        self.assertEqual(self.request('/api/orders', payload)[0], 400)

    def test_catalog_and_rounding_and_legacy_bill(self):
        self.assertEqual(order_pricing.money('1.005'), order_pricing.Decimal('1.01'))
        _, catalog = self.request('/api/product-catalog')
        self.assertEqual(len(catalog['chicken']), 30)
        self.assertIn('น่องสะโพกB', catalog['chicken'])
        with app.db() as conn:
            self.assertIsNone(order_pricing.billing(conn, -1))


if __name__ == '__main__':
    unittest.main()
