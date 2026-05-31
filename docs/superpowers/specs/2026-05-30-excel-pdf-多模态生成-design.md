# Excel + PDF 服务端多模态生成 — 设计 (子项目③)

日期: 2026-05-30
产品: Trade2GO.ai (chat2go.xyz)
后端: chat2go-worker (Modal, worker/)

## 背景

Hermes 时代有 excel_lib.py / contract_lib.py(weasyprint/reportlab 生 PDF),
2026-05-26 cloud cutover 后丢失。现状:
- 服务端生成 Excel: 无
- 服务端生成 PDF: 无 (CLAUDE.md 仍挂 "PDF 真生成" TODO)
- 仅前端 html2pdf.js: 把已渲染 markdown 截图式导出 PDF, 不能生成 Excel, 非真排版

本子项目以 serverless 原生方式(Claude tool-use)重建服务端 Excel + PDF 生成。

## 硬指标

- **PDF 中文必须正常显示, 绝不能出现 □□□ 豆腐块乱码**。
  → 用 reportlab 内置 `STSong-Light` (Adobe-GB1) CID 字体, 自带简体中文, 无需打包字体文件。
  → 测试用 pypdf 从生成的 PDF 提取文本, 断言含可读中文。

## 架构

### 2 个新工具 (接入子项目② 的 tool-use 循环)

仅外贸房(已挂会计工具)增加:
- **make_excel** — 把结构化数据(标题 + 表头 + 行 + 可选汇总)生成 .xlsx
- **make_pdf** — 把结构化文档(标题 + 段落 + 表格)生成 .pdf

流程:
1. AI 算完账(或整理好数据) → 调 make_excel / make_pdf, 传结构化 spec
2. worker: build bytes(纯函数) → 上传 Supabase Storage → 拿 public URL
3. tool_result 返回 {url, name, size} 给 AI (让它能在文字里提到"已生成可下载")
4. worker 累积该 attachment
5. AI 产出最终文字 → worker UPDATE 占位消息: content=文字, attachments=[累积的文件]
6. 前端 appendMessage 的 attachHtml 已支持渲染下载卡片(无需前端改动)

### 纯函数 vs 副作用分层

- **doc_gen.py (纯函数, 可单测)**:
  - `build_excel(spec: dict) -> bytes`
  - `build_pdf(spec: dict) -> bytes`
  - spec schema 见下。不碰网络/存储。
- **worker (副作用)**: 调 build_* 拿 bytes → upload storage → 累积 attachment。
  上传逻辑在 worker, 因为需要 supabase service-role client + room 上下文。

### spec schema

make_excel spec:
```
{
  "filename": "订单核算表",          # 中文显示名(无扩展名)
  "sheet_name": "Sheet1",
  "title": "2026-05 订单成本核算",    # 可选大标题
  "headers": ["项目", "金额"],
  "rows": [["采购", 100], ["运费", 20], ...],
  "summary": [["总成本", 135]]        # 可选, 加粗
}
```

make_pdf spec:
```
{
  "filename": "报价单",
  "title": "Trade2GO 报价单",
  "blocks": [
    {"type": "paragraph", "text": "尊敬的客户..."},
    {"type": "table", "headers": [...], "rows": [...]},
  ]
}
```

### 存储 / 文件名

- bucket: `chat-uploads` (public, 已存在)。
- **storage 路径必须 ASCII** (中文路径 Supabase Storage 返回 400, 踩过坑):
  路径用 `gen/{uuid}.xlsx` 形式; 中文名只放在 attachment.name 显示。
- attachment dict (对齐现有 messages.attachments schema):
  `{name, url, size, mime_type, storage_path}`

### 工具调用上限

复用子项目② 的 MAX_TOOL_ITERS=5 (会计 + 文件生成共享预算)。

## 依赖

Modal image pip_install 增加:
- `openpyxl` (xlsx)
- `reportlab` (pdf, 内置 CJK 字体)
测试机增加 `pypdf` (验证 PDF 文本; 已在 CLAUDE.md python deps 列表)。

## 测试 (TDD)

doc_gen.py 纯函数:
1. **build_excel**: 生成 bytes → openpyxl 重新打开 → 断言单元格值正确、汇总行存在。
2. **build_pdf 中文**: 生成含中文的 PDF → pypdf 提取文本 → **断言含中文字符且可读(无豆腐块)**。这是硬指标测试。
3. build_pdf 表格: 断言 PDF 字节非空、以 %PDF 开头、表格数据出现在文本里。
4. 边界: 空 rows / 缺字段不崩。

worker 接线(fake modal 注入, 真实代码):
5. make_excel/make_pdf 工具在 TOOL_SCHEMAS 里, dispatch 能路由。
6. 文件生成工具调用后 attachment 被累积、UPDATE 时写入 attachments。

联调(部署后 live):
7. 外贸房发"把这个订单核算做成Excel" → AI 调 make_excel → 消息带可下载 .xlsx。
8. 发"生成PDF报价单" → 下载 PDF 打开**中文正常无乱码**。

## 范围边界

- 不改其它 6 产品(作用域隔离, 仅外贸房挂工具)。
- 不做 Word/PPT。
- 前端无改动(下载卡片已支持; 若发现渲染问题再单独处理)。

## 部署

worker pip 依赖变了 → mini `modal deploy` 会重建 image(openpyxl/reportlab)。
