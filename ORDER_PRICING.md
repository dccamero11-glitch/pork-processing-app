# Ordering prices and billing

Admin sets central prices at `/order-prices.html`. Catalog comes from the ordering API, including new products. Blank means unpriced; zero is a valid price. A product present in both categories uses one price and one order line.

Orders require an invoice/order number, branch name, shipping address, and current quoted prices. Server validates prices and computes line totals with Decimal, half-up to two decimal places. Prices and billing details are stored in `order_billing` in the same transaction as the order. Price edits never rewrite old bills. New tables are additive and initialized at startup on SQLite and PostgreSQL.

Print saved bills at `/order-bill.html?id=ORDER_ID` or from order history. Old orders without snapshots show weights and explicitly indicate that historical prices were not recorded. They never use today's prices as historical values. Signatures and dates may be left blank for handwritten completion.

Validation: `python -m unittest test_app test_order_pricing` (35 tests); `node verify_order_ui.cjs` for optional local browser verification with Edge/Playwright. Test-only DB and screenshots must not be published.
