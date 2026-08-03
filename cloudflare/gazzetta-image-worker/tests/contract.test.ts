import { describe, expect, it } from 'vitest'
import {
  bearerTokenMatches,
  detectImageMime,
  parseGenerationRequest,
  sha256Text,
} from '../src/contract'

const JOB_ID = '7808e01e-61bc-4899-88bd-e26ad6d29e54'
const PROMPT = 'A documentary editorial illustration from Neveran, wide composition, no text, '
  + 'showing a guarded night market beneath cyan magitech lights and ancient stone arches.'

async function request() {
  return {
    jobId: JOB_ID,
    issueNumber: 7,
    prompt: PROMPT,
    promptSha256: await sha256Text(PROMPT),
    seed: 123456789,
  }
}

describe('contratto del Worker immagini', () => {
  it('accetta soltanto il body chiuso previsto', async () => {
    const valid = await request()
    expect(parseGenerationRequest(valid).issueNumber).toBe(7)
    expect(() => parseGenerationRequest({ ...valid, model: 'altro' })).toThrow(
      /campi inattesi/,
    )
  })

  it('riconosce soltanto formati immagine ammessi', () => {
    expect(detectImageMime(new Uint8Array([0x89, 0x50, 0x4e, 0x47, 13, 10, 26, 10])))
      .toBe('image/png')
    expect(() => detectImageMime(new TextEncoder().encode('non-image'))).toThrow(/Formato/)
  })

  it('confronta il bearer senza accettare token corti o prefissi', async () => {
    const token = '1234567890abcdef1234567890abcdef'
    await expect(bearerTokenMatches(`Bearer ${token}`, token)).resolves.toBe(true)
    await expect(bearerTokenMatches(`Bearer ${token}x`, token)).resolves.toBe(false)
    await expect(bearerTokenMatches('Basic abc', token)).resolves.toBe(false)
    await expect(bearerTokenMatches('Bearer corto', 'corto')).resolves.toBe(false)
  })
})
