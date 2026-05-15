# 明天的议题：Chat2GO.ai 自有 Agent 设计

> **决策已定（2026-05-09）：Chat2GO.ai 必须有自己的本地 Agent。不依赖 Hermes，不 fork Hermes，自己造。**
>
> 理由：marketplace 是核心商业模式，AI 引擎是壁垒，必须 100% 自己掌控。Hermes 的好思路（skills / tools / memory / soul / 自学习）作为参考，不作为依赖。

---

## 起点状态（v0.1-demo）

- `bridge.py` 当前直连 Anthropic API（claude 模式可用）
- `bridge.py` 里的 `call_hermes()` 子进程模式 → **明天起标记为废弃**，作为参考实现保留
- Hermes 在本地装着，明天起**只作为参考样本**研究它的设计，不调用它

---

## 明天要拍板的关键问题（自研版）

### 1. Agent 部署形态
- **A**：每个大咖自己电脑跑 Agent + bridge（大咖本地资源 / 隐私好 / 门槛高）
- **B**：平台云端跑 Agent，大咖无需安装（无门槛 / 平台承担成本）
- **C**：混合——免费大咖用云端版本，付费大咖可选本地自托管（更强能力 / 数据自主）

> **倾向**：先做 B（云端）让 demo 跑通，预留 A 接口。

### 2. Agent 进程边界
- **A**：Agent 就是 `bridge.py` 的一部分（一个进程，简单）
- **B**：Agent 作为独立进程 / 独立服务，bridge 通过 HTTP/stdio 调用（解耦，可独立升级）
- **C**：Agent 作为可被任何前端调用的 OpenAI-compatible API（最通用，但 over-engineering）

> **倾向**：先做 A（合在 bridge 里）。等 Agent 复杂到 1500 行 Python 时再拆。

### 3. 语言 / 框架
- **A**：纯 Python，无外部 agent 框架（最直接，全部自己写）
- **B**：用 LangGraph / LlamaIndex / Pydantic AI 等开源框架做骨架
- **C**：用 Claude Agent SDK（`@anthropic-ai/sdk` 的 agent 模式）

> **倾向**：A，自己写 600 行。框架增加学习成本和锁定风险。

### 4. Agent 的最小核心能力（v0.2 范围）
必做（v0.2）：
- [ ] **Skills 注册系统**（行业能力包：合同 / CRM / 报告）
- [ ] **Tool 调用**（function calling）：file_extract / pdf_export / web_search
- [ ] **Room 级长期 memory**（rooms_memory 表，跨会话记客户偏好）
- [ ] **Multi-model router**（按任务复杂度选 sonnet / haiku / 本地模型）

可延后（v0.3+）：
- 知识库 RAG
- 大咖纠正自动学习
- 图片 OCR / 语音转写
- Skills 市场（大咖间分享）

---

## 明天预期产出

1. **`docs/CHAT2GO_AGENT.md`** —— 自研 Agent 完整设计文档（替代之前 Hermes 集成方向）
2. **核心 API 草稿** —— Agent class 的 Python 接口签名（哪些方法、什么参数）
3. **目录结构** —— `chat2go/agent/`、`chat2go/skills/`、`chat2go/tools/` 怎么组织
4. **第一个 sprint 任务清单** —— 可立刻开干的颗粒度

---

## 设计原则（提前定，明天对齐）

1. **简单优先**：能用 100 行写完就不写 500 行
2. **数据所有权清晰**：每个 skill / memory / KB 必须知道归谁所有（大咖 / 房间 / 平台）
3. **可调教 > 全自动**：宁可大咖手动改 prompt，也不要做猜不准的"智能"
4. **可观测**：每次 AI 决策的输入、输出、用了哪个模型 / skill / tool 都要记录（model_usage 表）
5. **接口稳定**：API 一旦发布，老 skill 永远能跑

---

## 起来后怎么继续

> 跟我说一句「**开始 Chat2GO.ai Agent 设计**」，我接着这份文档继续：
>
> 1. 先帮你过一遍上面 4 个拍板问题
> 2. 把决定写进 `CHAT2GO_AGENT.md`
> 3. 列出第一周可以立刻动手的任务

---

## 备忘

- v0.1-demo tag 是稳定版回滚点
- 现在 `bridge.py` 全量保留，v0.2 在它基础上长出 agent/ 子模块
- Hermes 本地装着，需要时随手 `hermes skills list` 看看人家怎么做某个能力
