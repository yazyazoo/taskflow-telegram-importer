# Configurazione

Copiare `config.example.yml` nel file non tracciato `config.yml`. Chiavi
mancanti o sconosciute bloccano l'avvio.

`telegram.api_base_url` termina con `/bot`; `local_mode` resta attivo affinché
`getFile` restituisca un path locale assoluto. Il timeout è la durata massima
del long polling, non un ritardo: un update nuovo arriva subito.
`allowed_user_ids` contiene gli ID numerici degli operatori autorizzati; sono
accettate soltanto chat private.

Il token BotFather viene letto da Vaultwarden eseguendo direttamente, senza
shell:

```text
<token_command.executable> <token_command.alias> <token_command.field>
```

Staging e gate devono essere assolute, distinte, non annidate e sullo stesso
filesystem. Solo la gate è osservata da TaskFlow. Estensioni video, riserva
disco, URL, timeout, ID utenti, path e livello log sono tutti nel config, mai
hardcoded nei sorgenti. La fase uno non ha impostazioni 7z.
