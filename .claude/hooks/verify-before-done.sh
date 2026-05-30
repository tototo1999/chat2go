#!/usr/bin/env bash
# Stop hook: 纪律守卫 —— 当本轮助手「声称做完」却没跑任何验证命令时,拦一下让它先验证。
# 纯文本判定,无 LLM,正常聊天/无声称的回答 0 延迟、0 拦截。
# 输入(stdin JSON): { transcript_path, stop_hook_active, ... }
set -euo pipefail

input="$(cat)"
transcript="$(printf '%s' "$input" | jq -r '.transcript_path // empty')"
active="$(printf '%s' "$input" | jq -r '.stop_hook_active // false')"

# 已经因本钩子停过一次 → 放行,避免死循环
[ "$active" = "true" ] && exit 0
[ -z "$transcript" ] || [ ! -f "$transcript" ] && exit 0

# 取「最后一次真实用户提问」之后的本轮助手消息:
#   - 拼出本轮所有 assistant 文本
#   - 是否出现过验证类 tool_use(Bash / playwright / supabase / chrome 浏览器)
read -r enc_text used_verify < <(jq -rs '
  def is_user_prompt:
    .message.role == "user"
    and ( (.message.content) as $c
          | if ($c|type)=="string" then true
            elif ($c|type)=="array" then ($c | any(.type=="text"))
            else false end );
  (map(is_user_prompt) | (rindex(true) // -1)) as $u
  | .[($u+1):] as $turn
  | ($turn
     | map(select(.message.role=="assistant"))
     | map(.message.content // [] | map(select(.type=="text") | .text) | join("\n"))
     | join("\n")) as $text
  | ($turn
     | map(.message.content // [] | map(select(.type=="tool_use") | .name) | .[])
     | flatten
     | any(. == "Bash"
           or startswith("mcp__playwright__")
           or startswith("mcp__supabase__")
           or startswith("mcp__claude-in-chrome__"))) as $verified
  | ( ($text|@base64) + " " + ($verified|tostring) )
' "$transcript" 2>/dev/null)

# 解码本轮文本
text="$(printf '%s' "${enc_text:-}" | base64 --decode 2>/dev/null || true)"
used_verify="${used_verify:-false}"

# 已经跑过验证 → 放行
[ "$used_verify" = "true" ] && exit 0

# 是否出现「声称做完」的强信号(中英)。保守集合,降低误判。
if printf '%s' "$text" | grep -Eiq '修好了|已修复|修复完成|已完成|搞定|部署(完成|好了|成功)|测试(通过|都过|全过)|tests? (pass|passed|are passing)|all (tests )?pass|✅ ?(完成|done|fixed)|已上线|已推送并验证'; then
  printf '{"decision":"block","reason":"⚠️ 纪律守卫:你这轮声称已完成/修好/通过,但本轮没有跑过任何验证命令(Bash / Playwright / Supabase / 浏览器)。请先实际运行验证、贴出真实输出证据,再下结论。若本就是讨论性回答而非声称完成,可直接复述结论收尾。"}'
  exit 0
fi

exit 0
