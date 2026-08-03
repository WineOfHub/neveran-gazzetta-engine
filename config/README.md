# Configurazione versionata

- `default.yaml`: runtime, scheduler, adapter e budget tecnici.
- `editorial_policy.yaml`: forma della prima pagina e regole narrative.
- `logging.yaml`: logging locale senza contenuti sensibili.

I file non contengono segreti. I nomi `*_env` indicano la variabile d'ambiente da leggere.

Override locali: `config/local.yaml` o `config/*.local.yaml`, già ignorati da Git. Gli override
non devono introdurre comportamenti contrari alla specifica.

