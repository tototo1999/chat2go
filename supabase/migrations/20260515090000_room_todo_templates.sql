-- 大咖个人 todo 方案库 + 房间引用某方案
-- 大咖在 sidebar 维护若干 todo 方案（如「命理八字基础」），房间挂一个 active 方案
-- 编辑某方案 → 用同一方案的所有房间一起变（"方案库"自然语义；要"独立微调"留给后续 fork 按钮）

create table if not exists expert_todo_templates (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  payload jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_expert_todo_templates_owner on expert_todo_templates(owner_id);

alter table expert_todo_templates enable row level security;

-- 任何登录用户可读：方案名/payload 不敏感，跟 rooms 一样开放 SELECT
-- 避开 room_members join 引发的 RLS 递归（参考 20260511200000_fix_room_members_rls_recursion）
drop policy if exists "anyone reads templates" on expert_todo_templates;
create policy "anyone reads templates" on expert_todo_templates
  for select to authenticated using (true);

-- 写操作限 owner 自己
drop policy if exists "owner writes own templates" on expert_todo_templates;
create policy "owner writes own templates" on expert_todo_templates
  for insert to authenticated with check (owner_id = auth.uid());

drop policy if exists "owner updates own templates" on expert_todo_templates;
create policy "owner updates own templates" on expert_todo_templates
  for update to authenticated
  using (owner_id = auth.uid())
  with check (owner_id = auth.uid());

drop policy if exists "owner deletes own templates" on expert_todo_templates;
create policy "owner deletes own templates" on expert_todo_templates
  for delete to authenticated using (owner_id = auth.uid());

-- 房间引用当前激活的方案
alter table rooms add column if not exists active_todo_template_id uuid
  references expert_todo_templates(id) on delete set null;

-- payload 改了自动更新 updated_at
create or replace function _touch_expert_todo_templates_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_expert_todo_templates_updated_at on expert_todo_templates;
create trigger trg_expert_todo_templates_updated_at
  before update on expert_todo_templates
  for each row execute function _touch_expert_todo_templates_updated_at();
