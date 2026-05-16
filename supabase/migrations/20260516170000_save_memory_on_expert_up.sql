-- 大咖在 AI 消息打 ✓(ratings.up)时,自动把 [问→答] 对写进 memories 表
-- 触发条件:
--   1. 消息 role='ai'
--   2. main 频道(私聊频道不学)
--   3. ratings 里大咖 user_id 的值从非 up 变成 up(新打的钩,不是重复)
--   4. memories 表里还没有 source_message_id=该 AI 消息 id 的记录(防重)
--
-- 写入内容:
--   scope = 'expert'(跨房间永久记忆 —— 大咖打钩 = 认可这个回答模式)
--   content = "问: <最近一条用户/大咖消息>\n答: <AI 消息内容>"
--   tags = ['大咖打钩', '问答对']
--   source_message_id = AI 消息 id
--
-- rollback:
--   DROP TRIGGER IF EXISTS trg_save_memory_on_expert_up ON messages;
--   DROP FUNCTION IF EXISTS trg_save_memory_on_expert_up_fn();

create or replace function trg_save_memory_on_expert_up_fn()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $body$
declare
  v_expert_id uuid;
  v_old_val text;
  v_new_val text;
  v_q_content text;
  v_combined text;
begin
  -- 只关心 AI 消息 + main 频道
  if new.role <> 'ai' or coalesce(new.channel, 'main') <> 'main' then
    return new;
  end if;

  -- 拿到本房 expert_id
  select expert_id into v_expert_id from rooms where id = new.room_id;
  if v_expert_id is null then
    return new;
  end if;

  -- 大咖在 ratings 里的状态变化
  v_old_val := coalesce(old.ratings ->> v_expert_id::text, '');
  v_new_val := coalesce(new.ratings ->> v_expert_id::text, '');

  -- 必须是从「非 up」变成「up」才触发(避免取消 / 重复打钩重写)
  if v_new_val <> 'up' or v_old_val = 'up' then
    return new;
  end if;

  -- 拿这条 AI 之前最近一条用户/大咖消息(就是触发这条 AI 回复的"问")
  select content into v_q_content
  from messages
  where room_id = new.room_id
    and role in ('user', 'expert')
    and coalesce(channel, 'main') = 'main'
    and created_at < new.created_at
  order by created_at desc
  limit 1;

  v_combined := '问:' || coalesce(v_q_content, '?') || E'\n答:' || coalesce(new.content, '');

  -- 防重:同一条 AI 消息只写一次 memory(就算大咖反复打 ✓✗✓ 也只一条)
  if not exists (
    select 1 from memories
    where scope = 'expert'
      and scope_id = v_expert_id
      and source_message_id = new.id
  ) then
    insert into memories (scope, scope_id, content, tags, source_message_id)
    values (
      'expert',
      v_expert_id,
      v_combined,
      array['大咖打钩', '问答对'],
      new.id
    );
  end if;

  return new;
end;
$body$;

-- 只在 ratings 字段有变化时才进 trigger 函数(防无关 UPDATE 频繁触发)
drop trigger if exists trg_save_memory_on_expert_up on messages;
create trigger trg_save_memory_on_expert_up
  after update on messages
  for each row
  when (old.ratings is distinct from new.ratings)
  execute function trg_save_memory_on_expert_up_fn();
