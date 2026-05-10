# Chat2GO Agent 设计文档

> 版本：v0.1（设计阶段）
> 日期：2026-05-09
> 作者：lirui88888862@gmail.com（chat2go.cn 主理人）

---

## 0. TL;DR

**Chat2GO Agent 是一个 marketplace 专用 AI agent，不追求 Hermes 的「啥都能干」，而追求「专家的行业能力 → AI → 小白」这一条链路最短最稳。**

核心特性（继承 Hermes 但重构）：

| Hermes 能力 | Chat2GO 落地 | 改动点 |
|------------|-------------|-------|
| 自学习完善 md | 专家纠正 → 自动沉淀到 skill md | 增加「双 AI」链路（主答 + 学习） |
| 多模态工具箱 | 文件 / 图片 / PDF / OCR / Web / KB | 工具列表精简，行业向 |
| 快速切换大模型 | Router by task complexity + room.model | 加成本/性能维度的自动路由 |
| 知识库 | 专家上传 → pgvector → RAG | Supabase 原生，无独立服务 |

---

## 1. 整体架构

```
┌──────────────────────────────────────────────────────────────────┐
│                       Chat2GO Web UI                              │
│   (chat.html / login.html  ←  Supabase Auth + Realtime)          │
└──────────────────────────────────────────────────────────────────┘
              ↑                                ↓
              │ Realtime 推送                  │ 写消息 / 读历史
              │                                │
┌──────────────────────────────────────────────────────────────────┐
│                       Supabase 数据层                              │
│   rooms / messages / attachments / skills / lessons / kb_chunks   │
└──────────────────────────────────────────────────────────────────┘
              ↑                                ↑
              │ Realtime 订阅                  │ pgvector 检索
              │                                │
┌──────────────────────────────────────────────────────────────────┐
│            Chat2GO Agent Bridge (本地 / 云端 都可)                  │
│  ┌────────────┐ ┌──────────┐ ┌─────────┐ ┌────────────────────┐ │
│  │ Realtime   │→│ Planner  │→│ Router  │→│  Executor          │ │
│  │ Listener   │ │          │ │         │ │  (LLM + Tools)     │ │
│  └────────────┘ └──────────┘ └─────────┘ └────────────────────┘ │
│                       ↓             ↓               ↓             │
│                   Skills 库     Model 池        Tools 工具箱      │
│                   ────────     ────────        ──────────        │
│                   合同生成     claude-3-5       file_read         │
│                   报告输出     claude-haiku     pdf_export        │
│                   CRM 更新     gpt-4o-mini      ocr_image         │
│                   ...          deepseek         web_search       │
│                                qwen-local       kb_query          │
└──────────────────────────────────────────────────────────────────┘
              ↑
              │ 异步学习
              │
┌──────────────────────────────────────────────────────────────────┐
│                  Learner（学习子 agent）                           │
│   监控专家纠正 → LLM 总结 → 写回 skill.lessons.md                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. 数据模型

### 2.1 现有表（已建）

```sql
rooms (
  id, name, industry, expert_id, status, created_at,
  model         text default '',         -- 房间级模型覆盖
  system_prompt text default ''          -- 房间级专家指令
)

messages (
  id, room_id, user_id, role, content, created_at,
  type        text default 'text',       -- text | markdown
  attachments jsonb default '[]'         -- [{name, url, size, mime_type}]
)

storage.buckets: chat-uploads (public)
```

### 2.2 新增表（本设计文档核心）

```sql
-- Skills 库（行业能力包）
create table skills (
  id            uuid primary key default gen_random_uuid(),
  name          text not null,           -- "外贸合同生成"
  industry      text not null,           -- "外贸"
  expert_id     uuid references auth.users(id),
  description   text,                    -- 这个 skill 干啥
  system_prompt text,                    -- 加载该 skill 时注入的人设
  triggers      jsonb default '[]',      -- ["合同", "contract", "..."]
  templates     jsonb default '[]',      -- [{name, content}, ...]
  is_public     boolean default false,   -- 是否对其他专家可见
  created_at    timestamptz default now()
);

-- 房间启用了哪些 skills
create table room_skills (
  room_id  uuid references rooms(id) on delete cascade,
  skill_id uuid references skills(id) on delete cascade,
  primary key (room_id, skill_id)
);

-- Lessons：专家纠正 AI 后自动学到的规则
create table lessons (
  id           uuid primary key default gen_random_uuid(),
  room_id      uuid references rooms(id) on delete cascade,
  skill_id     uuid references skills(id),  -- 可关联到 skill，也可只对房间生效
  rule         text not null,                -- "瓷砖出口墨西哥默认走 CIF 不是 FOB"
  source_msg_ids uuid[],                     -- 触发学习的消息 IDs
  created_at   timestamptz default now()
);

-- 知识库切片（RAG）
create extension if not exists vector;
create table kb_chunks (
  id          uuid primary key default gen_random_uuid(),
  expert_id   uuid references auth.users(id),
  source_name text,                          -- "墨西哥关税手册2025.pdf"
  content     text not null,
  embedding   vector(1536),                  -- OpenAI ada-002 维度
  metadata    jsonb default '{}',            -- {page, chapter, ...}
  created_at  timestamptz default now()
);
create index on kb_chunks using ivfflat (embedding vector_cosine_ops);

-- 模型使用统计（计费用）
create table model_usage (
  id           uuid primary key default gen_random_uuid(),
  room_id      uuid references rooms(id),
  message_id   uuid references messages(id),
  model        text,
  input_tokens int,
  output_tokens int,
  cost_usd     numeric(10, 6),
  created_at   timestamptz default now()
);
```

---

## 3. 八个模块详细设计

### 3.1 模块一：专家纠正自动沉淀（Lessons）★ 优先级最高

#### 3.1.1 触发逻辑

每当 bridge 收到 `role = 'expert'` 消息时，**异步**调用 Learner 子 agent：

```
背景：刚才小白问 X，AI 答了 Y
现在专家说：Z
请提取「专家想纠正 AI 的规则」，1-2 行简洁描述。
如果专家只是聊天/澄清，不是纠正，输出 NULL。
```

#### 3.1.2 写回路径

| 适用范围 | 写到哪 | 何时使用 |
|---------|-------|---------|
| 仅本房间 | `rooms.system_prompt` 追加 | 默认 |
| 整个 skill | `lessons` 表 + skill 重新生成时合并 | 专家点「保存到 skill」按钮（未来 UI）|

#### 3.1.3 用户体验

专家发了纠正消息后，几秒后看到一条小提示：

```
✓ 已学到："瓷砖出口墨西哥默认走 CIF 不是 FOB"
```

下次小白问类似问题，AI 直接按新规则回答。

#### 3.1.4 实现成本：约 200 行 Python

---

### 3.2 模块二：PDF 真出 PDF（不只是 Markdown）★ 优先级高

#### 3.2.1 现状

AI 输出 Markdown 合同 → html2pdf.js 在浏览器把 HTML 转 PDF。问题：
- 中文字体支持差（要嵌入字体）
- 没法加印章/签名行
- 排版不专业

#### 3.2.2 新方案

bridge 检测到 AI 输出是合同/报告类时：
1. 用 Python `weasyprint` / `reportlab` 服务端生成 PDF
2. 上传到 `chat-uploads` bucket
3. 把 PDF URL 写进 message 的 attachments
4. 网页消息气泡里直接出现「📄 销售合同_2026-05-09.pdf」可点击下载

#### 3.2.3 模板结构

```
~/chat2go/pdf_templates/
├── contract_default.html     # 默认合同 HTML 模板（包含中文字体引用）
├── contract_default.css
├── stamp_placeholder.png     # 印章占位
└── signature_block.html
```

#### 3.2.4 实现成本：约 300 行 Python + 几个 HTML 模板

---

### 3.3 模块三：知识库 RAG ★ 优先级高（壁垒）

#### 3.3.1 上传流程

专家在「专家面板」（未来 UI）上传文件 → bridge 后台：

1. 用 pypdf / python-docx 提取全文
2. 切片（按段落 / 按 1000 字符 + overlap 200）
3. 调 OpenAI text-embedding-3-small 向量化
4. 写入 `kb_chunks`（带 expert_id）

#### 3.3.2 检索流程

每次小白发消息：
1. 用 embedding 模型把问题向量化
2. `select * from kb_chunks where expert_id = ? order by embedding <=> $1 limit 3`
3. 把 top-3 chunks 内容拼进 system context

#### 3.3.3 关键设计：知识所有权

```
expert_id = 张老师 → 张老师的知识库
expert_id = 林教练 → 林教练的知识库
小白进入「张老师的调试室」时，AI 只能看到张老师的知识库
```

这是 Chat2GO 商业模式的核心：**专家的私有知识 = 他的资产**。

#### 3.3.4 实现成本：约 400 行 Python + Supabase 加 pgvector 扩展

---

### 3.4 模块四：Multi-Model Router

#### 3.4.1 路由策略

```python
def route_model(query, attachments, history, room):
    # 1. 房间锁定优先
    if room.model:
        return room.model

    # 2. 多模态强制视觉模型
    if any(a.mime_type.startswith("image/") for a in attachments):
        return "claude-sonnet-4-5"  # 视觉

    # 3. 简单问候/确认
    if len(query) < 20 and not attachments:
        return "claude-haiku-3-5"   # 便宜快

    # 4. 复杂任务关键词
    if any(kw in query for kw in ["合同", "报告", "方案", "策略"]):
        return "claude-sonnet-4-5"

    # 5. 默认中等模型
    return "claude-sonnet-4-5"  # 也可以用 haiku 省钱
```

#### 3.4.2 成本估算（每月 1000 个房间，每房 50 条消息）

| 当前（全用 sonnet）| Router 后（70% haiku, 30% sonnet）| 节省 |
|----|----|----|
| ~$2400/月 | ~$900/月 | 62% |

#### 3.4.3 实现成本：约 100 行

---

### 3.5 模块五：图片 OCR

小白拍合同照片 → AI 识别文字 → 复用现有附件文本流程。

实现：用 Claude Vision 自带 OCR 能力，or 接入腾讯云 OCR API（中文更准）。

#### 实现成本：约 100 行（Claude Vision 0 行——已支持，只需提示）

---

### 3.6 模块六：Web 搜索

小白问「最新汇率」「最新政策」时调用。

实现：接入 Tavily / SerpAPI / Bocha（国内）的 search API，结果作为 tool 输出。

#### 实现成本：约 200 行 + 一个 API key

---

### 3.7 模块七：语音转文字

小白长按录音 → 上传 MP3 → bridge 调 Whisper API → 转文字 → 当作普通消息处理。

#### 实现成本：约 150 行（前端录音 + 后端 Whisper）

---

### 3.8 模块八：Skills 系统重构

把上面所有能力包装成统一接口。一个 skill 包含：

```yaml
# skills/contract-generation/skill.yaml
name: 合同生成
industry: 外贸
description: 根据小白需求和模板，生成 markdown + PDF 合同
triggers:
  - 合同
  - contract
  - 起草
required_tools:
  - kb_query
  - pdf_export
templates:
  - 销售合同.md
  - 服务合同.md
system_prompt: |
  你是合同生成专家。优先使用 templates 里的格式...
lessons:
  - 瓷砖出口墨西哥默认走 CIF 不是 FOB（@expert lirui88888862, 2026-05-09）
```

Bridge 启动时扫描所有 skills/ 目录，注册到内存。Planner 看小白消息 → 决定用哪个 skill → 加载 system_prompt + templates + lessons。

#### 实现成本：约 500 行（统筹）

---

## 4. 实施阶段

### Phase 1（MVP，2 周）：可演示的最小闭环

```
✅ 已完成：基础聊天、上传、Claude 直连
□ 模块 1：专家纠正自动沉淀
□ 模块 2：PDF 真生成
□ 模块 4：Multi-model router（最简版）
```

**Phase 1 出来的产品演示价值：** 专家给小白做合同 → 小白要 PDF → 专家说"违约金改 10%" → 下次自动按新规则。

### Phase 2（3 周）：壁垒成型

```
□ 模块 3：知识库 RAG
□ 模块 8：Skills 系统重构
```

**Phase 2 价值：** 专家上传整套行业资料 → AI 用专家知识精准回答 → 这是 Chat2GO 的真实差异化。

### Phase 3（2 周）：体验完善

```
□ 模块 5：图片 OCR
□ 模块 6：Web 搜索
□ 模块 7：语音转文字
```

### Phase 4（持续）：运营 / 商业化

- 模型计费（model_usage 表）
- 专家收益分成
- 知识库公开市场（专家可购买/订阅别的专家的知识库）
- 多语言（出海）

---

## 5. 与 Hermes 的关键差异回顾

| 维度 | Hermes | Chat2GO Agent | 为何不同 |
|------|--------|---------------|---------|
| 部署 | 每用户本地 | 云端 bridge | 小白不会装 CLI |
| 上下文 | 本地 sessions | Supabase rooms | 多人共享 / 跨设备 |
| 学习 | 用户改 md | **专家纠正自动学** | marketplace 自带反馈循环 |
| 知识 | 各种 search skill | **专家私有 KB** | 知识 = 专家资产 |
| 工具范围 | 通用（git/web/...）| 行业垂直 | 不需要那么多 |
| 计费 | 用户自己 API | **平台向小白计费** | 商业模式 |
| 多模型 | config 切换 | **task-aware 自动路由** | 省钱 |

---

## 6. 风险 & 决策点

| 风险 | 应对 |
|------|------|
| 专家自学习写错规则 | UI 上让专家审核 lessons，可一键回滚 |
| 知识库被专家"窃取"（爬虫导出）| 行级 RLS + 查询频率限制 + 不返回 raw chunk，只通过 AI 转述 |
| API 成本失控 | model_usage 表 + 每房间月度上限 |
| Realtime 断线 | bridge 已有轮询兜底 |
| 单专家学习污染 skill | lessons 默认仅房间级，专家手动晋升才进 skill |

**关键决策（待定）：**
1. **Bridge 部署模型**：每个专家本地跑？还是平台统一云端？（影响隐私/成本/稳定性）
2. **API Key 归属**：专家自带（更便宜，专家承担成本）？还是平台统一（更可控，平台向小白收费）？
3. **知识库粒度**：按 expert 隔离？还是按 room 隔离？

---

## 7. 下一步

如果按 Phase 1 启动，**第一个 sprint** 推荐顺序：

```
Day 1-2:  模块 4 (Router)         — 最快出效果，省成本立即可见
Day 3-5:  模块 1 (Lessons)        — 核心差异化
Day 6-9:  模块 2 (PDF)            — 演示亮点
Day 10:   集成测试 + 部署
```

**问题给自己回答：**
- 商业模式怎么收钱？（按 token 抽成？月费？知识库订阅？）
- 第一批种子专家怎么找？（自己当专家先 demo？拉熟人？）
- chat2go.cn 现在是 GitHub Pages，扛得住几百小白同时在线吗？（不行，要换 Vercel / Cloudflare Pages）

---

*本文档随实现进度持续更新。每完成一个模块，对应章节加入「实现笔记」段落，记录踩坑和决策变更。*
