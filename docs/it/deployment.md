# Deployment

Il deploy privato usa due programmi Supervisor separati:

1. `telegram-bot-api`, server ufficiale avviato con `--local`;
2. `taskflow-telegram-importer`, avviato indicando la directory progetto.

Il Bot API locale usa `api_id` e `api_hash`; l'importer usa il token BotFather.
I tre valori restano in Vaultwarden e vengono letti con alias `rp-secret`
allowlisted distinti. Non vanno inseriti in repository, Supervisor, argomenti
CLI o log.

Prima del passaggio dal Bot API cloud al server locale chiamare una volta il
metodo ufficiale `logOut`. Il bot usa long polling: non servono webhook o porte
pubbliche.

Entrambi i servizi devono poter usare lo staging; l'importer deve poter
scrivere nella gate. Staging e gate devono condividere filesystem per il rename
atomico. Prima dell'accettazione finale provare sulla seedbox un file reale, un
set reale e un riavvio durante i trasferimenti.
