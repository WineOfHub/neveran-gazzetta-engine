# Neveran Gazzetta Image Worker

Servizio privato e senza storage che genera l'illustrazione lead con Workers AI e restituisce il
binario Base64 al motore. Il chiamante non può selezionare modello o dimensioni; il motore valida
il risultato e lo conserva nel bucket Supabase Storage `gazzetta-artwork`.

## Sviluppo

```powershell
Copy-Item .dev.vars.example .dev.vars
npm install
npm test
npm run typecheck
npm run dev
```

`.dev.vars` è ignorato da Git. Non usare un token Cloudflare come token applicativo: il valore
`GAZZETTA_IMAGE_WORKER_TOKEN` è una password casuale condivisa esclusivamente fra il motore e
questo Worker.

## Deploy

Non richiede R2 né una sottoscrizione Cloudflare. I comandi completi sono nel runbook radice
`docs/cloudflare-artwork-runbook.md`.
