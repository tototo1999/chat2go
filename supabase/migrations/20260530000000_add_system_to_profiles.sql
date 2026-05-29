-- Phase 0: bind each user to one learning system + route after login.
-- Adds profiles.system (default 'speak2go' so all existing rows are unaffected),
-- updates handle_new_user() to read it from signup metadata, and an admin RPC to set it.
-- NOTE: This phase does NOT touch RLS (Phase 1). The USING(true) room policies stay.

-- 1. Column + index. Default 'speak2go' keeps every existing profile working.
--    'well2go' included so existing well2go users are representable (they currently
--    route by hostname, but the column can mirror that binding).
alter table public.profiles
  add column if not exists system text not null default 'speak2go'
  check (system in ('speak2go','essay','korean','well2go'));

create index if not exists idx_profiles_system on public.profiles(system);

-- 2. Preserve all existing handle_new_user() logic, additionally set system from
--    signup metadata (coalesce to 'speak2go' when absent).
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path to 'public', 'pg_temp'
as $function$
begin
  insert into profiles (user_id, role, display_name, system)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'role', 'user'),
    coalesce(new.raw_user_meta_data->>'display_name', split_part(new.email, '@', 1)),
    coalesce(new.raw_user_meta_data->>'system', 'speak2go')
  )
  on conflict (user_id) do nothing;
  return new;
end;
$function$;

-- 3. Admin-only RPC to (re)bind a user to a system. Guarded by the existing is_admin().
create or replace function public.admin_set_user_system(p_user_id uuid, p_system text)
returns void
language plpgsql
security definer
set search_path to 'public', 'pg_temp'
as $function$
begin
  if not public.is_admin() then
    raise exception 'admin_set_user_system: caller is not an admin';
  end if;
  if p_system not in ('speak2go','essay','korean','well2go') then
    raise exception 'admin_set_user_system: invalid system %', p_system;
  end if;
  update public.profiles set system = p_system, updated_at = now()
  where user_id = p_user_id;
end;
$function$;

revoke all on function public.admin_set_user_system(uuid, text) from public;
grant execute on function public.admin_set_user_system(uuid, text) to authenticated;
