-- 大咖 follower count / list 的公开 RPC
-- room_members 的 RLS 只允许读自己；用 SECURITY DEFINER 绕开，给落地页用。
-- count 对 anon 也开放（未登录访客也能看到数字）；list 仅 authenticated。

-- 1) 数 follower：大咖名下所有 room_members 去重，排掉大咖本人
create or replace function get_expert_follower_count(p_expert_id uuid)
returns int
language sql
security definer
set search_path = public, pg_temp
as $$
  select count(distinct rm.user_id)::int
  from rooms r
  join room_members rm on rm.room_id = r.id
  where r.expert_id = p_expert_id
    and rm.user_id <> p_expert_id;
$$;

grant execute on function get_expert_follower_count(uuid) to anon, authenticated;

-- 2) 列 follower：返回 display_name 和 joined_at（按时间倒序，最多 200 条）
create or replace function get_expert_followers(p_expert_id uuid)
returns table (
  user_id uuid,
  display_name text,
  joined_at timestamptz
)
language sql
security definer
set search_path = public, pg_temp
as $$
  select distinct on (rm.user_id)
    rm.user_id,
    coalesce(p.display_name, '匿名小白') as display_name,
    rm.joined_at
  from rooms r
  join room_members rm on rm.room_id = r.id
  left join profiles p on p.user_id = rm.user_id
  where r.expert_id = p_expert_id
    and rm.user_id <> p_expert_id
  order by rm.user_id, rm.joined_at desc
  limit 200;
$$;

grant execute on function get_expert_followers(uuid) to authenticated;
