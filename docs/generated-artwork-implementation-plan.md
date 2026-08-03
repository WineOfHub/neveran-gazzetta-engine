# Piano di implementazione — immagini generate della Gazzetta

> Stato: implementato e verificato localmente; deploy Worker e migration Storage pendenti
> Data: 2026-08-03
> Decisione corrente: `docs/adr/0002-artwork-supabase-storage-senza-billing.md`

## Obiettivo

Produrre una sola illustrazione landscape per edizione dalla notizia principale già validata,
conservarla nel piano Supabase Storage Free e mostrarla nella prima pagina senza perdere
l'artwork magitech di fallback. Nessun servizio può richiedere billing Cloudflare.

## Flusso autorevole

```text
planner + palette RAG
        -> writer
        -> validator e verifier
        -> image brief deterministico
        -> lookup key pubblica in Supabase Storage
             -> se presente: riuso idempotente
             -> se assente: Cloudflare Worker autenticato
                  -> Workers AI / FLUX.2 Klein 9B
                  -> Base64 + hash + MIME
             -> retention preventiva (massimo 24 file)
             -> upload immutabile con sessione gazzetta_worker
        -> leadArticle.image opzionale
        -> content hash
        -> submit e publish Supabase esistenti
        -> parser TypeScript
        -> LeadArtwork remoto o fallback SVG/CSS
```

## Contratti

### Richiesta privata al Worker

```json
{
  "jobId": "uuid",
  "issueNumber": 12,
  "prompt": "brief visivo senza istruzioni tipografiche",
  "promptSha256": "sha256",
  "seed": 123456789
}
```

Il Worker stabilisce modello e dimensioni; il chiamante non può scegliere provider o parametri
arbitrari.

### Risposta privata

```json
{
  "imageBase64": "iVBORw0KGgo...",
  "contentSha256": "sha256",
  "mimeType": "image/png",
  "model": "@cf/black-forest-labs/flux-2-klein-9b",
  "seed": 123456789,
  "width": 1536,
  "height": 896
}
```

### Snapshot player

```json
{
  "image": {
    "src": "https://<project>.supabase.co/storage/v1/object/public/gazzetta-artwork/...png",
    "alt": "Illustrazione editoriale dell'evento principale.",
    "caption": "Didascalia diegetica breve.",
    "credit": "Archivio ottico CCIN · sintesi illustrata",
    "focalPoint": "50% 42%"
  }
}
```

## Sicurezza, idempotenza e spazio

- endpoint `POST /v1/generate` protetto da bearer token dedicato;
- confronto del token tramite digest e nessun segreto o prompt nei log;
- body JSON chiuso e limitato;
- risposta immagine limitata a 6 MiB, hash verificato e MIME rilevato dai magic bytes;
- key Supabase deterministica basata su numero, job ID e hash prompt;
- lookup pubblico prima dell'inferenza e upload con `x-upsert=false`;
- account auth `gazzetta_worker`, mai `service_role`;
- RLS limitata al bucket e al formato del path;
- massimo 24 file, cancellati dal più vecchio tramite Storage API;
- origine e bucket validati anche dal parser TypeScript;
- nessun prompt, estratto lore o token esposto nello snapshot player.

## Fallimenti

| Caso | Comportamento |
| --- | --- |
| quota Workers AI terminata, timeout, 429 o 5xx | un retry tecnico, poi fallback statico |
| 400/401/403 dal Worker | nessun retry; fallback e telemetria interna |
| output Base64, hash o MIME invalido | fallback e telemetria interna |
| lista o retention Storage fallita | nessun upload; fallback per proteggere la quota |
| upload Supabase fallito | fallback; retry del job secondo policy |
| conflitto upload | download e riuso dell'oggetto già creato |
| immagine non caricabile nel player | `onError` ripristina l'artwork SVG/CSS |

## Verifica

1. Unit test Worker: contratto, autenticazione, body, hash, MIME e limite file.
2. Unit test Python: prompt, adapter, retry, cache, retention e upload immutabile.
3. Contract test: migration bucket/RLS e JSON Schema snapshot.
4. Test React: origine Supabase, bucket, rendering, caption e fallback.
5. `pytest`, `ruff`, `mypy`, typecheck, Vitest, build e dry-run Wrangler.
6. Canary live senza publish dopo deploy e migration.

## Operazioni manuali residue

Il proprietario deve soltanto autorizzare Wrangler nel browser. Non deve attivare R2 né inserire
informazioni di pagamento. La migration crea bucket e policy nel progetto Supabase esistente.
