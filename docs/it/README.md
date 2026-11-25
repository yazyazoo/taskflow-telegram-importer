# TaskFlow Telegram Importer

Importatore privato da Telegram al filesystem usato da TaskFlow.

Il servizio riceve video inoltrati direttamente tramite Telethon/MTProto,
mantiene sessioni persistenti e pubblica nella gate dell'integrazione
filesystem soltanto file completi. Non chiama le API TaskFlow e non crea
workflow.

La prima implementazione include autorizzazione privata, sessioni persistenti,
download concorrenti, recovery, pubblicazione atomica e azioni operatore.
La validazione finale con file Telegram reali sulla seedbox è
ancora necessaria.

- [Configurazione](configurazione.md)
- [Deployment](deployment.md)
- [Operazioni](operazioni.md)

