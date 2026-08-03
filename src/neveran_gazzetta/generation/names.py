from __future__ import annotations

import hashlib
import re

_MODERN_GIVEN_NAMES = frozenset(
    {
        "alessia",
        "andrea",
        "anna",
        "chiara",
        "davide",
        "elena",
        "elda",
        "fabio",
        "federico",
        "francesca",
        "francesco",
        "giulia",
        "giuseppe",
        "lara",
        "laura",
        "lina",
        "lorenzo",
        "livia",
        "luca",
        "marco",
        "maria",
        "mario",
        "mara",
        "marta",
        "martina",
        "matteo",
        "michele",
        "paolo",
        "pietro",
        "orfeo",
        "roberto",
        "sara",
        "silvia",
        "simone",
        "sofia",
        "stefano",
        "tomas",
        "timo",
        "valentina",
    }
)
_NEVERAN_GIVEN_NAMES = (
    "Aevra",
    "Caelis",
    "Deyr",
    "Ilyen",
    "Kelra",
    "Maev",
    "Neris",
    "Oryn",
    "Sael",
    "Tivar",
    "Vaeris",
    "Zeyra",
)
_NEVERAN_FAMILY_NAMES = (
    "Cartis",
    "Draik",
    "Korr",
    "Morn",
    "Neral",
    "Revas",
    "Saar",
    "Vael",
    "Velis",
    "Veyr",
    "Vhal",
    "Vos",
)
_ROLE_PREFIX = re.compile(
    r"^(?:capo|consigliere|consigliera|dottore|dottoressa|maestro|maestra|"
    r"professore|professoressa|signor|signora)\s+(?:della?\s+|del\s+)?",
    re.IGNORECASE,
)


def _stable_neveran_name(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    given = _NEVERAN_GIVEN_NAMES[digest[0] % len(_NEVERAN_GIVEN_NAMES)]
    family = _NEVERAN_FAMILY_NAMES[digest[1] % len(_NEVERAN_FAMILY_NAMES)]
    return f"{given} {family}"


def normalize_invented_person_name(value: str, *, seed: str) -> tuple[str, str | None]:
    """Separa il ruolo e sostituisce soltanto identità contemporanee inventate."""

    compact = " ".join(value.split())
    identity = compact.split(",", 1)[0].strip()
    identity = _ROLE_PREFIX.sub("", identity).strip() or identity
    first_token = (
        identity.split(maxsplit=1)[0]
        .casefold()
        .strip(".'\N{RIGHT SINGLE QUOTATION MARK}-")
    )
    if first_token not in _MODERN_GIVEN_NAMES:
        return identity, None
    replacement = _stable_neveran_name(seed)
    return replacement, identity


def replace_person_names(text: str, replacements: dict[str, str]) -> str:
    result = text
    for original in sorted(replacements, key=len, reverse=True):
        result = re.sub(re.escape(original), replacements[original], result, flags=re.IGNORECASE)
    return result


def select_newsroom_bylines(
    issue_number: int,
    names: tuple[str, ...],
    per_edition: int,
) -> tuple[str, ...]:
    start = ((issue_number - 1) * 2) % len(names)
    return tuple(names[(start + offset) % len(names)] for offset in range(per_edition))
