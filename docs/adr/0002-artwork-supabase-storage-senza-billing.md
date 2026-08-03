# ADR-0002 — Artwork su Supabase Storage senza billing Cloudflare

> Stato: accettata
> Data: 2026-08-03
> Supera: ADR-0001

## Contesto

R2 include una quota gratuita, ma la sua attivazione richiede una sottoscrizione Cloudflare e può
richiedere informazioni di pagamento. Neveran non deve dipendere da servizi che possano produrre
addebiti automatici. La Main App possiede già un progetto Supabase Free con Storage e CDN di base.

## Decisione

1. Cloudflare viene usato soltanto sul piano Workers Free per il Worker e Workers AI. Se la quota
   gratuita giornaliera termina, la generazione fallisce e parte il fallback; non viene eseguito
   alcun upgrade automatico.
2. Il Worker è stateless: valida il bearer, genera l'immagine con FLUX.2 Klein 9B, verifica tipo,
   dimensione e hash e restituisce il binario Base64. Non possiede R2, KV o credenziali Supabase.
3. Il motore controlla prima una key deterministica nel bucket pubblico Supabase
   `gazzetta-artwork`. Se esiste, la riusa senza chiamare Workers AI.
4. Il motore carica il file usando la stessa sessione dell'account auth `gazzetta_worker`; non usa
   mai `service_role`. Le policy Storage concedono a tale ruolo soltanto select, insert e delete
   nel bucket e nel formato di path previsto. Non è consentito update/upsert.
5. Il bucket accetta solo PNG, JPEG e WebP fino a 6 MiB. Prima di ogni nuovo upload, il motore
   conserva al massimo 24 immagini e rimuove le più vecchie tramite Storage API.
6. Lo snapshot Supabase contiene solo URL e metadati per il player, mai Base64. Il frontend
   accetta esclusivamente HTTPS, l'origine Supabase della Main App e il bucket previsto.
7. Qualunque errore Cloudflare o Storage mantiene pubblicabile l'edizione con il fallback
   magitech SVG/CSS.

## Conseguenze

- Nessuna informazione di pagamento Cloudflare è necessaria.
- L'immagine attraversa Worker e motore in Base64 una sola volta; è un costo di rete accettabile
  per un file massimo di 6 MiB ogni due giorni.
- Il tetto di 24 immagini limita il caso peggiore del bucket a 144 MiB, lasciando margine nel
  gigabyte Storage del piano Supabase Free condiviso con il resto dell'app.
- Lo storico testuale resta completo; lo storico visivo gratuito copre circa 48 giorni.
- Un futuro storage dedicato può sostituire Supabase dietro la stessa porta applicativa.

## Alternative considerate

- **Cloudflare R2:** scartato perché richiede una sottoscrizione con billing.
- **Base64 nel JSONB dell'edizione:** scartato perché gonfia database, RPC e payload del player.
- **service role Supabase nel Worker:** scartato per evitare un segreto privilegiato fuori dal
  motore e mantenere il principio del minimo privilegio.
- **File locali sul mini-PC:** scartati perché la Main App globale non avrebbe un'origine HTTPS
  affidabile e cacheabile.
