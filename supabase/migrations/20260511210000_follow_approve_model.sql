-- 改用 follow/approve 模型：
--   每个大咖 = 1 个固定房间
--   小白 → 落地页 / 入站后发起 follow → 大咖 approve → 小白进入大咖的房
--   作为副产物：清掉历史数据，重新开始

-- 1) 清空所有房间数据（CASCADE 处理子表：messages、room_members、model_usage 等）
TRUNCATE messages, room_members, rooms CASCADE;

-- 2) follow_requests 表
CREATE TABLE IF NOT EXISTS follow_requests (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  expert_id   uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  user_id     uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  status      text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','approved','rejected')),
  created_at  timestamptz NOT NULL DEFAULT now(),
  decided_at  timestamptz,
  CHECK (expert_id <> user_id)
);

-- 同一对 (大咖, 小白) 同时只能有一条 pending 请求
CREATE UNIQUE INDEX IF NOT EXISTS uq_follow_request_pending
  ON follow_requests (expert_id, user_id)
  WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_follow_requests_expert_status
  ON follow_requests (expert_id, status, created_at DESC);

ALTER TABLE follow_requests ENABLE ROW LEVEL SECURITY;

-- 3) RLS
-- 小白发起请求：只能写自己的 user_id
CREATE POLICY "小白可发起 follow" ON follow_requests
  FOR INSERT TO authenticated
  WITH CHECK (user_id = auth.uid());

-- 双方都能读和自己相关的请求
CREATE POLICY "双方可读相关 follow 请求" ON follow_requests
  FOR SELECT TO authenticated
  USING (user_id = auth.uid() OR expert_id = auth.uid());

-- 大咖更新自己被请求的状态
CREATE POLICY "大咖可决定 follow 请求" ON follow_requests
  FOR UPDATE TO authenticated
  USING (expert_id = auth.uid())
  WITH CHECK (expert_id = auth.uid());

-- 4) Trigger：approve 后自动把小白加入大咖唯一的房间
CREATE OR REPLACE FUNCTION trg_on_follow_decided()
RETURNS TRIGGER AS $$
DECLARE
  v_room_id uuid;
BEGIN
  IF NEW.status = 'approved' AND (OLD.status IS DISTINCT FROM 'approved') THEN
    NEW.decided_at := now();
    SELECT id INTO v_room_id FROM rooms WHERE expert_id = NEW.expert_id LIMIT 1;
    IF v_room_id IS NOT NULL THEN
      INSERT INTO room_members (room_id, user_id)
        VALUES (v_room_id, NEW.user_id)
        ON CONFLICT DO NOTHING;
    END IF;
  ELSIF NEW.status = 'rejected' AND (OLD.status IS DISTINCT FROM 'rejected') THEN
    NEW.decided_at := now();
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_follow_request_decided ON follow_requests;
CREATE TRIGGER on_follow_request_decided
  BEFORE UPDATE ON follow_requests
  FOR EACH ROW EXECUTE FUNCTION trg_on_follow_decided();
