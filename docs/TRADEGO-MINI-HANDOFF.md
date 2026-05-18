# TradeGO Mac mini 部署交接

> 给 Mac mini 上 Claude Code 的接手文档。dev 机这边把 Hermes 跑起来了,接下来 persona / skill / 大咖训练在 mini 本地继续。

## 部署现状(2026-05-17 16:04)

**机器**:`lexideMac-mini.local` / `192.168.1.111`,用户 `lexi`,HOME `/Users/lexi`

**Hermes**:`/Users/lexi/.hermes/hermes-agent/` (git checkout,**不是** pip install)
- venv:`/Users/lexi/.hermes/hermes-agent/venv/`(uv 装的,默认无 pip。`python -m ensurepip` 已注入)
- 启动方式:launchd `~/Library/LaunchAgents/ai.hermes.gateway.plist`,KeepAlive
- 日志:`~/.hermes/logs/gateway.{log,error.log}`
- brain:`~/.hermes/config.yaml` → `model.default: deepseek-chat`(= DeepSeek V3),provider=deepseek
  - 历史:2026-05-17 早 init 时是 `anthropic/claude-opus-4.6`,当天晚切 `claude-sonnet-4-6`,最终切到 `deepseek-chat`(便宜+快+稳)
  - vision:`auxiliary.vision.provider=anthropic, model=claude-haiku-4-5`(显式指定,避免 main=deepseek 不支持 vision 时 auto resolution 兜底失败)
  - 切换 SOP:`ssh lexi@192.168.1.111 "sed -i '' 's|^  default:.*|  default: NEW_MODEL|' ~/.hermes/config.yaml && launchctl kickstart -k gui/\$(id -u)/ai.hermes.gateway"`

**chat2go 接入**:
- 账号:`388388@vip.163.com`(外贸大咖独立账号)
- expert_id:`5dcec9b4-18a8-405b-837b-10bc27de114c`
- agent_key:`c2g-key_3d9bc8bf6198e9d8230a4fad0cb4f53a2eaafa5f091c8556f08c0c5b678dacaa`
- 子站:https://chat2go.cn/tradego/(industry='外贸跟单', product='tradego')

**已装组件**:
- chat2go adapter:`~/.hermes/hermes-agent/gateway/platforms/chat2go.py`(从 dev 机整文件复制)
- chat2go 集成 7 个文件(从 dev 整文件覆盖):`agent/prompt_builder.py` / `gateway/config.py` / `gateway/run.py` / `hermes_cli/gateway.py` / `hermes_cli/platforms.py` / `tools/send_message_tool.py` / `toolsets.py`
- 合同生成依赖:`~/.hermes/libs/{chat2go_upload,contract_generator,contract_lib}.py`
- 外贸 skill:`~/.hermes/skills/productivity/trade-go/`(SKILL.md + references/{documents,email-templates}.md)
- Python 依赖:`supabase httpx certifi pypdf python-docx` 已装在 hermes venv
- YUANBAO enum stub:`gateway/config.py` 第 71 行加了一行(`hermes update` 后会丢,见 `docs/hermes-patches/03-yuanbao-enum-stub.patch`)
- chat2go.py 三处新逻辑(2026-05-17 晚同步,见 patch 02):
  1. `_read_hermes_default_model()` — stub_model 自动跟随 `config.yaml`,切模型不用动 env
  2. `_watchdog_loop()` — 监控 _poll_loop 卡死,>60s 没心跳 `os._exit(1)` 让 launchd 拉起
  3. vision pre-process — 收到带图消息先调 `vision_analyze_tool`(走 `auxiliary.vision`)转文字,不再把 image_url 直传给 main(避免 DeepSeek 等不支持 vision 的 main 拒收)

**.env 关键变量**(`~/.hermes/.env`):
```
ANTHROPIC_API_KEY=sk-ant-...   (mini 自己原有,未动)
CHAT2GO_TOKEN=c2g-key_3d9b...
CHAT2GO_ALLOW_ALL_USERS=true
CHAT2GO_SUPABASE_URL=https://qjnagbzqhoansixqharb.supabase.co
CHAT2GO_SUPABASE_ANON_KEY=eyJ...
```

## 健康检查命令

```bash
# launchd 状态
launchctl print gui/$(id -u)/ai.hermes.gateway | grep -E 'state|pid'

# 看最近 log
tail -30 ~/.hermes/logs/gateway.log

# 强制重启
launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway

# 看 chat2go 连接 + room 加载
tail -50 ~/.hermes/logs/gateway.log | grep -i chat2go
```

期望看到:
```
Chat2GO authenticated: 388388@vip.163.com (expert=5dcec9b4)
Chat2GO: loaded N rooms
✓ chat2go connected
Gateway running with 1 platform(s)
```

## 已知非致命 warning

- `Channel directory build failed: 'coroutine' object has no attribute 'get'` —— dev 机的 7 个文件版本与 mini base 不完全对齐,出站消息路由的 channel directory 没建起来,但 chat2go adapter 自己收发不依赖它,不影响外贸房间消息往返。

## 未解决问题 (mini Claude 接手第一件事)

dev 这边消息收发链路还没完全跑通,卡在版本错配的连环 ImportError/AttributeError 上。dev 机 `~/.hermes/hermes-agent/` 是 2026-04-23 的老 commit (d1ce3586),mini base 是更新的 (bc7c608d5)。整文件覆盖 7 个文件后,mini base 其他文件仍然 reference dev 老版没定义的符号。

**已修两个**(stub 加在 mini 的相应文件里 + 仓库存了 patch):
- `Platform.YUANBAO` 缺失 → `gateway/config.py` 第 71 行加 enum stub (`03-yuanbao-enum-stub.patch`)
- `HERMES_AGENT_HELP_GUIDANCE` 缺失 → `agent/prompt_builder.py` 末尾加空字符串 stub (`04-help-guidance-stub.patch`)

**最后状态**:`16:22:34` Hermes 重启完连上 chat2go,但用户没再发测试消息验证,所以不确定下一次发消息会不会还有新的版本错配 ImportError。

**接手第一动作**:
1. 在 tradego 房间发个 `写个 PI 给印度客户 5000 美金 FOB 深圳`
2. `tail -f ~/.hermes/logs/gateway.log` 看是否还有新 ImportError / AttributeError
3. 如果有,用同样模式修(加 stub 在 mini 上 + 同步 patch 到 `~/chat2go/docs/hermes-patches/`)
4. 如果消息真跑通,就开始 Phase B/C(skill 调试 + 合同 PDF 链路)

**根本解决路径(可选,如果 stub 越加越多就值得做)**:
- 让 dev 机 hermes-agent `git pull` 升到跟 mini 一样的 commit
- 重新生成 chat2go 集成 7 个文件的 diff
- 重新走 `docs/hermes-patches/` patch 流程
- 这样 stub 就都不需要了

## ⚠ 安全注意:CHAT2GO_TOKEN

`scripts/tradego-mini/env.template` 里 `CHAT2GO_TOKEN=c2g-key_3d9b...` 是**真**外贸大咖 agent_key。仓库 `tototo1999/chat2go` 是 **public** GitHub repo,这文件**没 commit**(dev 端 untracked)。

若 mini Claude 要把部署包 commit + push 到 GitHub,**必须**先做以下任一:
- 把 env.template 里 token 改成 `__FILL_ME__`,重构 deploy.sh 让 token 走 env 变量传入
- 在 chat2go.cn revoke 这把 key + 生新的更新 mini .env,旧 token 失效后 template push 无害
- 把 env.template 加 .gitignore 不入仓库

**决策权交给 mini Claude / 用户**,dev 这边没动。

## 接下来 mini 本地 Claude 的任务

### Phase A:验证收发(优先做)
1. 在 chat2go.cn/tradego/chat.html 发条 `帮我写个 PI 给印度客户 5000 美金 FOB 深圳`
2. 看 mini log 有没有 inbound + AI 回复
3. AI 回复内容:确认是 trade-go skill 的格式(PI 模板/Incoterms 等)
4. 若 AI 报错,贴 stack trace 让 mini Claude 诊断

### Phase B:trade-go skill 完善
- skill 当前在 `~/.hermes/skills/productivity/trade-go/`,覆盖 12 类邮件模版 + 4 种单证 + 报价计算 + Incoterms
- 真实跑通后,看 AI 回复是否够"外贸大咖口吻"(术语/格式),不够就改 SKILL.md
- 可以加更多 references/:HS 编码表 / 主要市场买家偏好 / 不同付款方式风险等

### Phase C:合同 skill 触发链路
- chat2go.py adapter 第 357-364 行有个 `_try_handle_tradego_contract` 拦截器:room.product='tradego' + 合同关键词 → 绕开 brain 直接渲染 PDF 上传
- 关键词清单见 chat2go.py 第 930 行附近
- 测试方式:在 tradego 房间发 `给阿里巴巴印度站客户出个 PI,LED 灯 5000 美金 FOB 深圳`,看是否直接生成 PDF 附件(走 contract_generator)而不是 AI 文字回复
- contract_generator.py 依赖 weasyprint?reportlab?(让 mini Claude 看一下源码)

### Phase D:大咖训练 / memory
- `_sync_memory` 已经在跑(每条大咖发言后异步提取 fact 写 chat2go memories 表)
- 用 388388@vip.163.com 在 chat2go.cn 登录大咖视图,纠正 AI 的回复(说"不对,应该是 XXX"),看下次同类问题 AI 会不会自动用纠正过的版本

## 注意事项 / 坑

1. **不要在 mini 上用同一个 CHAT2GO_TOKEN 启动第二个 Hermes** —— 会跟当前 launchd 抢同一 expert_id 的房间,AI 回两遍。
2. **dev 机和 mini 不共享 token** —— dev 机的 Hermes 用 dev 自己的 chat2go 账号 token,只接 dev 那批 room;mini 接外贸大咖账号,只接 tradego 房间。
3. **改 chat2go.py 后**记得同步回 dev 机的 `~/chat2go/docs/hermes-patches/02-chat2go-platform-adapter.patch`,否则下次重装会丢。
4. **brain 模型切换**:改 `~/.hermes/config.yaml` 的 `model.default`,然后 kickstart 重启 launchd。chat2go.py 的 stub_model 会自动跟随,前端 brain badge 会显示新模型简称。

## 部署脚本位置(dev 机)

`/Users/dami2026/chat2go/scripts/tradego-mini/{deploy.sh,env.template,plist.template}`

若要重装,在 dev 机跑:
```bash
bash /Users/dami2026/chat2go/scripts/tradego-mini/deploy.sh lexi 192.168.1.111
```
(脚本会自动:推 chat2go.py / libs / trade-go skill,upsert .env,装 plist,kickstart launchd)

## 相关 memory

`~/.claude/projects/-Users-dami2026-chat2go/memory/project_hermes_routing.md` —— Hermes 多机路由模型(按 expert_id 隔离),为什么不能共用 token。
