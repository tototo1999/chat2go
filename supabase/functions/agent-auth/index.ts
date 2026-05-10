// Edge Function: 大咖 agent 用 connection_key 换可登录的 OTP
//
// POST /functions/v1/agent-auth/exchange  Body: { key: "c2g-key_xxx" }
//   Returns: { token_hash, email, expert_id }
//
// 大咖 agent 拿到后：
//   await sb.auth.verifyOtp({ token_hash, type: 'magiclink' })
//   → 得到完整 session（access_token + refresh_token，自动续命）

import { serve } from 'https://deno.land/std@0.168.0/http/server.ts'
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const SUPABASE_URL = Deno.env.get('SUPABASE_URL') ?? ''
const SERVICE_ROLE = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? ''

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
}

async function sha256Hex(s: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s))
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
  })
}

serve(async (req) => {
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: CORS_HEADERS })
  }
  const url = new URL(req.url)
  if (req.method !== 'POST' || !url.pathname.endsWith('/exchange')) {
    return json({ error: 'not found' }, 404)
  }

  let body: { key?: string }
  try { body = await req.json() } catch { return json({ error: 'invalid JSON body' }, 400) }
  const key = (body.key || '').trim()
  if (!key) return json({ error: 'missing key' }, 400)
  if (!key.startsWith('c2g-key_')) return json({ error: 'invalid key format' }, 400)

  const hash = await sha256Hex(key)
  const sb = createClient(SUPABASE_URL, SERVICE_ROLE)

  const { data: row, error: keyErr } = await sb
    .from('expert_agent_keys')
    .select('id, expert_id, revoked_at, expires_at')
    .eq('key_hash', hash)
    .maybeSingle()

  if (keyErr) return json({ error: 'db error: ' + keyErr.message }, 500)
  if (!row) return json({ error: 'invalid key' }, 401)
  if (row.revoked_at) return json({ error: 'key revoked' }, 401)
  if (row.expires_at && new Date(row.expires_at) < new Date()) {
    return json({ error: 'key expired' }, 401)
  }

  // 取大咖 email
  const { data: userInfo, error: uerr } = await sb.auth.admin.getUserById(row.expert_id)
  if (uerr || !userInfo?.user?.email) {
    return json({ error: 'cannot lookup user email' }, 500)
  }
  const email = userInfo.user.email

  // 生成 magiclink OTP（不发邮件，agent 直接拿 token_hash 用）
  const { data: linkData, error: linkErr } = await sb.auth.admin.generateLink({
    type: 'magiclink',
    email,
  })
  if (linkErr || !linkData?.properties?.hashed_token) {
    return json({ error: 'cannot generate OTP: ' + (linkErr?.message || 'unknown') }, 500)
  }

  // 更新 last_used（异步，不阻塞）
  const ip =
    req.headers.get('x-forwarded-for')?.split(',')[0]?.trim() ||
    req.headers.get('cf-connecting-ip') ||
    null
  sb.from('expert_agent_keys')
    .update({ last_used_at: new Date().toISOString(), last_used_ip: ip })
    .eq('id', row.id)
    .then(() => {})

  return json({
    token_hash: linkData.properties.hashed_token,
    email,
    expert_id: row.expert_id,
    verification_type: 'magiclink',
  })
})
