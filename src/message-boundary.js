import { field, isList, list } from './input.js'
import { PRIVATE_PERSONA, WHALE_PERSONA } from './persona.js'

const personas = [WHALE_PERSONA, PRIVATE_PERSONA].map(value => value.normalize('NFKC'))
const markers = /(?:[\[【]\s*不\s*回\s*[\]】]|【\s*(?:群聊数据|群聊历史|群聊记录|群聊隐私边界|私聊数据|可回应消息|本会话角色)\s*】|speakerIsOwner|账号已省略|只回应 eligible 中的当前记录|下面一行 JSON 是群聊数据|下一行是私聊数据|只回复 eligible 所标的当前消息)/iu
const promptKeys = ['history', 'current', 'eligible'].map(key => new RegExp(`"${key}"\\s*:\\s*\\[`, 'u'))
const privateBlocks = new Set(['reasoning', 'thinking', 'commentary'])
const MAX_BLOCKS = 64
const MAX_REPLY = 2000

export function containsInternalOutput(value) {
  if (typeof value !== 'string') return false
  const normalized = value.normalize('NFKC').replace(/\p{Cf}/gu, '')
  return markers.test(normalized) || personas.some(value => normalized.includes(value)) ||
    promptKeys.every(pattern => pattern.test(normalized))
}

function blocksText(message) {
  const role = field(message, 'role')
  const phase = field(message, 'phase')
  if ((role !== undefined && role !== 'assistant') || (phase !== undefined && phase !== 'final')) return ''
  if (field(message, 'source') !== undefined || field(message, 'toolCalls') !== undefined ||
    field(message, 'tool_calls') !== undefined) return ''
  const content = field(message, 'content')
  if (!isList(content) || field(content, 'length') > MAX_BLOCKS) return ''
  const parts = []
  let length = 0
  for (const block of list(content, MAX_BLOCKS)) {
    const type = field(block, 'type')
    if (privateBlocks.has(type)) continue
    if (type !== 'text') return ''
    const phase = field(block, 'phase')
    if (phase === 'commentary') continue
    if (phase !== undefined && phase !== 'final') return ''
    const text = field(block, 'text')
    if (typeof text !== 'string') return ''
    length += text.length + 1
    if (length > MAX_REPLY) return ''
    parts.push(text)
  }
  if (containsInternalOutput(parts.join(''))) return ''
  return parts.join('\n')
}

export function assistantReply(message) {
  const reply = typeof message === 'string' ? message : blocksText(message)
  if (reply.length > MAX_REPLY || containsInternalOutput(reply)) return ''
  return reply.trim()
}
