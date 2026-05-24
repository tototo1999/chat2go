# Speak2Go Handoff — 2026-05-24

> 接手者读这一篇 + 跑一遍下面"快速验证"就能上手。MVP 测试阶段。

## 1. 产品定位

**Speak2Go.ai** — 1v1 英语口语私教课 AI 助教。**只做课后工作流**(实时录音流已 ripped):

```
老师上完课 → 本地有 m4a 录音 → 上传到 speak2go.ai
                                  ↓
              系统 ~10 min 输出:
              ① 私聊频道:完整 T/S 标注 transcript (markdown)
              ② 左侧 todo:这堂课的时间轴 + 知识点树
              ③ 主聊:brain 简短回应 + todo_proposal 卡(暂保留)
```

老师拿这些回放教学、提取下节课重点、出作业 PDF 给学生(系统**外**)。

### 三角色模型(纠偏后)

| 角色 | 系统内 | 定位 |
|---|---|---|
| **OG** | 是 | AI 技术专家(我们/iamarobot)— 调 prompt、装 Hermes、解 bug |
| **小白(老师)** | 是 | 资深英语老师,但 AI 小白 — 只管教学,不管底层 |
| **AI** | 是 | 助教,听课后录音、出 transcript + 时间轴 |
| **学生** | **否(系统外)** | 老师课后把 PDF / 作业发给学生,系统不直接连学生 |

⚠️ 历史代码有"学生" / "声纹识别" / focal_user_id 等概念,**纠偏后已删**(2026-05-21)。

## 2. 当前生产链路

```
前端 https://speak2go.ai/chat.html   (GH Pages, tototo1999/speak2go)
   ↓ (Supabase JS SDK)
Supabase   project=qjnagbzqhoansixqharb  (Postgres + Realtime + Storage + Auth)
   ↑ ↓ (Realtime)
Hermes Gateway  ~/.hermes-speak2go/  (dev MacBook M5, launchd ai.hermes.gateway.speak2go)
   │
   ├─ chat2go.py adapter  (跨 4 产品共享,~/.hermes/hermes-agent/gateway/platforms/)
   ├─ libs/speak2go.py    (上传转写主流程)
   └─ libs/asr/           (mlx-whisper + pyannote + transcript_merger + ffmpeg helper)
```

### 4 产品共用代码,product='X' 守卫隔离

| 站 | Hermes label | HERMES_HOME | 主机 | 主模型 |
|---|---|---|---|---|
| chat2go.cn(命理) | `ai.hermes.gateway` | `~/.hermes` | dev MacBook | openrouter/gemini-2.5-pro |
| tradego(chat2go.xyz) | `ai.hermes.gateway` | `~/.hermes` | **mini** | deepseek/v3 |
| well2go.ai | `ai.hermes.gateway.well2go` | `~/.hermes-well2go` | **mini** | google/gemini-2.5-pro |
| **speak2go.ai** | `ai.hermes.gateway.speak2go` | `~/.hermes-speak2go` | **dev MacBook** | google/gemini-2.5-pro |

`chat2go.py` adapter 跨产品守卫:`if room.get("product") == "speak2go"` 或 `in ("speak2go", "well2go")`(well2go 复用 speak2go 上传链)。

## 3. 单例房模型

speak2go 不用多房,**1 个 room 全用户自动加入**:

- 房 id: `5b622bc4-88b4-47c1-9aa6-643c4b1e0f96`
- 老师 OG: `iamarobot@speak2go.ai` (user_id `0112a67b-25eb-436d-9f40-020e3c3f983a`)
- 学生测试号: `iamabot@speak2go.ai` (user_id `27f59b5a-4403-4a2d-8a9a-a1a39d14a346`,纠偏后概念上不再需要,但还在 DB 里)
- 新注册用户由 trigger `on_auth_user_speak2go` 自动加进单例房 + 2 条单例房专属 RLS policy(messages INSERT + SELECT 旁路 room_members 检查 — Safari session 状态下 EXISTS 子查询挂)
- agent_key (iamarobot): `c2g-key_1b4f549f...` ⚠️ 明文泄露过多次,待轮换

## 4. 上传转写核心流程(端到端)

```
① 老师上传 m4a (chat.html → Supabase Storage)
         ↓
② Realtime trigger → chat2go.py:_dispatch_inbound (line ~365)
         ↓
③ 检测 audio attachment + product='speak2go'
         ↓
④ INSERT placeholder "🎙 [▰▱▱▱▱] 1/5 已收到《...》— 转写中..."  ← Realtime UPDATE 进度条卡死,RLS 未补
         ↓
⑤ _extract_attachment_text(name, url):
   • 下载 m4a → tmpfile
   • mlx_whisper.transcribe (raw,无 segments) → 拼进 brain content
   • UPDATE placeholder → "📝 [▰▰▱▱▱] 2/5" (静默失败,RLS)
         ↓
⑥ asyncio.create_task(handle_audio_upload_lesson(...))    ← libs/speak2go.py:340
         ↓
⑦ _diarize_and_label(audio_url, transcript)               ← libs/speak2go.py:300+
   │
   ├─ httpx 下载 audio → 第二个 tmpfile
   └─ executor: _diarize_and_label_from_path
       │
       ├─ mlx_whisper_provider.transcribe(local_path)     ← libs/asr/mlx_whisper_provider.py
       │   • condition_on_previous_text=False  (防 token loop)
       │   • DEFAULT_INITIAL_PROMPT (英语教学词表 bias)
       │   • _strip_loops 正则后处理 (ngram×≥10 截到 ×3)
       │   → TranscribeResult{text, segments[{start,end,text}]}
       │
       ├─ _ffmpeg_to_wav16k_mono(local_path)              ← 绕 pyannote m4a sample mismatch quirk
       │   ffmpeg -i src.m4a -ac 1 -ar 16000 -acodec pcm_s16le → out.wav
       │
       ├─ pyannote_diarizer.diarize(wav_path, num_speakers=2)
       │   → DiarizeResult{segments:[(start,end,SPEAKER_XX)]}  MPS 加速 RTF≈0.1
       │
       └─ transcript_merger.merge(whisper_segs, diar)     ← libs/asr/transcript_merger.py
           │
           ├─ assign_speakers_to_segments  (时间窗 overlap 投票)
           ├─ map_speakers_by_text_metrics — 4 信号启发式
           │   score = avg_chars × (0.5 + uniq_ratio) × (1 + 0.3·q_rate + 0.3·tm_rate)
           │   最高得分 = T,其它 = S/S2/S3
           ├─ merge_consecutive_same_speaker
           └─ turns_to_markdown → "**T:** ...\n\n**S:** ..."
         ↓
⑧ INSERT private_channel 私聊:
     message_type='transcript_full', channel='expert_user',
     content = "# 📝 Transcript — `name` (timestamp)\n\n{T/S markdown}\n\n---\n\n_Speaker labels (T=teacher, S=student) inferred from voice activity._"
         ↓
⑨ Haiku 抽 timeline-knowledge 树(把带时间戳 turns 渲染成 "[mm:ss] T/S: text"
   喂 Haiku,要求 3-7 段 timeline,每段 1-6 个 knowledge points)
         ↓
⑩ APPEND 到 active expert_todo_templates.payload:
     新 group: {label="📅 2026-05-23 20:40 · NYC Global Center 12.m4a", items=[
       {label="0:00-8:30 Reading Toh & Frog", items=[
         {label="past tense: knocked, walked"}, ...
       ]},
       ...
     ]}
         ↓
⑪ INSERT AI reply (attachments._event='todos_updated') → 前端 Realtime reload sidebar
         ↓
⑫ 主聊 brain 平行回复(暂未砍,见 §10)
```

**实测时间**(1 hr 课):**~9-12 min** 全程,RSS peak ~850 MB(target 3 GB)。

## 5. 关键文件 / 代码位置

| 路径 | 作用 |
|---|---|
| `~/speak2go/chat.html` | 前端主文件(5300+ 行,vanilla HTML/JS) |
| `~/speak2go/login.html` | 注册关闭,只登录 |
| `~/speak2go/index.html` | landing |
| `~/.hermes/hermes-agent/gateway/platforms/chat2go.py` | Hermes 适配器,跨 4 产品共享 |
| `~/.hermes-speak2go/libs/speak2go.py` | 上传转写主 handler |
| `~/.hermes-speak2go/libs/asr/mlx_whisper_provider.py` | whisper 包装 + loop strip + initial_prompt |
| `~/.hermes-speak2go/libs/asr/transcript_merger.py` | 4 信号 T/S 启发式 + 合并 + markdown 渲染 |
| `~/.hermes-speak2go/libs/asr/pyannote_diarizer.py` | pyannote MPS 包装 |
| `~/.hermes-speak2go/.env` | CHAT2GO_TOKEN / ANTHROPIC_API_KEY / HF_TOKEN / OPENROUTER_API_KEY 等 |
| `~/.hermes-speak2go/logs/agent.log` | Hermes 日志(grep `chat2go.speak2go` 看 speak2go 专属) |
| **`~/chat2go/docs/hermes-patches/`** | Hermes 改动**归档**(下次 hermes update 后回放) |

⚠️ `libs/` **双路径**:`~/.hermes/libs/*` 跟 `~/.hermes-speak2go/libs/*` 必须**双向同步**(speak2go HERMES_HOME 隔离),改一边漏一边 = `AttributeError`。

## 6. DB schema(Supabase project `qjnagbzqhoansixqharb`)

### 主要表

| 表 | 字段 | 用途 |
|---|---|---|
| `auth.users` | (Supabase Auth) | 老师/学生账号 |
| `profiles` | user_id, display_name, ... | 用户公开资料 |
| `rooms` | id, name, expert_id, focal_user_id, product, active_todo_template_id, sidebar_title, ai_name, ... | 房间元数据 |
| `room_members` | room_id, user_id, joined_at | 房间成员 |
| `messages` | id, room_id, user_id, role(user/expert/ai), content, type(text/markdown), channel(main/expert_user), source, message_type, attachments(jsonb), ratings(jsonb), created_at | 聊天消息 |
| `expert_todo_templates` | id, owner_id, name, payload(jsonb), active | sidebar todo(timeline + knowledge points 树) |
| `expert_material_folders` | id, owner_id, room_id, name, payload(jsonb) | 教学材料文件夹(2026-05-22 删 UI 后表保留) |

### messages.message_type 路由表(speak2go)

| message_type | 触发方 | 处理 |
|---|---|---|
| (null / 'audio') | 老师 INSERT 含 audio attachment | chat2go.py adapter spawn `handle_audio_upload_lesson` |
| `voice_input` | 前端 🎤 按钮录制 | adapter 拉 attachment → mlx-whisper → INSERT callback `_event='voice_transcript'` |
| `extract_todos` | 老师点 🎙 重抽按钮 | `handle_extract_todos_from_recording` 拉最近 transcript_full |
| `translate` | 老师点 🌐 翻译按钮 | `handle_translate_message` |
| `confirm_todo_apply` | 老师点 ✓ Apply | append items to active todo template |
| `discard_todo_proposal` | 老师点 ✕ Discard | 标记放弃 |

### RLS 关键 policy(speak2go 单例房专属)

- `speak2go_singleton_messages_insert` — `room_id=单例 AND auth.uid()=user_id`
- `speak2go_singleton_messages_read` — `room_id=单例`(旁路 room_members 检查)
- ⚠️ **没有 messages UPDATE policy** — 这是当前进度条卡死的原因

## 7. 环境变量(.env)

```bash
# ~/.hermes-speak2go/.env
CHAT2GO_TOKEN=c2g-key_1b4f549f...                 # iamarobot agent key(待轮换)
CHAT2GO_SUPABASE_URL=https://qjnagbzqhoansixqharb.supabase.co
CHAT2GO_SUPABASE_ANON_KEY=eyJhbGciOiJI...
CHAT2GO_ALLOW_ALL_USERS=true
CHAT2GO_HOME_CHANNEL=main

ANTHROPIC_API_KEY=sk-ant-...                      # Haiku + Sonnet
OPENROUTER_API_KEY=sk-or-...                      # Gemini 2.5 Pro(主 brain)
HF_TOKEN=hf_arPUq...                              # pyannote diarize(待轮换)

MLX_WHISPER_MODEL=mlx-community/whisper-large-v3-turbo
# MLX_WHISPER_INITIAL_PROMPT=...                  # 可选覆盖默认英语教学 prompt
```

## 8. 维护 SOP

### 重启 speak2go Hermes
```bash
launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway.speak2go
sleep 3
launchctl print gui/$(id -u)/ai.hermes.gateway.speak2go | grep -E "state|pid"
tail -20 ~/.hermes-speak2go/logs/agent.log
```

### 同步 libs 双路径(改完 ~/.hermes-speak2go/libs/X.py 后必做)
```bash
cp ~/.hermes-speak2go/libs/X.py ~/.hermes/libs/X.py
diff -q ~/.hermes-speak2go/libs/X.py ~/.hermes/libs/X.py    # 验证一致
find ~/.hermes-speak2go ~/.hermes -path '*/__pycache__/*' -delete
launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway.speak2go
```

### 推前端 → GH Pages
```bash
cd ~/speak2go
git add chat.html
git commit -m "..."
git push origin main
# GH Pages 部署 30s-2min,后台轮询:
for i in $(seq 1 30); do
  if curl -sL "https://speak2go.ai/chat.html?_=$(date +%s)" | grep -q "<期待的新字符串>"; then
    echo "DEPLOYED"; break
  fi
  sleep 12
done
```

### Supabase SQL — 走 MCP(不用 Editor)
- `mcp__supabase__execute_sql` 跑读类 / 单行修
- `mcp__supabase__apply_migration` 跑 DDL(CREATE/ALTER/DROP)
- 都需要 **preview-then-go**(memory `feedback-autonomous-low-risk`)

### 看实时日志
```bash
tail -F ~/.hermes-speak2go/logs/agent.log | grep -E "(spawned|transcribed|metrics|merger:|transcript posted|recording-group|placeholder|ERROR)"
```

### 看其他产品 Hermes(对比)
- chat2go.cn 命理:dev 机 `~/.hermes/logs/agent.log`
- tradego / well2go:`ssh lexi@192.168.1.111 'tail ~/.hermes-well2go/logs/agent.log'`

## 9. 关键架构决策(读这一节别走弯路)

1. **实时课堂流 2026-05-22 已 ripped** — `asr_server.py` / WebSocket / VAD / classroom-btn 全删,备份在 `~/.hermes/_ripped-realtime-2026-05-22/`。**不要复用**;未来要做实时课堂从头设计
2. **brain 主聊回复目前还在跑** — 上传录音会触发 brain 简短回应(花 token + 写 expert memory)。**MVP 后建议砍**(prod=='speak2go' && 有 audio attachment → skip brain dispatch),avoid memory 污染
3. **声纹识别(SpeechBrain ECAPA)2026-05-21 已 ripped** — 不要再加,T/S 用启发式 + Swap 兜底
4. **DB residue**:`messages.lesson_session_id` 列 + `lesson_sessions` 表仍在,但**无代码引用**,Supabase MCP 可直接 drop
5. **三角色架构**:系统内只 OG + 小白(老师)+ AI。**不要加"学生"账号** — 学生是 PDF 接收方,系统外
6. **chat2go.py adapter 跨产品共享** — 改之前注意:任何无 `product==` 守卫的代码会影响 4 个 Hermes
7. **GH Pages 部署速度** — main push 30s-2min 可见,缓存有时挺顽固,加 `?_=$(date +%s)` cache-bust
8. **Hermes 端 Python 改动** — 务必同步到 `~/chat2go/docs/hermes-patches/` 不然 `hermes update` 冲掉

## 10. 当前已知问题(MVP test 前评估)

| 严重度 | 问题 | 影响 | 修法 |
|---|---|---|---|
| 🔴 高 | **进度条 UPDATE 失效** — RLS 没 UPDATE policy,placeholder 卡在 "1/5" | 老师等 9-12 min 看不到任何进度 | 加 messages UPDATE policy(`for update using auth.uid()=user_id`)|
| 🟡 中 | **Realtime WebSocket 偶尔 1006 断连**(2026-05-23 19:32 死 1h) | 上传后 Hermes 收不到 INSERT,完全卡死 | 检查 watchdog 实际生效 + 强化 reconnect |
| 🟡 中 | **brain 主聊回复污染 expert memory** | 老师"上传 1hr 餐饮聊天"被当真事写进 expert memory,跨课带走 | adapter 加 `if has_audio_upload and product=='speak2go': skip brain` |
| 🟢 低 | **#5 whisper-pyannote 边界不齐** | 某些短段被塞错 speaker(整段判定仍对) | merger 用 pyannote 段重切 whisper |
| 🟢 低 | **52 个 room_members 用户**(5-20 backfill 残留) | 老师 sidebar 看到很多陌生用户 | DELETE 多余 room_members |
| 🟢 低 | **HF_TOKEN / agent_key 明文泄露多次** | 安全风险 | 轮换 + 同步两 .env |
| 🟢 低 | **DB 残留** `lesson_session_id` 列 + `lesson_sessions` 表 | schema 杂乱 | drop |

## 11. MVP test 准备清单

### 必修(blocker)
- [ ] **加 messages UPDATE policy** — 让进度条真生效
- [ ] **Realtime 稳定性**:监控 + 自动恢复 + 检查 watchdog 阈值

### 强建议
- [ ] **错误反馈** — transcribe/Haiku/pyannote 失败,placeholder 改 `⚠️ 转写失败:<原因>`(部分有,需补全)
- [ ] **用户标识** — sidebar 头部小标 "以 XX 身份登录"
- [ ] **使用统计** — `model_usage` 表写 token / 录音秒数

### 可选
- [ ] 砍 brain 主聊回复(节省 token + 防 memory 污染)
- [ ] Hermes patch 存档同步(chat2go.py 最新改动尚未回写)
- [ ] tag stable 版本(`v0.1-mvp`)在 2 个 repo

### MVP test 邀请前要回答的
- 招几个老师? 1-3 个?
- 老师上传什么录音? 真课堂 / 测试段?
- 怎么收反馈? 微信 / 表单 / 直接看 supabase?
- 出问题怎么定位? 看 message id + log id?

## 12. 快速验证(接手第一件事)

```bash
# A. 4 个 Hermes 都在跑?
launchctl print gui/$(id -u)/ai.hermes.gateway.speak2go | grep -E "state|pid"
launchctl print gui/$(id -u)/ai.hermes.gateway | grep -E "state|pid"
ssh lexi@192.168.1.111 'launchctl print gui/$(id -u)/ai.hermes.gateway.well2go | grep -E "state|pid"'

# B. 3 个站都 200?
for url in https://speak2go.ai/chat.html https://well2go.ai/chat.html https://chat2go.cn/chat.html; do
  echo -n "$url  ";  curl -sI -o /dev/null -w "%{http_code}\n" $url
done

# C. speak2go 库双路径同步?
diff -q ~/.hermes/libs/speak2go.py ~/.hermes-speak2go/libs/speak2go.py
diff -qr ~/.hermes/libs/asr ~/.hermes-speak2go/libs/asr

# D. 看一眼最近一次上传是否成功
# (Supabase MCP:select latest transcript_full from messages where room_id=...)

# E. dev 机 brew 装的 ffmpeg / Python 包齐?
which ffmpeg && ffmpeg -version | head -1
~/.hermes/hermes-agent/venv/bin/python -c "import mlx_whisper, pyannote.audio, httpx, supabase; print('OK')"
```

全 OK → 系统可用,可以让老师上传录音。

## 13. 相关 memory(`/Users/dami2026/.claude/projects/-Users-dami2026-chat2go/memory/`)

| 文件 | 内容 |
|---|---|
| `project_speak2go_singleton_room_live.md` | speak2go 完整状态(常更新) |
| `project_three_role_architecture_corrected.md` | 三角色架构纠偏(必读) |
| `project_speak2go_testbed_isolation.md` | 测试只在 speak2go.ai,别碰 chat2go.cn 生产 |
| `project_hermes_routing.md` | 4 产品 expert_id 路由模型 |
| `chat2go-state-2026-05-21-pm.md` | m4a 上传转写打通(8 fix) |
| `chat2go-state-2026-05-23-eod.md` | well2go 健康健身上线 + 双产品守卫 |
| `feedback-supabase-sql-split.md` | SQL 默认走 MCP,fallback 拆 Editor |
| `feedback-autonomous-low-risk.md` | 没风险直 go,DDL/RLS preview-then-go |

## 14. 一句话给接手者

**Speak2Go 已经是个可用的"上传录音→看 transcript + sidebar 树"产品,核心链路稳定(1hr 课跑通),但 MVP 测试前**先把 RLS UPDATE 补上**(进度条体验),并**盯 Realtime 稳定性**(下午曾经死过 1 小时)。其它都是优化项,不影响主流程。
