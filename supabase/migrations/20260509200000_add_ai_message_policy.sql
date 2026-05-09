-- Allow service role (Edge Functions) to insert AI messages
-- The chat-ai function uses SUPABASE_SERVICE_ROLE_KEY which bypasses RLS,
-- but this policy covers future scenarios where anon key is used.
create policy "服务角色可插入AI消息" on messages
  for insert
  with check (role = 'ai');
