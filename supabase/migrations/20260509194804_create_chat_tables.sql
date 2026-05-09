-- 调试室表
create table rooms (
  id uuid default gen_random_uuid() primary key,
  name text not null,
  industry text not null,
  expert_id uuid references auth.users(id),
  status text default 'active',
  created_at timestamptz default now()
);

-- 消息表
create table messages (
  id uuid default gen_random_uuid() primary key,
  room_id uuid references rooms(id) on delete cascade,
  user_id uuid references auth.users(id),
  role text not null,
  content text not null,
  created_at timestamptz default now()
);

-- 开启实时订阅
alter publication supabase_realtime add table messages;

-- 权限设置
alter table rooms enable row level security;
alter table messages enable row level security;

create policy "任何人可读rooms" on rooms for select using (true);
create policy "任何人可读messages" on messages for select using (true);
create policy "登录用户可发消息" on messages for insert with check (auth.uid() = user_id);
