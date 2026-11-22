import assert from 'node:assert/strict'
import { test } from 'node:test'
import { IntakeState } from '../src/index.js'

const accepted = { accepted: true, reason: 'accepted' }
const rejected = reason => ({ accepted: false, reason })
const batch = (chatId, batchId, sequence) => ({ chatId, batchId, sequence })

test('deduplicates and tracks sequence independently per chat', () => {
  const state = new IntakeState()
  assert.deepEqual(state.accept(batch('room-a', 'batch-one', 5)), accepted)
  assert.deepEqual(state.accept(batch('room-a', 'batch-one', 9)), rejected('duplicate'))
  assert.deepEqual(state.accept(batch('room-a', 'batch-zero', 3)), rejected('stale'))
  assert.deepEqual(state.accept(batch('room-a', 'batch-two', 5)), accepted)
  assert.deepEqual(state.accept(batch('room-b', 'batch-one', 1)), accepted)
  assert.equal(state.isStale('room-a', 4), true)
  assert.equal(state.isStale('room-a', 5), false)
  assert.equal(state.isStale('room-b', 4), false)
  assert.equal(state.isStale('other-room', 4), false)
})

test('bounds receipts and least recently accepted chats', () => {
  const state = new IntakeState({ maxChats: 2, maxReceiptsPerChat: 2 })
  for (const id of ['one', 'two', 'three']) assert.deepEqual(state.accept(batch('a', id, 2)), accepted)
  assert.deepEqual(state.accept(batch('a', 'two', 2)), rejected('duplicate'))
  assert.deepEqual(state.accept(batch('a', 'one', 2)), accepted)
  assert.deepEqual(state.accept(batch('b', 'one', 9)), accepted)
  assert.deepEqual(state.accept(batch('a', 'four', 3)), accepted)
  assert.deepEqual(state.accept(batch('c', 'one', 1)), accepted)
  assert.equal(state.isStale('b', 1), false)
  assert.equal(state.isStale('a', 1), true)
  assert.deepEqual(state.accept(batch('b', 'one', 1)), accepted)
})

test('rejects malformed intake without changing state', () => {
  const state = new IntakeState(null)
  const inherited = Object.create({ chatId: 'room', batchId: 'batch', sequence: 1 })
  const object = { toString() { assert.fail('must not coerce identifiers') } }
  for (const input of [null, inherited, batch('room', 'batch', '8'), batch('room', 'batch', 0),
    batch('room', 'batch', Infinity), batch('room', 'batch', 1.5), batch('room', 'batch', 1e20),
    batch('room', '', 10), batch('room ', 'batch', 10), batch(null, 'batch', 10), batch(object, 'batch', 10)]) {
    assert.deepEqual(state.accept(input), rejected('invalid'))
  }
  assert.equal(state.isStale('room', 1), false)
  assert.equal(state.isStale('room', '1'), false)
  assert.deepEqual(state.accept(batch('__proto__', 'batch', 1)), accepted)
  assert.deepEqual(state.accept(batch('room', 'batch', 1)), accepted)
})

test('intake state does not survive construction of another instance', () => {
  const first = new IntakeState()
  const next = new IntakeState()
  assert.deepEqual(first.accept(batch('room', 'one', 9)), accepted)
  assert.deepEqual(first.accept(batch('room', 'one', 9)), rejected('duplicate'))
  assert.deepEqual(next.accept(batch('room', 'one', 9)), accepted)
  assert.equal(next.isStale('room', 8), true)
})
