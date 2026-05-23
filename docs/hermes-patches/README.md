# Hermes 本机改动存档

> 这些文件不是 hermes 上游代码,而是改在了 `~/.hermes/hermes-agent/` 和 `~/.hermes/libs/` 本机
> Hermes 安装里。Hermes 升级(`hermes update`)会冲掉 `hermes-agent/`,届时按 patch 重打。
> `libs/` 子目录是独立模块树,直接 `cp -r` 还原。

## 文件结构

| 路径 | 改的位置 | 干啥 |
|---|---|---|
| `01-skip-busy-ack-chat2go.patch` | `gateway/run.py` | chat2go 平台不发「⚡ Interrupting current task」占位消息 |
| `02-chat2go-platform-adapter.patch` | `gateway/platforms/chat2go.py`(整个新文件) | chat2go 平台适配器。包含:_prefetch_memory / _sync_memory / bridge_pong 心跳 / model_usage token 写入 / `_read_hermes_default_model()` stub_model 自动跟随 config.yaml / `_watchdog_loop()` 防 _poll_loop 卡死 / 上传音频(.mp3/.m4a/.wav)检测 + 二级 mlx-whisper 转写 + speak2go 专属 `handle_audio_upload_lesson` spawn / extract_todos / translate / confirm_todo_apply / discard_todo_proposal dispatcher |
| `03-yuanbao-enum-stub.patch` | `gateway/config.py` | 仅 mini 部署需要:dev 老 commit 缺 `Platform.YUANBAO`,mini base 引用了它 |
| `04-help-guidance-stub.patch` | `agent/prompt_builder.py` | 仅 mini 部署需要:dev 老 commit 没定义 `HERMES_AGENT_HELP_GUIDANCE`,mini base import 时挂 |
| `libs/speak2go.py` | `~/.hermes/libs/speak2go.py` | speak2go 上传录音 handler 全套:`handle_audio_upload_lesson`(主流程,Haiku 抽 todo + 私聊 transcript) / `_diarize_and_label*`(ffmpeg→pyannote→merge) / `_ffmpeg_to_wav16k_mono` / `handle_extract_todos_from_recording`(🎙 重抽,数据源=transcript_full) / `handle_translate_message`(🌐) / `handle_confirm_todo_apply` / `handle_discard_todo_proposal` / `call_claude` |
| `libs/asr/__init__.py` | 同 | namespace package |
| `libs/asr/mlx_whisper_provider.py` | 同 | mlx-whisper large-v3-turbo 包装。**关键参数**:`condition_on_previous_text=False`(防 token loop)+ `_strip_loops` 正则后处理(ngram×≥10 截到 ×3)+ `DEFAULT_INITIAL_PROMPT`(英语教学词表 bias,env `MLX_WHISPER_INITIAL_PROMPT` 可覆盖) |
| `libs/asr/transcript_merger.py` | 同 | 4 信号 T/S 启发式:`avg_chars × (0.5 + uniq_ratio) × (1 + 0.3·q_rate + 0.3·tm_rate)`。`q_rate` = 段含 `?` 比例,`tm_rate` = 教学标记词(`good`/`perfect`/`remember`/`look`/`try`/`say` 等 21 词)出现率。**实测**:5min 英语课 margin 76%,1hr 课 29% |
| `libs/asr/pyannote_diarizer.py` | 同 | pyannote/speaker-diarization-3.1 包装,MPS 加速,RTF≈0.1 |
| `libs/asr/speaker.py` | 同 | (旧 SpeechBrain ECAPA 模块。2026-05-21 声纹识别清理后**未删但未用**,留作 future revival) |

## 已删除(git history 可查)

- `05-realtime-classroom-asr.patch` — 2026-05-22 整条实时课堂 ws://asr_server 流删除,obsolete
- `06-mlx-whisper-audio-transcribe.snippet.py` — 被 `libs/` 全量镜像取代

## 应用方式(restore 时)

```bash
# 1. hermes-agent patches
cd ~/.hermes/hermes-agent
git apply ~/chat2go/docs/hermes-patches/01-skip-busy-ack-chat2go.patch

# 2. chat2go platform adapter(整文件)
cp ~/chat2go/docs/hermes-patches/02-chat2go-platform-adapter.patch \
   ~/.hermes/hermes-agent/gateway/platforms/chat2go.py
# 注意:patch 文件首两行是 diff 头,要手动跳过或 git apply

# 3. libs 子目录(speak2go 上传转写管线)
cp -r ~/chat2go/docs/hermes-patches/libs/* ~/.hermes/libs/

# 4. speak2go HERMES_HOME 双路径同步(see project_speak2go_singleton_room_live memory)
cp -r ~/.hermes/libs/* ~/.hermes-speak2go/libs/

# 5. 重启
launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway
launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway.speak2go
```

## 配套环境

```bash
# ~/.hermes/.env / ~/.hermes-speak2go/.env 必须有:
CHAT2GO_TOKEN=c2g-key_xxx
CHAT2GO_SUPABASE_URL=https://qjnagbzqhoansixqharb.supabase.co
CHAT2GO_SUPABASE_ANON_KEY=...
ANTHROPIC_API_KEY=sk-ant-...
HF_TOKEN=hf_...                       # pyannote diarize 需要(speak2go 才用)
MLX_WHISPER_INITIAL_PROMPT=...        # 可选,覆盖默认英语教学 prompt
MLX_WHISPER_MODEL=mlx-community/whisper-large-v3-turbo  # 可选

# Python 包(install 在 hermes venv):
pip install supabase httpx certifi pypdf python-docx \
            mlx-whisper pyannote.audio
```

## 维护陷阱

- `~/.hermes/libs/` 跟 `~/.hermes-speak2go/libs/` 是**两份独立副本**(speak2go Hermes HERMES_HOME 隔离),改 `libs/*.py` 必须**两边都 cp**,否则 speak2go gateway 跑旧版报 `AttributeError`
- 改完两边 + `find ... -name '__pycache__' -delete` + `launchctl kickstart -k` 才生效
- chat2go.py adapter 改动同时影响 4 个产品 Hermes(chat2go.cn 命理 / tradego / well2go / speak2go),用 `room.get("product") == "speak2go"` 守卫单产品逻辑
