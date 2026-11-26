# Operazioni

Inoltrare al bot una locandina/caption facoltativa e uno o più video. Durante la
raccolta non parte alcun download. `Ho finito di inoltrare · N file` apre due
rami:

- `Finalizza con WebUI TaskFlow` scarica e pubblica nella gate, lasciando la
  creazione manuale alla WebUI;
- `Quick Workflow` chiede media kind, titolo/anno, candidato TMDB, preset e
  override prima di avviare i download.

Nel ramo Quick, dopo la pubblicazione il bot forza la riconciliazione
filesystem, legge i package ID generati da TaskFlow e soltanto allora esegue
Create e Start. L'ID workflow restituito viene mostrato nel bot.

I manifest JSON nello staging conservano ID messaggio Telegram, avanzamento,
bozza Quick Workflow e path posseduti. Dopo un riavvio i file completi non
vengono riscaricati e ripartono solo gli incompleti di una sessione già
configurata. Un file fallito può essere ritentato o escluso.

`Elimina intera sessione` cancella, dopo conferma, soltanto i path registrati.
I file pubblicati potrebbero essere già usati da TaskFlow: l'operatore deve
verificarlo prima della cancellazione.

Prima del download, il pannello della sessione in raccolta elenca tutti i file
nell'ordine di arrivo e mostra risoluzione Telegram esatta, durata, bitrate
medio stimato e dimensione. I metadati assenti sono indicati come non
disponibili e non bloccano la sessione. Questa lettura non scarica byte video.

Il pannello elenca inoltre file attivi, in coda, completi, falliti ed esclusi;
per i download attivi mostra byte, percentuale, velocità ed ETA. I log usano
`DEBUG`, `INFO`, `WARNING` ed `ERROR`; token, `api_id` e `api_hash` non vengono
stampati. Il servizio non estrae ancora 7z.
