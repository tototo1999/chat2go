# Chat2GO.ai — 项目上下文

## 项目定位

Chat2GO.ai 是一个 AI marketplace 平台：**行业大咖 × AI × 小白用户**。大咖在「Chat 调试室」里陪小白把需求说清楚、演示 AI 能力，然后交付一个小白可以独立使用的专属 AI 助手（Go 交付室，尚未开发）。

域名：chat2go.ai（GitHub Pages 托管静态页面）

## 技术栈

- **前端**：纯 HTML/CSS/JS，无框架。三个页面：`index.html`（落地页）、`login.html`（登录/注册）、`chat.html`（调试室主界面）
- **后端 / 数据**：Supabase（PostgreSQL + Auth + Realtime + Storage）
- **AI Bridge**：`bridge.py`（Python asyncio），本地运行，通过 Supabase Realtime 订阅消息 → 调 Claude API → 写回 AI 回复
- **AI API**：Anthropic Claude（bridge.py 直连），默认 claude-sonnet-4-5
- **Edge Function**：`supabase/functions/chat-ai/index.ts`（Deno，备用的服务端 AI 调用，目前主要用 bridge.py）
- **JS 依赖**：本地化到 `vendor/`（supabase-js, marked.js, html2pdf.js），CDN 作 fallback
- **Python 依赖**：supabase, httpx, certifi, pypdf, python-docx（在 .venv 中）

## 数据库结构

```sql
rooms (id, name, industry, expert_id, status, model, system_prompt, created_at)
messages (id, room_id, user_id, role, content, type, attachments, created_at)
-- role: 'user' | 'expert' | 'ai'
-- type: 'text' | 'markdown'
-- attachments: jsonb [{name, url, size, mime_type, storage_path}]

storage.buckets: chat-uploads (public)
```

RLS 策略：所有人可读 rooms/messages，登录用户可发消息/建房，大咖可改自己的房间。

## 已完成功能（v0.1 demo）

1. **落地页** — 7 个行业场景展示，Chat→Go 双阶段流程说明
2. **邮箱登录/注册** — Supabase Auth，Demo 快捷登录（大咖/小白各一个账号）
3. **调试室 CRUD** — 左侧栏列表，新建调试室（选行业）
4. **三方实时对话** — 小白/大咖/AI 三色区分（黄/绿/紫），飞书风消息布局
5. **AI 响应** — bridge.py 通过 Realtime 监听 → Claude API → 写回（对 user 和 expert 消息都响应）
6. **文件上传** — 支持 txt/md/pdf/docx/csv/json/html/xml/图片，上传到 Supabase Storage
7. **AI 读文件** — bridge.py 下载附件、提取文本（PDF/DOCX/文本），拼入 context
8. **AI 看图** — Claude Vision，图片 URL 直接传给 API
9. **Markdown 渲染** — AI 输出自动检测 markdown，渲染为格式化内容
10. **PDF 导出** — 浏览器端 html2pdf.js，AI 的 markdown 输出可导出 PDF
11. **语音输入** — Web Speech API，浏览器原生中文实时识别
12. **复制按钮** — hover 出现，base64 编码绕过 HTML 转义问题
13. **行业 system prompt** — 6 个行业各有专属 prompt（外贸/健身/地产/教育/量化/医疗）
14. **大咖 system prompt** — 房间级别可配置（bridge.py set-prompt 命令）
15. **bridge 轮询兜底** — 每 5 秒轮询防 Realtime 断线漏消息
16. **SSL 证书修复** — Homebrew Python + certifi 兼容
17. **术语重命名** — 专家 → 大咖（UI 层面，数据库 role 字段保持 `expert` 不变）

## 关键技术决策

1. **自研 Agent，不依赖 Hermes** — bridge.py 里的 `call_hermes()` 保留为参考实现，实际走 `call_claude()` 直连
2. **纯静态前端** — 无 React/Vue，GitHub Pages 直接部署，CDN 不可靠所以 JS 库本地化到 vendor/
3. **bridge.py 本地运行** — 大咖在自己电脑跑（未来考虑云端统一部署）
4. **supabase 变量命名为 `sb`** — 避免与 UMD 全局 `supabase` 变量冲突（踩过坑）
5. **文件名清洗** — 上传时把中文文件名转为 ASCII，Supabase Storage 对非 ASCII 路径会 400
6. **AI 消息永远显示「AI 助手」** — 不管 user_id 是谁写入的（因为 bridge 用大咖账号写 AI 消息）

## 踩过的坑

- Supabase JS UMD 包会注入全局 `supabase` 变量，如果本地变量也叫 `supabase` 会冲突
- 中文文件名上传 Supabase Storage 返回 400，必须清洗为 ASCII
- Homebrew Python 的 SSL 证书路径不对，websocket 连接会失败，需要 certifi 修复
- CDN（jsdelivr 等）在国内不稳定，JS 依赖需要本地化
- AI 消息显示「我」的 bug：bridge 用大咖账号的 user_id 写入 AI 消息，前端判断 isOwn 时会误判

## 未完成的任务 / 下一步计划

### Phase 1（MVP）— 最优先

- [ ] **大咖纠正自动沉淀（Lessons）** — 大咖发消息纠正 AI → Learner 子 agent 提取规则 → 写回 room/skill
- [ ] **PDF 真生成** — 服务端用 weasyprint/reportlab 生成专业 PDF（替代浏览器端 html2pdf）
- [ ] **Multi-model Router** — 按任务复杂度自动选 sonnet/haiku，预计省 60% 成本

### Phase 2 — 壁垒成型

- [ ] **知识库 RAG** — 大咖上传行业资料 → pgvector 向量化 → 检索增强（大咖私有知识 = 资产）
- [ ] **Skills 系统** — 行业能力包（合同生成/CRM/报告），skill.yaml + triggers + templates + lessons

### Phase 3 — 体验完善

- [ ] **图片 OCR** — 用 Claude Vision 或腾讯云 OCR
- [ ] **Web 搜索** — 接入 Tavily/SerpAPI，实时信息查询
- [ ] **语音转文字（服务端）** — 上传录音 → Whisper API 转写

### Phase 4 — 商业化

- [ ] **Go 交付室** — 小白独立使用 AI 的私人空间
- [ ] **模型计费** — model_usage 表，按 token 计费
- [ ] **大咖收益分成**
- [ ] **部署迁移** — GitHub Pages → Vercel/Cloudflare Pages（扛并发）

## 目录结构

```
chat2go/
├── index.html              # 落地页
├── login.html              # 登录/注册
├── chat.html               # 调试室主界面（核心）
├── bridge.py               # AI Bridge（Python，本地运行）
├── vendor/                 # 本地化 JS 依赖
├── supabase/
│   ├── config.toml
│   ├── migrations/         # 5 个迁移文件
│   └── functions/chat-ai/  # Deno Edge Function（备用）
├── docs/
│   ├── AGENT_DESIGN.md     # 自研 Agent 设计文档
│   └── TOMORROW.md         # 决策记录
└── .gitignore
```

## 开发约定

- 提交信息用中文，格式：`类型: 描述`（feat/fix/ui/docs）
- 数据库 role 字段保持英文（user/expert/ai），UI 显示中文（小白/大咖/AI 助手）
- AI 模型默认 claude-sonnet-4-5，通过 room.model 可覆盖
- `.env` 文件不提交，放 ANTHROPIC_API_KEY 等密钥
