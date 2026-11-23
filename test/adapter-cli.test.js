import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

const cli = fileURLToPath(new URL('../src/adapter-cli.mjs', import.meta.url))
const run = (args, input) => spawnSync(process.execPath, [cli, ...args], {
  input, shell: false, encoding: 'utf8', timeout: 5000,
})

function result(operation, payload) {
  const child = run([operation], JSON.stringify(payload))
  assert.ifError(child.error)
  assert.equal(child.stderr, '')
  assert.equal(child.status, 0)
  return JSON.parse(child.stdout)
}

function checkRejected(args, input) {
  const child = run(args, input)
  assert.ifError(child.error)
  assert.equal(child.status, 1)
  assert.equal(child.stdout, '')
  assert.equal(child.stderr, '')
}

const selfId = 'fixture-bot-account'
const ownerAccountId = 'fixture-owner-account'
const syntheticText = '\u5408\u6210\u95ee\u9898; $(fixture-command)'

test('prepare returns only routing fields and the existing redacted UTF-8 prompt', () => {
  const row = { id: 'fixture-row', senderId: ownerAccountId, text: `${syntheticText} ${ownerAccountId}` }
  const prepared = result('prepare', {
    input: { selfId, messages: [{ ...row, mentions: [selfId] }] },
    adapter: { ownerAccountId },
  })
  assert.deepEqual(Object.keys(prepared).sort(), ['eligible', 'prompt', 'shouldReply'])
  assert.equal(prepared.shouldReply, true)
  assert.deepEqual(prepared.eligible, [row.id])
  const data = JSON.parse(prepared.prompt.split('\n').at(-1))
  assert.deepEqual(data.eligible, ['m1'])
  assert.equal(data.current[0].speakerIsOwner, true)
  assert.ok(data.current[0].text.startsWith(syntheticText))
  assert.ok(!prepared.prompt.includes(ownerAccountId))
  assert.ok(!prepared.prompt.includes(selfId))

  const skipped = result('prepare', { input: { selfId, messages: [row] }, adapter: {} })
  assert.equal(skipped.shouldReply, false)
  assert.deepEqual(skipped.eligible, [])
})

test('private chats reply to the chosen contact without a mention and exclude other conversations', () => {
  const contactId = 'fixture-selected-contact'
  const input = { selfId, messages: [
    { id: 'self', senderId: selfId, text: 'Earlier reply' },
    { id: 'incoming', senderId: contactId, text: `Hello ${contactId}` },
    { id: 'other', senderId: ownerAccountId, text: 'Unrelated current message', mentions: [selfId] },
  ], historyRecords: [
    { id: 'same-contact', senderId: contactId, text: 'Earlier incoming message' },
    { id: 'other-history', senderId: ownerAccountId, text: 'Unrelated history' },
  ] }
  const prepared = result('prepare-private', { input, contactId })
  assert.deepEqual(prepared.eligible, ['incoming'])
  assert.equal(prepared.shouldReply, true)
  assert.match(prepared.prompt, /【私聊数据】/u)
  assert.match(prepared.prompt, /Earlier incoming message/u)
  assert.doesNotMatch(prepared.prompt, /Unrelated|fixture-selected-contact|speakerIsOwner|【群聊数据】/u)
  assert.deepEqual(result('reply', { message: prepared.prompt }), { reply: '' })
  assert.deepEqual(result('reply', { message: '【私聊数据】' }), { reply: '' })
  assert.equal(result('prepare-private', { input: { ...input, messages: [input.messages[0]] }, contactId }).shouldReply, false)
  assert.equal(result('prepare-private', { input, contactId: selfId }).shouldReply, false)
})

test('reply uses the text boundary for plain and structured messages', () => {
  assert.deepEqual(result('reply', { message: ` ${syntheticText} ` }), { reply: syntheticText })
  assert.deepEqual(result('reply', { message: '[\u4e0d\u56de]' }), { reply: '' })
  assert.deepEqual(result('reply', { message: { role: 'assistant', content: [
    { type: 'thinking', text: 'fixture-private-text' }, { type: 'text', text: syntheticText },
  ] } }), { reply: syntheticText })
  assert.deepEqual(result('reply', { message: { role: 'assistant', tool_calls: [], content: [
    { type: 'text', text: syntheticText },
  ] } }), { reply: '' })
})

test('rejects unknown operations, extra arguments, and invalid envelopes without echo', () => {
  for (const args of [[], ['fixture-private-operation'], ['reply', 'fixture-extra']]) {
    checkRejected(args, JSON.stringify({ message: 'fixture-private-text' }))
  }
  for (const payload of [null, [], 1, {}, { message: null }, { message: [] }, { message: 'x', extra: 'fixture-private' }]) {
    checkRejected(['reply'], JSON.stringify(payload))
  }
  for (const payload of [{ input: {} }, { input: null, adapter: {} }, { input: {}, adapter: [] }]) {
    checkRejected(['prepare'], JSON.stringify(payload))
  }
  checkRejected(['reply'], '{"message":"fixture-private-text"')
  checkRejected(['reply'], Buffer.concat([Buffer.from('{"message":"'), Buffer.from([0xff]), Buffer.from('"}')]))
})

test('enforces the byte limit before parsing a JSON input', () => {
  const payload = '{"message":"fixture-oversized"}'
  const padding = ' '.repeat(2 * 1024 * 1024 - Buffer.byteLength(payload))
  const child = run(['reply'], payload + padding)
  assert.ifError(child.error)
  assert.equal(child.status, 0)
  assert.deepEqual(JSON.parse(child.stdout), { reply: 'fixture-oversized' })
  checkRejected(['reply'], payload + padding + ' ')
})
