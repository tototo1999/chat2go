-- 获取房间所有成员（含角色）—— 因 room_members SELECT RLS 限制只能看自己那行，用 SECURITY DEFINER 绕开
-- rollback:
--   DROP FUNCTION IF EXISTS get_room_members(uuid);

create or replace function get_room_members(p_room_id uuid)
returns table (
  user_id uuid,
  display_name text,
  role text,
  joined_at timestamptz
)
language sql
security definer
set search_path = public, pg_temp
as $$
  select
    rm.user_id,
    coalesce(p.display_name, '匿名') as display_name,
    case
      when rm.user_id = r.expert_id        then 'expert'
      when rm.user_id = r.focal_user_id    then 'focal'
      else                                       'audience'
    end as role,
    rm.joined_at
  from room_members rm
  join rooms r on r.id = rm.room_id
  left join profiles p on p.user_id = rm.user_id
  where rm.room_id = p_room_id
    and exists (
      select 1 from room_members rm2
      where rm2.room_id = p_room_id and rm2.user_id = auth.uid()
    )
  order by
    case
      when rm.user_id = r.expert_id        then 0
      when rm.user_id = r.focal_user_id    then 1
      else                                       2
    end,
    rm.joined_at asc;
$$;

grant execute on function get_room_members(uuid) to authenticated;
