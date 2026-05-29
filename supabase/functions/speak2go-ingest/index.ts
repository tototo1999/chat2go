// speak2go-ingest:Mentra Live glass-demo 上传触发端点
//
// 调用方:MentraOS app(配对后老师戴的眼镜)/ 任何客户端
// 行为:
//   1. 验证简单 token(GLASS_INGEST_TOKEN,Mentra app 配对时拿到)
//   2. INSERT placeholder message "📝 正在分析《name》..."(role=ai,channel=main)
//   3. POST trigger Modal worker(异步,不等返回)
//   4. 5s 内返回 {placeholder_id, modal_job_url}
//
// Modal worker 拉 Supabase Storage 文件 → Gemini 2.5 Flash 一次出 transcript+diarize+summary
// → 写回 messages(transcript_full 私聊 + multimodal_summary 主聊)+ UPDATE placeholder

import { serve } from 'https://deno.land/std@0.168.0/http/server.ts'
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const SUPABASE_URL = Deno.env.get('SUPABASE_URL') ?? ''
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? ''
const GLASS_INGEST_TOKEN = Deno.env.get('GLASS_INGEST_TOKEN') ?? ''
const MODAL_WORKER_URL = Deno.env.get('MODAL_WORKER_URL') ?? ''
const MODAL_WORKER_TOKEN = Deno.env.get('MODAL_WORKER_TOKEN') ?? ''

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type, x-glass-token',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
}

interface IngestPayload {
  room_id: string
  expert_user_id: string         // Mentra 配对时拿到,代表房间的"老师"账号(AI 助教等价物)
  audio_path: string              // Supabase Storage path: chat-uploads/<room>/glass/<id>.m4a
  audio_name?: string             // 文件名(显示用)
  audio_duration_s?: number       // 秒
  photo_paths?: string[]          // Storage paths for board snapshots
  captured_at?: string            // iso8601
  lesson_segment_id?: string      // 同一节课多次 trigger 时用,绑定段
  product?: string                // 可选覆盖;默认读 rooms.product(speak2go 词汇 / essay 写作 / korean 韩语)
}

serve(async (req) => {
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: CORS_HEADERS })
  }
  if (req.method !== 'POST') {
    return json({ error: 'method_not_allowed' }, 405)
  }

  // 1. 验证 token(MVP 共享密钥)
  const token = req.headers.get('x-glass-token') ?? ''
  if (!GLASS_INGEST_TOKEN || token !== GLASS_INGEST_TOKEN) {
    return json({ error: 'unauthorized' }, 401)
  }

  // 2. 解析 payload
  let body: IngestPayload
  try {
    body = await req.json()
  } catch {
    return json({ error: 'invalid_json' }, 400)
  }
  if (!body.room_id || !body.expert_user_id || !body.audio_path) {
    return json({ error: 'missing_required_fields' }, 400)
  }

  const sb = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, {
    auth: { autoRefreshToken: false, persistSessions: false },
  })

  // 2b. 取房间的 product(决定 worker 用哪套提炼 prompt);body.product 可覆盖,缺省 speak2go
  let product = (body.product || '').trim()
  if (!product) {
    const { data: roomRow } = await sb
      .from('rooms').select('product').eq('id', body.room_id).maybeSingle()
    product = (roomRow?.product || 'speak2go')
  }

  // 3. INSERT placeholder message(老师视角:看到"正在分析"的卡片)
  const audioName = body.audio_name || body.audio_path.split('/').pop() || 'recording'
  const durStr = body.audio_duration_s
    ? ` (${Math.round(body.audio_duration_s / 60)}min)`
    : ''
  const placeholderContent = `🎙 已收到《${audioName}》${durStr} — 转写 + 多模态分析中...`

  const { data: phRow, error: phErr } = await sb
    .from('messages')
    .insert({
      room_id: body.room_id,
      user_id: body.expert_user_id,
      role: 'ai',
      content: placeholderContent,
      type: 'text',
      message_type: 'multimodal_summary',  // 后续 UPDATE 用同一行
      source: 'ai-generated',
      channel: 'main',
      attachments: [],
    })
    .select('id')
    .single()

  if (phErr) {
    return json({ error: 'placeholder_insert_failed', detail: phErr.message }, 500)
  }

  // 4. POST trigger Modal worker(异步,fire-and-forget)
  //    Worker 拿到 placeholder_id 后会 UPDATE 它的 content,前端 Realtime 自动重渲
  const modalPayload = {
    placeholder_id: phRow.id,
    room_id: body.room_id,
    expert_user_id: body.expert_user_id,
    audio_path: body.audio_path,
    audio_name: audioName,
    audio_duration_s: body.audio_duration_s,
    photo_paths: body.photo_paths ?? [],
    captured_at: body.captured_at,
    lesson_segment_id: body.lesson_segment_id,
    product,
  }

  // 不 await — Modal worker 跑几分钟,Edge Function 5s 必须返回
  if (MODAL_WORKER_URL) {
    fetch(MODAL_WORKER_URL, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'authorization': `Bearer ${MODAL_WORKER_TOKEN}`,
      },
      body: JSON.stringify(modalPayload),
    }).catch(err => {
      console.error('[speak2go-ingest] modal trigger failed:', err)
      // worker 调用失败 → UPDATE placeholder 告警
      sb.from('messages').update({
        content: `⚠️ 转写服务暂时不可用,请稍后重试。(${err.message ?? 'unknown'})`,
      }).eq('id', phRow.id).then(() => {})
    })
  } else {
    console.warn('[speak2go-ingest] MODAL_WORKER_URL not configured, skipping trigger')
  }

  return json({
    ok: true,
    placeholder_id: phRow.id,
    modal_dispatched: !!MODAL_WORKER_URL,
  })
})

function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { ...CORS_HEADERS, 'content-type': 'application/json' },
  })
}
