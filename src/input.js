export function field(value, key) {
  if (value === null || typeof value !== 'object') return undefined
  try {
    return Object.getOwnPropertyDescriptor(value, key)?.value
  } catch {
    return undefined
  }
}

export function isList(value) {
  try {
    return Array.isArray(value)
  } catch {
    return false
  }
}

export function list(value, limit, tail = false) {
  if (!isList(value)) return []
  const length = field(value, 'length')
  if (!Number.isSafeInteger(length) || length < 0) return []
  const start = tail ? Math.max(0, length - limit) : 0
  return Array.from({ length: Math.min(length - start, limit) }, (_, i) => field(value, start + i))
}

export function identifier(value) {
  return typeof value === 'string' && value.length <= 256 && value.trim() === value &&
    !/[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/u.test(value) ? value : ''
}

export function text(value, limit) {
  return typeof value === 'string' ? value.trim().slice(0, limit) : ''
}
