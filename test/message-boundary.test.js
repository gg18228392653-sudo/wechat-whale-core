import assert from 'node:assert/strict'
import { test } from 'node:test'
import { assistantReply, containsInternalOutput, conversationPrompt, WHALE_PERSONA } from '../src/index.js'

const block = (text, phase) => ({ type: 'text', text, phase })
const message = (...content) => ({ role: 'assistant', content })

test('returns only the final text from a normalized provider response', () => {
  assert.equal(assistantReply('  收到，等我一下。\n'), '收到，等我一下。')
  assert.equal(assistantReply(message({ type: 'reasoning', text: '未公开想法' },
    block('中间状态', 'commentary'), block('收到。', 'final'), block('晚点聊。'))), '收到。\n晚点聊。')
  assert.equal(assistantReply(message(block('中间状态', 'commentary'))), '')
  assert.equal(assistantReply({ phase: 'commentary', content: [block('中间状态')] }), '')
  assert.equal(assistantReply({ role: 'user', content: [block('非助手消息')] }), '')
})

test('suppresses tool-use turns and malformed mixed content, even if there is text', () => {
  for (const type of ['tool-call', 'tool_use', 'tool_call', 'function_call', 'unknown']) {
    assert.equal(assistantReply(message(block('不要发出'), { type })), '')
  }
  assert.equal(assistantReply({ content: [block('不要发出')], toolCalls: [{}] }), '')
  assert.equal(assistantReply({ content: [block('不要发出')], source: {} }), '')
  assert.equal(assistantReply(message(block('不要发出'), null)), '')
  const unexpected = { toString() { assert.fail('must not coerce object content') } }
  assert.equal(assistantReply(message(block(unexpected))), '')
  assert.equal(assistantReply(unexpected), '')
  assert.equal(containsInternalOutput(unexpected), false)
})

test('blocks silence markers and leaked prompt data rather than forwarding any part', () => {
  const { prompt } = conversationPrompt({ messages: [{ id: 'r', senderId: 'person', text: '合成' }] })
  for (const leak of [
    '[不回]', '【不回】', '［不\u200b回］', '【群聊数据】', 'speakerIsOwner',
    '帐号提示：[账号已省略]', WHALE_PERSONA, prompt, prompt.split('\n').at(-1),
  ]) {
    assert.equal(containsInternalOutput(leak), true, leak)
    assert.equal(assistantReply(`正常开头\n${leak}`), '', leak)
  }
  assert.equal(assistantReply(message(block('speakerIs'), block('Owner'))), '')
  assert.equal(assistantReply(message(block('[不'), block('回]'))), '')
  assert.equal(assistantReply('大肥鱼这就来。'), '大肥鱼这就来。')
})
