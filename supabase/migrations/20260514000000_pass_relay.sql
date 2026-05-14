-- 做题模式：双钩 pass 时把 AI 原消息摘要 relay 到 expert_user 私聊频道

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
  -- 只关心 main 频道的 AI 消息
  if new.role <> 'ai' or coalesce(new.channel, 'main') <> 'main' then
    return new;
  end if;
  -- 数 'up' 票数（新旧）
  select count(*) into new_up from jsonb_each_text(coalesce(new.ratings, '{}'::jsonb)) where value = 'up';
  select count(*) into old_up from jsonb_each_text(coalesce(old.ratings, '{}'::jsonb)) where value = 'up';
  -- 仅当本次 update 让 up 数从 <2 跨过到 >=2 才发，防重复
  if new_up >= 2 and old_up < 2 then
    summary := '✓✓ pass · ' || left(regexp_replace(coalesce(new.content, ''), E'\\s+', ' ', 'g'), 100);
    if length(coalesce(new.content, '')) > 100 then summary := summary || '…'; end if;
    insert into messages (room_id, user_id, role, channel, content, type)
      values (new.room_id, new.user_id, 'ai', 'expert_user', summary, 'text');
  end if;
  return new;
end;
$body$;

drop trigger if exists relay_pass_to_private on messages;
create trigger relay_pass_to_private
  after update of ratings on messages
  for each row execute function trg_relay_pass_to_private();
