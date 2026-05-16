-- 撤回 20260516200000 加的 main 频道 marker 写入(bridge 没成功触发,
-- 改为前端 rateMessage 触发 pass 时由用户实发 "pass" 消息)。
-- 保留原 expert_user 摘要写入(私聊存档功能)。

create or replace function trg_relay_pass_to_private()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $body$
declare
  old_up int;
  new_up int;
  summary text;
begin
  if new.role <> 'ai' or coalesce(new.channel, 'main') <> 'main' then
    return new;
  end if;
  select count(*) into new_up from jsonb_each_text(coalesce(new.ratings, '{}'::jsonb)) where value = 'up';
  select count(*) into old_up from jsonb_each_text(coalesce(old.ratings, '{}'::jsonb)) where value = 'up';
  if new_up >= 2 and old_up < 2 then
    summary := '✓✓ pass · ' || left(regexp_replace(coalesce(new.content, ''), E'\\s+', ' ', 'g'), 100);
    if length(coalesce(new.content, '')) > 100 then summary := summary || '…'; end if;
    insert into messages (room_id, user_id, role, channel, content, type)
      values (new.room_id, new.user_id, 'ai', 'expert_user', summary, 'text');
  end if;
  return new;
end;
$body$;
