"""TDD 测试 — Excel/PDF 服务端生成 (子项目③)。
硬指标: PDF 中文不能出豆腐块 → pypdf 提取文本断言含可读中文。
run: python3 -m unittest test_doc_gen -v
"""
import io
import unittest

import doc_gen as dg


class TestBuildExcel(unittest.TestCase):
    def test_returns_valid_xlsx_bytes(self):
        spec = {
            "filename": "订单核算表",
            "title": "2026-05 订单成本核算",
            "headers": ["项目", "金额"],
            "rows": [["采购", 100], ["运费", 20], ["关税", 15]],
            "summary": [["总成本", 135]],
        }
        data = dg.build_excel(spec)
        self.assertIsInstance(data, bytes)
        # xlsx = zip, 以 PK 开头
        self.assertEqual(data[:2], b"PK")

    def test_cells_roundtrip(self):
        import openpyxl
        spec = {
            "filename": "x", "headers": ["项目", "金额"],
            "rows": [["采购", 100], ["运费", 20]],
            "summary": [["总成本", 120]],
        }
        wb = openpyxl.load_workbook(io.BytesIO(dg.build_excel(spec)))
        ws = wb.active
        # 表头 + 数据应能读回 (含中文)
        flat = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
        self.assertIn("项目", flat)
        self.assertIn("采购", flat)
        self.assertIn("100", flat)
        self.assertIn("总成本", flat)

    def test_empty_rows_ok(self):
        data = dg.build_excel({"filename": "空", "headers": ["a"], "rows": []})
        self.assertEqual(data[:2], b"PK")


class TestBuildPdf(unittest.TestCase):
    def test_returns_pdf_bytes(self):
        spec = {"filename": "报价单", "title": "测试", "blocks": [
            {"type": "paragraph", "text": "你好"}]}
        data = dg.build_pdf(spec)
        self.assertIsInstance(data, bytes)
        self.assertEqual(data[:4], b"%PDF")

    def test_chinese_no_tofu(self):
        """硬指标: 生成含中文的 PDF, pypdf 提取文本必须含可读中文, 不能是豆腐块。"""
        import pypdf
        zh = "尊敬的客户您好这是报价单"
        spec = {"filename": "报价单", "title": "Trade2GO 报价单", "blocks": [
            {"type": "paragraph", "text": zh},
            {"type": "table", "headers": ["产品", "单价"],
             "rows": [["不锈钢螺丝", "12.50"], ["铝合金支架", "88.00"]]},
        ]}
        data = dg.build_pdf(spec)
        reader = pypdf.PdfReader(io.BytesIO(data))
        text = "".join(p.extract_text() or "" for p in reader.pages)
        # 提取出的文本必须包含原中文(证明字体嵌入正确, 非 □□□)
        self.assertIn("尊敬的客户", text)
        self.assertIn("不锈钢螺丝", text)
        # 不应出现典型豆腐块字符
        self.assertNotIn("�", text)  # replacement char

    def test_table_only(self):
        spec = {"filename": "表", "blocks": [
            {"type": "table", "headers": ["项目", "金额"], "rows": [["成本", "135.00"]]}]}
        data = dg.build_pdf(spec)
        self.assertEqual(data[:4], b"%PDF")

    def test_empty_blocks_ok(self):
        data = dg.build_pdf({"filename": "空", "title": "空文档", "blocks": []})
        self.assertEqual(data[:4], b"%PDF")


class TestFilenameSanitize(unittest.TestCase):
    def test_ascii_storage_path(self):
        # 中文显示名 → ASCII storage 路径(踩过 Supabase 400 坑)
        path = dg.storage_path("订单核算表", "xlsx")
        self.assertTrue(path.startswith("gen/"))
        self.assertTrue(path.endswith(".xlsx"))
        self.assertTrue(path.isascii())

    def test_unique(self):
        a = dg.storage_path("同名", "pdf")
        b = dg.storage_path("同名", "pdf")
        self.assertNotEqual(a, b)  # 含随机/唯一段


if __name__ == "__main__":
    unittest.main()
