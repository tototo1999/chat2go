-- 给 rooms 加 product 字段,实现 chat2go / tradego 子目录的房间数据隔离
-- 存量行 DEFAULT 'chat2go',新插入由前端按当前产品页面写入
ALTER TABLE rooms ADD COLUMN product text NOT NULL DEFAULT 'chat2go';
CREATE INDEX IF NOT EXISTS idx_rooms_product ON rooms(product);
