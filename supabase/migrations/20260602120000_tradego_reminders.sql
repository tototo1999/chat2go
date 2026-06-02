-- Trade2GO 催单系统 Phase 1:提醒表(每个订单可挂多条带日期的待办)
create table if not exists tradego_reminders (
  id            uuid primary key default gen_random_uuid(),
  room_id       uuid not null references rooms(id) on delete cascade,
  order_id      uuid references tradego_orders(id) on delete set null,
  expert_id     uuid not null,
  product       text not null default 'tradego',
  kind          text not null,            -- 尾款/船期/交期/定金/跟进/自定义
  note          text not null,            -- 催单内容
  due_date      date not null,            -- 到期日
  lead_days     int  not null default 2,  -- 提前几天开始提醒
  status        text not null default 'pending',  -- pending|done|dismissed|snoozed
  last_fired_on date,                      -- 去重:最近一次已发催单的日期
  fire_count    int  not null default 0,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index if not exists idx_tradego_reminders_scan
  on tradego_reminders(status, due_date) where status = 'pending';
create index if not exists idx_tradego_reminders_room
  on tradego_reminders(room_id) where status = 'pending';

alter table tradego_reminders enable row level security;
-- 读:登录用户可读本房提醒(沿用 messages/orders 的「房可读」口径)。
create policy tradego_reminders_read on tradego_reminders
  for select using (true);
-- 写:仅 service-role(worker)。anon/authenticated 无写策略 = 默认拒。
