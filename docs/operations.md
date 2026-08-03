# Operazioni e deploy

## Target

Il worker e l'API operativa saranno eseguiti sul mini PC `neveranforge`. Supabase rimane la fonte
di verità per coda, scadenza, lease, pubblicazione e stato amministrativo.

## Processi previsti

```text
neveran-gazzetta-api.service
neveran-gazzetta-worker.service
neveran-gazzetta-worker.timer
```

Le unit reali e i percorsi scelti sono versionati in `deploy/systemd/README.md`.

## Bootstrap locale

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,api]'
cp .env.example .env
```

Non compilare `.env` con valori reali dentro una sessione registrata o output condiviso.

## Principi deploy

- utente Linux dedicato e non root;
- checkout in directory dedicata;
- virtual environment dedicato;
- `.env` leggibile soltanto dall'utente del servizio;
- working directory e commit deployato registrati;
- restart con backoff;
- tick immediato al boot;
- heartbeat Supabase;
- nessuna service role key sul mini PC;
- chiave Qdrant read-only;
- rollback del codice senza cancellazione dati.

## Configurazione

La configurazione è composta da:

- `config/default.yaml`: runtime e integrazioni non sensibili;
- `config/editorial_policy.yaml`: policy editoriale versionata;
- `config/logging.yaml`: logging locale;
- `.env`: segreti e valori ambiente, mai versionato.

Le variabili richieste sono documentate in `.env.example`.

## Scheduling

Il timer systemd non è fonte di verità. Sveglia il worker, che confronta l'ora corrente con
`next_due_at` in Supabase usando il fuso `Europe/Rome`.

Al recovery:

- se la prossima edizione non è ancora dovuta, genera quella in ritardo;
- se sono scaduti più slot, marca i precedenti `missed` e genera soltanto l'ultimo;
- usa l'orario reale di pubblicazione nello snapshot.

## Aggiornamenti

Prima del deploy:

1. eseguire test offline;
2. verificare migration e RLS in ambiente test;
3. verificare modelli e limiti Groq reali;
4. eseguire live eval opt-in senza pubblicazione;
5. applicare migration separatamente;
6. deployare il commit pin-nato;
7. verificare health e heartbeat;
8. osservare almeno un tick senza pubblicazione prima del canary.

## Canary live senza pubblicazione

```bash
gazzetta-preflight --confirm-live-read-only
gazzetta-canary --confirm-live-no-publish
```

Il preflight verifica login worker, manifest/release, Jina, Qdrant read-only e disponibilità dei
modelli Groq senza scrivere. Il canary usa retrieval e Groq reali, ma non acquisisce job e non chiama le RPC di submit o
publish. Il risultato completo viene scritto in `eval/live-results/`, cartella ignorata da Git,
per la revisione editoriale. Non trasformare il canary in una scorciatoia di pubblicazione.

## Retention

Le edizioni pubblicate e ritirate restano archiviate perché sono snapshot piccoli e utili al
rollback. Dopo 90 giorni il worker svuota soltanto i payload duplicati dei run completati;
mantiene ID, esito, modelli, token, durata, hash e riferimenti all'edizione. Le storyline terminali
da almeno 180 giorni restano come recap compatti. L'implementazione v1 non persiste le risposte raw
dei provider; il limite configurato di 30 giorni è un tetto conservativo per un eventuale adapter
futuro. Le entità ricorrenti non-giornalista inattive per 50 numeri vengono ritirate; firme
occasionali e altre entità non ricorrenti vengono ritirate o eliminate dopo 20 numeri. Prompt,
lore completa e risposte raw non entrano mai nei log permanenti.
