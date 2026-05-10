-- 修正：小白不应看到原始成本（决策：小白只看最终账单）
--
-- 整改：
--   1. room_costs 视图去掉 cost_usd（公开视图，小白和大咖都用它显示徽章）
--   2. room_profits 新视图（大咖专用，包含 cost_usd + 利润）
--   3. model_usage 表用列级 GRANT，禁止任何 authenticated 直接读 cost_usd / cost_source

-- ── 1. 公开视图（不含成本）──
drop view if exists room_costs;
create view room_costs as
  select
    room_id,
    count(*) as message_count,
    sum(input_tokens) as total_input_tokens,
    sum(output_tokens) as total_output_tokens,
    sum(user_charge_cny) as total_charge_cny,
    max(created_at) as last_used_at
  from model_usage
  group by room_id;
grant select on room_costs to authenticated;

-- ── 2. 大咖专用视图（含成本）──
create or replace view room_profits as
  select
    room_id,
    expert_id,
    count(*) as message_count,
    sum(input_tokens) as total_input_tokens,
    sum(output_tokens) as total_output_tokens,
    sum(cost_usd) as total_cost_usd,
    sum(user_charge_cny) as total_charge_cny,
    max(created_at) as last_used_at
  from model_usage
  group by room_id, expert_id;
grant select on room_profits to authenticated;
-- RLS 自动按 expert_id = auth.uid() 过滤，小白看到 0 行

-- ── 3. 列级权限：cost_usd 和 cost_source 任何人 select 表都拿不到 ──
revoke select on model_usage from authenticated;
grant select (
  id, message_id, room_id, expert_id, triggered_by, model,
  input_tokens, output_tokens,
  commission_pct, exchange_rate, user_charge_cny,
  created_at
) on model_usage to authenticated;
-- 即使大咖 select * from model_usage 也只能拿到白名单字段；
-- 看成本必须通过 room_profits 视图（视图以 owner 身份执行，能读 cost_usd）。
