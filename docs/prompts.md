# Contratti dei prompt

## Principio

I prompt sono asset versionati e testati. Non contengono segreti, URL privati, credenziali o
copie permanenti della lore.

Ogni prompt dichiara:

- nome e versione;
- ruolo nella pipeline;
- input ammessi;
- JSON Schema di output;
- token budget;
- invarianti;
- comportamenti vietati;
- casi di test.

## Event Planner

Responsabilità:

- proporre eventi strutturati per tutti gli slot;
- usare esclusivamente la Lore Palette fornita;
- distinguere assurdità reale, voce non verificata e fake deliberata;
- collegare al massimo una notizia per storyline nella stessa edizione;
- non scrivere articoli completi.

Output strict JSON. Tutti gli oggetti usano `additionalProperties: false`.

## Newspaper Writer

Responsabilità:

- trasformare eventi già validati nella prima pagina;
- rispettare budget e lingua italiana;
- creare ritmo, citazioni, fonti e colore umano superficiale;
- non aggiungere nuovi grandi eventi o claim cosmologici;
- non cambiare classificazioni interne di verità.

Il writer non riceve la history completa delle edizioni.

## Verifier

Responsabilità:

- produrre `pass`, `repairable` o `reject`;
- indicare difetti tramite codici stabili;
- non riscrivere contenuto;
- non promuovere fake a fatto;
- verificare l'uso di “Loop”.

Output strict JSON.

## Versionamento

Formato suggerito:

```text
gazzetta-event-planner-v1
gazzetta-newspaper-writer-v1
gazzetta-verifier-v1
```

Ogni run registra le versioni. Un cambiamento semantico incrementa la versione e richiede eval.

