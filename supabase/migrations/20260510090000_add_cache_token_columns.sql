-- Anthropic prompt caching 计费修复
--
-- 之前 input_tokens 包含 cache_read 部分，按 base 价计算，结果高估约 10×。
-- 改为：input_tokens 只算 fresh（未缓存）；cache_creation 单独一列；cache_read 单独一列。
-- pricing：fresh × base + cache_write × base × 1.25 + cache_read × base × 0.10 + output × out_rate

alter table model_usage add column if not exists cache_creation_input_tokens int default 0;
alter table model_usage add column if not exists cache_read_input_tokens int default 0;

-- 列级 GRANT 也要给新列（允许 SELECT 但不允许直接读 cost_usd / cost_source）
grant select (cache_creation_input_tokens, cache_read_input_tokens)
  on model_usage to authenticated;

-- 重建 room_costs 视图：total_input_tokens 改为含三档之和（用于前端"累计 token"显示）
drop view if exists room_costs;
create view room_costs as
  select
    room_id,
    count(*) as message_count,
    sum(input_tokens + cache_creation_input_tokens + cache_read_input_tokens) as total_input_tokens,
    sum(output_tokens) as total_output_tokens,
    sum(cache_creation_input_tokens) as total_cache_creation_tokens,
    sum(cache_read_input_tokens) as total_cache_read_tokens,
    sum(user_charge_cny) as total_charge_cny,
    max(created_at) as last_used_at
  from model_usage
  group by room_id;
grant select on room_costs to authenticated;

-- 大咖专用视图同步
create or replace view room_profits as
  select
    room_id,
    expert_id,
    count(*) as message_count,
    sum(input_tokens + cache_creation_input_tokens + cache_read_input_tokens) as total_input_tokens,
    sum(output_tokens) as total_output_tokens,
    sum(cost_usd) as total_cost_usd,
    sum(user_charge_cny) as total_charge_cny,
    max(created_at) as last_used_at
  from model_usage
  group by room_id, expert_id;
grant select on room_profits to authenticated;
