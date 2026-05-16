-- 撤回 20260516170000 的 trigger 方案
-- 原计划:大咖在 AI 消息打 ✓ → DB trigger 自动写 memory
-- 实际:trigger 注册后 0 fire(原因未深究),为避免跟 ratings 路径
-- (双钩 pass relay)耦合冲突,改用「大咖文字关键词触发」替代,
-- 实现在 Hermes adapter ~/.hermes/hermes-agent/gateway/platforms/chat2go.py
-- 的 _is_memory_save_cmd + _save_context_as_memory 里。
--
-- rollback(若要恢复 trigger 路径):见 migration 20260516170000

drop trigger if exists trg_save_memory_on_expert_up on messages;
drop function if exists trg_save_memory_on_expert_up_fn();
