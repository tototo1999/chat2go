-- 修复：上一个迁移 revoke select 之后，bridge 写不进 model_usage 了。
-- 显式 GRANT INSERT（RLS 的 with check 仍然限制只能写自己 expert_id 的行）。

grant insert on model_usage to authenticated;
