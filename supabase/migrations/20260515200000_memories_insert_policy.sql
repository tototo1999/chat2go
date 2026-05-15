-- memories 表 INSERT 策略缺失修复(2026-05-15)
--
-- 原 migration 20260510040000_add_memories.sql 只开了 SELECT,
-- INSERT 策略注释掉了(等 Phase B)。结果 bridge 的 sync_memory 调用一直被
-- RLS 默认 deny,没有任何记忆能写进 memories 表。
--
-- 策略对齐 memories_read_scoped 的语义:谁能读就谁能写自己 scope 的记忆。
--   room   scope:必须是该房间成员
--   expert scope:必须是 auth.uid() 本人
--   user   scope:必须是 auth.uid() 本人

drop policy if exists "memories_insert_scoped" on memories;
create policy "memories_insert_scoped" on memories
  for insert to authenticated
  with check (
    (scope = 'user'   and scope_id = auth.uid()) or
    (scope = 'expert' and scope_id = auth.uid()) or
    (scope = 'room'   and exists (
      select 1 from room_members rm
      where rm.room_id = scope_id and rm.user_id = auth.uid()
    ))
  );

-- 顺手开 UPDATE / DELETE owner-self,后续 UI 能给大咖编辑/删自己 memory 用
drop policy if exists "memories_update_own_scope" on memories;
create policy "memories_update_own_scope" on memories
  for update to authenticated
  using (
    (scope = 'user'   and scope_id = auth.uid()) or
    (scope = 'expert' and scope_id = auth.uid()) or
    (scope = 'room'   and exists (
      select 1 from room_members rm
      where rm.room_id = scope_id and rm.user_id = auth.uid()
    ))
  )
  with check (
    (scope = 'user'   and scope_id = auth.uid()) or
    (scope = 'expert' and scope_id = auth.uid()) or
    (scope = 'room'   and exists (
      select 1 from room_members rm
      where rm.room_id = scope_id and rm.user_id = auth.uid()
    ))
  );

drop policy if exists "memories_delete_own_scope" on memories;
create policy "memories_delete_own_scope" on memories
  for delete to authenticated
  using (
    (scope = 'user'   and scope_id = auth.uid()) or
    (scope = 'expert' and scope_id = auth.uid()) or
    (scope = 'room'   and exists (
      select 1 from room_members rm
      where rm.room_id = scope_id and rm.user_id = auth.uid()
    ))
  );
