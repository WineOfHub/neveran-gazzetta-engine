# ADR-0001 — Artwork lead generato con Cloudflare

> Stato: sostituita da ADR-0002
> Data: 2026-08-03

Questa decisione resta come memoria storica. R2 è stato rimosso perché richiede l'attivazione di
una sottoscrizione con billing, non compatibile con il vincolo operativo del progetto.

## Contesto

La prima versione della Gazzetta usa un artwork SVG/CSS statico. Ogni edizione deve ora avere,
quando il provider è disponibile, una vera illustrazione editoriale ispirata alla notizia
principale. L'immagine resta decorativa, effimera e non canonica: non può introdurre entità,
divinità, organizzazioni o leggi del mondo che non siano già ammesse dall'evento validato.

Il motore gira in Python su NeveranForge, mentre Cloudflare Workers AI offre il modello
`@cf/black-forest-labs/flux-2-klein-9b` e R2 offre lo storage degli oggetti. Supabase continua a
essere lo storage autorevole dello snapshot e non deve contenere binari o Base64.

## Decisione

1. Si genera una sola immagine, quella del lead, nello stesso run dell'edizione.
2. Il brief visivo deriva deterministicamente dal lead già verificato e dalla palette lore già
   recuperata. Non introduce chiamate aggiuntive a Groq, Jina o Qdrant.
3. Un Cloudflare Worker privato possiede i binding Workers AI e R2. Il motore Python lo chiama
   con un bearer token dedicato e non conserva credenziali R2 o token API Cloudflare.
4. Il Worker usa FLUX.2 Klein 9B con inferenza fissa a quattro step, formato landscape e seed
   derivata dal job. Il nome oggetto include job ID e hash del prompt, così i retry sono
   idempotenti.
5. R2 conserva il file; lo snapshot conserva soltanto `src`, `alt`, `caption`, `credit` e
   `focalPoint`. Hash, seed, modello, dimensioni e stato del fallback restano nel report interno
   del run.
6. La generazione è fail-open rispetto alla pubblicazione: un errore previsto produce un solo
   retry tecnico, poi l'edizione viene pubblicata con l'artwork SVG/CSS attuale.
7. Il client accetta solo URL HTTPS e usa l'artwork statico se parsing o caricamento falliscono.
8. Le immagini pubblicate sono immutabili. Soltanto canary e oggetti orfani sono candidati a una
   futura retention automatica.

## Conseguenze

- Un outage Cloudflare non toglie l'ultima edizione valida e non ritarda la Gazzetta.
- Il content hash comprende anche l'immagine quando presente.
- Il costo normale è una generazione ogni due giorni; il fallback non cambia silenziosamente
  modello e non introduce drift stilistico.
- Il deploy richiede un Worker, un bucket R2, un token applicativo condiviso e un'origine media
  HTTPS pubblica.
- Il contratto snapshot resta retrocompatibile perché `image` è opzionale.

## Alternative considerate

- **REST Workers AI direttamente dal mini-PC:** scartata perché richiede un token Cloudflare più
  ampio e credenziali R2 fuori da Cloudflare.
- **Job immagini separato:** scartato perché crea finestre in cui testo e immagine appartengono a
  edizioni diverse.
- **Bloccare la pubblicazione senza immagine:** scartato perché viola il requisito di mantenere
  disponibile una Gazzetta valida durante gli outage.
- **Fallback automatico al modello 4B:** scartato nella prima iterazione per evitare variazioni
  di stile non dichiarate.
- **Binario o Base64 in Supabase:** scartato per dimensione, cache e accoppiamento del player.
