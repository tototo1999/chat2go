-- 大咖重置房间：踢掉所有非大咖成员 + 清消息 + 清焦点 + 重发 invite/audience token
-- rollback:
--   DROP FUNCTION IF EXISTS reset_room(uuid);

create or replace function reset_room(p_room_id uuid)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_uid uuid := auth.uid();
  v_room rooms%rowtype;
begin
  if v_uid is null then
    raise exception 'not authenticated';
  end if;
  select * into v_room from rooms where id = p_room_id;
  if not found then
    raise exception 'room not found';
  end if;
  if v_room.expert_id <> v_uid then
    raise exception 'only expert can reset this room';
  end if;

  -- 1) 踢非大咖成员
  delete from room_members where room_id = p_room_id and user_id <> v_room.expert_id;
  -- 2) 清消息（CASCADE 处理 ratings / 子表）
  delete from messages where room_id = p_room_id;
  -- 3) 清焦点 + 重发 token
  update rooms
    set focal_user_id = null,
        invite_token = gen_random_uuid(),
        audience_invite_token = gen_random_uuid()
    where id = p_room_id;

  return p_room_id;
end;
$$;

grant execute on function reset_room(uuid) to authenticated;
