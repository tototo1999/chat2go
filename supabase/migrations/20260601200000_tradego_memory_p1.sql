-- P1:记忆条目加「类型」和「标题」(标题用于去重/更新同一条)
alter table tradego_memory_rules add column if not exists kind  text not null default 'rule';
alter table tradego_memory_rules add column if not exists title text;
-- 按 (大咖, 产品, 标题) 找同一条记忆(remember 去重/更新用)
create index if not exists idx_tradego_rules_title
  on tradego_memory_rules(expert_id, product, title);
comment on column tradego_memory_rules.kind  is 'rule|template|company|customer|fact';
comment on column tradego_memory_rules.title is '短标题,同 (expert,product,title) = 同一条,再 remember 即更新';
