# Unit systemd per neveranforge

Percorsi operativi scelti:

- utente/gruppo: `neveran-gazzetta`;
- release immutabili: `/opt/neveran/gazzetta-engine/releases/<commit>`;
- symlink corrente: `/opt/neveran/gazzetta-engine/current`;
- virtualenv: `/opt/neveran/gazzetta-engine/venv`;
- segreti: `/etc/neveran/gazzetta-engine.env`, owner root, mode `0640`;
- stato scrivibile: `/var/lib/neveran-gazzetta`.

Installazione delle unit:

```bash
sudo install -o root -g root -m 0644 deploy/systemd/neveran-gazzetta-api.service /etc/systemd/system/
sudo install -o root -g root -m 0644 deploy/systemd/neveran-gazzetta-worker.service /etc/systemd/system/
sudo install -o root -g root -m 0644 deploy/systemd/neveran-gazzetta-worker.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now neveran-gazzetta-api.service neveran-gazzetta-worker.timer
```

Il timer sveglia un tick ogni minuto ed è `Persistent`: dopo un periodo offline esegue subito il
recovery. Supabase resta l'unica fonte di verità sulla scadenza e conserva solo l'ultimo slot
scaduto. Non avviare manualmente più copie con lo stesso `GAZZETTA_WORKER_ID`.

## Rollback

Spostare atomicamente `current` su una release precedente già installata, poi riavviare API e
timer. Non applicare rollback distruttivi alla migration e non cancellare job o edizioni.
