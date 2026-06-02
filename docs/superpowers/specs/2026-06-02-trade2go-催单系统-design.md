# Trade2GO 全平台催单系统 — 设计(Phase 1)

> 状态:Phase 1 设计已经用户确认(2026-06-02)。Phase 2/3 仅列方向,各自另开 spec。

## 背景 / 问题

外贸跟单是多线程碎片化工作:一个订单同时有定金、交期、船期、尾款等多个时间点要盯。
当前 Trade2GO AI 是「你发消息它才回」的请求-响应模型,**无法主动提醒**,这是它对用户陈述的
唯一真限制。用户要求突破这条,做成一套**全平台催单系统**:后端定时扫描临近/逾期的跟单事项,
主动把催单送达用户,通道支持房间内留言、邮件、微信、短信。

关键事实(2026-06-02 勘查):
- `tradego_orders` 当前**无任何日期字段**(只有 customer/product_desc/amount/currency/status + 双时序 valid_from/valid_to)。
- 前端(`tototo1999/tradego` 的 chat.html)**无 service worker / PWA / manifest / Notification** 基建。
- Modal worker 目前只有一个 `ingest` web 端点,**无定时任务**,但 Modal 原生支持 `modal.Cron`。
- 中国环境约束:浏览器 Web Push 走 Google FCM,国内基本被墙不可靠;邮件 / 微信 / 短信 / 房间内留言均通。

## 架构总览 — 通道无关的「催单引擎」+ 可插拔通道适配器

```
催单引擎(共用核心)
 ├─ ① 提醒数据      :新表 tradego_reminders(每单可挂多条带日期的待办)
 ├─ ② AI 记提醒     :新工具 set_reminder / complete_reminder;pending 提醒注入 system prompt
 ├─ ③ 定时扫描器     :Modal Cron 每天扫「临近到期 / 逾期」的 pending 提醒
 ├─ ④ 催单规则       :提前 lead_days 提醒、逾期升级、每条每天最多发一次(去重)
 └─ ⑤ 派发层(适配器):统一接口 dispatch(reminder, channels) → 各通道实现
        ├─ 📥 房间内留言  in_room   ← Phase 1(零依赖,国内必通)
        ├─ 📧 邮件        email     ← Phase 2(Resend/SMTP,免审批)
        ├─ 📱 短信        sms       ← Phase 3(阿里/腾讯云,签名报备+计费)
        └─ 💬 微信        wechat    ← Phase 3(认证服务号模板消息,营业执照+模板审批)
```

引擎(①②③④)所有通道共享;通道只是末端插头。**Phase 1 建好引擎 + in_room 适配器**,
后续通道作为新的 dispatch 实现逐个接入,互不阻塞。

## Phase 1 详细设计

### ① 数据模型 — 新表 `tradego_reminders`

```sql
create table if not exists tradego_reminders (
  id            uuid primary key default gen_random_uuid(),
  room_id       uuid not null references rooms(id) on delete cascade,
  order_id      uuid references tradego_orders(id) on delete set null,  -- 可空:也允许无单提醒
  expert_id     uuid not null,
  product       text not null default 'tradego',
  kind          text not null,          -- 尾款/船期/交期/定金/跟进/自定义(自由文本)
  note          text not null,          -- 催单内容,如「催 ACME 尾款 $5000」
  due_date      date not null,          -- 到期日
  lead_days     int  not null default 2,-- 提前几天开始提醒
  status        text not null default 'pending', -- pending|done|dismissed|snoozed
  last_fired_on date,                    -- 去重:最近一次已发催单的日期(每条每天最多一次)
  fire_count    int  not null default 0,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index if not exists idx_tradego_reminders_scan
  on tradego_reminders(status, due_date) where status = 'pending';
-- RLS:沿用 tradego 表惯例(read own / service-role 写)。worker 用 service-role 绕过。
```

设计取舍:
- **独立表而非订单加列**:一个订单多个并发时间点(定金/尾款/船期…),且催单是这套系统的核心实体,
  独立表天然支持「每单多条」、便于派发层按条处理、易扩展多通道。
- `order_id` 可空:允许「无关联订单」的纯提醒(如「周五前给客户报新价」)。
- `last_fired_on` 用 **date** 而非 timestamptz:去重粒度就是「每天一次」,date 比较最直接。

### ② AI 怎么记提醒 — 2 个新工具 + 注入 prompt

新工具(挂进外贸房 tool-use 循环,schema 放 `trade_reminders.py`):
- `set_reminder(customer?, kind, note, due_date, lead_days?)`
  - 跟单聊到「6 月 10 号要付尾款」→ AI 自动挂一条。
  - `customer` 用于关联到对应活跃订单的 order_id(按 room + customer 匹配最新活跃单;匹配不到则 order_id 留空)。
  - `due_date` 传 ISO date 字符串(YYYY-MM-DD)。AI 不要编日期,缺就追问。
- `complete_reminder(reminder_ref | customer+kind)`
  - 用户说「尾款收到了」→ AI 标记对应提醒 status=done。
  - Phase 1 匹配策略:按 room + customer + kind 命中 pending 的最近一条;命中多条时在 note 里消歧后再标。

注入:当前 room 的 **pending 提醒**像活跃订单一样,在 `_resolve_system_prompt` / 外贸 prompt 拼装时
格式化注入 system(新函数 `format_reminders_for_prompt`),让 AI 随时看得到、能「同步进度」秒报、避免重复挂。

### ③ 定时扫描器 — Modal Cron

```python
@app.function(schedule=modal.Cron("0 0 * * *"), secrets=[...], image=image)
def scan_reminders():
    # 00:00 UTC = 08:00 Asia/Shanghai
    sb = _service_client()
    today = date.today()  # 注:Modal 容器时区为 UTC;用 UTC「今天」与 due_date(date)比较即可,
                           #     语义上等价于「北京时间早上扫昨夜到今晨该催的」,Phase 1 不引入 tz 库。
    rows = sb.table("tradego_reminders").select("*").eq("status","pending").execute().data or []
    due = trade_reminders.select_due(rows, today)   # 纯函数:命中 today >= due_date - lead_days 且 last_fired_on != today
    for r in due:
        msg = trade_reminders.format_reminder_message(r, today)  # 模板文案,逾期标 🔴
        dispatch_reminder(sb, r, msg, channels=["in_room"])
        sb.table("tradego_reminders").update({
            "last_fired_on": today.isoformat(),
            "fire_count": r["fire_count"] + 1,
            "updated_at": _now_iso(),
        }).eq("id", r["id"]).execute()
```

命中规则(`select_due`,纯函数,单测):
- `today >= due_date - lead_days`(临近)**或** `today > due_date`(逾期),且
- `last_fired_on != today`(今天还没发过 → 去重,每条每天最多一次),且
- `status == 'pending'`。

时区:Phase 1 不引 tz 库;cron 设 `0 0 * * *`(UTC 0 点 = 北京 8 点),`today` 取 UTC date。
对「提前 N 天 / 逾期」这种 date 粒度判断,UTC 与 CST 的差别只在跨日临界点,可接受。
(如需精确按本地日,Phase 2 再引 zoneinfo。)

### ④ 派发层 + 房间内留言适配器

```python
def dispatch_reminder(sb, reminder, message_text, channels):
    for ch in channels:
        if ch == "in_room":
            _deliver_in_room(sb, reminder, message_text)
        # elif ch == "email": ...   # Phase 2
        # elif ch == "wechat"/"sms": ...  # Phase 3

def _deliver_in_room(sb, reminder, message_text):
    # 往该提醒的房间写一条 AI 消息,用户下次打开就看到
    sb.table("messages").insert({
        "room_id": reminder["room_id"],
        "user_id": reminder["expert_id"],   # 沿用「AI 消息用大咖账号写入」惯例(前端永远显示「AI 助手」)
        "role": "ai",
        "type": "markdown",
        "content": message_text,            # 🔔 开头的催单文案
    }).execute()
```

- 文案**模板生成**(不调 LLM,cron 零成本、确定性):
  - 临近:`🔔 催单提醒:{kind} —— {note},{due_date} 到期(还有 {n} 天)。`
  - 逾期:`🔔🔴 逾期催单:{kind} —— {note},已逾期 {n} 天({due_date} 到期)!`
- in_room 消息走现有 messages 表 + Realtime,前端**无需改动**即可渲染(role=ai 的 markdown 消息)。
  - 前端高亮/置顶催单卡 = 可选增强,Phase 1 先不做(YAGNI)。
- `dispatch_reminder` 的 channels 列表就是 Phase 2/3 的插槽:加通道 = 加一个 `elif` + 一个 `_deliver_*`。

### ⑤ 代码落点

- **新文件 `worker/trade_reminders.py`**:纯逻辑 —— `REMINDER_TOOL_SCHEMAS`、`select_due(rows, today)`、
  `format_reminder_message(r, today)`、`format_reminders_for_prompt(rows)`、`set_reminder`/`complete_reminder`
  的 DB 薄封装(沿用 `trade_memory.py` 模式:纯函数可本地单测,DB 封装部署后真实验)。
- **`worker/chat2go_worker.py`**:
  - import `trade_reminders as trem` + image `.add_local_python_source("trade_reminders")`。
  - 外贸房 tools 追加 `REMINDER_TOOL_SCHEMAS`;tool 分派 elif 加 `set_reminder`/`complete_reminder`。
  - 外贸 prompt 拼装处注入 `format_reminders_for_prompt`。
  - 新增 `@app.function(schedule=modal.Cron("0 0 * * *"))` 的 `scan_reminders` + `dispatch_reminder`/`_deliver_in_room`。
- **新 migration**:建 `tradego_reminders` 表 + 索引 + RLS(走 Supabase MCP apply_migration,preview-then-go)。

### ⑥ 测试

- **单测(`worker/test_trade_reminders.py`,纯函数,TDD)**:
  - `select_due`:临近命中、逾期命中、未到不命中、当天已发(last_fired_on==today)不重发、非 pending 跳过、边界(due-lead 当天)。
  - `format_reminder_message`:临近文案 / 逾期文案 / 天数计算。
  - `format_reminders_for_prompt`:空列表 → 空串;多条分组。
- **E2E(部署后真实验)**:
  - 插一条 due_date=今天、status=pending 的提醒 → `modal run` 手动触发 `scan_reminders` →
    验证目标房间出现 🔔 催单 AI 消息、该提醒 `last_fired_on=今天`、`fire_count` +1。
  - 同日再次触发 → 不重复发(去重生效)。
  - AI 端:外贸房对话「ACME 6 月 10 号付尾款」→ 验证 AI 调 `set_reminder` 落库;「尾款收到了」→ 验证 complete。

## 验收标准(Phase 1)

1. AI 跟单时能把「带日期的待办」落进 `tradego_reminders`(set_reminder),收尾能 complete。
2. Modal Cron 每天自动扫描,临近/逾期的 pending 提醒**主动**在房间里留催单消息。
3. 去重生效:同一条提醒一天最多发一次;逾期持续催直到 done/dismissed。
4. pending 提醒注入 prompt,用户「同步进度」时 AI 能一次性汇总状态 + 临近到期项。
5. 派发层 `dispatch(reminder, channels)` 接口就位,in_room 实现完整,email/wechat/sms 为预留插槽。

## 非目标(Phase 1 不做)

- 邮件 / 微信 / 短信通道(Phase 2/3)。
- 前端催单卡高亮 / 置顶 / 一键标记完成的 UI(先用普通 AI 消息)。
- 精确本地时区(先用 UTC date 粒度)。
- 用户级通道偏好 / 订阅管理(多通道阶段再设计)。
- LLM 生成催单文案(先用模板,零成本确定性)。

## Phase 2 / 3 方向(各自另开 spec)

- **Phase 2 邮件**:`dispatch` 加 email 适配器;Resend/SMTP;需要 seller/expert 邮箱字段 + 退订;免审批,最快出真·主动推送到收件箱。
- **Phase 3 短信 / 微信**:阿里/腾讯云短信(签名报备 + 按条计费);微信认证服务号模板消息(营业执照 + 模板审批,起步重,先办账号);可能需用户级通道偏好表。
