# Neveran Gazzetta Engine — istruzioni per agenti AI

## Contesto

Questo repository contiene il motore autonomo della Gazzetta globale del CCIN. La fonte di
verità architetturale è `docs/software-design-specification.md`.

Lingua di codice, commenti, documentazione e commit: **italiano**. Identificatori tecnici possono
restare in inglese quando fanno parte di contratti o API.

## Fase corrente

**Bootstrap documentale/configurativo.** Non implementare chiamate live, migration, pubblicazione,
scritture Qdrant o deploy finché il task non lo richiede esplicitamente.

## Invarianti non negoziabili

1. La Gazzetta è globale, effimera, decorativa e non canonica.
2. Nessun output generato modifica lore, Qdrant o gameplay.
3. Qdrant è read-only; questo repository non indicizza.
4. Non usare `/ask`, prompt o persona Jhonny.
5. Non generare senza grounding sufficiente.
6. Un guasto lascia pubblicata l'ultima edizione valida.
7. Il publish è atomico e idempotente.
8. Groq è l'unico provider LLM; non introdurre fallback silenziosi.
9. “Loop” indica soltanto il materiale raro e pregiato di Neveran.
10. I segreti non entrano in Git, log, fixture o telemetria.

## Confini

- `neveran-knowledge-engine` possiede lore, policy e core condiviso di retrieval.
- Questo repository possiede planner, generazione, validazione, worker e API operativa.
- `neveran-main-app` possiede UI player, console admin e schema runtime Supabase.
- `neveran-monitor` possiede osservabilità aggregata, non stato autorevole.

Non copiare il retriever Lamp. Estrarre o consumare il package condiviso previsto dalla specifica.

## Regole di implementazione

- Domain e application non importano FastAPI, Qdrant, Groq o Supabase concreti.
- Gli adapter implementano porte esplicite.
- Pydantic usa `extra="forbid"` sui contratti autorevoli.
- Config non sensibile in YAML; segreti soltanto in environment.
- Ogni valore casuale deve derivare da una seed registrata.
- Ogni prompt ha versione, schema input/output e test.
- Distinguere sempre `NoEvidence`, outage, quota e output invalido.
- Nessun catch generico può trasformare un errore tecnico in lista vuota.
- Una sola riparazione LLM massima per edizione.
- Nessun test bloccante dipende dalla rete.

## Database e sicurezza

Ogni nuova tabella richiede migration, indici, RLS e test di ruolo. Il worker usa un account
dedicato e RPC, mai la service role key. Gli endpoint mutanti sono fail-closed.

## Qualità

Prima di completare una modifica Python eseguire, quando disponibili:

```powershell
pytest
ruff check .
mypy src
```

Per configurazioni YAML verificare parsing, somme delle probabilità e riferimenti incrociati.

## Git

- preservare modifiche concorrenti;
- non committare o pushare senza richiesta;
- non modificare cronologia con reset distruttivi;
- mantenere `docs/software-design-specification.md` tracciato;
- file locali e segreti devono restare coperti da `.gitignore`.

