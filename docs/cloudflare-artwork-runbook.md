# Runbook senza billing — immagini lead della Gazzetta

Il flusso usa Cloudflare Workers AI sul piano Free e il Supabase Storage già incluso nel progetto
della Main App. Non usa R2, Cloudflare Images, KV o un piano Workers Paid.

## Valori finali

| Valore | Dove vive | Segreto |
| --- | --- | --- |
| Worker `neveran-gazzetta-image-worker` | Cloudflare Workers Free | no |
| `GAZZETTA_IMAGE_WORKER_TOKEN` | secret Worker + env motore | sì |
| bucket `gazzetta-artwork` | Supabase Storage Free | no |
| URL `https://…workers.dev` | env motore | no |

Non servono dati di pagamento, API token R2, chiavi S3 o `service_role` Supabase.

## 1. Non attivare R2 o Workers Paid

Chiudere la pagina **Add R2 subscription** senza confermare. Workers AI è disponibile nel piano
Workers Free con una quota giornaliera. Se la quota termina, Cloudflare rifiuta altre operazioni:
il motore usa il fallback statico e non effettua upgrade automatici.

Fonte: https://developers.cloudflare.com/workers-ai/platform/pricing/

## 2. Autorizzare Wrangler

Da questa cartella:

```powershell
cd "D:\Neveran Universe\neveran-gazzetta-engine\cloudflare\gazzetta-image-worker"
pnpm exec wrangler login
```

Si apre Cloudflare: scegliere l'account corretto e confermare. Questa autorizzazione non attiva
un abbonamento.

## 3. Generare il token applicativo

`GAZZETTA_IMAGE_WORKER_TOKEN` è una password casuale condivisa, non un API token Cloudflare.

```powershell
$gazzettaBytes = New-Object byte[] 32
$gazzettaRng = [Security.Cryptography.RandomNumberGenerator]::Create()
$gazzettaRng.GetBytes($gazzettaBytes)
$gazzettaImageToken = ($gazzettaBytes | ForEach-Object { $_.ToString('x2') }) -join ''
$gazzettaRng.Dispose()
```

Non incollarlo in chat, Git, documentazione o log.

## 4. Distribuire il Worker Free

Il primo deploy crea il Worker stateless:

```powershell
pnpm run deploy
pnpm exec wrangler secret put GAZZETTA_IMAGE_WORKER_TOKEN
```

Al prompt del secondo comando incollare `$gazzettaImageToken`. Conservare l'URL stampato dal
deploy senza aggiungere `/v1/generate`.

Il file `wrangler.jsonc` contiene soltanto il binding Workers AI e parametri fissi del modello;
non contiene binding di storage o servizi fatturabili.

## 5. Applicare la migration Supabase Storage

Applicare nel progetto Supabase della Main App:

```text
neveran-main-app/supabase/migrations/20260803120000_gazzetta_artwork_storage.sql
```

La migration crea un bucket pubblico da massimo 6 MiB per file. Upload, elenco e cancellazione
sono concessi soltanto all'account con ruolo `gazzetta_worker`; update/upsert sono vietati.

## 6. Completare l'env del motore

Aggiungere soltanto:

```dotenv
GAZZETTA_IMAGE_WORKER_URL=https://neveran-gazzetta-image-worker.<account>.workers.dev
GAZZETTA_IMAGE_WORKER_TOKEN=<stesso-token-del-punto-3>
```

URL, chiave anon, email e password Supabase sono già quelli del motore. Non aggiungere una
`service_role` e non serve un'origine media separata.

## 7. Verifica senza pubblicazione

Health check senza generare immagini:

```powershell
Invoke-RestMethod https://neveran-gazzetta-image-worker.<account>.workers.dev/health
```

Bundling locale:

```powershell
pnpm exec wrangler deploy --dry-run
```

Canary completo, con una vera immagine ma senza pubblicare l'edizione:

```powershell
gazzetta-canary --confirm-live-no-publish
```

## Limiti automatici

- massimo 6 MiB per immagine;
- massimo 2.200 caratteri nel prompt immagine;
- massimo 24 immagini nel bucket, circa 48 giorni di storico visivo;
- upload immutabili con key deterministica;
- retention eseguita prima di ogni nuovo upload;
- se quota AI o Storage non sono disponibili, la Gazzetta pubblica il fallback magitech.

## Diagnostica rapida

- `storage_read_400` non deve comparire per un oggetto assente: Supabase esprime il cache miss
  pubblico come HTTP 400 con `code: NoSuchKey`, che l'adapter riconosce in modo stretto;
- `provider_unavailable` mantiene l'edizione utilizzabile col fallback e consente un tentativo
  successivo; verificare `/health` e poi un canary, senza attivare piani a pagamento;
- se l'immagine raffigura un giornale o contiene grandi pseudo-lettere, non riusare prompt `v1` o
  `v2`: il profilo installato è `neveran-lead-artwork-v3`.

## Rollback

Impostare `artwork.generation_enabled: false` in `config/editorial_policy.yaml` e riavviare il
motore. Il player continua a usare l'artwork SVG/CSS. Non eliminare manualmente righe dalla
tabella `storage.objects`: i file vanno rimossi soltanto attraverso Storage API.
