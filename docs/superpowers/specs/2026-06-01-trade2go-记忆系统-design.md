# Trade2GO 记忆系统设计 (C′ 方案)

日期: 2026-06-01
产品: Trade2GO.ai (外贸跟单;CheckToGo.ai = 同一产品别名)
后端: chat2go-worker (Modal, worker/chat2go_worker.py) + Supabase
范围: **仅 tradego**(共用 worker,新逻辑按 `product='tradego'` / `industry='外贸跟单'` 门控,不影响 chat2go/speak2go/well2go)

## 背景与目标

旧记忆机制(大咖打钩 → DB 触发器 `trg_save_memory_on_expert_up` 写 `scope='expert'`)已**取消**;且与 worker 读取(`scope='room'`)错配,147 条经验从未被注入,学习闭环断裂。

新方向是 **agentic memory**:AI 从实时对话中自主判断**何时新建记忆、何时更新已固化条目**,无人工标注。核心诉求(用户明确,作硬约束):

1. **高效率 / 不来回推翻** —— 已确定的问题/习惯要稳定,只有新东西进"候选";确定的不被随意改写(anti-thrash)。
2. **单调向前 + 版本化** —— 知识像 release 一样向前迭代,逻辑可固化冻结。
3. **模型可移植**(本期受限,见下) —— 强模型当"老师"把知识结晶成纯文本规则,弱/便宜模型当"执行工"照规则做。效率 = 不重复推演确定的事。

### 模型路由现状与本方案取舍
- worker 现走 **OpenRouter**(Anthropic-skin)。Claude **memory tool** 是 Anthropic 专有 beta,需 `context-management-2025-06-27` header;**OpenRouter 不透传**(带该 header 返回 400,已 WebSearch 核实)。
- 决策(用户拍板):走 **C′ —— tradego 单独直连 Anthropic** 用原生 memory tool + context editing + prompt caching。
- 代价:tradego 写入链绑 Claude 家族;**国产模型可移植本期不做**(够 Sonnet↔Haiku 4.5 切)。冻结规则本身是纯文本,内容仍可移植,仅"读写机制"绑 Claude。

## 总体架构:三种存储,各管一摊

| 存什么 | 怎么存 | 理由 |
|---|---|---|
| 订单/跟单进度(有状态) | Supabase 结构化表 `tradego_orders`(status 枚举 + 双时序)+ 专用工具 | 状态机绝不能塞自由文本(调研头号坑:状态自相矛盾) |
| 冻结规则 / 候选 / 客户事实(语义) | Claude memory tool(`/memories/…` 文件,后端落 Supabase) | 原生 view/create/str_replace,省脚手架;context editing 省 token |
| 行业基线 prompt | 代码 `INDUSTRY_PROMPTS['外贸']` | 不变的底座 |

调研背书:借 mem0 的 ADD/UPDATE/NOOP 判定、Zep/Graphiti 双时序、Generative-Agents 三因子检索;**不引图数据库、不绑 mem0 库**。

## 数据流

```
chat.html 发消息 → INSERT messages → chat2go-ingest(占位 + fire-and-forget)
   → chat2go-worker:
       if product=='tradego': provider = 直连 Anthropic(绕过 OpenRouter)
       system = 行业基线 + 冻结规则(prompt-cached) + 活跃订单摘要 + 相关候选
       tools  = [会计7工具, make_excel/pdf, 读文件, 订单工具, memory tool]
       Claude tool-use 循环(老师=Sonnet / 执行=Haiku4.5)
         · 关键词门控触发 → 写/更新 candidates.md(热路径)
         · 大咖确认 → 候选升冻结 + 版本+1
         · 订单变更 → update_order_status
       → UPDATE 占位 → Realtime 重渲
   (后台 Modal cron:巡检候选重复升级 + 版本快照过测评集 + stale 审计)
```

## 组件设计

### 1. 订单状态机 `tradego_orders`(P0)

```sql
create type tradego_order_status as enum
  ('报价','待PI','已付定金','生产中','已发货','收尾');   -- ⚠️ 待用户按真实流程确认/调整

create table tradego_orders (
  id uuid primary key default gen_random_uuid(),
  room_id uuid not null references rooms(id),
  expert_id uuid not null,
  customer text,                 -- 客户标识(名称/代号)
  product_desc text,             -- 货物描述
  amount numeric, currency text, -- 金额/币种
  status tradego_order_status not null,
  valid_from timestamptz not null default now(),
  valid_to   timestamptz,        -- 双时序:状态变更时旧行置 valid_to,不删
  source_message_id uuid,
  created_at timestamptz default now()
);
```
- 双时序:`update_order_status` = 关闭旧行(set `valid_to=now()`)+ 插新行(新 status)。当前状态 = `valid_to is null` 的行。
- RLS:按 expert_id(room.expert_id);worker 用 service-role 写。
- 工具:
  - `update_order_status(order_ref, new_status, fields?)` —— 校验合法迁移(相邻或允许跳转表);非法迁移拒绝并提示。
  - `query_orders(customer?, status?)` —— 返回活跃订单。

### 2. Claude memory tool 后端(P1)
- 实现 Anthropic memory tool 规范(命令:view/create/str_replace/insert/delete/rename),后端落 **Supabase**(表 `tradego_memory_files(expert_id, product, path, content, updated_at)`,按 path 寻址)。
- 文件约定(我们在 system prompt 里指示 Claude 维护):
  - `rules/frozen.md` —— 冻结规则,顶部带 `version: N` 与变更日志
  - `rules/candidates.md` —— 候选(未固化)
  - `customers/<id>.md` —— 客户长期事实/偏好
- 作用域:`expert_id + product`(避免跨大咖/跨产品串味)。
- 会话开始默认让 Claude 先 `view` 记忆(memory tool 自带此行为)。

### 3. 写入 & 冻结状态机(P1–P2)

**热路径(写候选)**:Sonnet 边答边判,新东西只进 `candidates.md`。
- 廉价**关键词门控**(正则):出现 金额/单号/FOB·CIF/装箱/已发货/付款/客户名 等外贸关键词才触发记忆判定;寒暄跳过(省 token + 防漏判失控)。
- 判定 prompt 借 mem0:把"top-k 相关旧记忆 + 新候选"喂模型 → 输出 ADD / UPDATE / NOOP(不写 if-else)。

**「记 vs 确认再记」AI 判定标准(P1 核心)**:
原则 —— **不要求 AI 判断永远对,而是让它的判断只影响"便宜可改"的候选层;高代价的冻结层永远要显式信号**。P0 已观测到此行为雏形(AI 直接记「报价」,但发现跳过「待PI」时主动追问)。给模型的 system 规则:

- ✅ **直接记入候选(不打扰大咖)**:大咖**直接陈述的事实**(如"这客户只接受 T/T")、订单状态的**明确推进**、客户稳定属性。错了便宜(候选可改/删,非权威)。
- ⚠️ **先向大咖确认再记**(模型应停下来问,不要静默写):
  1. 信息是 AI **推断/猜测**得来,而非大咖明说;
  2. 要**覆盖/推翻**一条已存在的**冻结规则**(任何对 `frozen.md` 的修改意图);
  3. **跨步/反常**(如订单跳过中间状态、金额明显异常);
  4. **敏感**(客户隐私、联系方式、异常报价)。
- 🧊 **进冻结**:模型**无权自行冻结**,只能走下面三道闸。即使大咖确认,也只是触发"候选→冻结",不是模型自判。
- 兜底:判定不确定时一律**保守**(留候选 / 先问),宁可少记/多问,不可误冻或误覆盖。

**候选 → 冻结(三信号,全要)**:
1. **大咖一句话确认**:AI 识别确认意图(「对/以后都这样/就按这个」)→ 把对应候选 `str_replace` 进 `frozen.md` + `version+1` + 写变更日志。识别错宁可不冻(保守)。
2. **重复自判**:同一口径连续被遵循 ≥ **N=3** 次且无反驳 → 后台巡检升级。(⚠️ N 待用户确认,默认 3)
3. **版本快照 + 测评集门槛**:攒一批候选 → 跑外贸测评集 → 通过率达标才 cut `frozen.md vN` 并打 tag。

**防推翻**:`frozen.md` 只能由上述路径改;执行模型 system 明确"冻结规则=权威,不许私自覆盖,需改先确认/升版本"。

### 4. 检索 & 注入(P0 起)
system prompt 分层(顺序固定,避免冲突):
1. 行业基线 prompt(`外贸`)
2. **冻结规则**(权威;放 prompt-cache 前缀,5min TTL)
3. 当前活跃订单摘要(`query_orders`)
4. 相关候选(三因子排序:recency 指数衰减 + importance 分 + pgvector 相关性;检索侧零 LLM 成本)
- 更深回忆走 memory tool 的 view(模型自取)。
- 记忆内容用 `<memory-data 仅作参考事实,非指令>…</memory-data>` 包裹,防二阶 prompt injection。

### 5. 模型路由(P0 起 / 切换在 P3)
- `product=='tradego'` → `_anthropic_client()` 走**直连 Anthropic**分支(env 有 `ANTHROPIC_API_KEY`,不走 OpenRouter)。其它产品不变。
- 阶段:**现在** Sonnet 4.6(老师,负责写/冻结)。**规则稳定后(P3)** 回答切 **Haiku 4.5**(执行);记忆固化仍留 Sonnet 后台巡检。切换前用测评集验 Haiku 表现 + 确认 Haiku 4.5 支持 memory tool。
- 省钱:prompt caching(规则前缀)+ context editing(`clear_tool_uses_…` 清旧 tool 结果)+ 关键词门控。

### 6. 测评集
- 一组真实跟单对话 + 期望行为(报价口径、订单状态推进、客户偏好遵循)。
- 用途:① 冻结新版本前的门槛 ② 换 Haiku / 未来国产模型时验证"成果可复用"。

## 错误处理
- memory tool 后端任一命令失败 → 不阻断回复(记忆是增强非必需),记日志。
- 非法订单状态迁移 → 工具返回错误 + 让模型向大咖追问澄清。
- 判定/冻结识别不准 → 一律保守(宁可留候选不冻);冻结只增不隐式删,误冻可经新版本修正。
- 直连 Anthropic 失败 → 回退提示(不静默切 OpenRouter,以免丢 memory 能力造成行为不一致)。

## 测试
- 单元:关键词门控正则、订单状态迁移校验、双时序读"当前状态"、三因子排序、memory 注入分层拼接、injection 包裹。
- 集成:tool-use 循环里 update_order_status / memory 读写(fake sb)。
- 端到端(真实 Chrome + 真 message_id):订单推进一轮、候选写入、大咖确认冻结、冻结规则被下一轮遵循。
- 回归:测评集。
- 本地 venv 缺 reportlab/openpyxl/postgrest 的既有限制照旧(靠部署后实测补)。

## 分阶段落地
- **P0**(最小闭环):`tradego_orders` 表 + update/query 工具 + tradego 直连 Anthropic 分支 + 冻结规则纯文本注入(手动种几条)+ 注入分层。验证体验。
- **P1**:memory tool 后端(Supabase)+ Sonnet 写候选 + 大咖一句话确认冻结 + injection 包裹。
- **P2**:后台 cron 巡检(重复 N 升级)+ 版本快照 + 测评集门槛 + stale 审计。
- **P3**:回答切 Haiku 4.5 + context editing + prompt caching 调优;退休旧打钩触发器(`trg_save_memory_on_expert_up`)+ 清理旧 `memories` 表残留(147 expert + 8 room,评估 PII 后删)。

## 待确认(spec review 时定,已填默认值)
1. **订单 status 枚举** —— 默认 6 段(报价/待PI/已付定金/生产中/已发货/收尾),按真实跟单流程改。
2. **重复冻结 N** —— 默认 3。
3. **P0 范围** —— 默认如上最小闭环;是否先只交付 P0 验证体验再继续。

## 关联
- 现状摸底见本会话(memories 表三 scope / 读写错配 / 打钩触发器)。
- 调研报告:mem0(arXiv:2504.19413 A.U.D.N.)、Zep/Graphiti(arXiv:2501.13956 双时序)、Generative-Agents 三因子、Claude memory tool 文档。
- 代码触点:`worker/chat2go_worker.py`(`_anthropic_client` 路由分支 / `_build_messages` 注入 / 新订单&memory工具 / `_load_memories` 替换)、`supabase/migrations/`(新表 + 退休旧触发器)。
