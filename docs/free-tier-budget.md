# Stima free tier e crescita dati

Stima aggiornata al 1 agosto 2026. I limiti reali dell'organizzazione prevalgono sempre e vanno
letti nella console Groq durante il preflight.

## Groq

La configurazione usa `openai/gpt-oss-120b` per planner, writer e verifier. Il precedente
`llama-3.3-70b-versatile` è stato rimosso dai default perché Groq ne ha annunciato lo shutdown
free/developer per il 16 agosto 2026.

Limiti base Free pubblicati per GPT-OSS 120B:

- 30 richieste/minuto;
- 1.000 richieste/giorno;
- 8.000 token/minuto;
- 200.000 token/giorno.

Fonti ufficiali:

- https://console.groq.com/docs/rate-limits
- https://console.groq.com/docs/deprecations
- https://console.groq.com/docs/model/openai/gpt-oss-120b

Il motore impone 3 chiamate normali, al massimo 1 repair e 35.000 token complessivi. Con una
edizione ogni due giorni sono circa 46 chiamate/mese normali, massimo 62, e al massimo circa
542.500 token/mese medio (560.000 in un intervallo di 31 giorni con 16 edizioni). Il limite
giornaliero è quindi ampio; il collo di bottiglia è il TPM. Le chiamate restano separate e il
worker attende fino a 60 secondi quando gli header indicano un reset breve. Per reset più lunghi
rinvia il job all'istante comunicato dal provider.

Il cap 35.000 è un guardrail, non l'obiettivo. Il canary deve misurare input/output reali; target
operativo consigliato: meno di 18.000 token per edizione e repair rate sotto il 25%.

## Supabase

Lo snapshot stimato è 15–30 KB. A 183 edizioni/anno occupa circa 2,7–5,5 MB/anno prima degli
indici. Eventi e memoria compatta portano una stima prudente sotto 10–15 MB/anno. Il Free Plan
pubblica una quota database di 500 MB, quindi la Gazzetta non è il limite dominante dell'app.

Fonti ufficiali:

- https://supabase.com/docs/guides/platform/database-size
- https://supabase.com/pricing

Non si cancellano edizioni ritirate o pubblicate: servono a rollback e futuro storico. Dopo 90
giorni si svuotano solo i payload duplicati dei run completati. Token, hash, esito, modelli e
durata rimangono per analisi longitudinale.

## Cloudflare Workers AI e Supabase Storage

ADR-0002 aggiunge una sola immagine lead ogni due giorni. Workers AI è disponibile sul piano Free
con 10.000 neuroni al giorno; oltre tale quota le ulteriori operazioni falliscono e non vengono
fatturate senza un upgrade esplicito. Il motore esegue un solo retry e poi usa il fallback.

Supabase Free include 1 GB di file storage e 5 GB di egress più 5 GB di egress in cache. Poiché
la quota è condivisa con le altre immagini dell'app, la Gazzetta non conserva tutto lo storico:
accetta file fino a 6 MiB e mantiene al massimo 24 artwork. Il limite teorico del bucket è quindi
144 MiB; con file tipici più piccoli il consumo reale sarà sensibilmente inferiore.

Fonti ufficiali:

- https://developers.cloudflare.com/workers-ai/platform/pricing/
- https://developers.cloudflare.com/workers-ai/models/flux-2-klein-9b/
- https://supabase.com/pricing
- https://supabase.com/docs/guides/storage/serving/bandwidth
