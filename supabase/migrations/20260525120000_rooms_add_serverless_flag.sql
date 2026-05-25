-- rooms.serverless:为 true 时,Hermes daemon 跳过本房;
-- chat.html 调 chat2go-ingest Edge Function 走 serverless 链路。
-- 2026-05-25 引入,迎接 chat2go.ai 全量去 Hermes 化。

ALTER TABLE rooms ADD COLUMN serverless boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS idx_rooms_serverless ON rooms(serverless) WHERE serverless = true;
COMMENT ON COLUMN rooms.serverless IS '为 true 时,Hermes daemon 跳过本房;chat.html 调 chat2go-ingest Edge Function 走 serverless 链路。2026-05-25 引入。';
