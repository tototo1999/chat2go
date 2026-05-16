# 2026-05-15 版本清单

> 一天 **47 commit**(chat2go 31 + chat2go-agent 16)。
> 重大里程碑:**大咖学习闭环首次端到端验证通过**(命理 vs 算命场景)。
> 重大决策:**放弃自研 chat2go-agent,迁纯 Hermes 生态**(明日 Phase 1 起)。

---

## chat2go(前端 + Supabase)— 31 commits

### 品牌/域名(7)
| hash | 主题 |
|---|---|
| c0d0ff4 | chore: 全站品牌对齐为 Chat2GO.Ai |
| acab4a2 | ui: logo .ai 改小写 + 缩小字号,正文统一 Chat2GO.ai |
| 13cbc69 | ui: chat.html 里森山的人设名对齐为「森山大道san命理教室」 |
| 4f201cc | chore: 主域名切到 chat2go.ai(.cn 后续做跳转) |
| f5d3bef | fix: CNAME 救火回 chat2go.cn |
| 547e8d9 | docs: HANDOFF 增量更新到 v0.7.10 |

### Sidebar Todo 方案库(7)
| hash | 主题 |
|---|---|
| 29a8bf2 | feat: sidebar todo 改大咖个人方案库 + dropdown 切换 + inline 编辑 |
| 02dce21 | fix: todo 编辑态在非首组加子项时该组被自动折叠 |
| 3dd3837 | fix: todo 方案 popup 被 sidebar 截断 + 编辑确认 affordance |
| d7f3af4 | feat: 方案 popup 加删除按钮 |
| ae90a02 | fix: todo-body 独立滚动,长方案不再溢出 sidebar |
| b957895 | feat: 编辑态可改方案名 |

### 房间标题 / 人设名解耦(6)
| hash | 主题 |
|---|---|
| e9d075f | feat: sidebar 房间主题可独立编辑(与大咖 display_name 解耦) |
| 4b97b82 | ui: 房间标题编辑挪到设置页(极简胶囊 + 10 字限制) |
| a08d505 | ui: 房间标题限制 10 → 13 字 |
| 5a67a75 | ui: 设置页合并保存 — 房间标题 inline 进个人资料块 |
| 88f594d | ui: 设置页「保存」按钮挪到「个人资料」标题右侧 |
| 89d7e28 | ui: 设置页保存按钮恢复原 size(覆盖 .btn-cancel 的 flex:1) |

### 邀请 / 昵称流程(5)
| hash | 主题 |
|---|---|
| 4c48e1b | fix: 邀请链接进入 — 已登录但缺 display_name 也强制补昵称 |
| 381f5ea | fix: 邀请链接进入总弹昵称 modal(input 预填现昵称可改可直进) |
| 2617ceb | ui: 设置弹层去掉底部「关闭」按钮,保存后自动关 |
| 355516c | fix: 邀请进入改昵称没生效(upsert 错误被吞 + role 覆盖隐患) |
| 20ec0ab | ui: 自己消息头像点击进设置(小白也能改昵称) |

### Token 用量进度环(4)
| hash | 主题 |
|---|---|
| 245f835 | ui: token 用量前加进度环图标(Claude 客户端风) |
| 91f9dff | ui: token 用量分母改为房间预算 10000(不再按模型 context window) |
| 6892964 | ui: token 用量分母后加「Token」单位 |
| 489fd7b | ui: token 用量环放大(13→17) + 改用更鲜明的配色 emerald/amber/red |

### Memory / 信号格 / Bridge(4)
| hash | 主题 |
|---|---|
| 406293d | fix: 路人/小白不能重启 hermes bridge |
| **ed2e7db** | **fix: memories INSERT 策略 + 信号格连续失败转 offline** ★ |
| ae9a86b | ui: 信号格 SVG 并入 bridgeStatus,跟呼吸灯一起反映 bridge 状态 |
| 6b80532 | ui: bridge 离线时信号格变红 ✕ + dot 也变红,更醒目 |

---

## chat2go-agent(Python bridge 包)— 16 commits

### 品牌/域名(3)
| hash | 主题 |
|---|---|
| 18da21d | chore: 跟随主域名切换,文档与默认提示改 chat2go.ai |
| 52fdee1 | chore: chat2go-agent 全包品牌对齐为 Chat2GO.Ai |
| 2261f1b | chore: 品牌字样小写化为 Chat2GO.ai |

### Memory / Skills 重构(3)
| hash | 主题 |
|---|---|
| 8768258 | feat(memory): Phase B 大咖纠正自动沉淀 + 接入 DSPy 远程记忆 |
| 3601bb6 | refactor(skills): SKILL.md 只保留 frontmatter,行业 prompt 移交大咖 |
| c9034b1 | fix(memory): sync_memory 异常防御 + LLM 原始输出可诊断 |

### Memory 写入路径 6 层 bug 链(10)★★★
| hash | 主题 |
|---|---|
| **163a133** | **fix(memory): `_EXTRACT_PROMPT.format()` 抛 KeyError(JSON 示例花括号被误当占位符)** |
| **ee60c20** | **fix(bridge): `asyncio.create_task` 协程被 GC 静默回收 → 加 `_bg_tasks` 集合持引用** |
| 55c774c | debug(memory): 加 sync_memory 入口 print 确认协程是否被执行 |
| f44427f | fix(memory): asyncio.wait_for 硬超时 15s,避免 macOS DNS 卡死 |
| 520edfc | debug(memory): 加 '准备调 LLM 提取' print,定位是 import 卡还是 await 卡 |
| **24b1d2a** | **fix(memory): asyncio.wait 而非 wait_for,真正硬超时不被 cancel-and-wait 卡** |
| d7e8ac5 | debug(memory): 加 wait 前后 print 定位卡点 |
| ab5e371 | fix(memory): 无事实可记的路径也打 log,避免误以为是 hang |
| **93f4aa9** | **fix(memory): max_tokens 512 → 2048,避免 LLM JSON 输出被截断** |
| **4d72677** | **fix(memory): timeout 加大 — 内 httpx=30s 外 wait=25s,适配 Gemini 2.5 Pro JSON 耗时** |

---

## 关键里程碑

1. **memories 表 RLS INSERT 策略落库**(`supabase/migrations/20260515200000_memories_insert_policy.sql`)
   —— Phase B 写入路径正式打通。
2. **学习闭环端到端验证通过** —— 大咖发「命理是科学,算命是神学」→ Gemini 提取 fact 落库 → 新进房 focal user Lexi 说「算命可以吗」→ AI 主动纠正「我们一般不叫'算命'」。无人工 prompt-engineering,纯数据驱动。
3. **方向决策** —— 自研 agent 6 层 bug 揭示了「重写 = 把 Hermes 经验从头踩」的代价,明日起按 4 阶段迁纯 Hermes 生态(详见 memory `chat2go-migrate-to-pure-hermes.md`)。

## 明日计划速览(供 git blame 时回溯用)

- Phase 1 双跑验证 Hermes 接得住(30 min)
- Phase 2 补 model_usage 只写 token 数(30 min,计费砍掉)
- Phase 3 补 bridge_state 心跳 + 重启(1 h)
- Phase 4 chat2go-agent 就地手术 + rename → `chat2go-hermes-platform`(30 min)

终态:< 800 行(对比当前 ~3000 行,削 70%)。
