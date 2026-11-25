# Configurazione

Copiare `config.example.yml` nel file non tracciato `config.yml`. Chiavi
mancanti o sconosciute bloccano l'avvio.

`telegram.api_id`, `api_hash` e `bot_token` autenticano la sessione Telethon.
`session_path` conserva la sessione MTProto tra i riavvii.
`progress_refresh_seconds` regola l'aggiornamento del pannello senza rallentare
il download. `max_concurrent_downloads` limita i trasferimenti simultanei.
`allowed_user_ids` contiene gli ID numerici degli operatori autorizzati; sono
accettate soltanto chat private.

Staging e gate devono essere assolute, distinte, non annidate e sullo stesso
filesystem. Solo la gate è osservata da TaskFlow. Estensioni video, riserva
disco, URL, timeout, ID utenti, path e livello log sono tutti nel config, mai
hardcoded nei sorgenti. L'estrazione 7z non è ancora implementata.

`taskflow.api_base_url` e `api_token` autorizzano il ramo Quick Workflow;
`filesystem_integration_code` indica quale integrazione riconciliare dopo la
pubblicazione. `tmdb.api_key` è la chiave usata direttamente dal bot per la
ricerca. Lingua, numero massimo di risultati, timeout e polling sono nel config.
`episode_patterns` normalizza i token delle serie, per esempio `1x10` in
`S01E10`, senza importare codice da TaskFlow.
