-- 大咖入住基础设施：profiles 表 + agent connection key 系统
--
-- 1. profiles：区分大咖 / 小白角色（role）
-- 2. expert_agent_keys：大咖给本地 agent 用的连接密钥
-- 3. RPC：generate / list / revoke agent_key

-- ── 1. profiles 表 ──
create table if not exists profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  role text not null default 'user' check (role in ('user', 'expert')),
  display_name text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table profiles enable row level security;

create policy "profiles_read_all_authenticated"
  on profiles for select
  to authenticated
  using (true);

create policy "profiles_update_own"
  on profiles for update
  to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

-- 注册时 user_metadata.role 决定角色；缺省 'user'（小白）
create or replace function handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  insert into profiles (user_id, role, display_name)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'role', 'user'),
    coalesce(new.raw_user_meta_data->>'display_name', split_part(new.email, '@', 1))
  )
  on conflict (user_id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function handle_new_user();

-- 给已有用户回填 profile 行（默认 user 角色，display_name = email 前缀）
insert into profiles (user_id, role, display_name)
  select id, 'user', split_part(email, '@', 1) from auth.users
  on conflict (user_id) do nothing;

-- ── 2. expert_agent_keys 表 ──
create table if not exists expert_agent_keys (
  id uuid primary key default gen_random_uuid(),
  expert_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  key_hash text not null,                                -- sha256(token) hex
  key_prefix text not null,                              -- 前 16 字符显示用
  last_used_at timestamptz,
  last_used_ip inet,
  expires_at timestamptz,                                -- NULL = 永久
  revoked_at timestamptz,
  created_at timestamptz not null default now()
);

create unique index if not exists expert_agent_keys_hash_idx on expert_agent_keys (key_hash);
create index if not exists expert_agent_keys_expert_idx on expert_agent_keys (expert_id, created_at desc);

alter table expert_agent_keys enable row level security;

-- 大咖看自己的 key（不含 hash 字段，靠 RPC 严格控制）
create policy "agent_keys_read_own"
  on expert_agent_keys for select
  to authenticated
  using (expert_id = auth.uid());

-- 写入只能通过 RPC（generate_agent_key / revoke_agent_key），不允许直接 insert/update
-- 不创建 INSERT / UPDATE policy = 所有直接写入都被拒

-- ── 3. RPC：生成新 key ──
create or replace function generate_agent_key(p_name text)
returns table (token text, prefix text, id uuid)
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_caller uuid;
  v_role text;
  v_raw_token text;
  v_hash text;
  v_prefix text;
  v_id uuid;
begin
  v_caller := auth.uid();
  if v_caller is null then
    raise exception 'not authenticated';
  end if;

  -- 只有 expert 角色能生成 key
  select role into v_role from profiles where user_id = v_caller;
  if v_role is null or v_role <> 'expert' then
    raise exception 'only experts can generate agent keys (current role: %)', coalesce(v_role, 'none');
  end if;

  -- 生成 64 字符随机 token，加 c2g-key_ 前缀
  v_raw_token := 'c2g-key_' || encode(gen_random_bytes(32), 'hex');
  v_hash := encode(digest(v_raw_token, 'sha256'), 'hex');
  v_prefix := substring(v_raw_token from 1 for 16);

  insert into expert_agent_keys (expert_id, name, key_hash, key_prefix)
    values (v_caller, p_name, v_hash, v_prefix)
    returning expert_agent_keys.id into v_id;

  return query select v_raw_token, v_prefix, v_id;
end;
$$;

grant execute on function generate_agent_key(text) to authenticated;

-- ── 4. RPC：列出我的 key ──
create or replace function list_agent_keys()
returns table (
  id uuid,
  name text,
  prefix text,
  last_used_at timestamptz,
  last_used_ip inet,
  expires_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz
)
language sql
security definer
set search_path = public, pg_temp
as $$
  select id, name, key_prefix, last_used_at, last_used_ip,
         expires_at, revoked_at, created_at
  from expert_agent_keys
  where expert_id = auth.uid()
  order by created_at desc;
$$;

grant execute on function list_agent_keys() to authenticated;

-- ── 5. RPC：撤销 key ──
create or replace function revoke_agent_key(p_id uuid)
returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  if auth.uid() is null then
    raise exception 'not authenticated';
  end if;
  update expert_agent_keys
    set revoked_at = now()
  where id = p_id
    and expert_id = auth.uid()        -- 只能撤自己的
    and revoked_at is null;
end;
$$;

grant execute on function revoke_agent_key(uuid) to authenticated;
