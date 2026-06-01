# Trade2GO 记忆系统 · Anthropic 天花板版(混合制)— 设计

- 日期:2026-06-01
- 状态:设计稿(待用户复核 → 再进 writing-plans)
- 产品:**Trade2GO**(品牌名);代码 slug 保持 `tradego` 不变(`rooms.product='tradego'`、repo `tototo1999/tradego`)
- 后端:`worker/chat2go_worker.py` + `worker/trade_memory.py`(Modal)

---

## 1. 背景与目标

Trade2GO 的本质不是"做表格",而是**高度多线程、碎片化的有状态跟单工作流**:很多合同/发货并行推进(报价→合同→定金→生产→提货→发货→尾款→收款),输入碎片化(今天 A 付定金、明天 B 货到港、后天催 C 尾款),每次状态/单据都要被智能接住、归到对的合同线、需要时主动调出。

**战略:先摸天花板,再 A/B 找优。** 本设计用 Anthropic 顶配(Opus 4.8 + 原生 agentic memory + 全套 beta)把这类工作能做到的**能力上限**建出来并量化,作为后续(约 2026-07,真实业务流程跑够后)与更便宜/可移植方案做 A/B 的**标尺**。**本阶段不为可移植性砍能力。**

## 2. 核心决策(已与用户拍板)

- **架构 A — 混合制,全 Anthropic**:钱与状态用**确定性账本**(DB + Decimal 工具)兜底,绝不漂;软智能用 **Anthropic 原生 agentic memory**。"确定性"不是另一个 AI,是数据库格子 + 几行代码,所以"全 Anthropic"成立、智能不打折。
- **为什么钱不能进自由文本记忆**:纯文本记忆维护精确财务态有 5 个漏点——誊写/读串、跨合同记串、半更新不一致、无校验、自算错。顶级模型只压低概率、消不掉;外贸里一个尾款数字错就是真金白银损失。故钱的真值存 DB,模型经工具读写、代码算账有校验。
- **粒度先简单**:**合同级**起步(长在现有 `tradego_orders`),发货批次级 later、真实跑过再优化。

## 2.1 为什么至今没用原生 memory tool(已取证)
**不是"用不上",也不是"被记忆锁住"——是"设计里要用,但 P1 后端从未实现"。** 证据:
- worker + `trade_memory.py` grep `memory_2025`/`context_management`/`client.beta` **零命中**;现在的 `remember` 是**普通自定义工具 + 文本注入**,不是原生 memory tool。
- "冻结规则"只是 `tradego_memory_rules` 的 `status='frozen'` 字段(当文本注入),**不是锁**。
- DB 现存 `tradego_orders` + `tradego_memory_rules`,**无 `tradego_memory_files`**(P1 该建的 memory 文件后端表)。
- 最初的真障碍(OpenRouter 不透传 memory beta,返回 400)**已被 C′ 直连搬掉**:`force_direct=True` 已在跑。
- 结论:前置已就位、P1 已解锁,但**那块后端一行没建**。**本天花板版 = 把这块欠着的 P1 真正建出来。**

## 3. 架构:两层

### ① 确定性账本层 —— 钱与状态的唯一真值
- 复用并扩展现有 `tradego_orders`(状态机 + 双时序已存在),**合同级**。
- 持有:合同/客户/产品、总额/定金/尾款/应收应付、阶段(报价→合同→定金→生产→提货→发货→尾款→收款)、合法转移校验、双时序(业务时间 vs 录入时间)。
- 模型**只能经确定性工具**读写,钱绝不进自由文本:
  - `update_order_status` / `query_orders`(已存在,`trade_memory.py`)
  - Decimal 会计工具(`trade_accounting.py`:calc_unit_cost/quote_from_margin/order_pnl/fx_convert/export_rebate/commission/reconcile)负责**所有算术**。
- 校验:拒绝非法状态(余额变负、未发货先收款等非法转移)。

### ② Anthropic agentic memory 层 —— 软智能
- **新增**:Anthropic 原生 memory tool `memory_20250818`(客户端工具,模型自主 view/create/str_replace/insert/delete/rename)。
- **后端持久化到 Supabase**(跨周/月不丢,按 room/expert 隔离)——新建一张 memory store 表实现该工具的文件读写后端。
- 持有(**无唯一真值的东西**):客户偏好、沟通历史、把碎片更新归到对的合同线的线索、"该催谁尾款"这类待办上下文。
- 模型自由组织(如每客户一份笔记 + 一个工作索引)。
- **取代现状**:现在 `trade_memory.py` 把软规则当**静态文本每轮注入**;本设计把软层升级为 agentic memory(模型自管),账本层(订单/规则的硬态注入 + 工具)保留。

## 4. 模型 / 系统配置(= "天花板")

- **Opus 4.8**(`claude-opus-4-8`)—— 从现 `claude-sonnet-4-6` 升顶。
- **adaptive thinking + 高 effort**。
- **context-management / compaction beta** —— 扛跨周长历史(具体 beta header 在 plan 阶段用 claude-api skill 核定)。
- **直连 Anthropic**(已有 `force_direct=True`)—— memory tool + 这些 beta **OpenRouter 不转发**,必须直连。
- **prompt caching**(已上线)—— 缓存 system + tools 前缀。

## 5. 数据流(碎片如何流转)

1. 大咖发碎片更新("A 付了 30% 定金""B 货到深圳港")。
2. 模型识别属于哪个合同(agentic)。
3. **硬事实**经确定性工具写入账本(精确、校验)。**软上下文**写入 agentic memory。
4. 后续提问/推进时:模型读**账本**(准数字/阶段)+ 读 **memory**(偏好/历史/待办)作答。
5. 主动能力:交互时浮现"D 合同尾款到期该催了"(定时 cron 主动推送 = later)。

## 6. 钱安全不变量(贯穿全设计)
- 钱的唯一真值 **只在 DB**,**永不进自由文本记忆**。
- 一切算术经 Decimal 工具,模型不凭脑子算。
- 账本写入有合法性校验;agentic memory 只存无唯一真值的软信息。

## 7. 评测语料采集 + 怎么量天花板(本阶段产出)

### 7.1 Trace 采集(关键 — 用户明确要求,A/B 回放的命脉)
**天花板这版就开始把每条真实外贸房请求结构化落库**,作为将来换模型的**回放语料**。
- **为什么不靠 Modal 日志**:`modal app logs` 是流式、**保留期有限、非结构化**,一个月后大概率滚掉/查不全,无法可靠回放。
- **新建表 `trade_eval_traces`**(Supabase),每条真实请求落一行:
  - `room_id` / 触发 `message_id` / 时间戳 / `model`
  - **输入快照**:注入的 system、history、memory 当时状态(够还原现场)
  - **tool-use 全序列**:每个工具名 + 入参 + 返回(会计/账本/memory/文档)
  - **对应系统触发链**:ingest→worker→工具→DB 写 的关键节点
  - **最终输出** + `usage`(含 cache_read/write/in/out)
- **隐私/边界**:含真实业务数据,按 room/expert 隔离、仅内部评测用;敏感字段按需脱敏。

### 7.2 衡量天花板
- 跑**真实多合同场景**(优先回放 7.1 采集的真实 trace;不足则造贴近真实的多合同碎片剧本)。
- 指标:(a)**钱/状态对真值的错误率**(账本应≈0,验证不变量);(b)**软智能人评**(碎片归线准确度、历史调取、主动提醒质量)。
- 该分数 = 后续 A/B 的**标尺**。

### 7.3 A/B 回放(将来换模型)
把 7.1 的真实输入**原样喂给候选模型**(Kimi/DeepSeek/Sonnet vs 本 Opus 顶配),diff:输出质量、tool-use 是否一致、钱/状态准确率、成本。得出"换模型损失多少"的硬数据。

## 8. 边界 / YAGNI(先跑后优化)
- 合同级起步;发货批次级 later。
- 主动提醒先"交互时浮现";定时 cron later。
- agentic memory 的文件组织交给模型,不预设硬 schema。

## 9. 可移植性说明(对接后续 A/B)
- 本版是 **Anthropic 天花板**,刻意用 Anthropic 专属能力(memory tool / compaction beta,直连)。
- **账本层 + 会计工具 = 模型无关,100% 可移植**。
- **agentic memory 层 = Anthropic 专属**;A/B 时若换模型,该层需用自定义工具重写(能力可复刻,行为质量可能降)——这正是 A/B 要量的差距。
- 详见 `docs/TRADE2GO-CN-MODEL-RESERVE-PLAN.md`。

## 10. 风险与对策
| 风险 | 对策 |
|---|---|
| agentic memory 把钱记错 | 钱不进 memory,只进账本(本设计核心) |
| 跨合同记串 | 模型识别合同 → 写账本时带合同 id 校验;memory 出错不影响钱 |
| 长历史爆 context | compaction beta + prompt caching |
| memory tool 后端没实现 | 本设计的主要新建工作量:Supabase 后端实现 view/create/str_replace 等 |
| Opus 4.8 成本高 | 天花板阶段可接受;A/B 阶段比成本 |

## 11. 开放/延后(不阻塞本设计)
- 发货批次级账本、定时 cron 主动催款、memory 后端的精确表结构、真实回放数据来源 —— 留到 plan 或真实跑后定。

---
关联:[[2026-06-01-trade2go-记忆系统-design]](P0 现状)· `worker/trade_memory.py` · `worker/trade_accounting.py` · `docs/TRADE2GO-CN-MODEL-RESERVE-PLAN.md`
