-- Fix: room_members SELECT 策略和 rooms SELECT 策略交叉 EXISTS 触发 RLS 递归
-- 症状：创建房间时 .insert().select() 报 "infinite recursion detected in policy for relation rooms"
-- 修复：room_members SELECT 只检查 user_id = auth.uid()，不再反查 rooms

DROP POLICY IF EXISTS "成员或房主可读成员表" ON room_members;
DROP POLICY IF EXISTS "成员可读成员表" ON room_members;
CREATE POLICY "成员可读成员表" ON room_members
  FOR SELECT TO authenticated
  USING (user_id = auth.uid());
