// chat2go-ingest: chat2go.ai 文本对话的 serverless 入口
//
// 调用方: chat.html(发完消息后 fetch 一次本端点)
// 行为:
//   1. 验证用户 JWT(Edge Function 默认 verify_jwt=true)
//   2. 查 room(industry / system_prompt / serverless 标志)
//   3. INSERT 一条 placeholder AI 消息(role=ai, content='...')
//   4. POST Modal worker(fire-and-forget,不等返回)
//   5. 5s 内返回 { placeholder_id }
//
// Modal worker(worker/chat2go_worker.py)拿到 placeholder_id 后:
//   - 拉本房最近 N 轮 messages 拼上下文
//   - 拼行业 system prompt
//   - 调 Anthropic Claude
//   - UPDATE placeholder.content 为最终回复 → Realtime 推送前端

import { serve } from 'https://deno.land/std@0.168.0/http/server.ts'
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const SUPABASE_URL = Deno.env.get('SUPABASE_URL') ?? ''
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? ''
const MODAL_WORKER_URL = Deno.env.get('CHAT2GO_MODAL_WORKER_URL') ?? ''
const MODAL_WORKER_TOKEN = Deno.env.get('CHAT2GO_MODAL_WORKER_TOKEN') ?? ''

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
}

interface IngestPayload {
  room_id: string
  message_id: string          // 刚 INSERT 的 user/expert 消息 id,worker 拉上下文时用作截止点
  channel?: string            // 'main' | 'expert_ai' (默认 main)
}

serve(async (req) => {
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: CORS_HEADERS })
  }
  if (req.method !== 'POST') {
    return json({ error: 'method_not_allowed' }, 405)
  }

  let body: IngestPayload
  try {
    body = await req.json()
  } catch {
    return json({ error: 'invalid_json' }, 400)
  }
  if (!body.room_id || !body.message_id) {
    return json({ error: 'missing_required_fields' }, 400)
  }

  const sb = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, {
    auth: { autoRefreshToken: false, persistSessions: false },
  })

  // 1. 查 room
  const { data: room, error: rErr } = await sb
    .from('rooms')
    .select('id, industry, system_prompt, model, expert_id, serverless')
    .eq('id', body.room_id)
    .single()
  if (rErr || !room) {
    return json({ error: 'room_not_found', detail: rErr?.message }, 404)
  }
  if (!room.serverless) {
    return json({ error: 'room_not_serverless', hint: '需先把 rooms.serverless 设为 true' }, 409)
  }

  // 2. INSERT placeholder AI 消息。
  //    user_id 用 expert_id(沿用 chat2go 既有约定:AI 消息以大咖账号写入,
  //    前端按 role=ai 判定显示「AI 助手」)
  const channel = body.channel === 'expert_ai' ? 'expert_ai' : 'main'
  const { data: ph, error: phErr } = await sb
    .from('messages')
    .insert({
      room_id: body.room_id,
      user_id: room.expert_id,
      role: 'ai',
      content: '...',
      type: 'text',
      source: 'ai-generated',
      channel,
      attachments: [],
    })
    .select('id')
    .single()
  if (phErr) {
    return json({ error: 'placeholder_insert_failed', detail: phErr.message }, 500)
  }

  // 3. 触发 Modal worker(fire-and-forget)
  const modalPayload = {
    placeholder_id: ph.id,
    room_id: body.room_id,
    trigger_message_id: body.message_id,
    channel,
    industry: room.industry,
    system_prompt: room.system_prompt || '',
    model: room.model || '',
  }

  if (MODAL_WORKER_URL) {
    fetch(MODAL_WORKER_URL, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'authorization': `Bearer ${MODAL_WORKER_TOKEN}`,
      },
      body: JSON.stringify(modalPayload),
    }).catch(err => {
      console.error('[chat2go-ingest] modal trigger failed:', err)
      sb.from('messages').update({
        content: `⚠️ AI 服务暂时不可用,请稍后重试。(${err?.message ?? 'unknown'})`,
      }).eq('id', ph.id).then(() => {})
    })
  } else {
    console.warn('[chat2go-ingest] CHAT2GO_MODAL_WORKER_URL 未配置,跳过触发')
    // 没配 worker 时,把 placeholder 标成提示,避免前端永远转圈
    sb.from('messages').update({
      content: '⚠️ chat2go-ingest 未配置 Modal worker。请联系管理员设置 CHAT2GO_MODAL_WORKER_URL。',
    }).eq('id', ph.id).then(() => {})
  }

  return json({
    ok: true,
    placeholder_id: ph.id,
    modal_dispatched: !!MODAL_WORKER_URL,
  })
})

function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { ...CORS_HEADERS, 'content-type': 'application/json' },
  })
}
