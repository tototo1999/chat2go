-- 管理员后台基础设施
-- email 白名单制 → is_admin() 函数 + 一组 SECURITY DEFINER RPC 让 admin 绕过 RLS

-- 1) profiles 加 banned_at（软封禁；NULL = 正常）
alter table profiles add column if not exists banned_at timestamptz;

-- 2) is_admin() —— 用 auth.users.email 比对白名单
create or replace function is_admin() returns boolean
language sql stable security definer
set search_path = public, pg_temp
as $$
  select coalesce(
    (select email from auth.users where id = auth.uid()) in (
      'iamdami2026@gmail.com'
    ),
    false
  );
$$;

grant execute on function is_admin() to authenticated;

-- 3) 概览仪表盘 stats
create or replace function admin_dashboard_stats()
returns table (
  total_users bigint,
  total_experts bigint,
  banned_users bigint,
  new_users_today bigint,
  total_rooms bigint,
  total_messages bigint,
  msgs_today bigint,
  ai_calls_today bigint,
  total_cost_usd numeric,
  total_charge_cny numeric,
  cost_usd_today numeric,
  charge_cny_today numeric
)
language plpgsql security definer
set search_path = public, pg_temp
as $$
begin
  if not is_admin() then raise exception 'unauthorized'; end if;
  return query
  select
    (select count(*) from profiles)::bigint                                                          as total_users,
    (select count(*) from profiles where role='expert')::bigint                                      as total_experts,
    (select count(*) from profiles where banned_at is not null)::bigint                              as banned_users,
    (select count(*) from profiles where created_at >= date_trunc('day', now()))::bigint             as new_users_today,
    (select count(*) from rooms)::bigint                                                             as total_rooms,
    (select count(*) from messages)::bigint                                                          as total_messages,
    (select count(*) from messages where created_at >= date_trunc('day', now()))::bigint             as msgs_today,
    (select count(*) from model_usage where created_at >= date_trunc('day', now()))::bigint          as ai_calls_today,
    coalesce((select sum(cost_usd) from model_usage), 0)::numeric                                    as total_cost_usd,
    coalesce((select sum(user_charge_cny) from model_usage), 0)::numeric                             as total_charge_cny,
    coalesce((select sum(cost_usd) from model_usage where created_at >= date_trunc('day', now())), 0)::numeric        as cost_usd_today,
    coalesce((select sum(user_charge_cny) from model_usage where created_at >= date_trunc('day', now())), 0)::numeric as charge_cny_today
  ;
end;
$$;

grant execute on function admin_dashboard_stats() to authenticated;

-- 4) 用户列表（带衍生统计；可按 email/display_name 模糊搜）
create or replace function admin_list_users(
  p_search text default '',
  p_limit  int default 50,
  p_offset int default 0
)
returns table (
  user_id uuid,
  email text,
  display_name text,
  role text,
  banned_at timestamptz,
  created_at timestamptz,
  follow_count bigint,
  msg_count bigint
)
language plpgsql security definer
set search_path = public, pg_temp
as $$
begin
  if not is_admin() then raise exception 'unauthorized'; end if;
  return query
  select
    p.user_id,
    u.email::text,
    p.display_name,
    p.role,
    p.banned_at,
    p.created_at,
    (select count(*) from room_members rm where rm.user_id = p.user_id and rm.user_id <> (select expert_id from rooms r where r.id = rm.room_id))::bigint as follow_count,
    (select count(*) from messages m where m.user_id = p.user_id and m.role <> 'ai')::bigint as msg_count
  from profiles p
  join auth.users u on u.id = p.user_id
  where (p_search = '' or u.email ilike '%'||p_search||'%' or p.display_name ilike '%'||p_search||'%')
  order by p.created_at desc
  limit p_limit offset p_offset;
end;
$$;

grant execute on function admin_list_users(text, int, int) to authenticated;

-- 5) 改用户角色 / 封禁
create or replace function admin_update_user_role(p_user_id uuid, p_role text)
returns void
language plpgsql security definer
set search_path = public, pg_temp
as $$
begin
  if not is_admin() then raise exception 'unauthorized'; end if;
  if p_role not in ('user', 'expert') then raise exception 'invalid role'; end if;
  update profiles set role = p_role, updated_at = now() where user_id = p_user_id;
end;
$$;
grant execute on function admin_update_user_role(uuid, text) to authenticated;

create or replace function admin_set_ban(p_user_id uuid, p_banned boolean)
returns void
language plpgsql security definer
set search_path = public, pg_temp
as $$
begin
  if not is_admin() then raise exception 'unauthorized'; end if;
  update profiles set banned_at = case when p_banned then now() else null end, updated_at = now()
   where user_id = p_user_id;
end;
$$;
grant execute on function admin_set_ban(uuid, boolean) to authenticated;

-- 6) 房间列表（带 cost / 消息数 / expert 信息）
create or replace function admin_list_rooms(
  p_search text default '',
  p_limit  int default 50,
  p_offset int default 0
)
returns table (
  id uuid,
  name text,
  industry text,
  status text,
  expert_id uuid,
  expert_email text,
  expert_name text,
  msg_count bigint,
  total_cost_usd numeric,
  total_charge_cny numeric,
  member_count bigint,
  created_at timestamptz
)
language plpgsql security definer
set search_path = public, pg_temp
as $$
begin
  if not is_admin() then raise exception 'unauthorized'; end if;
  return query
  select
    r.id, r.name, r.industry, r.status,
    r.expert_id,
    u.email::text as expert_email,
    p.display_name as expert_name,
    (select count(*) from messages m where m.room_id = r.id)::bigint as msg_count,
    coalesce((select sum(cost_usd) from model_usage mu where mu.room_id = r.id), 0)::numeric as total_cost_usd,
    coalesce((select sum(user_charge_cny) from model_usage mu where mu.room_id = r.id), 0)::numeric as total_charge_cny,
    (select count(*) from room_members rm where rm.room_id = r.id)::bigint as member_count,
    r.created_at
  from rooms r
  left join auth.users u on u.id = r.expert_id
  left join profiles p on p.user_id = r.expert_id
  where (p_search = '' or r.name ilike '%'||p_search||'%' or p.display_name ilike '%'||p_search||'%' or u.email ilike '%'||p_search||'%')
  order by r.created_at desc
  limit p_limit offset p_offset;
end;
$$;

grant execute on function admin_list_rooms(text, int, int) to authenticated;

-- 7) 删房（绕过 RLS）
create or replace function admin_delete_room(p_room_id uuid)
returns int
language plpgsql security definer
set search_path = public, pg_temp
as $$
declare v_count int;
begin
  if not is_admin() then raise exception 'unauthorized'; end if;
  delete from rooms where id = p_room_id;
  get diagnostics v_count = row_count;
  return v_count;
end;
$$;
grant execute on function admin_delete_room(uuid) to authenticated;

-- 8) Bridge 状态推断：以每个 expert 最近 5 分钟有没有 model_usage 写入
create or replace function admin_bridge_status()
returns table (
  expert_id uuid,
  email text,
  display_name text,
  last_seen_at timestamptz,
  is_online boolean,
  msgs_24h bigint,
  cost_usd_24h numeric
)
language plpgsql security definer
set search_path = public, pg_temp
as $$
begin
  if not is_admin() then raise exception 'unauthorized'; end if;
  return query
  with last as (
    select expert_id, max(created_at) as last_seen_at,
           count(*) filter (where created_at > now() - interval '24 hours') as msgs_24h,
           coalesce(sum(cost_usd) filter (where created_at > now() - interval '24 hours'), 0) as cost_usd_24h
      from model_usage
     group by expert_id
  )
  select
    p.user_id as expert_id,
    u.email::text as email,
    p.display_name,
    l.last_seen_at,
    (l.last_seen_at is not null and l.last_seen_at > now() - interval '5 minutes') as is_online,
    coalesce(l.msgs_24h, 0)::bigint as msgs_24h,
    coalesce(l.cost_usd_24h, 0)::numeric as cost_usd_24h
  from profiles p
  join auth.users u on u.id = p.user_id
  left join last l on l.expert_id = p.user_id
  where p.role = 'expert'
  order by l.last_seen_at desc nulls last;
end;
$$;

grant execute on function admin_bridge_status() to authenticated;
