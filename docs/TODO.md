# Chat2GO TODO(滚动清单)

> 形式:按计划日期分段;做完 `[x]`,新加 `[ ]` 追加到当天那段。
> 跨天没做完的不挪,留在原日期,显示"延期"。

## 2026-05-19

### ✅ 今天已做(无需再操作)

- ✅ **Well2GO.ai 康复师版完整上线** — 独立 repo `tototo1999/well2go` + GoDaddy DNS + GH Pages HTTPS + Enforce HTTPS + mini 新 Hermes 实例 `ai.hermes.gateway.well2go` 跑起来(`iamaog@well2go.ai`, expert=29b53260)。SOP 已落 memory `project_well2go_deployment_inflight.md`
- ✅ **所有平台关闭注册 tab** — chat2go.cn 早已关,tradego + well2go 今天关掉(commit `c19a90c` + tradego/well2go login.html)
- ✅ **邀请码多 token 模型** — Supabase 新表 `room_invites` + RPC `create_invite_token` / `consume_invite_token`,前端 chat2go.cn 已 push `48e7c11`;tradego + well2go 用户 ToDesk 同步中

### 🔥 未完成(继续)

- [ ] **邀请码多 token 同步 tradego/well2go** — ToDesk mini 跑 patch.py 命令(已发,等用户操作)
- [ ] **patch 02 重生成** — chat2go.py 今天没动,但近期 `_CONTRACT_KEYWORDS` 扩展未回写(同 2026-05-18 段的 TODO)

### speak2go.ai 老师上课版部署(参照 well2go SOP)

> 第 4 个垂直产品:语言老师 / 口语训练 / 课堂场景。沿用 mini 多实例架构。

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
