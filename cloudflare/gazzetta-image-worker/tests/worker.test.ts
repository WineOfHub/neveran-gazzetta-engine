import { describe, expect, it, vi } from 'vitest'
import worker, { type Env } from '../src/index'
import { MAX_BODY_BYTES, sha256Text } from '../src/contract'

const TOKEN = '1234567890abcdef1234567890abcdef'
const PROMPT = 'A cinematic editorial illustration from Neveran showing a guarded caravan at '
  + 'dawn, restrained cyan magitech light, old stone roads, no lettering, wide composition.'
const PNG_BYTES = new Uint8Array([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
  ...new TextEncoder().encode('fake-png-image-content'),
])
const PNG_BASE64 = btoa(String.fromCharCode(...PNG_BYTES))

function fakeEnv() {
  const run = vi.fn(async () => ({ image: PNG_BASE64 }))
  const env = {
    AI: { run },
    GAZZETTA_IMAGE_WORKER_TOKEN: TOKEN,
    IMAGE_MODEL: '@cf/black-forest-labs/flux-2-klein-9b',
    IMAGE_WIDTH: '1536',
    IMAGE_HEIGHT: '896',
  } as unknown as Env
  return { env, run }
}

async function generationRequest() {
  return new Request('https://worker.example/v1/generate', {
    method: 'POST',
    headers: { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      jobId: '7808e01e-61bc-4899-88bd-e26ad6d29e54',
      issueNumber: 7,
      prompt: PROMPT,
      promptSha256: await sha256Text(PROMPT),
      seed: 42,
    }),
  })
}

describe('gazzetta image worker', () => {
  it('nega le richieste senza token', async () => {
    const { env } = fakeEnv()
    const response = await worker.fetch(new Request('https://worker.example/v1/generate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    }), env)
    expect(response.status).toBe(401)
  })

  it('rifiuta il body reale oltre il limite anche senza Content-Length', async () => {
    const { env } = fakeEnv()
    const response = await worker.fetch(new Request('https://worker.example/v1/generate', {
      method: 'POST',
      headers: { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ padding: 'x'.repeat(MAX_BODY_BYTES) }),
    }), env)
    expect(response.status).toBe(413)
  })

  it('genera e restituisce il PNG senza usare storage Cloudflare', async () => {
    const { env, run } = fakeEnv()
    const response = await worker.fetch(await generationRequest(), env)
    const payload = await response.json() as { imageBase64: string; mimeType: string }

    expect(response.status).toBe(200)
    expect(payload.imageBase64).toBe(PNG_BASE64)
    expect(payload.mimeType).toBe('image/png')
    expect(run).toHaveBeenCalledTimes(1)
  })
})
