-- 小白 follow 即生效（简化版）：
-- 直接放 RLS 让小白自助 INSERT room_members，并开放 rooms SELECT 让小白能查到大咖的房。
-- 不再使用 RPC（避免 SQL Editor 对 dollar quote 的兼容性问题）。

-- 1) room_members INSERT：允许任何登录用户把自己加进任意房间
CREATE POLICY "小白可自助加入房间" ON room_members
  FOR INSERT TO authenticated
  WITH CHECK (user_id = auth.uid());

-- 2) rooms SELECT：放开给所有登录用户（小白要能查到 expert 的 room_id 才能加入）
DROP POLICY IF EXISTS "成员可读rooms" ON rooms;
CREATE POLICY "登录用户可读rooms" ON rooms
  FOR SELECT TO authenticated
  USING (true);

-- 3) 兜底：把已 approved 的 follow_requests 同步到 room_members（防止历史脏数据）
INSERT INTO room_members (room_id, user_id)
SELECT r.id, fr.user_id
  FROM follow_requests fr
  JOIN rooms r ON r.expert_id = fr.expert_id
 WHERE fr.status = 'approved'
ON CONFLICT DO NOTHING;
