-- 房间级别可指定 brain：'builtin' | 'hermes' | 'auto' | NULL
-- NULL 时走 chat2go-agent 的默认（credentials.yaml defaults.brain）

alter table rooms add column if not exists brain text;
alter table rooms add constraint rooms_brain_check
  check (brain is null or brain in ('builtin', 'hermes', 'auto'));
