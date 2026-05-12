-- 小白 follow 即生效：跳过审批，直接加入大咖唯一的房间。
-- 旧 follow_requests 表保留以记录关注关系，但 status 立即为 'approved'。
-- 新 RPC follow_expert(p_expert_id) 原子完成：写/升级 follow_requests + 加入 room_members。

-- 1) follow_expert RPC（SECURITY DEFINER 绕开 RLS 写 room_members）
CREATE OR REPLACE FUNCTION follow_expert(p_expert_id uuid)
RETURNS uuid AS $$
DECLARE
  v_user_id uuid := auth.uid();
  v_room_id uuid;
  v_existing int;
BEGIN
  IF v_user_id IS NULL THEN
    RAISE EXCEPTION 'must be authenticated';
  END IF;
  IF v_user_id = p_expert_id THEN
    RAISE EXCEPTION 'cannot follow yourself';
  END IF;

  SELECT id INTO v_room_id FROM rooms WHERE expert_id = p_expert_id LIMIT 1;

  -- 已有任意状态的记录：升级为 approved
  UPDATE follow_requests
     SET status = 'approved', decided_at = now()
   WHERE expert_id = p_expert_id
     AND user_id = v_user_id
     AND status <> 'approved';

  -- 没有任何记录：插一条 approved
  SELECT count(*) INTO v_existing
    FROM follow_requests
   WHERE expert_id = p_expert_id AND user_id = v_user_id;
  IF v_existing = 0 THEN
    INSERT INTO follow_requests (expert_id, user_id, status, decided_at)
      VALUES (p_expert_id, v_user_id, 'approved', now());
  END IF;

  -- 加入大咖房间
  IF v_room_id IS NOT NULL THEN
    INSERT INTO room_members (room_id, user_id)
      VALUES (v_room_id, v_user_id)
      ON CONFLICT DO NOTHING;
  END IF;

  RETURN v_room_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION follow_expert(uuid) TO authenticated;

-- 2) 历史 pending 一次性 approve，并把已 approved 的小白补齐 room_members
UPDATE follow_requests
   SET status = 'approved', decided_at = COALESCE(decided_at, now())
 WHERE status = 'pending';

INSERT INTO room_members (room_id, user_id)
SELECT r.id, fr.user_id
  FROM follow_requests fr
  JOIN rooms r ON r.expert_id = fr.expert_id
 WHERE fr.status = 'approved'
ON CONFLICT DO NOTHING;
