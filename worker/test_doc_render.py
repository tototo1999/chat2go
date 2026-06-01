# worker/test_doc_render.py
"""单证渲染纯逻辑单测。run: python3 -m unittest test_doc_render -v"""
import unittest
import doc_render as dr


class TestPrepareContext(unittest.TestCase):
    def _data(self):
        return {
            "doc_type": "quote", "doc_no": "QT-1", "date": "2026-06-01",
            "buyer": {"name": "EURO STANDARD"},
            "items": [
                {"name": "A", "qty": 2000, "unit_price": 3.85},          # amount 省略
                {"name": "B", "qty": 5000, "unit_price": 1.2, "amount": 6000.0},
            ],
            "extra_charges": [{"label": "Freight", "amount": 680.0}],
            "trade_term": "CNF Busan",
        }

    def test_amount_computed_when_missing(self):
        ctx = dr.prepare_context("quote", self._data(), {})
        self.assertEqual(ctx["items"][0]["amount"], 7700.0)   # 2000*3.85

    def test_subtotal_and_total(self):
        ctx = dr.prepare_context("quote", self._data(), {})
        self.assertEqual(ctx["subtotal"], 13700.0)            # 7700 + 6000
        self.assertEqual(ctx["total"], 14380.0)               # + 680

    def test_currency_default_usd(self):
        ctx = dr.prepare_context("quote", self._data(), {})
        self.assertEqual(ctx["currency"], "USD")

    def test_seller_from_profile(self):
        prof = {"name_cn": "佛山外艾斯", "bank": {"swift": "X"}}
        ctx = dr.prepare_context("quote", self._data(), prof)
        self.assertEqual(ctx["seller"]["name_cn"], "佛山外艾斯")
        self.assertEqual(ctx["seller"]["bank"]["swift"], "X")

    def test_empty_profile_no_crash(self):
        ctx = dr.prepare_context("quote", self._data(), {})
        self.assertEqual(ctx["seller"].get("name_cn", ""), "")
