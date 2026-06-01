-- Trade2GO 记忆 P0:订单状态机(双时序)+ 冻结规则表
-- 仅服务 tradego(product='tradego');worker 用 service-role 读写,RLS 给大咖自己读。

-- 订单状态枚举(P0 默认 6 段,后续按真实跟单流程可加值)
do $$ begin
  create type tradego_order_status as enum
    ('报价','待PI','已付定金','生产中','已发货','收尾');
exception when duplicate_object then null; end $$;

create table if not exists tradego_orders (
  id uuid primary key default gen_random_uuid(),
  room_id uuid not null references rooms(id) on delete cascade,
  expert_id uuid not null,
  customer text,
  product_desc text,
  amount numeric,
  currency text,
  status tradego_order_status not null,
  valid_from timestamptz not null default now(),
  valid_to   timestamptz,                 -- 双时序:当前态 = valid_to is null
  source_message_id uuid,
  created_at timestamptz not null default now()
);
create index if not exists idx_tradego_orders_room_active
  on tradego_orders(room_id) where valid_to is null;

create table if not exists tradego_memory_rules (
  id uuid primary key default gen_random_uuid(),
  expert_id uuid not null,
  product text not null default 'tradego',
  content text not null,
  status text not null default 'frozen',   -- 'frozen' | 'candidate'(P0 只用 frozen)
  version int not null default 1,
  source_message_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_tradego_rules_lookup
  on tradego_memory_rules(expert_id, product, status);

alter table tradego_orders enable row level security;
alter table tradego_memory_rules enable row level security;

-- 大咖只读自己的(写入走 service-role,绕 RLS)
create policy tradego_orders_read_own on tradego_orders
  for select to authenticated using (expert_id = auth.uid());
create policy tradego_rules_read_own on tradego_memory_rules
  for select to authenticated using (expert_id = auth.uid());

-- 种子:给外贸大咖(388388, expert_id=5dcec9b4-18a8-405b-837b-10bc27de114c)种两条冻结规则,验注入
insert into tradego_memory_rules (expert_id, product, content, status, version) values
  ('5dcec9b4-18a8-405b-837b-10bc27de114c','tradego',
   '默认报价币种用 USD;客户没指定 Incoterm 时默认按 FOB 深圳报。','frozen',1),
  ('5dcec9b4-18a8-405b-837b-10bc27de114c','tradego',
   '报价默认在成本价基础上加 12% 利润;低于此需大咖确认。','frozen',1);
