# Neveran Gazzetta Engine

Motore autonomo che genera e pubblica la prima pagina globale della Gazzetta del CCIN.

Il servizio usa la lore pubblica di Neveran indicizzata in Qdrant come vincolo editoriale,
inventa eventi effimeri e non canonici, genera l'edizione tramite Groq e pubblica uno snapshot
atomico in Supabase. La main app legge soltanto l'ultima edizione pubblicata.

## Stato

**Implementazione locale completa fino al rollout.** Worker, scheduler, RAG condiviso,
pipeline Groq, validator, memoria editoriale, API operativa, publisher Supabase, Main App,
console admin, Monitor, canary read-only e unit systemd sono implementati e verificati offline.

La pubblicazione automatica non è stata attivata: migration live, credenziali, canary reali,
prima edizione controllata e soak di due settimane richiedono gli ambienti dell'utente. Nessun
commit o push è stato eseguito durante lo sviluppo.

## Decisioni fondamentali

- una sola Gazzetta globale;
- pubblicazione autonoma ogni due giorni alle 06:00 `Europe/Rome`;
- contenuti decorativi, effimeri e non canonici;
- RAG proprio, senza usare `/ask` del Lamp Assistant;
- stessa collection Qdrant pubblica, rigorosamente read-only;
- Groq come unico provider LLM;
- Supabase per coda, memoria, pubblicazione e controllo remoto;
- worker sul mini PC `neveranforge`;
- ultimo snapshot valido sempre disponibile in caso di guasto.

La specifica completa è in
[docs/software-design-specification.md](docs/software-design-specification.md).
Il percorso di implementazione verificabile è in
[docs/development-plan.md](docs/development-plan.md).

## Repository dell'ecosistema

- `neveran-knowledge-engine`: contratti lore e core condiviso di retrieval;
- `neveran-lamp-assistant-rag`: consumer factual della stessa lore;
- `neveran-main-app`: pagina Gazzetta e console admin;
- `neveran-monitor`: telemetria e quote;
- `neveran-npc-dialogue-forge`: precedente operativo per worker, lease e pubblicazione.

## Struttura

```text
config/                 configurazione versionata non sensibile
deploy/systemd/         unit reali e procedure neveranforge
docs/                   specifica, runbook e contratti
prompts/                prompt operativi versionati e JSON Schema
src/neveran_gazzetta/   package Python
tests/                  suite unit, contract, integration ed eval
```

## Sviluppo locale

Prerequisito: Python 3.12.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,api,retrieval]"
pytest
ruff check .
mypy src
```

I test predefiniti non usano rete né credenziali. I soli comandi live sono opt-in:

```text
gazzetta-preflight --confirm-live-read-only
gazzetta-canary --confirm-live-no-publish
```

### Anteprima del canary nella Main App

Il canary può essere mostrato dal vero componente magitech della Main App senza pubblicarlo.
Dopo la generazione, prepara il file locale ignorato da Git:

```powershell
.\.venv\Scripts\python.exe scripts\render_canary_preview.py `
  eval\live-results\canary-1-first-live.json `
  --snapshot-output ..\neveran-main-app\frontend\public\__gazzetta-preview.json
```

Avvia Vite in `neveran-main-app/frontend` e apri
`http://localhost:5173/__preview/gazzetta?motionTier=cinematic`. La route esiste soltanto in
sviluppo e non interroga Supabase.

## Configurazione

1. copiare `.env.example` in `.env`;
2. compilare i valori locali senza commetterli;
3. mantenere le policy non sensibili in `config/`;
4. non inserire mai chiavi, password o URL firmati nei prompt o nei log.

## Git

Remote configurato:

```text
https://github.com/WineOfHub/neveran-gazzetta-engine.git
```

Lo sviluppo locale non esegue commit o push automaticamente.
