-- bridge 心跳和重启信号
-- bridge.py 每 ~5 秒 UPDATE last_seen；
-- 前端检测 last_seen 超过 30 秒就当离线，点击图标 → 调 request_bridge_restart()
-- bridge.py 检测 restart_requested_at > 启动时间 → sys.exit(1) 让 launchd KeepAlive 拉起新进程

create table if not exists bridge_state (
  id text primary key default 'singleton',
  last_seen timestamptz,
  restart_requested_at timestamptz,
  pid int,
  hostname text
);

insert into bridge_state (id) values ('singleton') on conflict do nothing;

alter table bridge_state enable row level security;

-- 任何登录用户可读（前端要看状态）
drop policy if exists "anyone reads bridge_state" on bridge_state;
create policy "anyone reads bridge_state" on bridge_state
  for select to authenticated using (true);

-- 不开放直接写 —— bridge 用 service_role bypass，前端走 RPC

-- 请求重启：写 restart_requested_at = now()
create or replace function request_bridge_restart()
returns timestamptz
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_now timestamptz := now();
begin
  if auth.uid() is null then
    raise exception 'not authenticated';
  end if;
  update bridge_state set restart_requested_at = v_now where id = 'singleton';
  if not found then
    insert into bridge_state (id, restart_requested_at) values ('singleton', v_now);
  end if;
  return v_now;
end;
$$;

grant execute on function request_bridge_restart() to authenticated;
