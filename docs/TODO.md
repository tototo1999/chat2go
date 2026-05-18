# Chat2GO TODO(滚动清单)

> 形式:按计划日期分段;做完 `[x]`,新加 `[ ]` 追加到当天那段。
> 跨天没做完的不挪,留在原日期,显示"延期"。

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

### 文档

- [ ] **`TRADEGO-MINI-HANDOFF.md`** 加"如何只单文件同步 chat2go.py 到 mini"的安全 SOP(避免下次又触发 deploy.sh 全套覆盖风险)

### mini 多大咖部署模板

- [ ] **改造 `scripts/tradego-mini/deploy.sh` → `scripts/deploy-expert.sh`**:参数化部署任意行业大咖
  - 参数:`<industry> <ssh_user> <ssh_host> <chat2go_token> <model_provider> <model_default>`
  - 例:`deploy-expert.sh fitness lexi 192.168.1.111 c2g-key_xxx anthropic claude-haiku-4-5`
  - 关键:每个大咖独立 `~/.hermes-<industry>/` 目录(独立 venv/config.yaml/.env/logs),launchd label 也带行业前缀 `ai.hermes.gateway.<industry>`
  - 同步代码用 git pull 而不是 rsync(避免覆盖 mini 本地 persona/skill 改动)
- [ ] **mini 容量计算公式 + 当前占用情况** 写进 `TRADEGO-MINI-HANDOFF.md`:稳态 RSS / 网络 / API rate limit 三条天花板
- [ ] **mini 服役大咖清单**:跑个简单脚本扫 `~/.hermes-*` 目录,输出 `[industry, expert_id, model, status, last_activity]`,方便快速看健康状态
