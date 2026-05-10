-- 补齐 demo 必需的 RLS 策略

-- 1. 任何登录用户可以创建调试室（自己自动成为 expert_id）
create policy "登录用户可建房" on rooms
  for insert
  to authenticated
  with check (auth.uid() = expert_id);

-- 2. 大咖可以更新自己创建的调试室（改 model / system_prompt）
create policy "大咖可改自己房间" on rooms
  for update
  to authenticated
  using (auth.uid() = expert_id)
  with check (auth.uid() = expert_id);
