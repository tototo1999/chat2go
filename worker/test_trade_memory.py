# worker/test_trade_memory.py
"""Trade2GO 记忆 P0 纯逻辑单测(不碰 DB)。run: python3 -m unittest test_trade_memory -v"""
import unittest
import trade_memory as tm


class TestTransition(unittest.TestCase):
    def test_new_order_any_status_ok(self):
        self.assertTrue(tm.is_valid_transition(None, "报价"))
        self.assertTrue(tm.is_valid_transition(None, "已发货"))  # 可补录

    def test_forward_ok_including_jump(self):
        self.assertTrue(tm.is_valid_transition("报价", "待PI"))
        self.assertTrue(tm.is_valid_transition("报价", "已发货"))  # 跳级允许

    def test_backward_rejected(self):
        self.assertFalse(tm.is_valid_transition("已发货", "报价"))

    def test_same_status_rejected_as_noop(self):
        self.assertFalse(tm.is_valid_transition("生产中", "生产中"))

    def test_unknown_status_rejected(self):
        self.assertFalse(tm.is_valid_transition("报价", "天马行空"))
        self.assertFalse(tm.is_valid_transition("瞎写", "报价"))


class TestBitemporal(unittest.TestCase):
    def test_current_orders_filters_closed(self):
        rows = [
            {"customer": "A", "status": "报价", "valid_to": "2026-06-01T00:00:00+00"},
            {"customer": "A", "status": "待PI", "valid_to": None},
            {"customer": "B", "status": "生产中", "valid_to": None},
        ]
        cur = tm.current_orders_from_rows(rows)
        self.assertEqual({(o["customer"], o["status"]) for o in cur},
                         {("A", "待PI"), ("B", "生产中")})

    def test_empty(self):
        self.assertEqual(tm.current_orders_from_rows(None), [])


class TestFormat(unittest.TestCase):
    def test_rules_prompt(self):
        out = tm.format_rules_for_prompt([{"content": "默认 USD", "version": 2}])
        self.assertIn("默认 USD", out)
        self.assertIn("v2", out)
        self.assertIn("冻结", out)

    def test_rules_empty_returns_blank(self):
        self.assertEqual(tm.format_rules_for_prompt([]), "")

    def test_orders_prompt(self):
        out = tm.format_orders_for_prompt([
            {"customer": "印度客户", "product_desc": "LED灯", "amount": 40000,
             "currency": "USD", "status": "已发货"}])
        self.assertIn("已发货", out)
        self.assertIn("印度客户", out)
        self.assertIn("40000", out)

    def test_orders_empty_returns_blank(self):
        self.assertEqual(tm.format_orders_for_prompt([]), "")


class TestToolSchemas(unittest.TestCase):
    def test_order_tools_shape(self):
        names = {t["name"] for t in tm.ORDER_TOOL_SCHEMAS}
        self.assertEqual(names, {"update_order_status", "query_orders"})
        upd = next(t for t in tm.ORDER_TOOL_SCHEMAS if t["name"] == "update_order_status")
        self.assertEqual(set(upd["input_schema"]["required"]), {"customer", "new_status"})
        self.assertEqual(upd["input_schema"]["properties"]["new_status"]["enum"], tm.ORDER_STATUSES)


if __name__ == "__main__":
    unittest.main()
