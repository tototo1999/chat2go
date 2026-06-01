# Trade2GO 国产模型复用 — 储备方案(暂不执行)

> 状态:**储备 / 待命**。2026-06-01 决策:**现在只备方案,不碰生产、不跑 A/B**。原因:还有很多真实业务流程没跑出来,样本不足。
> **计划 A/B 触发时间:~2026-07-01**(约一个月后,真实业务流程跑够之后)。
> 本文目标:一个月后能照着这份直接执行,不用重新调研/设计。

---

## 0. 一句话

整套架构(`anthropic` SDK + `base_url` 路由 + tool_use + `cache_control`)对国产模型**复用性很高**,切换成本 ≈ 改 `base_url` + `api_key` + `DEFAULT_MODEL` 三处,跟已做过的 OpenRouter 切换同构。**唯一真正要验的是:tool-use 循环(会计 7 工具 + 出 PDF)和读图 Vision 在国产模型上稳不稳。** 其余(WeasyPrint/reportlab 出 PDF、Decimal 会计、订单/记忆业务逻辑)与模型无关,零风险复用。

---

## 1. 复用面盘点

| 能力 | 复用 | 备注 |
|---|---|---|
| `anthropic` SDK + base_url 路由 | ✅ 原样 | `_anthropic_client` 已有 `force_direct` 条件路由,加个 provider 分支即可 |
| tool_use(会计/订单/记忆/make_document) | ⚠️ 要实测 | 协议透传 OK,但多工具循环可靠性按模型差异大 |
| prompt caching(`cache_control`) | ⚠️ 优雅降级 | 国产多为**自动上下文缓存**(DeepSeek/Kimi),`cache_control` 多半被忽略但不报错,自动缓存照样省 |
| 读图 Vision(读单据/挑公章) | ⚠️ 要实测 | 经 Anthropic-skin 的视觉支持参差 |
| WeasyPrint/reportlab 出 PDF、会计 Decimal | ✅ 100% | 自己的确定性代码,与模型无关 |
| Excel/订单状态机/记忆 业务逻辑 | ✅ 全复用 | — |

---

## 1b. 记忆系统可移植性(关键 — 回答"换模型影响多大")

**核实结论(2026-06-01,grep worker 源码):当前已上线的 tradego 记忆系统 0 个 Anthropic beta 依赖,100% 可移植。**

现状(`trade_memory.py`)三件套,全部模型无关:
1. **纯文本注入** —— 冻结规则 + 订单双时序当前态拼成文本进 system prompt(`format_*_for_prompt`)。
2. **普通自定义工具** —— `update_order_status` / `query_orders` / `remember`,标准 function calling,非 Anthropic 专有工具类型。
3. **Supabase 存储** —— `tradego_orders` / `tradego_memory_rules` / company profile。

| | 换模型影响 |
|---|---|
| 已上线记忆(注入+自定义工具+Supabase) | 🟢 ≈ 0,直接复用 |
| 将来用 Anthropic 原生 `memory_20250818` tool | 🟡 中等但可规避:用自定义工具重写即跨模型,少的是 Claude 调教好的记忆行为 |
| 将来依赖 context-management/compaction beta(服务端压缩长上下文)| 🔴 不可移植 —— 但 tradego 单房 + `HISTORY_LIMIT=40` 自管上下文就够,不一定需要 |

**设计铁律(保住可移植性)**:记忆路线图坚持「文本注入 + 自定义工具 + 自管上下文」(现在已在走的路);把 Anthropic 原生 memory tool / compaction 当作**仅 Claude 时的"增强模式"**,不要做成地基。

> 附带:当前 worker **没用任何 beta**,所以 trade 房 `force_direct=True` 现在不是被 live 功能强制的(给未来预留)。换国产时调这个分支即可,功能不断。

---

## 2. 候选模型(2026 年都已开 Anthropic 兼容端点)

| 模型 | Anthropic 端点 | 定位 |
|---|---|---|
| **Kimi K2.6**(Moonshot)| `https://api.moonshot.cn/anthropic` | 🥇 首选 pilot。为 agentic/工具调用而生,重 tool-use 的外贸流最稳;中文好 |
| **DeepSeek V4** | `https://api.deepseek.com/anthropic` | 💰 最便宜 + 自动缓存;多工具循环可靠性需重点测 |
| **GLM-5.1**(智谱/z.ai)| `https://api.z.ai/api/anthropic` | 工具调用 + 中文都不错 |
| **Qwen 3.6**(阿里 DashScope)| `https://dashscope.aliyuncs.com/apps/anthropic` | 企业级生态最稳 |
| MiniMax M2.7 | `https://api.minimaxi.com/anthropic` | 备选 |

> 端点/模型 id 一个月后**执行前再核一遍**(国产迭代快,版本号会变)。用 Context7 / 官网查当前 id。

---

## 3. 代码改动规格(待应用,现在不改)

在 `worker/chat2go_worker.py` 的 `_anthropic_client` 加一个 **provider 开关**,env 未设时**完全不改变现有行为**(dormant):

```python
# 规格示意 — 一个月后执行时再落地
CN_ENDPOINTS = {
    "kimi":     ("https://api.moonshot.cn/anthropic", "MOONSHOT_API_KEY",  "kimi-k2-..."),
    "deepseek": ("https://api.deepseek.com/anthropic", "DEEPSEEK_API_KEY",  "deepseek-chat"),
    "glm":      ("https://api.z.ai/api/anthropic",      "ZHIPU_API_KEY",     "glm-4.6"),
}

def _anthropic_client(force_direct=False):
    from anthropic import Anthropic
    cn = os.environ.get("CN_PROVIDER", "").strip().lower()   # 空 = 关,现有行为不变
    if cn in CN_ENDPOINTS and not force_direct:
        base, key_env, _ = CN_ENDPOINTS[cn]
        return Anthropic(api_key=os.environ[key_env], base_url=base)
    or_key = os.environ.get("OPENROUTER_API_KEY")
    if or_key and not force_direct:
        return Anthropic(api_key=or_key, base_url="https://openrouter.ai/api")
    return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
```

`DEFAULT_MODEL` / `DIRECT_MODEL` 同理按 `CN_PROVIDER` 取对应 id。
**可逆**:删 `CN_PROVIDER` secret + redeploy 即回退,与现有 OpenRouter/直连开关同构。

> ⚠️ 注意:外贸房现在是 `force_direct=True`(为 memory beta 直连 Claude)。要测国产模型需临时让 trade 房也走 CN 分支,或只在**测试房**灰度——见 §4。

---

## 4. A/B 执行清单(~2026-07-01 真跑时照做)

1. **只在测试房灰度**:iamarobot 房 `38ebcd0e`,**别碰小白实时房 `0ac15b5b`**。
2. 准备 key:Kimi(`MOONSHOT_API_KEY`)、DeepSeek(`DEEPSEEK_API_KEY`)各一把,进 Modal secret。
   - ⚠️ openclaw 明文里那把 Moonshot key **必须先轮换**再用新的(参 [[project_local_hermes_node_agent]] 待轮换清单)。
3. 落地 §3 代码 + 按 provider 选 model id → `modal deploy`。
4. **三个真实场景验收**(三个都过才考虑放量):
   - ① 报价/PI **出 PDF**(tool-use 循环 + make_document)
   - ② **会计核算**(7 工具:calc_unit_cost / quote_from_margin / order_pnl / fx_convert / export_rebate / commission / reconcile)
   - ③ **读单据图**(Vision)
5. 看 `modal app logs chat2go-worker` 的 usage 行(已加)对比 token/缓存命中;人工评回复质量 + 中文外贸口吻。
6. 出结论:Claude vs Kimi vs DeepSeek 的 质量 / 成本 / tool-use 可靠性 三维对比。

## 5. 回滚
删 `CN_PROVIDER`(及对应 key)secret + `modal deploy` → 立即回到当前 Claude/OpenRouter 路由。生产房全程不受影响(只测试房灰度)。

## 6. 现在(储备阶段)不做
- ❌ 不改 worker 代码 ❌ 不进 CN key ❌ 不跑 A/B ❌ 不碰生产房。
- ✅ 只留这份文档 + 等一个月真实业务流程跑够。

---
关联:[[project_worker_via_openrouter_2026_05_31]](同构的 base_url 切换)· [[project_tradego_accounting_multimodal]](要验的 tool-use/读图能力)· [[feedback_saas_self_hosted_bias]](选型先列候选 + Context7 查现状)
