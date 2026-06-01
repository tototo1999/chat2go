# Trade2GO 项目完整交接（Handoff）

> 最后更新：2026-05-31。本文是 **tradego（外贸站）整个项目的单一交接入口**。
> 旧文档 `docs/TRADEGO-MINI-HANDOFF.md` 是 **Hermes 时代（2026-05-17）的 mini 部署 SOP，已整体作废**——Hermes 已全部 bootout，后端改走 serverless。读那份只为了解历史，别照着做部署。

---

## 0. 一句话定位

**Trade2GO.ai = chat2go 平台的「外贸跟单」垂直站**：独立 GitHub repo、独立域名（chat2go.xyz）、独立前端主题（蓝），但**共用同一个 Supabase 后端 + 同一个 Modal worker**，靠 `rooms.product='tradego'` / `industry='外贸跟单'` 隔离。AI 是外贸跟单员的助手，能生成合同条款、做会计核算、出 Excel/PDF 报表。

---

## 1. 架构全景（2026-05-26 全 cloud cutover 之后的现状）

```
chat2go.xyz (前端, GitHub Pages, repo tototo1999/tradego)
   │  用户发消息 → INSERT messages
   │  fetch /functions/v1/chat2go-ingest
   ▼
Supabase Edge Function  chat2go-ingest
   │  INSERT 一条占位 AI 消息(role=ai, content='...')
   │  fire-and-forget POST(带 industry / system_prompt / model)
   ▼
Modal worker  chat2go-worker
   (https://tototo1999--chat2go-worker-ingest.modal.run)
   │  拉 history(40) + memories(scope=room) + 行业 prompt
   │  外贸房:挂会计/文档工具 → Claude tool-use 循环
   │  → Claude Sonnet 4.6
   │  UPDATE 占位消息 content (+ attachments)
   ▼
Supabase Realtime → chat.html 自动重渲
```

**关键事实**：现在**没有任何 Hermes daemon 在跑**。本地 + mini 上的 `ai.hermes.gateway*` 全部 `bootout + disable`。4 个产品（chat2go / tradego / speak2go / well2go）都走这一条 `chat2go-ingest → chat2go-worker` 链路。详见 memory `project_all_cloud_2026_05_26`。

### 仓库与域名

| 项 | 值 |
|---|---|
| 主站(命理) repo | `tototo1999/chat2go` → chat2go.cn（本机 `~/chat2go/`，dev 主维护） |
| **tradego repo** | **`tototo1999/tradego`** → **chat2go.xyz**（CNAME 文件写 `chat2go.xyz`） |
| tradego 前端源码位置 | **仅在 mini `~/tradego-site/`**——dev 机**没有** tradego 的 git checkout |
| `chat2go.cn/tradego/` 子目录 | **已永久删除**（commit `e453fdf`，2026-05-17）。**绝不再往这条路径推任何东西。** |

### 账号 / ID

| 项 | 值 |
|---|---|
| 外贸大咖账号 | `388388@vip.163.com` |
| expert_id | `5dcec9b4-18a8-405b-837b-10bc27de114c` |
| tradego 房间 id（cloud） | `0ac15b5b-...`（`rooms.product='tradego'`, `industry='外贸跟单'`, `serverless=true`） |
| Supabase project_id | `qjnagbzqhoansixqharb` |
| Modal app | `chat2go-worker`（4 产品共用，单一 app） |

> ⚠️ `industry` 字段历史值是 `外贸跟单`，worker 里 `INDUSTRY_ALIASES['外贸跟单'] = '外贸'` 映射到正式 prompt key。

---

## 2. 后端实现（`worker/`，这是现在改 tradego AI 行为的唯一地方）

所有 tradego 后端逻辑都在 `worker/`，部署到 Modal。改完 `modal deploy worker/chat2go_worker.py` 约 1 秒热生效。

### 2.1 行业 prompt
`worker/chat2go_worker.py` 的 `INDUSTRY_PROMPTS["外贸"]`：合同条款（FOB/CIF/CFR）、信用证、提单、装箱单、报关、物流、汇率结算。`room.system_prompt` 非空则优先用大咖自定义，否则用这条。

### 2.2 外贸专属：tool-use 能力（重建 Hermes 时代 contract_lib/excel_lib）
cutover 后丢了 Hermes 的 `contract_lib.py`/`excel_lib.py`。2026-05-30 起以 serverless 原生方式（Claude tool-use）重建为两个子项目：

**子项目② — 外贸会计核算（`worker/trade_accounting.py`）**
- 7 个确定性计算工具（全 `Decimal` 运算，禁 float；金额 2 位、单价/汇率 4 位，`ROUND_HALF_UP`）：
  `calc_unit_cost`（单位成本）· `quote_from_margin`（按利润率倒推报价 + FOB/CIF/CFR）· `order_pnl`（订单损益）· `fx_convert`（汇率换算，汇率由用户给、AI 不编）· `export_rebate`（出口退税）· `commission`（佣金）· `reconcile`（对账 + 账期 aging）。
- 入口 `ta.dispatch(name, input)`；schemas = `ta.TOOL_SCHEMAS`。
- 设计：`docs/superpowers/specs/2026-05-30-外贸会计核算技能-design.md`

**子项目③ — Excel/PDF 服务端生成（`worker/doc_gen.py`）**
- `make_excel`（openpyxl）· `make_pdf`（reportlab，内置 `STSong-Light` CID 字体，**中文不出豆腐块**）。
- `build_excel(spec)`/`build_pdf(spec)` 纯函数返回 bytes；worker 负责上传 Storage 并附到消息 attachments。
- 设计：`docs/superpowers/specs/2026-05-30-excel-pdf-多模态生成-design.md`

**tool-use 循环（`_run_completion`）**
- `_is_trade_room(industry)` 判定外贸房（基于 industry，不受 system_prompt 覆盖影响）。
- 外贸房：system prompt 追加 `TRADE_ACCOUNTING_GUIDE`（强制"涉及金额必须调工具、不许心算、缺数字先追问"）+ 挂 `ta.TOOL_SCHEMAS + dg.DOC_TOOL_SCHEMAS`，跑最多 `MAX_TOOL_ITERS=5` 轮 tool-use；文档工具生成文件→上传→进 attachments。用尽迭代再要一次无工具的收尾文字。
- 非外贸房：单次普通调用。

### 2.3 安全（worker 鉴权）
- `_check_worker_auth`：env-gated bearer（`CHAT2GO_MODAL_WORKER_TOKEN` 未设则放行=灰度，设了则常数时间比对）。
- `_verify_placeholder`：worker 持 service-role 绕 RLS，只允许更新本房 `role='ai'` 占位消息，防攻击者传任意 message_id 覆盖正文。

### 2.4 Modal image 依赖
`chat2go_worker.py` 的 `.pip_install(...)`：`openpyxl reportlab Pillow pypdf python-docx`。这些只在 Modal image 里，**本地 `worker/.venv` 没装**（本地纯逻辑测试用 `~/.venv-c2g` 跑，有这些库 + certifi）。

### 2.5 文档生成能力（合同/单证）— 2026-06-01 大幅增强
`worker/doc_gen.py`，从小白真实跟单会话挖出并修的能力，**都已部署上线**：
- **读文件**（`_build_messages`）：用户上传的 **PDF/Excel/Word/txt/csv** 附件 → worker 下载 → 抽文本注入上下文（pypdf/openpyxl/python-docx）。图片仍走 Vision。SSRF：只下本项目 Storage。8MB/16k 字上限。
- **一页压缩**（`make_pdf` 的 `fit_pages:1`）：`build_pdf` 等比缩字号/行距/边距，边渲染边用 pypdf 数页，收敛到 N 页。用户说「压成一页」AI 传 `fit_pages:1`。
- **盖公章**（`{type:'image', overlay:true}`）：
  - worker **自动从用户传的图里挑「最接近正方形」那张当章**（`_pick_seal_url`，圆章≈1:1;不靠 AI 视觉挑，实测不可靠);章图**查库找**（`_image_choices` 走 DB，不受 40 条历史窗口限制，公章聊久了不会丢)。
  - **抠白底**（PIL，`_seal_png`，近白像素转透明,红章干净叠文字上）。
  - **精确 overlay**（`_seal_overlay` 零高度 Flowable）：章压在上一行「需方盖章:」上,不占版面、随排版/缩放自动跟位。章用**实际尺寸,不随 fit 压页缩小**。可选 `offset_x_mm/offset_y_mm` 微调。
- **禁止编造下载链接**（`TRADE_ACCOUNTING_GUIDE` 铁律）：AI 必须真调 make_pdf/make_excel,不许在正文写 `gen/xxx.pdf` 假链接谎称已生成。
- ⚠️ **已知可靠性边界**:一个房里传了**多张都偏方形**的图时,自动挑章可能挑错。干净做法:盖章前把公章图重发一次作为最新图。
- 验证方法:本地 `~/.venv-c2g` 渲染 PDF + macOS `sips -s format png` 转图肉眼看;或受控触发(iamarobot 房 38ebcd0e,**别在小白实时房 0ac15b5b 注入测试**)。

### 2.6 记忆系统 P0（2026-06-01）— 见独立设计/计划
- tradego 外贸房**直连 Anthropic**（`_anthropic_client(force_direct=True)` + `DIRECT_MODEL=claude-sonnet-4-6`,绕 OpenRouter,为 memory tool 等 beta 铺路;OpenRouter 不透传 context-management beta)。
- `tradego_orders`（订单状态机 + 双时序)+ `tradego_memory_rules`（冻结规则)注入 system;`worker/trade_memory.py`。
- 设计 `docs/superpowers/specs/2026-06-01-trade2go-记忆系统-design.md`,计划 `docs/superpowers/plans/2026-06-01-trade2go-memory-p0.md`,详情 memory `project_tradego_memory_p0`。

---

## 3. 前端（`tototo1999/tradego`，源码只在 mini）

- **主题色**：`#2563eb`（蓝）——区别于主站绿 `#1D9E75`。title/文案也有差异。
- dev 机**没有** checkout，要改必须 ssh mini `~/tradego-site/`。
- **同步主站 chat.html 改动 → tradego 的 SOP（别整文件 rsync，会冲掉蓝主题和 tradego 专属文案）**：
  1. dev 写 `/tmp/tradego_patch.py`（用 `str.replace` 做 surgical 改动）
  2. `scp /tmp/tradego_patch.py lexi@192.168.1.111:/tmp/`
  3. `ssh lexi@192.168.1.111 'cd ~/tradego-site && cp chat.html chat.html.bak.$(date +%s) && python3 /tmp/tradego_patch.py && git add chat.html && git commit -m "..." && git push'`
  4. 后台轮询 `https://chat2go.xyz/chat.html` 验证。
- HTTPS：GH Settings custom domain `chat2go.xyz` → Let's Encrypt 已签发。

---

## 4. 历史演进（读懂"为什么是现在这样"）

1. **起点**：`chat2go.cn/tradego/` 子目录（commit `0985741`）。
2. **拆站**：改为独立 repo `tototo1999/tradego` + chat2go.xyz + mini 上独立 Hermes，删 `chat2go.cn/tradego/`（`e453fdf`）。
3. **Hermes 时代**（2026-05-17）：mini 跑 launchd Hermes，main 模型一路切到 DeepSeek V3，vision 显式走 claude-haiku-4-5；有 `_try_handle_tradego_contract` 拦截器直接渲 PDF；外贸 skill 在 `~/.hermes/skills/productivity/trade-go/`。**这套现在全废**。
4. **全 cloud cutover**（2026-05-26）：所有产品切 `chat2go-ingest + chat2go-worker`，Hermes 全 bootout。外贸专属能力一度丢失（worker 只复用 prompt）。
5. **能力重建**（2026-05-30~31）：以 Claude tool-use 重建会计核算（子项目②）+ Excel/PDF 生成（子项目③）。

---

## 5. 测试与验证现状（2026-05-31）

本地 `worker/.venv` 跑 `python -m unittest`：
- ✅ `test_trade_accounting`：**27/27 通过**（纯 Decimal 逻辑）。
- ⚠️ `test_doc_gen` / `test_worker_toolloop` 中涉及文档生成的用例**本地报 `ModuleNotFoundError: openpyxl/reportlab/pypdf`**——因为这些依赖只在 **Modal image** 里，本地 venv 没装。**不是真回归**，是本地环境缺包。要本地全绿需 `worker/.venv/bin/pip install openpyxl reportlab pypdf`。

**端到端验证（还没做）**：在 tradego 房间发真实外贸 query（如 `给印度客户报价：采购价 80 元/个，5000 个，海运费 ¥6000，目标利润率 25%，FOB 深圳`），确认：① AI 调 `quote_from_margin` 等工具而非心算 ② 出 markdown 表格 ③ 要 Excel/PDF 时真生成文件附件并能下载。

---

## 6. 维护 SOP

| 想做的事 | 怎么做 |
|---|---|
| 看 tradego AI 是否在响应 | `modal app logs chat2go-worker`（4 产品流量都在这一个 app） |
| 改外贸 prompt / 会计指引 | 编辑 `worker/chat2go_worker.py` → `modal deploy worker/chat2go_worker.py`（~1s 生效） |
| 加/改会计工具 | 改 `worker/trade_accounting.py`（加函数 + `TOOL_SCHEMAS` + `dispatch`）→ 加单测 → deploy |
| 改前端 | ssh mini `~/tradego-site/`，走 §3 patch SOP |
| 改 RLS / schema | Supabase MCP（共用项目，注意 4 产品都受影响，DDL 走 preview-then-go） |

---

## 7. 待办 / 已知风险

- [ ] **端到端实测**会计 + Excel/PDF 链路（见 §5），用真 tradego 房间录一遍。
- [ ] **本地补依赖** `openpyxl reportlab pypdf` 让 worker 测试本地可全绿（CI 友好）。
- [ ] **Modal worker 公开 URL 无强制 token**：`CHAT2GO_MODAL_WORKER_TOKEN` 是灰度（未设即放行）。两边密钥配齐后应设上，否则有白嫖 Claude/Storage 风险。
- [ ] **mini 残留清理**：`/Users/lexi/.hermes*` + 旧 plist 仍占盘，确认不用可 `ssh lexi@192.168.1.111 'rm -rf ~/.hermes ~/.hermes-well2go && rm ~/Library/LaunchAgents/ai.hermes.gateway*.plist'`。
- [ ] **历史密钥泄露**（Hermes 时代明文贴过，待确认是否已轮换）：OpenRouter key、DeepSeek key、tradego repo push 用的 GitHub PAT。`docs/TRADEGO-MINI-HANDOFF.md` 里的 `CHAT2GO_TOKEN` 是真 agent_key（该 repo public，注意别 commit）。

---

## 8. 相关文件 / memory 索引

- `worker/chat2go_worker.py` — 主 worker（prompt + tool-use 循环 + 鉴权）
- `worker/trade_accounting.py` / `worker/test_trade_accounting.py` — 会计 7 工具
- `worker/doc_gen.py` / `worker/test_doc_gen.py` — Excel/PDF 生成
- `worker/test_worker_toolloop.py` — tool-use 循环集成测
- `docs/superpowers/specs/2026-05-30-外贸会计核算技能-design.md`
- `docs/superpowers/specs/2026-05-30-excel-pdf-多模态生成-design.md`
- `supabase/migrations/20260517000000_add_product_to_rooms.sql` — `rooms.product` 隔离字段
- `supabase/migrations/20260517020000_update_tradego_todo_payload.sql` — tradego todo 模板
- `docs/TRADEGO-MINI-HANDOFF.md` — ⚠️ Hermes 时代，已作废，仅供历史
- memory：`project_tradego_architecture`（双 repo 架构）· `project_all_cloud_2026_05_26`（cloud cutover 全景）· `chat2go-state-2026-05-17-pm`（拆站 + Hermes 历史快照）
