-- 扩展 trg_relay_pass_to_private:
-- 双钩 pass 时,除现有 expert_user 频道写摘要外,
-- 再往 main 频道写一条 marker 消息 '__SYS_ADVANCE_QUIZ__',
-- bridge 收到这条 expert 消息会触发 AI 响应(quiz-state 注入已让
-- AI 知道下一题是什么)。前端 appendMessage 识别 marker 后隐藏不渲染。
--
-- rollback:
--   恢复 20260514000000_pass_relay.sql 原 trigger 函数。

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
    -- ★ 双钩 pass marker:让 bridge 触发 AI 响应进入下一题。前端隐藏不渲染。
    insert into messages (room_id, user_id, role, channel, content, type)
      values (new.room_id, new.user_id, 'expert', 'main', '__SYS_ADVANCE_QUIZ__', 'text');
  end if;
  return new;
end;
$body$;
