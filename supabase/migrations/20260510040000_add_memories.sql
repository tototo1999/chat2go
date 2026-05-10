-- Phase A：Memory 表（只读 prefetch；写入留 Phase B Lessons 自动沉淀）
--
-- 三种 scope：
--   room   ← 此调试室的累积事实（客户预算、需求、偏好）
--   expert ← 大咖的全局事实（服务过的客户、常用模板）
--   user   ← 小白的事实（小白的公司、产品）

create table if not exists memories (
  id uuid primary key default gen_random_uuid(),
  scope text not null check (scope in ('room', 'expert', 'user')),
  scope_id uuid not null,
  content text not null,
  tags text[] default '{}',
  source_message_id uuid references messages(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists memories_scope_idx on memories (scope, scope_id, updated_at desc);

alter table memories enable row level security;

-- Phase A 只读：所有登录用户可读
create policy "memories_read_all_authenticated"
  on memories for select
  to authenticated
  using (true);

-- Phase B 才会开写入：先关
-- create policy "memories_insert_owner"
--   on memories for insert
--   to authenticated
--   with check (...);

-- updated_at 自动维护
create or replace function set_updated_at() returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger memories_updated_at
  before update on memories
  for each row execute function set_updated_at();
