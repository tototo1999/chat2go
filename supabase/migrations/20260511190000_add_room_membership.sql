-- 房间成员制 + 邀请 token + RLS 收紧
-- 设计：每个 room 一个 invite_token；大咖创建房时自动成为成员；
-- 小白通过 /chat.html?room=<id>&t=<token> 链接调用 join_room_by_token(token) 加入。
-- 收紧 rooms/messages 的 SELECT/INSERT：必须是 room_members 中的成员。

-- 1) rooms 加 invite_token（唯一邀请凭证）
ALTER TABLE rooms
  ADD COLUMN IF NOT EXISTS invite_token uuid NOT NULL DEFAULT gen_random_uuid();
CREATE UNIQUE INDEX IF NOT EXISTS idx_rooms_invite_token ON rooms (invite_token);

-- 2) 成员表
CREATE TABLE IF NOT EXISTS room_members (
  room_id   uuid NOT NULL REFERENCES rooms(id)      ON DELETE CASCADE,
  user_id   uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  joined_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (room_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_room_members_user ON room_members (user_id);

ALTER TABLE room_members ENABLE ROW LEVEL SECURITY;

-- 3) 自动把大咖加成成员（建房触发器）
CREATE OR REPLACE FUNCTION trg_auto_add_expert_as_member()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO room_members (room_id, user_id)
    VALUES (NEW.id, NEW.expert_id)
    ON CONFLICT DO NOTHING;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS auto_add_expert_member ON rooms;
CREATE TRIGGER auto_add_expert_member
  AFTER INSERT ON rooms
  FOR EACH ROW EXECUTE FUNCTION trg_auto_add_expert_as_member();

-- 4) 历史数据回填：已有房间把 expert 补成成员
INSERT INTO room_members (room_id, user_id)
SELECT id, expert_id FROM rooms WHERE expert_id IS NOT NULL
ON CONFLICT DO NOTHING;

-- 5) 凭 token 加入房间 RPC（绕开 RLS 直插成员表）
CREATE OR REPLACE FUNCTION join_room_by_token(p_token uuid)
RETURNS uuid AS $$
DECLARE
  v_room_id uuid;
  v_user_id uuid;
BEGIN
  v_user_id := auth.uid();
  IF v_user_id IS NULL THEN
    RAISE EXCEPTION 'must be authenticated';
  END IF;
  SELECT id INTO v_room_id FROM rooms WHERE invite_token = p_token;
  IF v_room_id IS NULL THEN
    RAISE EXCEPTION 'invalid invite token';
  END IF;
  INSERT INTO room_members (room_id, user_id)
    VALUES (v_room_id, v_user_id)
    ON CONFLICT DO NOTHING;
  RETURN v_room_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION join_room_by_token(uuid) TO authenticated;

-- 6) 收紧 rooms SELECT：必须是成员
DROP POLICY IF EXISTS "任何人可读rooms" ON rooms;
CREATE POLICY "成员可读rooms" ON rooms
  FOR SELECT TO authenticated
  USING (
    expert_id = auth.uid() OR
    EXISTS (SELECT 1 FROM room_members WHERE room_id = rooms.id AND user_id = auth.uid())
  );

-- 7) 收紧 messages SELECT：必须是房间成员
DROP POLICY IF EXISTS "任何人可读messages" ON messages;
CREATE POLICY "成员可读messages" ON messages
  FOR SELECT TO authenticated
  USING (
    EXISTS (SELECT 1 FROM room_members WHERE room_id = messages.room_id AND user_id = auth.uid())
  );

-- 8) 收紧 messages INSERT：必须是成员（保留 user_id 自检）
DROP POLICY IF EXISTS "登录用户可发消息" ON messages;
CREATE POLICY "成员可发消息" ON messages
  FOR INSERT TO authenticated
  WITH CHECK (
    auth.uid() = user_id
    AND EXISTS (SELECT 1 FROM room_members WHERE room_id = messages.room_id AND user_id = auth.uid())
  );

-- 9) room_members 读取：本人或房主可读
CREATE POLICY "成员或房主可读成员表" ON room_members
  FOR SELECT TO authenticated
  USING (
    user_id = auth.uid() OR
    EXISTS (SELECT 1 FROM rooms WHERE rooms.id = room_members.room_id AND rooms.expert_id = auth.uid())
  );

-- 10) 房主可踢人（DELETE 自己房的成员，但不能踢自己）
CREATE POLICY "房主可踢成员" ON room_members
  FOR DELETE TO authenticated
  USING (
    user_id <> auth.uid()
    AND EXISTS (SELECT 1 FROM rooms WHERE rooms.id = room_members.room_id AND rooms.expert_id = auth.uid())
  );
