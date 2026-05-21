# Chat2GO TODO(滚动清单)

> 形式:按计划日期分段;做完 `[x]`,新加 `[ ]` 追加到当天那段。
> 跨天没做完的不挪,留在原日期,显示"延期"。

## 2026-05-21

### 🆕 速跑 — speak2go 教学材料文件库 v2 (新建表)

4 条**单条**贴 Supabase SQL Editor 跑(按 [[feedback-supabase-sql-split]] 习惯):

```sql
-- ① 建表
create table expert_material_folders (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id),
  room_id uuid references rooms(id) on delete cascade,
  name text not null default 'Materials',
  payload jsonb not null default '[]',
  product text default 'speak2go',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
```

```sql
-- ② 索引 + RLS 开
create index idx_emf_owner on expert_material_folders(owner_id);
create index idx_emf_room on expert_material_folders(room_id);
alter table expert_material_folders enable row level security;
```

```sql
-- ③ SELECT 任何人可读
create policy "materials_select_all" on expert_material_folders
  for select to authenticated using (true);
```

```sql
-- ④ INSERT/UPDATE/DELETE: owner OR speak2go 单例房放行(老师+OG 都能编辑)
create policy "materials_write_speak2go_singleton" on expert_material_folders
  for all to authenticated
  using (owner_id = auth.uid() OR room_id = '5b622bc4-88b4-47c1-9aa6-643c4b1e0f96')
  with check (owner_id = auth.uid() OR room_id = '5b622bc4-88b4-47c1-9aa6-643c4b1e0f96');
```

跑完 ① 到 ④ 都 success → 前端材料库 v2 可用。表不存在前 panel 会回到旧的扁平列表(已写了 fallback)。

### speak2go 声纹/lesson_sessions 残留 SQL drop(部分完成)

- [x] **① profiles 删 3 列声纹字段**(2026-05-21 跑过 + Claude 验证 PostgREST 返回 column does not exist)

```sql
-- ① profiles 表删 voice_embedding 系列列(声纹模块已下线)— DONE
alter table profiles
  drop column if exists voice_embedding,
  drop column if exists voice_registered_at,
  drop column if exists voice_sample_url;
```

- [ ] **② + ③ 阻塞:有代码依赖 messages.lesson_session_id 列 + lesson_sessions 表**
  - `asr_server.py:_insert_asr_message` 还在写 `lesson_session_id` row 字段(每段 ASR)
  - `libs/speak2go.py` 的 `fetch_lesson_transcript` / `handle_knowledge_unit_end` / `handle_lesson_ended` 还在用列做查询/INSERT
  - 直接 drop 会让实时 ASR 写入全挂
  - **要做的清理顺序**:① 删 asr_server.py 那行 row 字段 ② 短路/删 libs/speak2go.py 三个 handler ③ 删 chat2go.py 对应 dispatch ④ 重启 asr_server + speak2go Hermes ⑤ 才能跑下面 ②③ SQL

```sql
-- ② messages.lesson_session_id FK 先解除依赖(避免 cascade 误删消息)
alter table messages drop column if exists lesson_session_id;
```

```sql
-- ③ lesson_sessions 表整张删(三角色架构纠偏:speak2go 不需要"1v1 课堂会话")
drop table if exists lesson_sessions;
```

```sql
-- ④ 验证清理完成(② ③ 跑完用):
select to_regclass('public.lesson_sessions') is null as dropped;  -- 应 true
```

---

## 2026-05-19

### ✅ 今天已做(无需再操作)

- ✅ **Well2GO.ai 康复师版完整上线** — 独立 repo `tototo1999/well2go` + GoDaddy DNS + GH Pages HTTPS + Enforce HTTPS + mini 新 Hermes 实例 `ai.hermes.gateway.well2go` 跑起来(`iamaog@well2go.ai`, expert=29b53260)。SOP 已落 memory `project_well2go_deployment_inflight.md`
- ✅ **所有平台关闭注册 tab** — chat2go.cn 早已关,tradego + well2go 今天关掉(commit `c19a90c` + tradego/well2go login.html)
- ✅ **邀请码多 token 模型** — Supabase 新表 `room_invites` + RPC `create_invite_token` / `consume_invite_token`,前端 chat2go.cn 已 push `48e7c11`;tradego + well2go 用户 ToDesk 同步中

### 🔥 未完成(继续)

- [ ] **reset_room 一键真清**(2026-05-19 发现) — 当前 `reset_room` RPC 只清 messages + room-scope memory,但 expert-scope memory(OG 跨房累积)+ Hermes 本地 `~/.hermes/sessions/` + `state.db` 会残留,导致 AI 还能"想起"旧个案。**真正清干净的 3 步**:① `reset_room` RPC ② `DELETE FROM memories WHERE scope='expert' AND scope_id IN (该 OG)` ③ ssh 跑 Hermes 机器 `rm -rf ~/.hermes/sessions/* ~/.hermes/state.db* && launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway`。
  - 工程化方案:加"深度重置"按钮 → RPC 同时清两 scope + 写一条 `bridge_state.reset_requested_at` → Hermes 端 _watchdog 检测到该字段更新就清自己 sessions/state.db 再重启
  - 或者 RPC 同时发 SIGTERM 给 Hermes(需要 webhook / 进程 socket,工程更重)

- [ ] **邀请码多 token 同步 tradego/well2go** — ToDesk mini 跑 patch.py 命令(已发,等用户操作)
- [ ] **patch 02 重生成** — chat2go.py 今天没动,但近期 `_CONTRACT_KEYWORDS` 扩展未回写(同 2026-05-18 段的 TODO)

### speak2go.ai 老师上课版部署(参照 well2go SOP)

> 第 4 个垂直产品:语言老师 / 口语训练 / 课堂场景。沿用 mini 多实例架构。

**★ 核心架构差异 — 三角色,AI 角色重新定位**

跟 chat2go / tradego / well2go 不同:speak2go 不是"OG ↔ AI ↔ 小白"对话主体三方,而是 **3 个独立角色** + AI 是后台助手:

| 角色 | DB role | 定位 | 发言频率 |
|---|---|---|---|
| **老师** | `expert` | 课堂主导,教内容 | 主动,高频 |
| **学生** | `user` | 学习者,问/答/练 | 主动,高频 |
| **AI 助教** | `ai` | **后台助手**,不抢戏 | **按触发条件**,低频 |

**AI 助教的核心价值 — 评估者,不是教学者**

AI 助教做的事就一件:**确认知识点的学习完成度,不断更新进度条**。

**两个数据源驱动进度条**:

```
                     ┌─→ ASR 转写 ─→ 分析"教了哪些知识点 + 学生回答情况"
   上课录音 ────────┘                                              ↓
                                                              更新 student_mastery
   测试题 / quiz ──→ 学生答对答错 ─→ 直接判定知识点掌握度 ───────────↑
```

**两个输出**:
1. **进度条**(UI 主呈现):每个学生 × 每个知识点 = 1 个 mastery%(0/初学/熟练/掌握)→ sidebar 用进度条可视化
2. **知识点笔记**(memory 副产物):课中出现的词/句/语法 → 写 memories 表

**新数据模型(待设计 schema)**:

| 表 | 字段 | 作用 |
|---|---|---|
| `lesson_recordings` | id, room_id, audio_url, transcript, lesson_idx, created_at | 录音 + ASR 转写 |
| `student_mastery` | student_id, topic_key, mastery_level, evidence_count, last_updated | 学生 × 知识点 掌握度 |
| `quiz_results` | student_id, quiz_id, topic_key, correct, answered_at | 测试记录,直接喂 mastery |
| `topic_dictionary` | topic_key, label, category | 知识点字典(教学大纲) |

**AI 助教工作流(后台 job)**:

1. 监听 room 新消息(含语音附件 → 触发 ASR 转写)
2. 监听 quiz 答题事件
3. 周期性 / 触发式 job:跑 mastery analyzer
   - LLM 分析转写 + 答题数据 → 更新 `student_mastery`
   - LLM 提取知识点 → 写 memories
4. AI 助教**很少发言**,只在:
   - 老师显式 `@助教 当前进度` / `@助教 学生 X 掌握情况`
   - 单元结束触发 `本单元学完了,知识点 A/B 已掌握,C 待巩固`
   - 阶段测试后总结

**架构改造点**:

- chat2go.py 加 `_should_respond` 钩子:speak2go room 默认**不**响应消息,只响应特定触发(@助教 / 单元完成 / quiz 提交)
- 新增后台 job(可以 launchd 独立 task,也可以 Hermes 内 cron):`mastery_analyzer`,周期处理 unprocessed transcripts + quiz events
- 前端 sidebar 改:speak2go 显示**学生进度条矩阵**(横轴知识点,纵轴学生),不再只是 todo checkbox
- 录音转写依赖 2026-05-19 段已有的 ASR TODO(speak2go 强依赖,优先做)

**风险**:
- mastery analyzer 用什么模型? Gemini Flash 便宜但分析深度有限,Sonnet 准但贵 → MVP 用 Flash,正式上线评估
- topic_dictionary 谁维护?老师上课前预设,还是 AI 从课程内容自动抽取?(选后者更省事,但首批知识点不可控)

**Phase 0 — 准备**
- [ ] 在 GoDaddy(或现有 DNS provider)买 / 确认 `speak2go.ai` 域名
- [ ] GitHub 建空 repo `tototo1999/speak2go`
- [ ] 主题色拍板:跟现有 3 个产品区分
  - chat2go.cn = 深绿 #1D9E75 / tradego = 蓝 #2563eb / well2go = mint green #10b981
  - speak2go 候选:**Indigo #6366f1**(语言学术感) / **Coral #f97316**(温暖课堂感) / **Violet #8b5cf6**

**Phase 1 — 前端 fork(预估 1h)**
- [ ] mini 上 `cp -r ~/well2go-site ~/speak2go-site`(基于最接近的 well2go 蓝本)
- [ ] git remote 改 `tototo1999/speak2go.git`,rm -rf .git 重 init 干净历史
- [ ] CNAME → `speak2go.ai`
- [ ] CSS `--teal` 系列换主题色(参考 well2go init patch 的写法)
- [ ] DEMO_INDUSTRY=`英语口语` / `语言培训` / `课堂教学`(待定具体细分),DEMO_PRODUCT=`speak2go`
- [ ] title / brand:`Speak2GO.ai`,nav logo `Speak2<span>GO</span>.ai`
- [ ] DEFAULT_TODO_PAYLOAD = 10 组口语教学工作流 × 3 项(草稿:**水平测评 → 学习目标 → 教材选定 → 课程节奏 → 单词积累 → 句型操练 → 口语对话 → 听力训练 → 阶段测验 → 进阶规划**)
- [ ] TYPING_VERBS = 100 组语言老师 typing 用语(评测/造句/纠音/听写/翻译/批改/教练 等动作)
- [ ] commit + push `tototo1999/speak2go`

**Phase 2 — mini Hermes 新实例**
- [ ] `cp -r ~/.hermes ~/.hermes-speak2go`(沿用 well2go 那次模式)
- [ ] 清运行态(logs/state.db/sessions/gateway.lock)
- [ ] `.env` `CHAT2GO_TOKEN` 占位,API keys 复用
- [ ] launchd plist `ai.hermes.gateway.speak2go.plist`,`HERMES_HOME=/Users/lexi/.hermes-speak2go`
- [ ] 一键脚本 `~/speak2go-launch.sh`(参照 `~/well2go-launch.sh`)

**Phase 3 — 行业定制**
- [ ] 拦截器(类比 tradego-contract):**口语作业批改 PDF 生成 / 词汇本导出 / 课堂记录**
- [ ] system_prompt:语言老师专业风(双语提示 / 错误纠正 / 鼓励式反馈)
- [ ] skill 包 `~/.hermes-speak2go/skills/productivity/speak-go/`

**Phase 4 — DNS + HTTPS**
- [ ] GoDaddy 加 4 条 A 记录指 GH Pages IP(同 well2go.ai 流程)
- [ ] GH repo Settings → Pages 启用 + Custom domain
- [ ] 等 DNS check successful + Let's Encrypt 自动签发 + 勾 Enforce HTTPS

**Phase 5 — 注册账号 + 一键启动**
- [ ] 在 https://speak2go.ai/login.html 注册老师 OG 账号
- [ ] 拿 agent_key → 在 mini 跑 `bash ~/speak2go-launch.sh c2g-key_xxx`
- [ ] 验证 chat2go connected + 房间内文字/语音/图片测试

**风险点 / 决策点**
- speak2go 主线场景是"老师 ↔ 学生"还是"老师 ↔ 助教(AI)备课"?决定 industry 细分 + todo 模板方向
- 口语场景对**录音转写**强依赖(语音是主要输入),建议 speak2go 部署同时**优先实现录音转写**(2026-05-19 段已有该 TODO)
- 容量评估:mini 现在跑 2 个 Hermes 实例(tradego + well2go),加 speak2go 是第 3 个,预计稳态 ~1.5GB RSS,16GB mini 完全 OK

**预估总时长**:4-6h(同 well2go 那次),不包含 DNS / Let's Encrypt 等待时间

### chat2go.cn / xyz 接录音转写(让 AI 能"听"语音消息)

- [ ] **adapter 加音频支持** `chat2go.py` 的 `_extract_attachment_text` 扩展:
  - 检测 `.qta` / `.m4a` / `.mp3` / `.wav` / `.aac` 后缀(QuickTime / Apple Voice Memo 系列)
  - ffmpeg 先把容器抽成纯 wav/mp3(`.qta` 是 QT 装 AAC,需要先解一层)
  - 调 DashScope(Qwen-Audio) 或 OpenRouter Gemini 转写,中文优先 Qwen
  - 转写文本以 `【录音转写 (XX 秒)】\n<text>` 前缀塞进 content,brain 看到的就是文字
- [ ] **依赖**:mini 上装 ffmpeg(本机已 ffmpeg 8.1) + DashScope SDK 或 google-genai
- [ ] **验证**:用样本录音(20 秒中文) → 看转写质量 → 再决定走 Qwen 还是 Gemini
- [ ] **adapter 改动同步**:回写 `docs/hermes-patches/02-chat2go-platform-adapter.patch` (跟今晚 dispatcher 那波一起整理)
- [ ] **样本录音保留**:`~/Library/Containers/com.apple.VoiceMemos/Data/tmp/.com.apple.uikit.itemprovider.temporary.ekw9C3/新录音 10.qta` 可作为 1 号测试用例(0:20, 94kbps AAC LC, 48kHz mono)

## 2026-05-18

### tradego 拦截器扩展(让大咖出 Excel 报表不打开 terminal)

- [ ] **扩 `_try_handle_tradego_contract` 拦截器范围**:除 PDF 合同外,加 Excel 报价单/quote/packing list/装箱单
  - 新模块:`~/.hermes/libs/excel_generator.py`(对应现有 `contract_generator.py`)
  - 新模块:`~/.hermes/libs/excel_lib.py`(用 openpyxl,对应 `contract_lib.py`)
  - 关键词扩:`出报价` / `出 quote` / `出 quotation` / `做报价单` / `出 packing list` / `出装箱单` / `出 PL`
  - 模板类型:`quotation`(报价单)、`packing-list`(装箱单)、`shipping-mark`(唛头)
- [ ] **chat2go.py 拦截器分流**:把 `_try_handle_tradego_contract` 拆成多个 dispatcher,按关键词路由到 contract / excel / 其它
- [ ] **同步到 mini**:rsync chat2go.py + libs/excel_*.py 到 lexi@192.168.1.111,然后 ssh kickstart
- [ ] **patch 02 重生成 + commit** + 更新 `TRADEGO-MINI-HANDOFF.md`

### 验证 + 数据

- [ ] 跑 **10 个外贸实战个案** + **10 个命理实战个案** → 看 memory / token / 延迟数据
- [ ] `model_usage` 表给 anon role 加 SELECT 权限(昨天拉数据被 RLS 拒绝)

### 安全清理

- [ ] **轮换 OPENROUTER_API_KEY**(昨晚明文贴过 `sk-or-v1-e472...`,已泄露在会话历史)
- [ ] **轮换 DEEPSEEK_API_KEY**(今天明文贴过 `sk-7f711eca...`,已泄露)
- [ ] **轮换 GitHub PAT `ghp_ynsm9dfh...`**(2026-05-17 晚 ssh mini 看 ~/tradego-site/.git/config 时明文显示在 dev session,要去 https://github.com/settings/tokens 撤销 + 换新)
- [ ] **轮换 well2go agent_key `c2g-key_c9de2791...`**(2026-05-19 中午明文贴过 — well2go 注册后初次部署用)

### 文档

- [ ] **`TRADEGO-MINI-HANDOFF.md`** 加"如何只单文件同步 chat2go.py 到 mini"的安全 SOP(避免下次又触发 deploy.sh 全套覆盖风险)
- [ ] **patch 02 关键词块过期**:2026-05-18 晚 dev 这条 terminal 在 mini #2 上原地扩展了 `_CONTRACT_KEYWORDS` 元组(从 7 行老版 → 14 行带"做pi/出ci/全套单证"等 30+ 变体),没回写到 `docs/hermes-patches/02-chat2go-platform-adapter.patch`。下次任何人跑 `deploy.sh lexi 192.168.1.111` 整文件覆盖会回滚这次扩展,小白发"做PI"又会进 brain 失败。
  - 操作步骤:
    1. `ssh lexi@192.168.1.111 'diff ~/.hermes/hermes-agent/gateway/platforms/chat2go.py.bak.20260518230048 ~/.hermes/hermes-agent/gateway/platforms/chat2go.py'` 看清楚扩展了什么
    2. 把新的 30+ 关键词元组塞进 `02-chat2go-platform-adapter.patch` 同一行
    3. commit + push 这份更新的 patch
  - 关键词新版完整列表见 mini #2 上 `~/.hermes/hermes-agent/gateway/platforms/chat2go.py` 第 ~967 行的 `_CONTRACT_KEYWORDS = (...)` 段

### mini 多大咖部署模板

- [ ] **改造 `scripts/tradego-mini/deploy.sh` → `scripts/deploy-expert.sh`**:参数化部署任意行业大咖
  - 参数:`<industry> <ssh_user> <ssh_host> <chat2go_token> <model_provider> <model_default>`
  - 例:`deploy-expert.sh fitness lexi 192.168.1.111 c2g-key_xxx anthropic claude-haiku-4-5`
  - 关键:每个大咖独立 `~/.hermes-<industry>/` 目录(独立 venv/config.yaml/.env/logs),launchd label 也带行业前缀 `ai.hermes.gateway.<industry>`
  - 同步代码用 git pull 而不是 rsync(避免覆盖 mini 本地 persona/skill 改动)
- [ ] **mini 容量计算公式 + 当前占用情况** 写进 `TRADEGO-MINI-HANDOFF.md`:稳态 RSS / 网络 / API rate limit 三条天花板
- [ ] **mini 服役大咖清单**:跑个简单脚本扫 `~/.hermes-*` 目录,输出 `[industry, expert_id, model, status, last_activity]`,方便快速看健康状态
