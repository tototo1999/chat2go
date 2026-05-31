"""TDD 测试 — 外贸会计 7 个确定性计算工具 (子项目②)。
零依赖, stdlib unittest: python3 -m unittest test_trade_accounting -v
金额全部 Decimal, 2 位小数 ROUND_HALF_UP; 已知输入对已知输出。
"""
import unittest
from decimal import Decimal as D

import trade_accounting as ta


class TestCalcUnitCost(unittest.TestCase):
    def test_basic(self):
        r = ta.calc_unit_cost(purchase_total=100, freight=20, duty=15, misc_fees=0, quantity=10)
        self.assertEqual(r["total_cost"], "135.00")
        self.assertEqual(r["unit_cost"], "13.5000")  # 单价 4 位

    def test_with_misc(self):
        r = ta.calc_unit_cost(purchase_total=1000, freight=80, duty=50, misc_fees=20, quantity=50)
        self.assertEqual(r["total_cost"], "1150.00")
        self.assertEqual(r["unit_cost"], "23.0000")

    def test_rounding(self):
        # 100/3 = 33.333... → 单价 4 位 33.3333
        r = ta.calc_unit_cost(purchase_total=100, freight=0, duty=0, misc_fees=0, quantity=3)
        self.assertEqual(r["unit_cost"], "33.3333")

    def test_zero_qty_raises(self):
        with self.assertRaises(ValueError):
            ta.calc_unit_cost(purchase_total=100, freight=0, duty=0, misc_fees=0, quantity=0)


class TestQuoteFromMargin(unittest.TestCase):
    def test_fob_margin(self):
        # 报价 = 成本/(1-利润率); 100/(1-0.2)=125
        r = ta.quote_from_margin(unit_cost=100, target_margin=0.2, incoterm="FOB")
        self.assertEqual(r["quote_price"], "125.00")

    def test_cif(self):
        # FOB 125, 运费 10, 保费 2 → CIF 137
        r = ta.quote_from_margin(unit_cost=100, target_margin=0.2, incoterm="CIF",
                                 freight=10, insurance=2)
        self.assertEqual(r["quote_price"], "137.00")

    def test_cfr(self):
        # FOB 125 + 运费 10 → CFR 135 (无保费)
        r = ta.quote_from_margin(unit_cost=100, target_margin=0.2, incoterm="CFR", freight=10)
        self.assertEqual(r["quote_price"], "135.00")

    def test_margin_ge_1_raises(self):
        with self.assertRaises(ValueError):
            ta.quote_from_margin(unit_cost=100, target_margin=1.0, incoterm="FOB")


class TestOrderPnl(unittest.TestCase):
    def test_basic(self):
        # 收入1000 - 成本600 - 费用50 - 佣金30 - 税20 = 净利300
        r = ta.order_pnl(revenue=1000, cost=600, expenses=50, commission=30, tax=20)
        self.assertEqual(r["gross_profit"], "400.00")   # 收入-成本
        self.assertEqual(r["net_profit"], "300.00")
        self.assertEqual(r["gross_margin"], "40.00")    # 百分比
        self.assertEqual(r["net_margin"], "30.00")

    def test_loss(self):
        r = ta.order_pnl(revenue=500, cost=600, expenses=0, commission=0, tax=0)
        self.assertEqual(r["net_profit"], "-100.00")

    def test_zero_revenue(self):
        r = ta.order_pnl(revenue=0, cost=0, expenses=0, commission=0, tax=0)
        self.assertEqual(r["net_margin"], "0.00")  # 不应除零崩溃


class TestFxConvert(unittest.TestCase):
    def test_single(self):
        r = ta.fx_convert(amount=100, from_ccy="USD", to_ccy="CNY", rate=7.2)
        self.assertEqual(r["converted"], "720.00")

    def test_rounding(self):
        # 33.33 USD * 7.25 = 241.6425 → 241.64
        r = ta.fx_convert(amount=33.33, from_ccy="USD", to_ccy="CNY", rate=7.25)
        self.assertEqual(r["converted"], "241.64")


class TestExportRebate(unittest.TestCase):
    def test_basic(self):
        # 退税额 = 采购额/(1+增值税率) * 退税率; 1130/(1.13)*0.13 = 130
        r = ta.export_rebate(purchase_amount=1130, vat_rate=0.13, rebate_rate=0.13)
        self.assertEqual(r["rebate_amount"], "130.00")

    def test_partial_rebate(self):
        # 11300/(1.13)*0.09 = 900
        r = ta.export_rebate(purchase_amount=11300, vat_rate=0.13, rebate_rate=0.09)
        self.assertEqual(r["rebate_amount"], "900.00")


class TestCommission(unittest.TestCase):
    def test_rate(self):
        # 佣金 = 10000 * 0.05 = 500; 净利 = 2000-500 = 1500
        r = ta.commission(base_amount=10000, commission_rate=0.05, net_before=2000)
        self.assertEqual(r["commission_amount"], "500.00")
        self.assertEqual(r["net_after"], "1500.00")

    def test_fixed(self):
        r = ta.commission(base_amount=10000, commission_fixed=300, net_before=2000)
        self.assertEqual(r["commission_amount"], "300.00")
        self.assertEqual(r["net_after"], "1700.00")


class TestReconcile(unittest.TestCase):
    def test_balance_and_aging(self):
        recv = [
            {"amount": 1000, "due_date": "2026-05-01", "paid": False},  # as_of 2026-05-30 → 29 天 → 0-30
            {"amount": 500, "due_date": "2026-03-01", "paid": False},   # 90 天 → 61-90 区间
            {"amount": 800, "due_date": "2026-05-20", "paid": True},    # 已付 → 不计 aging
        ]
        pay = [{"amount": 600, "due_date": "2026-05-10", "paid": False}]
        r = ta.reconcile(receivables=recv, payables=pay, as_of_date="2026-05-30")
        self.assertEqual(r["total_recv"], "1500.00")   # 未付应收 1000+500
        self.assertEqual(r["total_pay"], "600.00")
        self.assertEqual(r["balance"], "900.00")       # 应收-应付
        # aging buckets 存在且为 dict
        self.assertIn("0-30", r["aging_buckets"])
        self.assertEqual(r["aging_buckets"]["0-30"], "1000.00")

    def test_empty(self):
        r = ta.reconcile(receivables=[], payables=[], as_of_date="2026-05-30")
        self.assertEqual(r["balance"], "0.00")


class TestDispatch(unittest.TestCase):
    def test_dispatch_known(self):
        r = ta.dispatch("calc_unit_cost",
                        {"purchase_total": 100, "freight": 20, "duty": 15,
                         "misc_fees": 0, "quantity": 10})
        self.assertEqual(r["total_cost"], "135.00")

    def test_dispatch_unknown(self):
        r = ta.dispatch("nope", {})
        self.assertIn("error", r)

    def test_dispatch_bad_args_returns_error(self):
        # quantity=0 → calc_unit_cost 抛 ValueError → dispatch 捕获成 error
        r = ta.dispatch("calc_unit_cost", {"purchase_total": 100, "quantity": 0})
        self.assertIn("error", r)

    def test_schemas_match_dispatch(self):
        names = {t["name"] for t in ta.TOOL_SCHEMAS}
        self.assertEqual(names, set(ta._DISPATCH.keys()))
        self.assertEqual(len(ta.TOOL_SCHEMAS), 7)


if __name__ == "__main__":
    unittest.main()
