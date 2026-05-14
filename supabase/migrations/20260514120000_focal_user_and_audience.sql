-- 三角色 (大咖 / 小白[focal] / 路人[audience]) 数据层
-- rollback:
--   DROP FUNCTION IF EXISTS get_my_room_role(uuid);
--   DROP POLICY IF EXISTS "expert+focal 读私聊" ON messages;
--   DROP POLICY IF EXISTS "expert+focal 发私聊" ON messages;
--   重建被替换的 "成员可读messages" / "成员可发消息" policy（见 20260511190000_add_room_membership.sql）
--   DROP TRIGGER IF EXISTS auto_lock_focal_on_member_insert ON room_members;
--   DROP FUNCTION IF EXISTS trg_auto_lock_focal();
--   ALTER TABLE rooms DROP COLUMN IF EXISTS focal_user_id;

-- 1) rooms 加 focal_user_id：每个房一个「八字主」小白
alter table rooms add column if not exists focal_user_id uuid references auth.users(id);

-- 2) 第一个非大咖加入 → 自动锁定为 focal；后续加入的都是路人
create or replace function trg_auto_lock_focal()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_room rooms%rowtype;
begin
  select * into v_room from rooms where id = new.room_id;
  -- 大咖本人加入（建房自动）不算 focal
  if new.user_id = v_room.expert_id then
    return new;
  end if;
  -- 已经有 focal 了 → 当前加入者就是路人，不动
  if v_room.focal_user_id is not null then
    return new;
  end if;
  update rooms set focal_user_id = new.user_id where id = new.room_id and focal_user_id is null;
  return new;
end;
$$;

drop trigger if exists auto_lock_focal_on_member_insert on room_members;
create trigger auto_lock_focal_on_member_insert
  after insert on room_members
  for each row execute function trg_auto_lock_focal();

-- 3) 历史回填：每个房间已有的非大咖成员里，最早加入的那个 = focal
update rooms r
set focal_user_id = sub.user_id
from (
  select distinct on (rm.room_id) rm.room_id, rm.user_id
  from room_members rm
  join rooms r2 on r2.id = rm.room_id
  where rm.user_id <> r2.expert_id
  order by rm.room_id, rm.joined_at asc
) sub
where r.id = sub.room_id and r.focal_user_id is null;

-- 4) 收紧 expert_user 频道：只让大咖 + focal_user_id 读/写
--    main 频道保持开放给所有成员（路人也能看 + 发言）

-- 删旧的全成员读 policy，换成按 channel 分流
drop policy if exists "成员可读messages" on messages;
create policy "成员可读 main"
  on messages for select to authenticated
  using (
    coalesce(channel, 'main') = 'main'
    and exists (select 1 from room_members where room_id = messages.room_id and user_id = auth.uid())
  );

create policy "expert+focal 读私聊"
  on messages for select to authenticated
  using (
    channel = 'expert_user'
    and exists (
      select 1 from rooms r
      where r.id = messages.room_id
        and (r.expert_id = auth.uid() or r.focal_user_id = auth.uid())
    )
  );

-- INSERT 同样分流
drop policy if exists "成员可发消息" on messages;
create policy "成员可发 main"
  on messages for insert to authenticated
  with check (
    auth.uid() = user_id
    and coalesce(channel, 'main') = 'main'
    and exists (select 1 from room_members where room_id = messages.room_id and user_id = auth.uid())
  );

create policy "expert+focal 发私聊"
  on messages for insert to authenticated
  with check (
    auth.uid() = user_id
    and channel = 'expert_user'
    and exists (
      select 1 from rooms r
      where r.id = messages.room_id
        and (r.expert_id = auth.uid() or r.focal_user_id = auth.uid())
    )
  );

-- 5) 角色查询 RPC：前端进房后调一次，决定显示哪些 UI
create or replace function get_my_room_role(p_room_id uuid)
returns text
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_uid uuid := auth.uid();
  v_room rooms%rowtype;
begin
  if v_uid is null then return 'anon'; end if;
  select * into v_room from rooms where id = p_room_id;
  if not found then return 'none'; end if;
  if v_room.expert_id = v_uid then return 'expert'; end if;
  if v_room.focal_user_id = v_uid then return 'focal'; end if;
  if exists (select 1 from room_members where room_id = p_room_id and user_id = v_uid) then return 'audience'; end if;
  return 'none';
end;
$$;

grant execute on function get_my_room_role(uuid) to authenticated;
