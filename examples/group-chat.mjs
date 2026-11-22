import assert from 'node:assert/strict'
import { assistantReply, conversationPrompt, IntakeState } from '../src/index.js'

const intake = new IntakeState()
const batch = { chatId: 'example-group', batchId: 'batch-1', sequence: 3 }
const receipt = intake.accept(batch)

const input = {
  selfId: 'example-bot',
  messages: [
    { id: '1', senderId: 'example-a', text: '大肥鱼，今晚吃什么？', time: 1000, mentions: ['example-bot'] },
    { id: '2', senderId: 'example-a', text: '食堂还有白饭。', time: 1001 },
    { id: '3', senderId: 'example-b', text: '你画的图发我一下。', time: 1002, mentions: ['example-c'] },
  ],
}

assert.equal(receipt.accepted, true)
const { eligible, prompt, shouldReply } = conversationPrompt(input, { ownerAccountId: 'example-a' })
assert.equal(shouldReply, true)
assert.deepEqual(eligible, ['1', '2'])
const sample = '白饭还有？那本鱼可不潜了'
const reply = assistantReply(sample)
assert.equal(reply, sample)
assert.equal(assistantReply('[不回]'), '')
const replay = intake.accept(batch)
assert.deepEqual(replay, { accepted: false, reason: 'duplicate' })
console.log(JSON.stringify({ eligible, shouldReply, prompt, reply, replay }, null, 2))
