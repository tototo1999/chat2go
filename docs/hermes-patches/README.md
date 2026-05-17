# Hermes 本机改动存档

> 这些 patch 不是在 chat2go / chat2go-cloud / chat2go-archive 仓库里的代码,
> 而是改在了 `~/.hermes/hermes-agent/` 本机 Hermes 安装里。
> Hermes 升级(`hermes update`)会冲掉,届时按这些 patch 重打。

## 文件

| 文件 | 改的位置 | 干啥 |
|---|---|---|
| `01-skip-busy-ack-chat2go.patch` | `gateway/run.py` | chat2go 平台不发「⚡ Interrupting current task」占位消息 |
| `02-chat2go-platform-adapter.patch` | `gateway/platforms/chat2go.py`(整个新文件) | chat2go 平台适配器实现,含 _prefetch_memory / _sync_memory / bridge_pong 心跳 / model_usage token 写入 / `_read_hermes_default_model()` 让 stub_model 自动跟随 `~/.hermes/config.yaml`(切模型不用动 env) / `_watchdog_loop()` 监控 _poll_loop 卡死(>60s 没心跳就 os._exit(1) 让 launchd 拉起,防 Realtime 1006 反复掉线引发的 event loop 卡死) |

## 应用方式

```bash
cd ~/.hermes/hermes-agent
git apply ~/chat2go/docs/hermes-patches/01-skip-busy-ack-chat2go.patch
# chat2go.py 直接拷:
cp ~/chat2go/docs/hermes-patches/02-... gateway/platforms/chat2go.py  # 视情况手动
```

## 配套环境(也要重新配)

```bash
# ~/.hermes/.env 必须有:
echo "CHAT2GO_TOKEN=c2g-key_xxx" >> ~/.hermes/.env

# ~/.hermes/config.yaml display.busy_input_mode 改:
# busy_input_mode: queue

launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway
```
