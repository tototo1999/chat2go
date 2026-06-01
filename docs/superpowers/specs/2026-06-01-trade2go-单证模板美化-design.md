# Trade2GO 单证模板美化 设计文档

**日期**：2026-06-01
**状态**：设计已确认，待写实现计划
**目标读者**：实现该功能的工程师（假设不了解本项目）

---

## 1. 目标

把 Trade2GO 的 PDF 单证从「reportlab 代码画、样式朴素」升级为「**品牌级精致、全套统一风格**」。核心做法：**渲染路线换成 HTML/CSS 模板 → PDF（WeasyPrint），AI 只提供结构化数据，模板掌管全部样式**。

成功标准：
- 报价单 / 形式发票（PI）输出达到"设计稿级"观感（已通过 HTML 样稿确认：绿色品牌系统、页眉 logo、双方信息卡、专业货物表、合计区、贸易条款、收款银行、签章 + 公章叠加、页脚页码）。
- 各单据共享一套品牌视觉（同字体/配色/页眉页脚）→ 全套统一。
- 中文正常渲染；公章能精确压在签字行上。
- AI 不再低层画版式 → 样式 100% 一致、不会被 AI 画乱。

非目标（本期不做）：商业发票 CI / 装箱单 PL（Phase 2 用同一 base 扩展）；连发合并、串答排队（另有 TODO）。

---

## 2. 架构

```
AI（worker tool-use）
  └─ 调 make_document(doc_type, data)        ← AI 只给结构化字段
        │
        ▼
  doc_render.render_document(doc_type, data, profile, seal_png)
        │  1. 载入公司档案 profile（记忆 kind='company' 的结构化 JSON）
        │  2. Jinja2 渲染 templates/<doc_type>.html（继承 base.html + brand.css）
        │  3. WeasyPrint HTML(string=...).write_pdf()  ← 中文字体已打包进镜像
        │  4. 若 data.stamp → 公章 PNG（PIL 抠白）绝对定位叠在签字区
        ▼
  PDF bytes → 上传 Supabase Storage → 回链给聊天（复用现有上传逻辑）
```

关键原则：**seller / 银行 / logo / 公章来自公司档案（自动注入），AI 只提供 buyer + 货物明细 + 条款 + 标志位**。这样 AI 输入小、品牌强一致。

---

## 3. 渲染引擎选型（已定）

**WeasyPrint**（纯 Python，CSS Paged Media）。
- 理由：专为文档设计，`@page` 支持页边距/页眉页脚/页码（`counter(page)`），表格跨页自动重复表头；比 headless Chromium 轻太多（无需塞 ~300MB Chromium）。
- 放弃：Chromium/Playwright（过重、冷启慢）；reportlab 继续打磨（做不出设计稿质感，已被"品牌级"目标排除）。
- 中文：镜像构建时下载 **Noto Sans SC** 字体到字体目录并 `fc-cache`；CSS 按 family 名引用。

---

## 4. 组件与文件

| 文件 | 职责 |
|---|---|
| `worker/doc_render.py`（新建） | `render_document(doc_type, data, profile, seal_png) -> bytes`：Jinja2 渲染 + WeasyPrint 出 PDF + 公章叠加。唯一对外接口。 |
| `worker/templates/brand.css`（新建） | 品牌令牌（绿色系 `--brand:#0f5a52`）+ 页眉/页脚/表格/分页/签章/公章定位的全部样式。**所有单据共用**。 |
| `worker/templates/base.html`（新建） | 页面骨架：`<head>` 引 brand.css、`@page` 页眉 logo+公司名、页脚公司名+页码；`{% block body %}`。 |
| `worker/templates/quote.html`（新建） | 报价单，继承 base。 |
| `worker/templates/pi.html`（新建） | 形式发票 PI，继承 base。 |
| `worker/templates/contract.html`（Phase 2） | 销售合同，英文条款结构（QUALITY/TOLERANCE/PARTIAL SHIPMENT/BANK INFO…）。 |
| `worker/templates/statement.html`（Phase 2） | 对账单 / 收款通知。 |
| `worker/doc_gen.py`（改） | 保留 `make_pdf(blocks)` / `build_excel` 作自由内容兜底；公章抠白函数 `_seal_png` 提取为可复用。 |
| `worker/chat2go_worker.py`（改） | 注册 `make_document` 工具 schema + dispatch；载入公司档案 + 公章；指引 TRADE_ACCOUNTING_GUIDE 增「单证走 make_document」。 |
| Modal 镜像（改） | `pip_install` 加 `weasyprint`；`run_commands` 下载 Noto Sans SC + `fc-cache`。 |
| `worker/test_doc_render.py`（新建） | 各 doc_type 渲染单测。 |

---

## 5. `make_document` 工具

### 5.1 Schema（AI 可见）

```json
{
  "name": "make_document",
  "description": "生成品牌级外贸单证 PDF（报价单/PI 等）。只需给结构化字段，公司抬头/银行/logo/公章由系统按公司档案自动填充。",
  "input_schema": {
    "type": "object",
    "properties": {
      "doc_type": {"type": "string", "enum": ["quote", "pi"]},
      "title_cn": {"type": "string", "description": "单据中文名，如 报价单 / 形式发票"},
      "doc_no":   {"type": "string"},
      "date":     {"type": "string", "description": "YYYY-MM-DD"},
      "currency": {"type": "string", "default": "USD"},
      "validity": {"type": "string", "description": "有效期，如 15 天（报价单用）"},
      "buyer": {
        "type": "object",
        "properties": {
          "name": {"type": "string"}, "attn": {"type": "string"},
          "address": {"type": "string"}, "tel": {"type": "string"}
        },
        "required": ["name"]
      },
      "items": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "name": {"type": "string"}, "spec": {"type": "string"},
            "qty": {"type": "number"}, "unit_price": {"type": "number"},
            "amount": {"type": "number", "description": "可省略，系统按 qty×unit_price 计算"}
          },
          "required": ["name", "qty", "unit_price"]
        }
      },
      "extra_charges": {
        "type": "array",
        "description": "海运费等附加项",
        "items": {"type": "object", "properties": {"label": {"type": "string"}, "amount": {"type": "number"}}}
      },
      "trade_term": {"type": "string", "description": "如 CNF Busan / FOB Ningbo"},
      "terms": {
        "type": "object",
        "description": "贸易条款键值对：price_term/payment/lead_time/packing/origin 等",
        "additionalProperties": {"type": "string"}
      },
      "stamp": {"type": "boolean", "description": "true=在卖方签章处盖公司公章", "default": false}
    },
    "required": ["doc_type", "buyer", "items"]
  }
}
```

### 5.2 计算与默认
- `amount` 省略 → `round(qty * unit_price, 2)`。
- `subtotal = Σ amount`；`total = subtotal + Σ extra_charges.amount`。
- `currency` 默认 USD；`date` 省略 → 由 worker 注入当天（worker 侧已有 `_now_iso`，不在模板里取时间）。
- seller / bank / logo / seal 不从 AI 取，来自公司档案。

---

## 6. 公司档案（brand 数据源）

复用记忆系统，**不新建表**。

- 存储：`tradego_memory_rules`，`kind='company'`、`title='公司档案'`，`content` = 结构化 JSON：
  ```json
  {
    "name_cn": "…有限公司", "name_en": "… CO., LTD.",
    "address": "…", "tel": "…", "email": "…", "contact": "李锐",
    "logo_text": "W",
    "bank": {"beneficiary": "…", "bank_name": "…", "account": "…", "swift": "…"}
  }
  ```
- 载入：`trade_memory.load_company_profile(sb, expert_id, product) -> dict`（找不到返回 `{}`，模板用空白/「—」兜底，单据照常出）。
- logo：优先 `logo_text`（字母色块，如样稿的「W」）；后续可扩展上传 logo 图。
- 公章：复用现有"最方形红章图"识别（`_pick_seal_url`）+ `_seal_png` 抠白；`data.stamp=true` 时叠加。
- AI 可通过现有 `remember` 工具维护公司档案（kind='company'），与 P1 记忆机制一致。
- **隐私**：公司档案/银行/账号属敏感数据，只存数据库、随单据渲染，**不写入代码仓库**（chat2go 为公开仓库）。模板与测试用占位数据。

---

## 7. 品牌系统（brand.css 雏形已在样稿验证）

令牌（绿色系，确认稿）：
```
--ink:#1a2230; --muted:#6b7686; --line:#e3e7ee; --line2:#cfd6e0;
--brand:#0f5a52; --brand-2:#0f766e; --brand-wash:#f1f6f5; --amount:#0f5a52;
```
区块：页眉（logo 色块 + 中英文公司名 + 大字单据标题 + 主色描边）、单据元信息、双方信息卡（To Buyer / From Seller）、货物表（主色表头白字、隔行浅底、数字右对齐 `tabular-nums`、品名中英双行）、合计区（合计行主色加粗）、贸易条款（两栏）、收款银行（主色竖条强调块）、签章区（公章绝对定位压签字行）、页脚（公司名 + Trade2GO.ai 生成 + 页码）。

页面：A4，`@page` 边距 18/16mm；页脚用 `@bottom-center` 或 running element + `counter(page)`；表格 `thead` 跨页重复。

---

## 8. 公章叠加（HTML 方案）

- 模板在卖方签章区放锚点 `<div class="seal-anchor">`。
- `render_document` 若 `stamp=true` 且有公章图：`_seal_png` 抠白 → base64 内联 `<img class="seal">`，CSS `position:absolute` 相对锚点定位（约 42mm、`rotate(-14deg)`、`opacity:.85`），**精确压在「卖方盖章/Authorized Signature」行上**。
- 无公章图或 stamp=false → 不渲染，签章区留手签线。

---

## 9. 与现有能力的关系

- `make_pdf(blocks)` / `build_excel` **保留**作自由内容兜底；公章抠白逻辑提取复用。
- 指引 TRADE_ACCOUNTING_GUIDE 更新：**报价单/PI 等标准单证 → 调 `make_document`**；非标准自由文档 → `make_pdf`。AI 仍**严禁编造下载链接**（必须真的调工具，沿用 P0 规则）。
- 其它 3 产品零影响（仅 trade 房注册 make_document）。

---

## 10. 错误处理

- 缺必填项（buyer/items 之外的可选字段）→ 模板渲染空白/「—」，不崩。
- WeasyPrint 渲染异常 → 捕获，回退 `make_pdf` 或向聊天返回明确错误（**不编造链接**），并记日志。
- 字体缺失 → 镜像构建阶段就装好 Noto Sans SC；构建脚本验证字体存在，缺失则构建失败（不在运行期才发现）。
- 公司档案 JSON 解析失败 → 当作空档案，单据照常出（不阻断）。

---

## 11. 测试

- **单测** `test_doc_render.py`：对 quote / pi 各喂样例 data + 占位 profile → 渲染 → 断言 PDF 非空、`pypdf` 页数 ≥1、提取文本含关键字段（单据号、买方名、合计）。
- **计算单测**：amount 省略时按 qty×unit_price；subtotal/total 正确。
- **公章单测**：stamp=true + 测试章图 → PDF 字节比 stamp=false 大（确有图嵌入）。
- **视觉验证**（人眼，关卡）：渲染样例 PDF，在**真实 Chrome** 打开核对观感（遵循项目「视觉测试用真实浏览器」约定）。

---

## 12. 落地节奏

- **Phase 1（本 spec 的实现计划）**：WeasyPrint + 字体入镜像；doc_render.py；brand.css + base + **quote + pi** 模板；make_document 工具 + dispatch；公司档案载入；公章叠加；指引更新；单测。→ 上线报价单 + PI。
- **Phase 2（后续）**：用同一 base 加 contract（英文条款结构）+ statement 模板，扩 `make_document` 的 doc_type 枚举。

---

## 13. 风险与缓解

- WeasyPrint 镜像体积/构建时长上升（字体 + 依赖）→ 可接受；构建一次缓存。
- WeasyPrint 对部分新 CSS（flex/grid）支持有版本差异 → 样稿已用 grid/flex，实现时锁定 WeasyPrint 版本并在单测渲染验证；必要处回退表格布局。
- 公司档案需大咖/AI 先建立 → 缺档案时空白兜底，不阻断；可在指引里提示 AI 首次生成单证前先 `remember` 公司档案。
