---
name: gazzetta-repair
version: gazzetta-repair-v5
---

Correggi la prima pagina della Gazzetta senza cambiare le notizie già presenti nella bozza.
Applica esclusivamente i difetti deterministici elencati. Restituisci
l'intera edizione nello schema richiesto, in italiano, senza spiegazioni.

Usa `slotBudgets` come vincolo numerico esatto per parole, paragrafi e lunghezze. Le tre breaking
restano stringhe in `breakingNews`; non trasformarle in articoli. L'output contiene un lead, due
major, due minor e un brief secondo i campi dello schema, senza ID, importanza o firme scelti da te.

L'oggetto `edition` deve contenere sempre `mastheadSubtitle`, `locationLabel`, `breakingNews`,
`leadArticle`, `majorArticles`, `minorArticles`, `briefArticle`, `editorialQuote` e
`closingMotto`. Restituisci esattamente tre stringhe in `breakingNews`, esattamente due oggetti in
`majorArticles` ed esattamente due oggetti in `minorArticles`. `leadArticle` contiene esattamente
tre stringhe in `paragraphs`; ciascun major ne contiene esattamente due; ciascun minor e il brief
ne contengono esattamente una. Ogni articolo contiene sempre `category`, `title`, `kicker`,
`summary`, `paragraphs` e `pullQuote`; usa `null` per `kicker` o `pullQuote` quando non servono.
Non interrompere il JSON prima di avere ricopiato e corretto tutti gli slot.

Non aggiungere nuove notizie. Non rimuovere slot. “Loop” resta soltanto il materiale raro e
pregiato. Non inserire HTML, Markdown, placeholder o metadati tecnici.
Conserva esattamente i nomi Neveran presenti nella bozza e non introdurre nomi contemporanei.
