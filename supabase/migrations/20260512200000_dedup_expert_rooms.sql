-- 去重：删除同一大咖（expert_id）下同名（name）的重复房间，仅保留最早创建的一个
-- 兜底历史脏数据，配合前端 renderRoomItem / openRoomById 的外来房拒绝逻辑

WITH ranked AS (
  SELECT
    id,
    ROW_NUMBER() OVER (PARTITION BY expert_id, name ORDER BY created_at ASC) AS rn
  FROM rooms
)
DELETE FROM rooms
WHERE id IN (
  SELECT id FROM ranked WHERE rn > 1
);
