# Rapporto di verifica locale — 1 agosto 2026

## Esito

Le fasi F0–F8 sono implementate e verificate localmente. F9 resta intenzionalmente aperta perché
richiede infrastruttura reale, identità dedicate, migrazioni revisionate, provider live,
approvazione della prima pubblicazione e almeno due settimane di osservazione.

Nessun commit o push è stato eseguito. Nessuna migration è stata applicata e nessun provider è
stato contattato durante la suite bloccante.

## Matrice eseguita

| Modulo | Verifica | Esito |
| --- | --- | --- |
| Gazzetta Engine | `pytest` | 90 pass, 1 warning di deprecazione Starlette/httpx |
| Gazzetta Engine | Ruff | verde |
| Gazzetta Engine | mypy strict | 39 file verdi |
| Gazzetta Engine | scansione segreti | verde |
| Gazzetta Engine | export JSON Schema | allineato |
| Gazzetta Engine | entrypoint worker/canary/preflight e API | caricamento/help verdi |
| Knowledge Engine | suite completa | 137 pass, 1 warning di deprecazione |
| Knowledge Engine | Ruff sul retrieval condiviso | verde |
| Lamp Assistant | contratto retrieval condiviso | 8 pass, 1 skip previsto su Python 3.10 |
| Lamp Assistant | suite completa | 334 pass, 3 xfail, 1 skip; 1 failure ambientale opzionale |
| Main App | Vitest | 34 file, 184 test verdi |
| Main App | ESLint moduli Gazzetta/admin modificati | verde |
| Main App | TypeScript + build PWA | verde |
| Neveran Monitor | TypeScript + build Vite | verde |
| Neveran Monitor | compileall backend/API | verde |

La failure Lamp residua è nel test storico del reranker che importa direttamente
`sentence_transformers`, dipendenza opzionale non installata nel virtualenv Python 3.10. I test
nuovi di error mapping Qdrant, release e adapter condiviso sono verdi.

Il lint globale della Main App rileva 86 errori preesistenti in aree non Gazzetta, soprattutto
quest, carte, assistant e asset Android generati. Non sono stati modificati per evitare di
mescolare refactor estranei alla feature.

## Integrità verificata durante l'audit

- uno slot più vecchio ancora leased/running viene marcato `missed` e revocato quando scade una
  nuova cadenza;
- due tick simultanei nello stesso processo non possono eseguire due pipeline concorrenti;
- il ruolo player ha privilegio di colonna soltanto su `gazzetta_editions.snapshot` e la RLS
  applica `published AND is_current`;
- il run conserva l'hash del draft, mentre l'edizione conserva l'hash ricalcolato dopo ID, numero,
  slug e ora reale di pubblicazione;
- policy e quattro prompt hanno versione e SHA-256 registrati;
- il publish ricontrolla nove eventi, grounding, fonti, affidabilità, massimo una fake secondaria,
  sei articoli e rotazione di 3–5 firme;
- storyline duplicate nello stesso numero vengono rifiutate;
- retention conserva tutte le edizioni, compatta filoni terminali e svecchia entità effimere.

## Artefatti

- `neveran_gazzetta_engine-0.1.0-py3-none-any.whl`;
- `neveran_gazzetta_engine-0.1.0.tar.gz`;
- `neveran_knowledge_engine-0.4.0-py3-none-any.whl`;
- `neveran_knowledge_engine-0.4.0.tar.gz`.

Gli artefatti sono locali e ignorati da Git. Gli SHA-256 vengono calcolati dopo la build finale e
riportati nell'handoff, non dentro la sdist che li contiene.

## Verifiche che restano necessariamente live

- parsing/applicazione della migration su un progetto Supabase test e prove RLS per player,
  admin, worker e anon;
- provisioning dell'account `gazzetta_worker`, chiave Qdrant read-only e token Monitor;
- preflight Jina/Qdrant/Groq e misura dei limiti effettivi dell'organizzazione;
- canary senza pubblicazione con revisione editoriale italiana;
- prova autenticata responsive/Android WebView della pagina Gazzetta;
- prima pubblicazione approvata, ritiro/ripristino in staging e soak di almeno due settimane.

L'ordine vincolante di queste attività è mantenuto nel piano di sviluppo e nel runbook.
