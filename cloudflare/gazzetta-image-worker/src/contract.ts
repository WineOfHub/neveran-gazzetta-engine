export const PROMPT_MAX_CHARACTERS = 6000
export const MAX_BODY_BYTES = 16_384
export const MAX_IMAGE_BYTES = 6 * 1024 * 1024

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const SHA256_PATTERN = /^[a-f0-9]{64}$/

export class ContractError extends Error {
  readonly code: string

  constructor(code: string, message: string) {
    super(message)
    this.name = 'ContractError'
    this.code = code
  }
}

export interface GenerationRequest {
  jobId: string
  issueNumber: number
  prompt: string
  promptSha256: string
  seed: number
}

export interface GenerationResponse {
  imageBase64: string
  contentSha256: string
  mimeType: 'image/png' | 'image/jpeg' | 'image/webp'
  model: string
  seed: number
  width: number
  height: number
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

export function parseGenerationRequest(value: unknown): GenerationRequest {
  if (!isRecord(value)) throw new ContractError('invalid_body', 'Il body deve essere un oggetto')
  const allowed = new Set(['jobId', 'issueNumber', 'prompt', 'promptSha256', 'seed'])
  if (Object.keys(value).some(key => !allowed.has(key))) {
    throw new ContractError('unexpected_field', 'Il body contiene campi inattesi')
  }
  if (typeof value.jobId !== 'string' || !UUID_PATTERN.test(value.jobId)) {
    throw new ContractError('invalid_job_id', 'jobId non valido')
  }
  if (!Number.isInteger(value.issueNumber) || Number(value.issueNumber) < 1) {
    throw new ContractError('invalid_issue_number', 'issueNumber non valido')
  }
  if (typeof value.prompt !== 'string' || value.prompt.trim().length < 80
    || value.prompt.length > PROMPT_MAX_CHARACTERS) {
    throw new ContractError('invalid_prompt', 'prompt non valido')
  }
  if (typeof value.promptSha256 !== 'string' || !SHA256_PATTERN.test(value.promptSha256)) {
    throw new ContractError('invalid_prompt_hash', 'promptSha256 non valido')
  }
  if (!Number.isInteger(value.seed) || Number(value.seed) < 0
    || Number(value.seed) > 0xffff_ffff) {
    throw new ContractError('invalid_seed', 'seed non valido')
  }
  return {
    jobId: value.jobId,
    issueNumber: Number(value.issueNumber),
    prompt: value.prompt,
    promptSha256: value.promptSha256,
    seed: Number(value.seed),
  }
}

function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
}

export async function sha256Text(value: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))
  return bytesToHex(new Uint8Array(digest))
}

export async function sha256Bytes(value: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', Uint8Array.from(value).buffer)
  return bytesToHex(new Uint8Array(digest))
}

export async function bearerTokenMatches(header: string | null, expected: string): Promise<boolean> {
  if (!header?.startsWith('Bearer ') || expected.length < 32) return false
  const supplied = header.slice('Bearer '.length)
  const [actualDigest, expectedDigest] = await Promise.all([
    crypto.subtle.digest('SHA-256', new TextEncoder().encode(supplied)),
    crypto.subtle.digest('SHA-256', new TextEncoder().encode(expected)),
  ])
  const actual = new Uint8Array(actualDigest)
  const wanted = new Uint8Array(expectedDigest)
  let difference = 0
  for (let index = 0; index < actual.length; index += 1) {
    difference |= actual[index] ^ wanted[index]
  }
  return difference === 0
}

export function decodeBase64Image(value: unknown): Uint8Array {
  if (typeof value !== 'string' || value.length < 16
    || value.length > Math.ceil(MAX_IMAGE_BYTES * 4 / 3) + 4) {
    throw new ContractError('invalid_model_output', 'Output immagine assente')
  }
  let binary: string
  try {
    binary = atob(value)
  } catch {
    throw new ContractError('invalid_model_output', 'Output immagine non decodificabile')
  }
  const bytes = Uint8Array.from(binary, character => character.charCodeAt(0))
  if (bytes.byteLength > MAX_IMAGE_BYTES) {
    throw new ContractError('image_too_large', 'Immagine oltre il limite consentito')
  }
  return bytes
}

export function detectImageMime(bytes: Uint8Array): GenerationResponse['mimeType'] {
  if (bytes.length >= 8
    && bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47
    && bytes[4] === 0x0d && bytes[5] === 0x0a && bytes[6] === 0x1a && bytes[7] === 0x0a) {
    return 'image/png'
  }
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
    return 'image/jpeg'
  }
  if (bytes.length >= 12
    && String.fromCharCode(...bytes.slice(0, 4)) === 'RIFF'
    && String.fromCharCode(...bytes.slice(8, 12)) === 'WEBP') {
    return 'image/webp'
  }
  throw new ContractError('unsupported_image_type', 'Formato immagine non supportato')
}
