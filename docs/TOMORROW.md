# 明天的议题：Chat2GO · Hermes 版本规划

> 目的：把今天 Claude 直连版本进化成 Hermes 驱动版本，让专家的本地能力（skills / tools / memory / soul.md）真正接进 Chat2GO 调试室。

---

## 起点状态（v0.1-demo 已交付）

- bridge.py 当前走 `--ai-mode claude` → 直连 Anthropic API
- bridge.py 已预留 `--ai-mode hermes` 分支，但 Hermes session ID 命名问题未解决
- Hermes 在本地正常运行（`hermes chat` 可用）

---

## 明天要决定的关键问题

### 1. 部署形态
- **方案 A**：每个专家本地跑 bridge.py + Hermes（隐私好，门槛高）
- **方案 B**：把 Hermes 部署到平台云端（Linux server / fly.io），bridge 在云端跑（无门槛，专家失去本地控制）
- **方案 C**：混合——bridge 云端跑，Hermes 既支持「本地专家自托管」也支持「平台托管」

### 2. Hermes 集成方式
- **方案 A**：保留 subprocess `hermes chat` 模式，解决 session 命名问题（用 `hermes sessions list` + 文件名映射，或纯 stateless）
- **方案 B**：导入 Hermes 的 `AIAgent` 类，进程内调用（更快，但耦合 Hermes 内部 API）
- **方案 C**：作为 Hermes 原生平台插件 `gateway/platforms/chat2go.py`（最干净，按 ADDING_A_PLATFORM.md 7 步走）

### 3. 模型 / 凭据归属
- **方案 A**：专家自己的 `~/.hermes/config.yaml` 决定用哪个模型，专家自掏 API 费
- **方案 B**：平台统一模型，向小白计费，分成给专家
- **方案 C**：双轨制（专家可选）

---

## 明天预期产出

1. **决策记录**：上面 3 个问题的拍板答案，写进 `docs/HERMES_PLAN.md`
2. **技术架构图**：bridge ↔ Hermes ↔ Supabase 三方关系图
3. **迁移步骤清单**：从 v0.1（Claude 直连）→ v0.2（Hermes 驱动）的具体改动列表
4. **第一周任务**：可立即开干的小颗粒度任务

---

## 准备工作（可选，今晚做）

如果想加速明天进度，今晚可以先：

- [ ] 想清楚 #1 部署形态偏好（影响后续一切）
- [ ] 看一遍 `~/.hermes/hermes-agent/gateway/platforms/ADDING_A_PLATFORM.md`（5 分钟）
- [ ] 在 Hermes 里跑一两个 skill，体会下 skill 系统（`hermes skills list`）

---

## 复用的现有资料

- `docs/AGENT_DESIGN.md` — 已有的 8 模块整体架构，Hermes 版本是其中一种实现
- `bridge.py` 里的 `call_hermes()` 函数 — 已实现 subprocess 模式，明天可以基于这个继续
- v0.1-demo tag — 任何时候可以回滚的稳定版本

---

*起来后说一声「开始 Hermes 规划」就接着这份文档继续。*
