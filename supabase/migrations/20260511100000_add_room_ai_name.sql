-- 给 rooms 加 ai_name：每个调试室可以独立给 AI 起名（大咖编辑）
-- 默认 null，前端 fallback 到 'AI 助手'

alter table rooms add column if not exists ai_name text;

comment on column rooms.ai_name is '本房间 AI 显示名（大咖可编辑），为空时前端显示默认 "AI 助手"';
