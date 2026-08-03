# Prompt operativi

Ogni prompt contiene frontmatter `name` e `version`, input esplicito e output con modello
Pydantic/JSON Schema. Il flusso è:

1. `event_planner.system.md`: eventi, fonti e classificazioni interne;
2. `newspaper_writer.system.md`: sola prosa italiana dagli eventi validati;
3. `repair.system.md`: una sola correzione sui difetti deterministici;
4. `verifier.system.md`: verdict finale, senza capacità di riscrittura.

Gli schema player versionati sono in `schemas/` e si rigenerano con
`python scripts/export_schemas.py`. Nessun prompt può pubblicare direttamente o ricevere segreti.
