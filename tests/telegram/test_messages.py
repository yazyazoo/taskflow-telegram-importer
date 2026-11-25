from taskflow_telegram_importer.telegram.messages import operator_error_message


def test_known_operator_error_is_translated_to_italian() -> None:
    assert operator_error_message(
        ValueError("sealed session needs valid title and year")
    ) == "La sessione richiede un titolo e un anno validi."


def test_unknown_operator_error_keeps_the_reason() -> None:
    assert operator_error_message(
        ValueError("unexpected provider response")
    ) == "Operazione non riuscita: unexpected provider response"
