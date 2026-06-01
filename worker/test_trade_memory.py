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


class TestPlanMemoryWrite(unittest.TestCase):
    def test_new_candidate(self):
        self.assertEqual(tm.plan_memory_write(None, None, False), ("candidate", 1, False))

    def test_new_frozen(self):
        self.assertEqual(tm.plan_memory_write(None, None, True), ("frozen", 1, False))

    def test_candidate_update_stays_candidate(self):
        self.assertEqual(tm.plan_memory_write("candidate", 1, False), ("candidate", 1, False))

    def test_candidate_promote_to_frozen(self):
        self.assertEqual(tm.plan_memory_write("candidate", 1, True), ("frozen", 1, False))

    def test_frozen_rewrite_bumps_version(self):
        self.assertEqual(tm.plan_memory_write("frozen", 2, True), ("frozen", 3, False))

    def test_candidate_cannot_silently_overwrite_frozen(self):
        status, ver, blocked = tm.plan_memory_write("frozen", 2, False)
        self.assertTrue(blocked)


class TestMemoryFormat(unittest.TestCase):
    def test_block_wraps_and_groups(self):
        frozen = [{"kind": "rule", "title": "报价口径", "content": "默认 USD/FOB 深圳/+12%", "version": 2}]
        cand = [{"kind": "template", "title": "PI模板", "content": "抬头+银行+签字", "version": 1}]
        out = tm.format_memory_block(frozen, cand)
        self.assertIn("<memory-data", out)
        self.assertIn("</memory-data>", out)
        self.assertIn("默认 USD", out)
        self.assertIn("PI模板", out)
        self.assertIn("v2", out)
        self.assertIn("冻结", out)
        self.assertIn("候选", out)

    def test_block_empty(self):
        self.assertEqual(tm.format_memory_block([], []), "")

    def test_remember_schema(self):
        s = tm.REMEMBER_TOOL_SCHEMA
        self.assertEqual(s["name"], "remember")
        props = s["input_schema"]["properties"]
        self.assertEqual(set(s["input_schema"]["required"]), {"title", "content", "kind"})
        self.assertIn("freeze", props)


if __name__ == "__main__":
    unittest.main()
