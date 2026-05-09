-- messages: 支持 markdown 类型（AI 输出合同/文档）
alter table messages add column if not exists type text not null default 'text';

-- rooms: 专家可通过 Hermes CLI 配置房间级模型和 system prompt
alter table rooms add column if not exists model text not null default '';
alter table rooms add column if not exists system_prompt text not null default '';

comment on column messages.type is 'text | markdown';
comment on column rooms.model is '覆盖 Hermes 全局模型，如 qwen2.5:14b 或 gpt-4o';
comment on column rooms.system_prompt is '专家在 Hermes CLI 设置的房间级 system prompt，追加在行业 prompt 之后';
