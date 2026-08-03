# Changelog

Le modifiche rilevanti al motore vengono documentate qui seguendo Keep a Changelog e versioni
SemVer.

## [Unreleased]

### Added

- bootstrap documentale e configurativo;
- piano di sviluppo end-to-end;
- configurazione tipizzata fail-fast;
- struttura iniziale domain/application/adapters;
- CI offline;
- core retrieval read-only condiviso con Knowledge Engine e adapter Lamp;
- dominio Pydantic, schemi player e migration Supabase con RLS/RPC atomiche;
- scheduler Europe/Rome, lease, recovery latest-only e retention;
- planner, storyline, entità ricorrenti, Lore Palette e guardrail Loop/canon;
- firme visibili ricorrenti, fonti diegetiche obbligatorie e guardrail di affidabilità;
- pipeline Groq a budget, JSON Schema/JSON mode, repair singola e verifier;
- hash verificabili di policy, prompt, draft e snapshot pubblicato;
- evaluation dataset, preflight e canary senza pubblicazione;
- lettura globale Main App, fallback locale, preview e console admin;
- telemetria fail-open e dashboard Neveran Monitor;
- entrypoint, wheel verificata e unit systemd per neveranforge.
- generazione opzionale dell'illustrazione principale tramite Worker Cloudflare autenticato e
  Workers AI Free, con persistenza Supabase Storage, retention, retry e fallback magitech;
- contratto immagine nello snapshot, parser sicuro nella Main App e rendering remoto con
  ripristino automatico dell'artwork SVG/CSS.

### Changed

- assegnazione deterministica delle firme da una redazione Neveran ruotata per numero;
- normalizzazione stabile dei nomi contemporanei per i soli PNG inventati, lasciando intatte le
  identità provenienti dalla lore;
- prompt planner, writer e repair aggiornati con la forma JSON completa per ridurre gli scarti
  `json_validate_failed` senza allentare gli schemi;
- cache miss Supabase compatibile con la risposta HTTP 400/`NoSuchKey` dell'endpoint pubblico;
- brief artwork `neveran-lead-artwork-v3` limitato a 2.200 caratteri e orientato a una scena
  full-bleed, senza giornali, mockup o pseudo-tipografia generata.
