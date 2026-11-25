# Deployment

Il deploy privato usa un programma Supervisor:

1. `taskflow-telegram-importer`, avviato indicando la directory progetto.

Telethon usa `api_id`, `api_hash` e token BotFather dal `config.yml` non
tracciato. Il file sessione MTProto deve essere persistente. Non servono
webhook, porte pubbliche o un secondo servizio Telegram.

L'importer deve poter usare staging, sessione MTProto e gate. Staging e gate
devono condividere filesystem per il rename
atomico. Prima dell'accettazione finale provare sulla seedbox un file reale, un
set reale e un riavvio durante i trasferimenti.
