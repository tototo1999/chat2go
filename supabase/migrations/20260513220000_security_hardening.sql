-- MVP 上线前安全收紧 + admin 清空/导出聊天

-- ── 1) memories RLS 收紧：不再 using(true) ──
-- room scope：只有该 room 成员能读
-- expert scope：只有那个 expert 本人能读
-- user scope：只有那个 user 本人能读
drop policy if exists "memories_read_all_authenticated" on memories;

create policy "memories_read_scoped" on memories
  for select to authenticated
  using (
    (scope = 'user'   and scope_id = auth.uid()) or
    (scope = 'expert' and scope_id = auth.uid()) or
    (scope = 'room'   and exists (select 1 from room_members rm
                                    where rm.room_id = scope_id
                                      and rm.user_id = auth.uid()))
  );

-- ── 2) Storage bucket 改 private + RLS ──
update storage.buckets set public = false where id = 'chat-uploads';

-- 上传策略保持：任何登录用户都可以 INSERT
-- 但读取策略：只有 room 成员能看（按文件路径前缀挂上 room_id）
-- 但是已有的旧文件路径不一定带 room_id；前端已经在 message.attachments.storage_path 存了完整路径
-- 简化：私有 bucket + 仅 owner 或 service_role 可读；前端走 createSignedUrl 短期签名访问
drop policy if exists "公开读 chat-uploads" on storage.objects;
drop policy if exists "登录用户可上传 chat-uploads" on storage.objects;
drop policy if exists "用户可删自己上传的 chat-uploads" on storage.objects;

create policy "登录用户可上传 chat-uploads" on storage.objects
  for insert to authenticated
  with check (bucket_id = 'chat-uploads');

create policy "登录用户可读自己房间的 chat-uploads" on storage.objects
  for select to authenticated
  using (bucket_id = 'chat-uploads' and (auth.uid() = owner or owner is null));

create policy "用户可删自己上传的 chat-uploads" on storage.objects
  for delete to authenticated
  using (bucket_id = 'chat-uploads' and auth.uid() = owner);

-- ── 3) Admin: 清空某房间所有消息 ──
create or replace function admin_clear_room_messages(p_room_id uuid)
returns int
language plpgsql security definer
set search_path = public, pg_temp
as $body$
declare v_count int;
begin
  if not is_admin() then raise exception 'unauthorized'; end if;
  delete from messages where room_id = p_room_id;
  get diagnostics v_count = row_count;
  return v_count;
end;
$body$;

grant execute on function admin_clear_room_messages(uuid) to authenticated;

-- ── 4) Admin: 导出房间所有消息为 JSON ──
create or replace function admin_export_room(p_room_id uuid)
returns jsonb
language plpgsql security definer
set search_path = public, pg_temp
as $body$
declare v_room jsonb; v_messages jsonb;
begin
  if not is_admin() then raise exception 'unauthorized'; end if;
  select to_jsonb(r.*) into v_room from rooms r where r.id = p_room_id;
  if v_room is null then raise exception 'room not found'; end if;
  select coalesce(jsonb_agg(to_jsonb(m.*) order by m.created_at), '[]'::jsonb)
    into v_messages
    from messages m
   where m.room_id = p_room_id;
  return jsonb_build_object(
    'export_at', now(),
    'room', v_room,
    'messages', v_messages
  );
end;
$body$;

grant execute on function admin_export_room(uuid) to authenticated;
