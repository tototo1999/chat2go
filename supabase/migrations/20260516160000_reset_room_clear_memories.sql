-- reset_room 隐私加强：清掉本房 room scope 的 memories
-- 之前 reset 只删 room_members + messages，memories 表里 scope='room' 的个案
-- 内容（八字、姓名、家庭背景等）残留 → 下一个八字主进来 AI 仍记得旧个案 → 隐私泄露
--
-- 设计：
--   scope='room'  → 本次个案内容，reset 时**删除**
--   scope='expert' → 大咖跨房经验 / lessons / 命理纠正方法，reset 时**保留**
--   scope='user'  → 用户跨房偏好，reset 时**保留**
--
-- rollback: 复原成 20260514140000 的版本（不删 memories）。

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
  -- 3) ★ 清本房 room scope 记忆（保留 expert/user scope = 跨房经验）
  delete from memories where scope = 'room' and scope_id = p_room_id;
  -- 4) 清焦点 + 重发 token
  update rooms
    set focal_user_id = null,
        invite_token = gen_random_uuid(),
        audience_invite_token = gen_random_uuid()
    where id = p_room_id;

  return p_room_id;
end;
$$;

grant execute on function reset_room(uuid) to authenticated;
