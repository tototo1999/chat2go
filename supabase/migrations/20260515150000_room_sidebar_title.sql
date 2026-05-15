-- sidebar 顶部绿色卡片的房间主题，跟大咖 profile.display_name 解耦
-- null 时前端 fallback 到 expert.display_name（保持旧行为）

alter table rooms add column if not exists sidebar_title text;
