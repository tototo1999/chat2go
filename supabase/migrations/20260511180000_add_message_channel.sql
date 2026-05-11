-- messages 加 channel 字段，支持房间内大咖↔小白私聊
-- 'main'         : 三方共聊（默认，向后兼容；AI 参与）
-- 'expert_user'  : 大咖 ↔ 小白 私聊（AI 不响应）

ALTER TABLE messages
  ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'main'
  CHECK (channel IN ('main', 'expert_user'));

-- 加速 (room_id, channel, created_at) 查询路径
CREATE INDEX IF NOT EXISTS idx_messages_room_channel_time
  ON messages (room_id, channel, created_at);
