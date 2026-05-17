-- 给 expert_todo_templates 加 product 字段,实现两个产品的 todo 方案隔离
-- 存量行 DEFAULT 'chat2go',新插入由前端按当前产品页面写入
ALTER TABLE expert_todo_templates ADD COLUMN product text NOT NULL DEFAULT 'chat2go';
CREATE INDEX IF NOT EXISTS idx_expert_todo_templates_owner_product ON expert_todo_templates(owner_id, product);
