-- bridge 心跳 RPC：bridge.py 每 ~5s 调一次，更新 bridge_state.last_seen
-- bridge 登录是 authenticated 用户，没有直接 UPDATE bridge_state 的 policy，必须走 SECURITY DEFINER

create or replace function bridge_pong(p_pid int default null, p_hostname text default null)
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
  update bridge_state
    set last_seen = v_now,
        pid = coalesce(p_pid, pid),
        hostname = coalesce(p_hostname, hostname)
    where id = 'singleton';
  if not found then
    insert into bridge_state (id, last_seen, pid, hostname)
      values ('singleton', v_now, p_pid, p_hostname);
  end if;
  return v_now;
end;
$$;

grant execute on function bridge_pong(int, text) to authenticated;
