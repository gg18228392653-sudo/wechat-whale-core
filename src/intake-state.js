import { field, identifier } from './input.js'

const positiveInteger = value => Number.isSafeInteger(value) && value > 0
const capacity = (value, fallback, limit) => positiveInteger(value) ? Math.min(value, limit) : fallback

export class IntakeState {
  #chats = new Map()
  #maxChats
  #maxReceiptsPerChat

  constructor(options) {
    this.#maxChats = capacity(field(options, 'maxChats'), 256, 1024)
    this.#maxReceiptsPerChat = capacity(field(options, 'maxReceiptsPerChat'), 128, 512)
  }

  isStale(chatId, sequence) {
    return Boolean(identifier(chatId) && positiveInteger(sequence) &&
      (this.#chats.get(chatId)?.sequence ?? 0) > sequence)
  }

  accept(input) {
    const chatId = identifier(field(input, 'chatId'))
    const batchId = identifier(field(input, 'batchId'))
    const sequence = field(input, 'sequence')
    if (!chatId || !batchId || !positiveInteger(sequence)) return { accepted: false, reason: 'invalid' }

    const chat = this.#chats.get(chatId) ?? { sequence: 0, receipts: new Set() }
    if (chat.receipts.has(batchId)) return { accepted: false, reason: 'duplicate' }
    if (chat.sequence > sequence) return { accepted: false, reason: 'stale' }

    chat.sequence = sequence
    chat.receipts.add(batchId)
    if (chat.receipts.size > this.#maxReceiptsPerChat) chat.receipts.delete(chat.receipts.values().next().value)
    this.#chats.delete(chatId)
    this.#chats.set(chatId, chat)
    if (this.#chats.size > this.#maxChats) this.#chats.delete(this.#chats.keys().next().value)
    return { accepted: true, reason: 'accepted' }
  }
}
