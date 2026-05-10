-- 修复：gen_random_bytes / digest 在 extensions schema 里，必须 schema-qualified
-- （Supabase 的 search_path 默认不包含 extensions）

create or replace function generate_agent_key(p_name text)
returns table (token text, prefix text, id uuid)
language plpgsql
security definer
set search_path = public, extensions, pg_temp
as $$
declare
  v_caller uuid;
  v_role text;
  v_raw_token text;
  v_hash text;
  v_prefix text;
  v_id uuid;
begin
  v_caller := auth.uid();
  if v_caller is null then
    raise exception 'not authenticated';
  end if;

  select role into v_role from profiles where user_id = v_caller;
  if v_role is null or v_role <> 'expert' then
    raise exception 'only experts can generate agent keys (current role: %)', coalesce(v_role, 'none');
  end if;

  v_raw_token := 'c2g-key_' || encode(extensions.gen_random_bytes(32), 'hex');
  v_hash := encode(extensions.digest(v_raw_token, 'sha256'), 'hex');
  v_prefix := substring(v_raw_token from 1 for 16);

  insert into expert_agent_keys (expert_id, name, key_hash, key_prefix)
    values (v_caller, p_name, v_hash, v_prefix)
    returning expert_agent_keys.id into v_id;

  return query select v_raw_token, v_prefix, v_id;
end;
$$;
