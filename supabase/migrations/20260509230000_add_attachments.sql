-- messages 表加附件列（JSONB 数组：[{name, url, size, mime_type, storage_path}, ...]）
alter table messages add column if not exists attachments jsonb not null default '[]';

-- 创建 Storage bucket：调试室上传文件（公共可读，登录用户可写）
insert into storage.buckets (id, name, public)
values ('chat-uploads', 'chat-uploads', true)
on conflict (id) do nothing;

-- Storage 策略
drop policy if exists "登录用户可上传chat文件" on storage.objects;
create policy "登录用户可上传chat文件" on storage.objects
  for insert
  to authenticated
  with check (bucket_id = 'chat-uploads');

drop policy if exists "任何人可读chat文件" on storage.objects;
create policy "任何人可读chat文件" on storage.objects
  for select
  using (bucket_id = 'chat-uploads');

drop policy if exists "上传者可删自己的chat文件" on storage.objects;
create policy "上传者可删自己的chat文件" on storage.objects
  for delete
  to authenticated
  using (bucket_id = 'chat-uploads' and auth.uid() = owner);
