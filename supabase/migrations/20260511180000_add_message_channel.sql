-- messages 加 channel 字段，支持房间内私聊分页
-- 'main'         : 三方共聊（默认，向后兼容）
-- 'expert_ai'    : 大咖 ↔ AI 私聊（小白不可见）
-- 'expert_user'  : 大咖 ↔ 小白 私聊（AI 不响应）

ALTER TABLE messages
  ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'main'
  CHECK (channel IN ('main', 'expert_ai', 'expert_user'));

-- 加速 (room_id, channel, created_at) 查询路径
CREATE INDEX IF NOT EXISTS idx_messages_room_channel_time
  ON messages (room_id, channel, created_at);
