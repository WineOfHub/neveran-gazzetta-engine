# Test

La suite predefinita è offline. I test live usano il marker `live` e richiedono invocazione
esplicita.

Cartelle future:

- `unit/`: domain, scheduler, policy e validatori;
- `contract/`: JSON Schema, config, Supabase e retrieval core;
- `integration/`: adapter con stub/local services;
- `eval/`: qualità narrativa e regressioni;
- `fixtures/`: dati sintetici e non sensibili.

Comandi previsti:

```powershell
pytest
pytest -m live
```

`pytest` non deve selezionare automaticamente i test live.

