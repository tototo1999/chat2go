-- 拆分邀请：大咖的 invite_token 限定一次（小白专用，焦点锁定后失效）；
-- audience_invite_token 给小白用，无限次接路人。
-- rollback:
--   create trigger auto_lock_focal_on_member_insert ... (恢复 20260514120000 的版本)
--   ALTER TABLE rooms DROP COLUMN audience_invite_token;
--   重写 join_room_by_token 回 20260511190000 的版本

-- 1) 加 audience_invite_token（独立 uuid）
alter table rooms add column if not exists audience_invite_token uuid not null default gen_random_uuid();
create unique index if not exists idx_rooms_audience_invite_token on rooms (audience_invite_token);

-- 2) 去掉「自动 lock focal」的 INSERT 触发器，逻辑搬进 join_room_by_token RPC
drop trigger if exists auto_lock_focal_on_member_insert on room_members;
drop function if exists trg_auto_lock_focal();

-- 3) 重写 join_room_by_token：识别 token 类型 + 焦点是否锁定
create or replace function join_room_by_token(p_token uuid)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_uid uuid;
  v_room rooms%rowtype;
  v_is_focal_token boolean;
begin
  v_uid := auth.uid();
  if v_uid is null then
    raise exception 'must be authenticated';
  end if;

  -- 优先匹配 invite_token（大咖的小白邀请），不中再匹配 audience_invite_token
  select * into v_room from rooms where invite_token = p_token;
  if found then
    v_is_focal_token := true;
  else
    select * into v_room from rooms where audience_invite_token = p_token;
    if not found then
      raise exception 'invalid invite token';
    end if;
    v_is_focal_token := false;
  end if;

  -- 大咖本人扫自己链接 → 直接进
  if v_room.expert_id = v_uid then
    insert into room_members (room_id, user_id) values (v_room.id, v_uid)
      on conflict do nothing;
    return v_room.id;
  end if;

  if v_is_focal_token then
    -- 小白邀请：焦点未锁就把当前用户锁为 focal；已锁就拒
    if v_room.focal_user_id is not null and v_room.focal_user_id <> v_uid then
      raise exception 'invite_used: focal already locked';
    end if;
    if v_room.focal_user_id is null then
      update rooms set focal_user_id = v_uid where id = v_room.id and focal_user_id is null;
    end if;
  end if;
  -- audience token：不动 focal，直接加成员（如果已是 focal 也允许重入）

  insert into room_members (room_id, user_id) values (v_room.id, v_uid)
    on conflict do nothing;
  return v_room.id;
end;
$$;

grant execute on function join_room_by_token(uuid) to authenticated;
