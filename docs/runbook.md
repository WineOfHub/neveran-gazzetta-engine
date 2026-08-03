# Runbook operativo

## Regola principale

Un errore non deve mai sostituire, svuotare o corrompere l'edizione corrente. La nuova edizione
diventa visibile soltanto dopo la RPC atomica di pubblicazione.

## Worker offline

Segnali:

- heartbeat scaduto;
- service systemd inattivo;
- nessun tick recente.

Azione:

1. verificare host e service;
2. riavviare il processo soltanto dopo aver letto l'ultimo errore;
3. lasciare che il worker calcoli il catch-up;
4. non creare manualmente edizioni arretrate.

## Groq quota o 429

Segnali:

- `error_class=provider_quota`;
- HTTP 429;
- header `retry-after`.

Azione:

1. non cambiare chiave per aggirare il limite;
2. verificare token residui e reset;
3. lasciare il job disponibile dopo il reset;
4. controllare che non siano avvenuti retry ciechi;
5. mantenere l'edizione corrente.

## Qdrant o Jina indisponibili

Il job deve fallire in modo distinto da `no_evidence`. Non consentire generazione senza lore.
Verificare endpoint, chiavi, collection, dimensione embedding e release attiva.

## Release mismatch

Se la release cambia durante un run:

1. abortire il run;
2. non riutilizzare eventi già pianificati;
3. ricominciare con la release nuova dopo backoff;
4. registrare entrambe le release nella diagnostica.

## Output invalido

È consentita una sola riparazione. Se fallisce:

- job `failed` o `dead_letter` secondo i tentativi;
- nessuna pubblicazione;
- conservare report di validazione;
- non correggere manualmente il payload nel database.

## Edizione ritirata

La console admin usa RPC autorizzata. Il ritiro:

- conserva numero e snapshot;
- marca l'edizione `withdrawn`;
- attiva atomicamente una precedente edizione valida, se esiste;
- scrive audit e motivo;
- non cancella eventi o storyline.

## Monitor indisponibile

La telemetria è fail-open. Il worker può continuare, usando un buffer locale limitato e privo di
prompt/lore. Non accumulare log senza limite.
