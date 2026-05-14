-- 做题模式：messages 加 ratings jsonb + rate_message RPC
-- ratings 结构示例: {"<user_id1>": "up", "<user_id2>": "down"}
-- 双方都 'up' 才算 pass

alter table messages add column if not exists ratings jsonb not null default '{}'::jsonb;

-- atomic 评价 RPC：用户对某条 AI 消息打 up/down/clear
create or replace function rate_message(p_msg_id uuid, p_val text)
returns jsonb
language plpgsql security definer
set search_path = public, pg_temp
as $body$
declare
  v_uid uuid := auth.uid();
  v_room uuid;
  v_role text;
  v_new jsonb;
begin
  if v_uid is null then raise exception 'auth required'; end if;
  if p_val not in ('up', 'down', '') then raise exception 'invalid val'; end if;

  -- 校验：消息必须存在 + 当前用户必须是该房成员
  select room_id, role into v_room, v_role from messages where id = p_msg_id;
  if v_room is null then raise exception 'message not found'; end if;
  if v_role <> 'ai' then raise exception 'can only rate AI messages'; end if;
  if not exists (select 1 from room_members where room_id = v_room and user_id = v_uid) then
    raise exception 'not a member of this room';
  end if;

  -- 更新 ratings：空 = 删除该用户键；否则覆盖
  if p_val = '' then
    update messages
       set ratings = ratings - v_uid::text
     where id = p_msg_id
     returning ratings into v_new;
  else
    update messages
       set ratings = coalesce(ratings, '{}'::jsonb) || jsonb_build_object(v_uid::text, p_val)
     where id = p_msg_id
     returning ratings into v_new;
  end if;
  return v_new;
end;
$body$;

grant execute on function rate_message(uuid, text) to authenticated;
