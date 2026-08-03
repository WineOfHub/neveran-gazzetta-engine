import {
  MAX_BODY_BYTES,
  ContractError,
  bearerTokenMatches,
  decodeBase64Image,
  detectImageMime,
  parseGenerationRequest,
  sha256Bytes,
  sha256Text,
  type GenerationRequest,
  type GenerationResponse,
} from './contract'

interface AiBinding {
  run(model: string, input: {
    multipart: { body: ReadableStream<Uint8Array> | null; contentType: string }
  }): Promise<unknown>
}

export interface Env {
  AI: AiBinding
  GAZZETTA_IMAGE_WORKER_TOKEN: string
  IMAGE_MODEL: string
  IMAGE_WIDTH: string
  IMAGE_HEIGHT: string
}

function json(payload: object, status = 200): Response {
  return Response.json(payload, {
    status,
    headers: {
      'Cache-Control': 'no-store',
      'Content-Security-Policy': "default-src 'none'",
      'X-Content-Type-Options': 'nosniff',
    },
  })
}

function positiveDimension(value: string, name: string): number {
  const parsed = Number(value)
  if (!Number.isInteger(parsed) || parsed < 256 || parsed > 1920) {
    throw new ContractError('invalid_worker_config', `${name} non valido`)
  }
  return parsed
}

async function generate(request: GenerationRequest, env: Env): Promise<GenerationResponse> {
  const width = positiveDimension(env.IMAGE_WIDTH, 'IMAGE_WIDTH')
  const height = positiveDimension(env.IMAGE_HEIGHT, 'IMAGE_HEIGHT')
  const actualPromptHash = await sha256Text(request.prompt)
  if (actualPromptHash !== request.promptSha256) {
    throw new ContractError('prompt_hash_mismatch', 'Hash del prompt non coerente')
  }

  const form = new FormData()
  form.append('prompt', request.prompt)
  form.append('width', String(width))
  form.append('height', String(height))
  form.append('seed', String(request.seed))
  const serialized = new Response(form)
  const contentType = serialized.headers.get('content-type')
  if (!contentType) throw new ContractError('multipart_failure', 'Multipart non serializzabile')

  const raw = await env.AI.run(env.IMAGE_MODEL, {
    multipart: { body: serialized.body, contentType },
  })
  const image = raw && typeof raw === 'object' && 'image' in raw
    ? (raw as { image: unknown }).image
    : null
  const bytes = decodeBase64Image(image)
  const contentSha256 = await sha256Bytes(bytes)
  return {
    imageBase64: image as string,
    contentSha256,
    mimeType: detectImageMime(bytes),
    model: env.IMAGE_MODEL,
    seed: request.seed,
    width,
    height,
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url)
    if (request.method === 'GET' && url.pathname === '/health') {
      return json({ status: 'ok', service: 'neveran-gazzetta-image-worker' })
    }
    if (request.method !== 'POST' || url.pathname !== '/v1/generate') {
      return json({ error: 'not_found' }, 404)
    }
    if (!await bearerTokenMatches(
      request.headers.get('authorization'),
      env.GAZZETTA_IMAGE_WORKER_TOKEN,
    )) {
      return json({ error: 'unauthorized' }, 401)
    }
    const contentLength = Number(request.headers.get('content-length') || '0')
    if (contentLength > MAX_BODY_BYTES) return json({ error: 'body_too_large' }, 413)
    if (!request.headers.get('content-type')?.toLowerCase().startsWith('application/json')) {
      return json({ error: 'unsupported_media_type' }, 415)
    }

    const requestId = crypto.randomUUID()
    try {
      const rawBody = await request.text()
      if (new TextEncoder().encode(rawBody).byteLength > MAX_BODY_BYTES) {
        return json({ error: 'body_too_large', requestId }, 413)
      }
      const payload = JSON.parse(rawBody) as unknown
      const parsed = parseGenerationRequest(payload)
      return json(await generate(parsed, env))
    } catch (error) {
      if (error instanceof ContractError) {
        return json({ error: error.code, requestId }, 400)
      }
      console.error(JSON.stringify({
        event: 'gazzetta_image_generation_failed',
        requestId,
        errorClass: error instanceof Error ? error.name : 'UnknownError',
      }))
      return json({ error: 'provider_unavailable', requestId }, 502)
    }
  },
}
