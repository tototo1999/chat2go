import { serve } from 'https://deno.land/std@0.168.0/http/server.ts'
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const ANTHROPIC_API_KEY = Deno.env.get('ANTHROPIC_API_KEY') ?? ''
const SUPABASE_URL = Deno.env.get('SUPABASE_URL') ?? ''
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? ''

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
}

// Industry-specific system prompts for Chat 调试室
const INDUSTRY_PROMPTS: Record<string, string> = {
  外贸: `你是一位外贸行业的AI助手，专注于帮助跟单员处理外贸业务。
你熟悉：合同生成（FOB/CIF/CFR条款）、信用证、提单、装箱单、报关、物流跟踪、汇率结算。
用简洁、专业的中文回复。对于合同条款，直接给出可复用的模板片段。`,

  健身: `你是一位健身行业的AI助手，帮助健身教练管理学员和课程。
你熟悉：学员CRM记录、训练计划制定、体测数据分析、课程排期、营养建议。
用鼓励、专业的语气回复，给出具体可操作的建议。`,

  地产: `你是一位房地产行业的AI助手，帮助中介提升带客效率。
你熟悉：房源分析、周边配套研报、客户意向判断、谈判策略、合同要点。
回复简洁有力，优先给出数据支撑的分析。`,

  教育: `你是一位教育行业的AI助手，帮助学生和教师提升学习效果。
你熟悉：课件整理、知识点讲解、习题解析、学习计划制定、考点总结。
用清晰、有条理的方式解释，适合中学生和大学生理解。`,

  量化: `你是一位量化交易领域的AI助手，帮助用户理解量化策略。
你熟悉：回测逻辑、因子分析、风险控制、仓位管理、Python/pandas数据处理。
面向非专业用户时，用类比和简单语言解释复杂概念。`,

  医疗: `你是一位医疗辅助AI助手，帮助医生处理患者咨询和诊疗记录整理。
重要：你只提供信息参考，不做最终诊断，每次回复都提醒用户以医生判断为准。
你熟悉：常见症状描述规范、病历整理格式、患者沟通话术。`,
}

const DEFAULT_SYSTEM = `你是 Chat2GO.Ai 平台的专属 AI 助手，工作在"Chat 调试室"中。
你的目标是帮助用户和大咖共同理清需求，展示 AI 能做什么，最终为用户交付一个可以独立使用的专属 AI 助手。
请用简洁、专业的中文回复。如果需要更多信息才能准确回答，请直接追问关键细节。`

serve(async (req) => {
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: CORS_HEADERS })
  }

  try {
    // Verify auth
    const authHeader = req.headers.get('Authorization')
    if (!authHeader) {
      return new Response(JSON.stringify({ error: 'Unauthorized' }), {
        status: 401,
        headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
      })
    }

    const { room_id, messages } = await req.json()

    if (!room_id || !Array.isArray(messages)) {
      return new Response(JSON.stringify({ error: 'Invalid request body' }), {
        status: 400,
        headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
      })
    }

    // Look up room to get industry
    let systemPrompt = DEFAULT_SYSTEM
    if (SUPABASE_URL && SUPABASE_SERVICE_ROLE_KEY) {
      const sb = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
      const { data: room } = await sb.from('rooms').select('industry').eq('id', room_id).single()
      if (room?.industry && INDUSTRY_PROMPTS[room.industry]) {
        systemPrompt = INDUSTRY_PROMPTS[room.industry]
      }
    }

    // Call Claude API
    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'x-api-key': ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
      },
      body: JSON.stringify({
        model: 'claude-sonnet-4-6',
        max_tokens: 1024,
        system: systemPrompt,
        messages: messages.map(m => ({
          role: m.role === 'assistant' ? 'assistant' : 'user',
          content: m.content,
        })),
      }),
    })

    if (!response.ok) {
      const err = await response.text()
      console.error('Anthropic API error:', err)
      return new Response(JSON.stringify({ error: 'AI service error' }), {
        status: 502,
        headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
      })
    }

    const result = await response.json()
    const content = result.content?.[0]?.text ?? ''

    return new Response(JSON.stringify({ content }), {
      headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
    })
  } catch (e) {
    console.error('chat-ai function error:', e)
    return new Response(JSON.stringify({ error: 'Internal error' }), {
      status: 500,
      headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
    })
  }
})
