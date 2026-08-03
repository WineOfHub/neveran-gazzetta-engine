# Documentazione

- `generated-artwork-implementation-plan.md`: progetto delle immagini lead generate.
- `cloudflare-artwork-runbook.md`: deploy Workers Free e Storage Supabase senza billing.
- `adr/0002-artwork-supabase-storage-senza-billing.md`: decisione corrente su generazione,
  persistenza gratuita, retention e fallback.

## Fonti autorevoli

- [Software Design Specification](software-design-specification.md): architettura, contratti,
  sicurezza, modello dati, rollout e acceptance criteria.
- [Piano di sviluppo end-to-end](development-plan.md): sequenza operativa, work item,
  dipendenze, test e gate di avanzamento tra repository.
- [Operazioni](operations.md): configurazione e deploy previsto su `neveranforge`.
- [Runbook](runbook.md): diagnosi e risposta ai guasti.
- [Prompt](prompts.md): confini e versionamento dei prompt Groq.
- [Stima free tier](free-tier-budget.md): budget Groq, crescita Supabase e retention.
- [Rapporto di verifica locale](verification-report-2026-08-01.md): suite, artefatti, limiti e
  attività live ancora necessarie.
- [ADR](adr/README.md): processo per decisioni architetturali incompatibili o trasversali.

La specifica è la fonte di verità. I documenti operativi non possono modificarne gli invarianti.
Ogni decisione incompatibile richiede una ADR e un aggiornamento esplicito della specifica.

## Stato

Il target software è implementato localmente. I documenti distinguono le verifiche offline già
superate dalle operazioni live ancora da eseguire su Supabase, Groq, Qdrant, Monitor e
`neveranforge`.
