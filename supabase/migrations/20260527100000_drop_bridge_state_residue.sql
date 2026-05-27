-- 2026-05-27: serverless cutover 后清 schema 残留。
-- bridge_state 表 + bridge_pong / request_bridge_restart RPC 已无调用方:
-- chat.html 4 个 setBridgeStatus 已改钉绿空 stub,Hermes daemon 全部 bootout。
-- admin_bridge_status() 名字误导但实查 model_usage 表,保留。

DROP FUNCTION IF EXISTS bridge_pong(integer, text);
DROP FUNCTION IF EXISTS request_bridge_restart();
DROP TABLE IF EXISTS bridge_state CASCADE;
