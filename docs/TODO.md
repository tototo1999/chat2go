# Chat2GO TODO(滚动清单)

> 形式:按计划日期分段;做完 `[x]`,新加 `[ ]` 追加到当天那段。
> 跨天没做完的不挪,留在原日期,显示"延期"。

## 2026-05-28

### 🛠️ 工具链探索 — Figma REST API 接入(待启动)

- [ ] **Figma REST API 接入探索** — 现状:Figma Dev Mode MCP 已配通(`http://127.0.0.1:3845/mcp`,全局 `~/.claude.json`),够"边开桌面端 Figma 边写代码"的场景用。REST API 真正补的缺口是**离线/批量/自动化**:CI 里 Figma 文件 → 自动 export design tokens、批量拉团队多文件、webhook 监听稿件变更。
  - 触发条件:**当真的开始在 Figma 里画 wooooow / chat2go 设计稿时再接**,现在 freestyle HTML 没经过设计稿这一步,接了就是为了接而接。
  - 接入步骤:① 去 [figma.com/developers/api](https://www.figma.com/developers/api) 申请 personal access token → 写进 `.env`(`FIGMA_TOKEN=`)② 写 `scripts/figma_pull.py`(~30 行):输入 file key,拉节点树 JSON + 渲染图 URL ③ 跑通后再考虑自动化(GH Actions 定时 sync / pre-commit hook 校验 design tokens 一致)
  - 不要做的:为了接而接、给现在没有 Figma 稿的产品先接 API。

### 🗂️ speak2go 单词表 — 搜不到的词一键联网查并加入(上线)

- [x] **glossary 联网查词加词闭环**:搜索无结果时出现「🌐 在网络上查 X 并加入「当前分类」」按钮,一键 → 联网查 → 去重 → 加进当前 tab → 清搜索 → 跳新词高亮。
  - 后端:新 edge function `glossary-lookup`(Gemini Flash + retry/flash-lite fallback,跟 `glossary-grade` 同套路 anon key + `verify_jwt:false`),输入中/英词 → 返回 `en/罗马注音/中文/用法/例句/词性` 双语词卡;乱码返回「无法识别」。
  - 前端双路径同步 `glossary/index.html`(线上)+ `glossary.html`(legacy);nyc-global-center + 动态 lesson cat 自动带艾宾浩斯字段。
  - 验证(playwright 跑真实 edge fn):session ✅ / 中文「拖延」→procrastinate ✅ / 乱码→无法识别 ✅ / 重复词搜索直接命中 ✅。speak2go commit `3342a64`,线上已生效。

### 🧰 Gamma 接入(MCP + API)

- [x] **Gamma API + MCP 部署**:API key 存 `chat2go/.env`(`GAMMA_API_KEY`);用 `format:"webpage"` 跑出 LoRA 冰箱贴概念页 v1/v2。装 CryptoJym/gamma-mcp-server 到 `~/mcp-servers/gamma-mcp-server`,注册 user scope(`mcp__gamma__*` 4 tool),patch 加 `webpage` format。重启 Claude Code 后 MCP 用新 dist。

### 🎨 设计稿落地

- [x] **wow-fridge 概念长卷 v2 上线**:`wow-fridge/index_v2.html`(1717 行) — 沿用原 `index.html` 多巴胺糖果设计语言,但把概念图密度翻 3 倍:① 同 6 张 gamma_concept 在 hero 飘带 / 愿景画板蒙太奇 / 概念剖析剖面 / 家庭瞬间拼贴 4 个区段各演一遍 ② 自绘 8 张 SVG/CSS 设计标本卡(配色板/材质栈/声纹波形/传感器拓扑/电池环/24h 律动环/家人头像/连线波纹)③ ACT 06 自绘 SVG 家庭 mesh 拓扑大图(6 家人节点 + 厨房 hub + 云/手机 fallback)。跟原 `index.html` 并列不替换,用户可对比。

## 2026-05-27

### 已完成

- [x] **DROP `bridge_state` schema 残留**:`bridge_state` 表 + `bridge_pong()` + `request_bridge_restart()` RPC 全部 drop;`admin_bridge_status()` 保留(实查 `model_usage`,与名字相反)。migration `supabase/migrations/20260527100000_drop_bridge_state_residue.sql`
- [x] **本地 `~/.hermes*` 清盘**:`~/.hermes` (2.1G) + `~/.hermes-speak2go` (1.8G) + 2 个 launchd plist rm 干净
- [x] **well2go 默认 todo 切康复治疗中文**:拆 `DEFAULT_TODO_PAYLOAD_SPEAK2GO` / `_WELL2GO`,well2go 走 **「康复治疗 — 核心计划」** 10 组中文模板(评估建档/康复目标/训练计划/疼痛管理/姿势矫正/日常活动/物理因子/居家训练/阶段复评/长期维护),speak2go 保留 English Speaking - Core。运行时按 `_IS_WELL2GO` 选。speak2go 仓库 commit `8b02555`,well2go 仓库 commit `475f08f`
- [x] **验证 DB 老 schema 残留**:`messages.lesson_session_id` 列不在、`lesson_sessions` 表不在(早期 cutover 已清);`room_members` 当前只 8 行(每房 1-2 人),52 user 历史污染问题已被清理 — 都是 no-op,无需新 migration

### 🌱 新 idea — wooooow.ai 中文 vibe coding 穿戴开源社区(待启动)

> 详细 plan:`~/.claude/plans/merry-questing-elephant.md`(出 plan mode 时保存,审批通过未启动)

**域名锁定**:[wooooow.ai](https://wooooow.ai)(「哇~~」拉长版,中文极客感拉满)— **未注册,实施前 check 可用性 + 注册**

**一句话**:做一个完全独立的中文开源社区站,服务"想在智能穿戴(眼镜/耳机/手环/胸针 PIN)上写自己 App 的中文 vibe coder 极客"。

**已锁定的 7 个 high-level 决策**:

| # | 维度 | 选项 |
|---|---|---|
| 1 | 目标用户 | 中文 vibe coder 极客(会基础编程) |
| 2 | 硬件长期 | 自营矩阵(MVP 阶段借) |
| 3 | MVP 切口 | vibe coding 工坊接 1 款硬件 |
| 4 | 站点架构 | 完全独立的开源社区站(新域 + 新仓库) |
| 5 | 首阶段硬件 | ⚠️ **重审中** — 原锁定 [Mentra Live](https://mentra.glass/) $299,但 [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32)(26k★/中文/¥40-300)可能更优 |
| 6 | 技术栈 | Astro 静态站 + GH Pages + Supabase 复用(独立 schema `wooooow`) |
| 7 | 域名 | **wooooow.ai** |

**赛道关键事实(2026-05 调研)**:

- vibe coding 已是 Collins 2025 年度词,Karpathy 2025-02 起爆
- 开源穿戴龙头:[Omi 12.6k★](https://github.com/BasedHardware/omi) / [MentraOS 2k★](https://github.com/Mentra-Community/MentraOS) / [Bangle.js](https://banglejs.com)
- MentraOS 已有 miniapp App Store(TypeScript bundle),但需要懂 TS
- 3 个明显空白:① **中文自然语言 → 穿戴 App 端到端无人做** ② 中文 DIY 穿戴黑客文化几乎为零 ③ 手环手表 App 生态空白

**MVP 范围**(4 件事,3-4 周):

1. 新域名 + Astro 静态站上线(候选 `vibewear.dev`,实施前确认)
2. **vibe coding 工坊**:用户跟 AI 大咖对话 → AI 生成 MentraOS miniapp TS 代码 → 一键下载 .ts → 用户本地 `mentra-miniapp dev` 推到自己眼镜
3. **作品广场**:用户上传自己 vibe-coded 的 miniapp(带 demo 视频/截图),其他人可 fork
4. **Discord + 微信群**圈 100 人种子

**核心 trick**:vibe coding 工坊本质是 `chat2go-worker` 加一个新 industry `wooooow` + 新 system prompt,**不**重建 chat 引擎。新 repo `tototo1999/wooooow` 的 chat.html 从 speak2go 复制 + runtime `host.includes('wooooow')` 切 brand(跟 well2go 同套路)。后端复用 Supabase project `qjnagbzqhoansixqharb` 的新 schema `wooooow`,跟 public schema RLS 隔离。

**2026-05-27 国内开源硬件调研发现**(plan 后续 research note):
- **颠覆性发现**:[xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) **26k★**,中文社区,MIT,¥40-300,支持豆包/Qwen/DeepSeek REST API。**比 MentraOS (2k★) 大 10 倍,比 Omi (12.6k★) 大 1 倍** — 中文极客早已在这里聚集
- **国内 3 个明确空白**:① AI 摆件/挂件(CES 2026 展 30+ 款国产 AI 陪伴机器人,0 个开 SDK,Omi 国内无对标)② 手环 Health API 名义开放但个人难审过 ③ 录音设备「硬件闭源 + 云 API 全开」裂缝(讯飞)
- **Phase 2-3 候选硬件矩阵**:[xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) / [M5Stack LLM630](https://docs.m5stack.com/zh_CN/core/LLM630%20Compute%20Kit) / [TuyaOpen](https://github.com/tuya/TuyaOpen) / [雷鸟 X2](https://open.rayneo.cn/) / [Rokid Glasses](https://ar.rokid.com/sdk) / [FoloToy](https://github.com/FoloToy)
- **Phase 3 自研「胸针 PIN」(ESP32-S3 + 麦 + 蓝牙)正是填 AI 摆件空白的最优切入点**

**MVP 不做**:支付 / 评论 / 真硬件 / 第二款硬件 / 自研 PIN 胸针(Phase 3)/ 教育市场(Phase 4)。

**待启动前最后一步**:
- [ ] 域名 `wooooow.ai` 可用性 check + 注册
- [ ] 决策:首阶段硬件保持 Mentra Live,还是切到 xiaozhi-esp32,还是两条并行?
- [ ] 用户给绿灯启动 Week 1 实施

---

## 2026-05-23

### 🔥 转写进度条(上传录音 → transcript 全链路 9-10 min 体验补)

**痛点**:今天测 1 小时录音,从上传到看到 `transcript_full` 总耗时 9 分 14 秒。期间老师只看到一句 `"🎙 正在转写《name》,长录音可能要几分钟,请稍候..."` 静态 placeholder,没有任何进度反馈 — 不知道卡住了还是在跑、还要等多久。

**实现思路**:

复用现有 placeholder message(`chat2go.py` adapter line ~549 INSERT 的那条),把 `_pl_id` 传给后台任务 `handle_audio_upload_lesson`,在每个 checkpoint UPDATE 该消息 content,前端 Realtime UPDATE 事件自动重渲。

**Checkpoint 序列**(实测时长基于 1hr m4a):
1. `🎙 已收到《name》(56 min, 8 MB)... 转写中`(立刻)
2. `📝 转写完成(29292 字, 2:24)— 抽取知识点中...`(+2.4 min,whisper 完成)
3. `🎯 知识点已抽出(6 项)— 识别说话人中...`(+2.4 min + Haiku ~5s,todo_proposal 同步出主聊)
4. `🧠 说话人识别中(预计 ~7 min)...`(进 pyannote 阶段,可显倒计时)
5. `✅ 完成 — 私聊频道查看完整 transcript`(+9 min,删除或淡化 placeholder)

**实现细节**:

- `chat2go.py:_dispatch_inbound` 把 `_pl_id` 通过参数传进 `handle_audio_upload_lesson(...)`
- `libs/speak2go.py:handle_audio_upload_lesson` 在每步前后 await `_update_placeholder(sb, _pl_id, content)` 工具函数
- 时间估算公式硬编码近似:`whisper ≈ dur × 0.05`,`pyannote ≈ dur × 0.12`,从 whisper 完成时刻减去开始时刻得出实际值再外推
- 前端:placeholder 消息已经被 `appendMessage` 渲染,UPDATE 事件被 realtime 推送(检查 chat.html `UPDATE` 处理逻辑是否走 in-place 更新)
- 短录音(<30s)跳 diarize 时,直接跳到 step 5 "完成 — 单人录音不需说话人识别"

**风险点**:
- Realtime UPDATE 事件前端可能不刷渲染(只刷新 INSERT/DELETE)→ 需要检查 / 加 UPDATE 处理
- 老师在主聊点别的消息时 placeholder 是否还能找到 / 滚动到位置
- 如果 pyannote / Haiku 失败,placeholder 要变成"⚠️ 部分失败 — 见私聊看 fallback"

**预估工作量**:1-2h(后端 + 前端 + 端到端测一遍)

### 其它 backlog(参 2026-05-22 段「接下来」)

- [ ] **#5 whisper-pyannote 边界对齐** — 今天 1hr 测试暴露的"读书段被塞 T"问题
- [ ] **撤掉 brain 主聊回复** — 上传录音不再触发 brain LLM(省 token + 防 memory 污染)
- [ ] **DB 残留删** — `messages.lesson_session_id` 列 + `lesson_sessions` 表(Supabase MCP preview-then-go)
- [ ] **Hermes 端 patch 存档** — 今天改的 `libs/asr/*` / `libs/speak2go.py` / `chat2go.py` adapter 都没回写到 `docs/hermes-patches/`,下次 `hermes update` 会冲掉
- [ ] **52 个 room_members 用户清理**(从 5-21 延期)
- [ ] **HF token 轮换** — `hf_arPUq...` 仍未撤

---

## 2026-05-22

### 🎯 范围调整 — 实时录音 AI 响应整条线已 ripped,聚焦上传录音转写

**今天大切**:把"现场实时课堂录音 + AI 现场反馈"整条线**代码全删了**(不只是 hide),只走"老师上传 → 转写 → todo + 私聊 transcript"。

#### ✅ 今天已完成

- [x] 前端 chat.html 删 Classroom IIFE / mic 按钮 / classroom-bar / asr-badge / VAD CDN(-414 行)
- [x] 后端 `libs/speak2go.py` 删 6 个 realtime handler(-380 行)
- [x] `chat2go.py` adapter 删 3 个 realtime message_type dispatcher
- [x] launchd `ai.hermes.asr_server` bootout + 删 plist + 删 `~/.hermes/asr_server.py`(备份在 `~/.hermes/_ripped-realtime-2026-05-22/`)
- [x] m4a sample mismatch 修(ffmpeg 预转 16kHz mono wav)
- [x] whisper 幻觉 loop 治(`condition_on_previous_text=False` + 正则后处理)
- [x] T/S 启发式翻车修(换 `avg_chars × (0.5 + unique_word_ratio)` 替代总时长)
- [x] `handle_extract_todos_from_recording` 数据源切到 `message_type='transcript_full'`
- [x] libs 双路径同步 + Hermes 重启

#### 🔥 接下来

- [ ] **真用户重测一次 m4a 上传** — 验证新启发式(NYC 那段录音翻车场景)T/S 标对
- [ ] **删 DB 残留对象**(Supabase MCP preview-then-go):`alter table messages drop column if exists lesson_session_id` + `drop table if exists lesson_sessions`
- [ ] **52 个 room_members 用户清理**(5-20 backfill 把全部 52 用户加进单例房,纠偏后只该剩 OG)
- [ ] **HF token 轮换** — `hf_arPUq...` 明文出现在 5-21 session,撤销 + 新建 + 同步两个 .env
- [ ] **whisper 加 initial_prompt** — 英语教学场景词表(reading / pronunciation / vocabulary / past tense / short vowel...)提升英文专业词识别
- [ ] **RSS 峰值监控** — 长录音(>15min)峰值 RSS < 3GB?

#### 🟡 可考虑(基于上次讨论,看是否要做)

- [ ] **timeline + 知识点树状 todo 输出** — 替换"老师课后 todo 提议",改成 group=时段+主题 / items=该时段知识点的 2 层树
- [ ] **关掉上传时 brain 主聊回复** — 上传录音不再触发 brain LLM(省 token + 防 memory 污染);brain 仍响应其他文本/截图输入
- [ ] **UI Swap T↔S 按钮** — 私聊 transcript_full 加按钮反转标签 → 写 room_speaker_map 持久化(corner case 兜底)

### 其它跨天延期(参 2026-05-21 段)

- [ ] **52 个 room_members 用户清理**(5-20 backfill 把全部 52 用户加进单例房,纠偏后只该剩 OG + AI)
- [ ] **AI 写 todo 第二次复测**(关键词收紧后 ① 不再误触发"今天 todo 有啥"等查询;② 仍正常触发"加进左侧 todo")

---

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
