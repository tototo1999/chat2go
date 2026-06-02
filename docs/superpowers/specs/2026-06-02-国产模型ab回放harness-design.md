# 国产模型 A/B 回放 Harness 设计文档

**日期**:2026-06-02
**状态**:设计已确认(brainstorm),待写实现计划
**背景**:微信小程序化要求 AI 后端换国产备案模型(见 `project_tradego_miniprogram_todo`)。本 harness 用现有 `trade_eval_traces`(小白真实请求语料)做离线 A/B,验证国产模型替代 Claude 后**全链路是否够用**。

---

## 1. 目标

对每条历史 trace × 每个候选国产模型,离线回放整条外贸跟单请求,验证 **recall(改预注入)+ 出单证(make_document)+ 会计 + 工具调用 + 格式** 整套不掉链子;自动打分 + 汇总记分卡,供决策"哪个国产模型可替代 Claude"。

**确认的参数**:
- **目标**:全链路能用(非只验 recall、非只比成本)。
- **模型**:DeepSeek V3 / 通义 Qwen / 豆包 Doubao / Kimi K2,共 4 个,对标 Claude(trace 里的原输出)。
- **判分**:结构检查(客观自动)+ LLM 评委(Claude 打质量分)。
- **范围**:全量现有 trace(~26 条,Phase 2;Phase 1 先 smoke)。

**非目标**:不改生产 worker;不真发消息/不真上传单证(只渲染校验);不做模型微调。

---

## 2. 架构(离线 harness,复用 worker 工具模块)

```
trade_eval_traces (Supabase, 小白真实请求)
   └─ 每条 trace × 每个国产模型:
        replay.run_one(trace, model)
          1. 取 trace.input_messages(原始对话历史)
          2. 预注入 recall:format_memory_block(frozen+candidate) + /memories 内容 → system prompt
                          （去掉原生 memory tool）
          3. 工具:Anthropic schema → OpenAI function schema
          4. OpenAI 式 tool-use 循环（调 OpenRouter）：
                model → tool_calls? → 执行(复用现有 Python 工具，写操作隔离) → 回灌 → 循环
          5. 捕获:output_text + 调用的工具(名+参数) + 单证是否渲染成功 + usage
          6. 打分:结构检查 + LLM 评委(Claude 直连)
        → 落 trade_eval_runs 表 + JSONL
   └─ 汇总:每模型记分卡(pass 率/均分/排名/失败清单)
```

**关键原则**:工具的**执行**复用现有模块(`trade_accounting`/`doc_render`/`doc_gen`/`trade_memory`),只**自建 OpenAI 式调用协议层** —— 这层正是将来国产迁移真要用的,非一次性。

---

## 3. 组件与文件(均在 chat2go repo `worker/eval/`)

| 文件 | 职责 |
|---|---|
| `worker/eval/openai_loop.py` | Anthropic tools schema → OpenAI function schema 转换;OpenAI 式 tool-use 循环(调 OpenRouter);工具 dispatch(复用现有执行 fn,写操作隔离)。**纯逻辑可单测的部分独立出来**。 |
| `worker/eval/recall.py` | 预注入 recall:从 `tradego_memory_rules`(frozen+candidate)+ `tradego_memory_files`(/memories)组装记忆块,拼进 system prompt。 |
| `worker/eval/scoring.py` | 结构检查(纯函数)+ LLM 评委(Claude 直连)调用 + rubric。 |
| `worker/eval/replay.py` | 编排:load trace → 跑模型 → 打分 → 落库/JSONL。 |
| `worker/eval/run_eval.py` | Modal job 入口(镜像带 openai+anthropic+weasyprint 等;secrets);批量跑 + 汇总记分卡。 |
| migration `trade_eval_runs` | 结果表(下方 §8)。 |
| `worker/eval/test_eval.py` | schema 转换 + 结构检查 纯逻辑单测。 |

---

## 4. 三个关键改造

### 4.1 模型换国产(OpenRouter)
- 统一走 OpenRouter 的 OpenAI 兼容端点:`client.chat.completions.create(model=<id>, messages, tools, tool_choice="auto")`。
- 候选 model id(**实现时用 OpenRouter 实际 id 核对,可能变**):
  - DeepSeek V3 → `deepseek/deepseek-chat`
  - 通义 Qwen → `qwen/qwen-max`(或百炼直连)
  - Kimi K2 → `moonshotai/kimi-k2`
  - 豆包 Doubao → OpenRouter **可能没有** → 火山方舟直连(OpenAI 兼容);实现时确认,缺则直连适配。
- Claude 基线:不重跑,直接用 trace 里记录的 `output_text` + `tool_steps`(已是真实历史)。

### 4.2 recall 换预注入(去原生 memory tool)
- 现状:Claude 靠原生 `memory_20250818` 工具 `memory view` 主动 recall(国产模型不支持)。
- 改:回放时**预先**把记忆注入 system prompt —— `trade_memory.format_memory_block(frozen, candidate)` + 读 `tradego_memory_files` 里该 expert 的 `/memories/*.md` 内容,整段(`<memory-data>` 包裹防注入)拼到 system 末尾。**工具列表里不含 memory 工具**。
- 这正是国产迁移的真实形态;harness 在验它够不够。

### 4.3 工具协议适配(核心工作量)
- 转换:Anthropic `{name, description, input_schema}` → OpenAI `{type:"function", function:{name, description, parameters:<input_schema>}}`(JSON Schema 近 1:1)。
- 循环:调 model → resp 有 `tool_calls` → 逐个解析 `function.name`+`arguments`(JSON) → dispatch 执行 → 结果作 `{role:"tool", tool_call_id, content}` 回灌 → 再调,直到无 tool_calls 或达 MAX_ITERS(8)。
- 工具集 = 现有 `ta.TOOL_SCHEMAS + dg.DOC_TOOL_SCHEMAS + dr.DOCUMENT_TOOL_SCHEMA + tm.ORDER_TOOL_SCHEMAS + remember`(去掉 memory 工具),全部转 OpenAI 格式。

---

## 5. 副作用隔离(eval 不污染生产)

回放时按工具分两类:
- **读/算类 → 真执行**:`calc_*`/`quote_*`/`order_pnl`/`fx_*`/`reconcile`(ta.dispatch)、`query_orders`、`make_document`/`make_excel`/`make_pdf` 的**渲染**(doc_render/doc_gen 出 bytes)。
- **写类 → 捕获不执行**:`remember`(不写 `tradego_memory_rules`)、`update_order_status`(不写 `tradego_orders`)、单证生成的**上传**(不写 Storage/messages)。这些只记录"模型想写什么"(intent + 参数),用于打分,不落库。
- 实现:eval 专用 dispatch 包一层,写类工具返回成功 stub + 捕获参数;`make_*` 渲染出 bytes 后只取 `{generated:true, bytes_len, text_extract}`,不调上传。

---

## 6. 打分

### 6.1 结构检查(纯函数,客观,对标 trace 里 Claude 的行为)
对每条 trace×model 算:
- `tools_match`:国产调用的工具名集合 vs Claude(trace.tool_steps 里的 tool_uses 名,排除 memory)。指标 = |交集| / |Claude 应调集合|。
- `doc_generated`:若 Claude 在该 trace 生成了单证(调了 make_document/excel/pdf),国产是否也调了**且**渲染出有效 bytes(PDF>2KB / xlsx 合法)。bool。
- `recall_hit`:若该 trace 涉及 recall(Claude 调了 memory view,或已知记忆事实出现在期望输出里),国产输出是否**包含正确事实**(对该 expert 的已知记忆关键词做包含检查,如 "CNF 釜山"/"尾款见提单"/对应客户名)。bool / NA。
- `format_ok`:输出是连贯文本/markdown、无异常、无空输出。bool。

### 6.2 LLM 评委(Claude 直连)
- 输入:该轮用户请求(最后一条 user 消息)+ 注入的记忆 + Claude 原输出(trace.output_text)+ 国产模型输出。
- rubric(各 1–5)+ 总判(pass/fail)+ 一句理由:
  1. 准确性(金额/数据/客户事实对不对)
  2. 完整性(该出的单证/条款/追问都到位)
  3. 专业度(外贸口径、单证规范)
  4. 与 Claude 一致度(关键结论是否一致;允许风格差异)
- 评委用 StructuredOutput(强制 JSON),防解析失败。

---

## 7. 产出

- **每条×模型**:落 `trade_eval_runs` 表 + 本地 `worker/eval/results/<date>.jsonl`(含输出全文 + 工具调用 + 结构分 + 评委分 + usage,供人眼 drill-down)。
- **汇总记分卡**(markdown,打印 + 存文件):每模型一行 —— trace 数 / tools_match 均值 / doc_generated 通过率 / recall_hit 命中率 / format 通过率 / 评委均分 / 综合 pass% / 排名;附**失败清单**(trace_id+model+失败项)给人眼抽查。

---

## 8. `trade_eval_runs` 表(migration)

```sql
create table trade_eval_runs (
  id uuid primary key default gen_random_uuid(),
  trace_id uuid references trade_eval_traces(id),
  model text not null,
  output_text text,
  tool_calls jsonb,        -- 国产调用的工具(名+参数+渲染结果摘要)
  structured jsonb,        -- {tools_match, doc_generated, recall_hit, format_ok}
  judge jsonb,             -- {accuracy, completeness, professional, consistency, verdict, reason}
  usage jsonb,             -- {input_tokens, output_tokens, ...}
  run_batch text,          -- 本次跑的批次标签(便于多轮对比)
  created_at timestamptz not null default now()
);
create index idx_eval_runs_batch_model on trade_eval_runs(run_batch, model);
```

---

## 9. 运行环境

- **Modal job**(`chat2go-eval` app):镜像复用 worker 同款(weasyprint/字体/工具模块)+ 加 `openai` 包;secrets 用现成的(需 `OPENROUTER_API_KEY` 调 4 模型 + `ANTHROPIC_API_KEY` 当评委)。
- 离线、不影响生产 worker。
- 若 secrets 里没有 `OPENROUTER_API_KEY`:实现时先 `modal secret` 加(或确认现有 chat2go-extras 里有)。

---

## 10. 错误处理
- 模型 API 报错/超时 → 该 run 记 `fail`(reason),不中断整批。
- tool_calls 的 arguments JSON 解析失败 → 记 `format_ok=false` + reason,继续。
- 单证渲染异常 → `doc_generated=false` + reason。
- 评委调用失败 → 重试 1 次,仍失败则跳过评委、保留结构分(标 judge=null)。
- 豆包无 OpenRouter id → 跳过该模型 + 日志说明,不阻断其余 3 个。

---

## 11. 测试
- 纯逻辑单测(`test_eval.py`):① Anthropic→OpenAI schema 转换正确(名/描述/parameters);② 结构检查函数(给构造的 trace + 输出,断言 tools_match/doc_generated/recall_hit/format_ok)。
- **Smoke(Phase 1 关卡)**:1 条 trace × DeepSeek V3 跑通端到端,人看一眼输出合理 → 再批量。

---

## 12. 落地节奏
- **Phase 1**:harness 骨架(openai_loop + recall + 隔离 dispatch + scoring 结构检查)+ DeepSeek V3 smoke 1 条跑通。
- **Phase 2**:接 LLM 评委 + 其余 3 模型 + 全量 ~26 条 + 汇总记分卡 + `trade_eval_runs` 表。

## 自查
覆盖:全链路(§2/4/5)、4 模型(§4.1)、recall 预注入(§4.2)、工具适配(§4.3)、副作用隔离(§5)、结构+评委打分(§6)、汇总产出(§7/8)、运行环境(§9)、全量范围(§1/12)。无占位;model id 标注"实现时核对"非占位(是真实不确定项,已给 fallback 策略)。
