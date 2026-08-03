import pytest

from neveran_gazzetta.generation.names import (
    normalize_invented_person_name,
    replace_person_names,
    select_newsroom_bylines,
)


@pytest.mark.parametrize("modern_name", ["Pietro Lume", "Mara Lenti", "Luca Bianchi"])
def test_nome_contemporaneo_inventato_diventa_stabilmente_neveran(
    modern_name: str,
) -> None:
    first = normalize_invented_person_name(
        f"{modern_name}, proprietario",
        seed="issue-1:minor-1:0",
    )
    second = normalize_invented_person_name(
        f"{modern_name}, proprietario",
        seed="issue-1:minor-1:0",
    )

    assert first == second
    assert first[0] != modern_name
    assert first[1] == modern_name
    assert "," not in first[0]


def test_nome_neveran_rimane_intatto_ma_senza_ruolo() -> None:
    assert normalize_invented_person_name(
        "Consigliere Arin Vost",
        seed="issue-1:major-1:0",
    ) == ("Arin Vost", None)


def test_sostituzione_allinea_il_testo_dellevento() -> None:
    text = replace_person_names(
        "Pietro Lume apre la bottega di Pietro Lume.",
        {"Pietro Lume": "Neris Vhal"},
    )

    assert text == "Neris Vhal apre la bottega di Neris Vhal."


def test_redazione_ruota_due_firme_e_ne_conserva_una() -> None:
    names = ("Uno", "Due", "Tre", "Quattro", "Cinque", "Sei", "Sette")

    first = set(select_newsroom_bylines(1, names, 3))
    second = set(select_newsroom_bylines(2, names, 3))

    assert first == {"Uno", "Due", "Tre"}
    assert second == {"Tre", "Quattro", "Cinque"}
