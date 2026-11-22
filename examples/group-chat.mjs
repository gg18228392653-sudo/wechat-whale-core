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

if (receipt.accepted) {
  const { eligible, prompt, shouldReply } = conversationPrompt(input, { ownerAccountId: 'example-a' })
  console.log(JSON.stringify({ eligible, shouldReply, prompt }, null, 2))
  console.log(JSON.stringify({ reply: assistantReply('白饭还有？那本鱼可不潜了') }))
}
console.log(JSON.stringify({ replay: intake.accept(batch) }))
