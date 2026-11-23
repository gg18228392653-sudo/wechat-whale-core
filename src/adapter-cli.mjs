import { assistantReply, conversationPrompt } from './index.js'
import { privatePrompt } from './conversation.js'

const MAX_STDIN = 2 * 1024 * 1024
const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const hasFields = (value, ...names) => isObject(value) && Object.keys(value).length === names.length &&
  names.every(name => Object.hasOwn(value, name))

async function readInput() {
  const chunks = []
  let length = 0
  for await (const chunk of process.stdin) {
    length += chunk.length
    if (length > MAX_STDIN) throw new Error('Invalid input')
    chunks.push(chunk)
  }
  return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks, length)))
}

async function main() {
  const operation = process.argv[2]
  if (process.argv.length !== 3 || !['prepare', 'prepare-private', 'reply'].includes(operation)) {
    throw new Error('Invalid operation')
  }

  const payload = await readInput()
  if (operation === 'prepare' && hasFields(payload, 'input', 'adapter') &&
      isObject(payload.input) && isObject(payload.adapter)) {
    const { shouldReply, prompt, eligible } = conversationPrompt(payload.input, payload.adapter)
    return { shouldReply, prompt, eligible }
  }
  if (operation === 'prepare-private' && hasFields(payload, 'input', 'contactId') &&
      isObject(payload.input) && typeof payload.contactId === 'string') {
    const { shouldReply, prompt, eligible } = privatePrompt(payload.input, payload.contactId)
    return { shouldReply, prompt, eligible }
  }
  if (operation === 'reply' && hasFields(payload, 'message') &&
      (typeof payload.message === 'string' || isObject(payload.message))) {
    return { reply: assistantReply(payload.message) }
  }
  throw new Error('Invalid input')
}

process.stdout.on('error', () => { process.exitCode = 1 })
try {
  process.stdout.write(`${JSON.stringify(await main())}\n`)
} catch {
  process.exitCode = 1
}
