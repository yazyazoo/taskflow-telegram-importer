# Operazioni

Inoltrare al bot una locandina/caption facoltativa e uno o più video. Tutti i
download partono subito. `Ho finito di inoltrare · N file` chiude soltanto la
raccolta. L'operatore conferma o modifica titolo/anno; soltanto dopo il
completamento il set entra atomicamente nella gate filesystem di TaskFlow.

I manifest JSON nello staging conservano ID Telegram e path posseduti. Dopo un
riavvio i file completi non vengono riscaricati e ripartono solo gli
incompleti. Un file fallito può essere ritentato o escluso.

`Elimina intera sessione` cancella, dopo conferma, soltanto i path registrati.
L'importer non interroga TaskFlow: se i file pubblicati sono già stati usati da
un workflow, la cancellazione può rimuoverli e resta responsabilità
dell'operatore verificarlo.

I log usano `DEBUG`, `INFO`, `WARNING` ed `ERROR`; token, `api_id` e `api_hash`
non vengono mai stampati. La fase uno non estrae 7z e non crea workflow.
