from __future__ import annotations


_OPERATOR_ERRORS = {
    "operator has no collecting session": "Non esiste una sessione in raccolta.",
    "cannot finish an empty session": "Non è possibile chiudere una sessione senza file.",
    "title and four-digit year are required": "Sono richiesti un titolo e un anno di quattro cifre.",
    "title and year must be supplied together": "Titolo e anno devono essere inseriti insieme.",
    "sealed session needs valid title and year": "La sessione richiede un titolo e un anno validi.",
    "collecting session belongs to another chat": "La sessione in raccolta appartiene a un'altra chat.",
    "session belongs to another operator": "La sessione appartiene a un altro operatore.",
    "stale finish action": "Questo pulsante non è più valido.",
}


def operator_error_message(error: Exception) -> str:
    reason = str(error)
    return _OPERATOR_ERRORS.get(reason, f"Operazione non riuscita: {reason}")
