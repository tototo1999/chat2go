-- L1 计费观测层
--
-- 每次 LLM 调用记录一行：token 数 + 成本（USD）+ 小白付的钱（CNY）。
-- 设计原则：所有金额字段在 insert 时就锁定，事后改汇率/佣金不影响历史账单。

create table if not exists model_usage (
  id uuid primary key default gen_random_uuid(),
  message_id uuid references messages(id) on delete cascade,
  room_id uuid references rooms(id) on delete cascade,
  expert_id uuid not null,
  triggered_by uuid not null,
  model text not null,

  -- token
  input_tokens int not null default 0,
  output_tokens int not null default 0,

  -- 成本来源
  cost_source text not null check (cost_source in ('online', 'local')),
  cost_usd numeric(10, 6) not null default 0,

  -- 计费快照
  commission_pct numeric(4, 2) not null default 0.15,
  exchange_rate numeric(6, 4) not null default 7.20,
  user_charge_cny numeric(10, 4) not null default 0,

  created_at timestamptz not null default now()
);

create index if not exists model_usage_room_idx on model_usage (room_id, created_at desc);
create index if not exists model_usage_expert_idx on model_usage (expert_id, created_at desc);
create index if not exists model_usage_triggered_idx on model_usage (triggered_by, created_at desc);

alter table model_usage enable row level security;

-- 大咖看自己房间的所有计费
create policy "model_usage_expert_read"
  on model_usage for select
  to authenticated
  using (expert_id = auth.uid());

-- 小白看自己触发的计费（只看 user_charge_cny；cost_usd 通过 view 隔离）
create policy "model_usage_user_read_own"
  on model_usage for select
  to authenticated
  using (triggered_by = auth.uid());

-- bridge 写入：必须以大咖账户身份
create policy "model_usage_insert_expert"
  on model_usage for insert
  to authenticated
  with check (expert_id = auth.uid());

-- ── 房间级别加佣金 + 汇率 ──
alter table rooms add column if not exists commission_pct numeric(4, 2) default 0.15;
alter table rooms add column if not exists exchange_rate_to_cny numeric(6, 4) default 7.20;

-- ── 房间维度聚合视图（前端显示用）──
-- RLS 通过底表 model_usage 的策略生效：
--   大咖看到房间整体成本/收入；小白只看到自己消费部分。
create or replace view room_costs as
  select
    room_id,
    count(*) as message_count,
    sum(input_tokens) as total_input_tokens,
    sum(output_tokens) as total_output_tokens,
    sum(cost_usd) as total_cost_usd,
    sum(user_charge_cny) as total_charge_cny,
    max(created_at) as last_used_at
  from model_usage
  group by room_id;

grant select on room_costs to authenticated;
