-- 大咖可以删除自己创建的房间（级联会删 messages 等子表）

create policy "大咖可删自己房间" on rooms
  for delete
  to authenticated
  using (expert_id = auth.uid());
