-- 让 messages.user_id 在用户被删除时级联删除
-- 否则 admin_delete_user 会撞 FK：
--   "update or delete on table users violates foreign key constraint
--    messages_user_id_fkey on table messages"

alter table messages drop constraint if exists messages_user_id_fkey;

alter table messages
  add constraint messages_user_id_fkey
  foreign key (user_id) references auth.users(id) on delete cascade;
