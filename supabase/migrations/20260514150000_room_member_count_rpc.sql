-- 群人数 RPC：因 room_members 的 SELECT RLS 限制只能看自己那行，直接 count(*) 拿不到全表
-- 用 SECURITY DEFINER 绕开，前端展示用
-- rollback:
--   DROP FUNCTION IF EXISTS get_room_member_count(uuid);

create or replace function get_room_member_count(p_room_id uuid)
returns int
language sql
security definer
set search_path = public, pg_temp
as $$
  select count(*)::int from room_members where room_id = p_room_id;
$$;

grant execute on function get_room_member_count(uuid) to authenticated;
