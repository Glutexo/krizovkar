"""České texty pro chyby předávané operačním systémem."""

from __future__ import annotations

import errno


_SYSTEM_ERROR_MESSAGES = {
    errno.EBADF: "soubor není otevřený pro požadovanou operaci",
    errno.EEXIST: "soubor nebo adresář již existuje",
    errno.EIO: "vstupně-výstupní operace selhala",
    errno.EISDIR: "zadaná cesta je adresář",
    errno.EMFILE: "program má otevřeno příliš mnoho souborů",
    errno.ENAMETOOLONG: "název souboru je příliš dlouhý",
    errno.ENFILE: "systém má otevřeno příliš mnoho souborů",
    errno.ENOENT: "soubor nebo adresář neexistuje",
    errno.ENOSPC: "na cílovém zařízení není dostatek volného místa",
    errno.ENOTDIR: "část zadané cesty není adresář",
    errno.ENOTEMPTY: "adresář není prázdný",
    errno.EPERM: "operace není povolena",
    errno.EPIPE: "zápis byl předčasně ukončen",
    errno.EROFS: "souborový systém je pouze pro čtení",
}


def system_error_message(error: OSError) -> str:
    """Vrátí český popis systémové chyby bez závislosti na jazyku systému."""

    if isinstance(error, PermissionError):
        return "přístup byl odepřen"

    message = _SYSTEM_ERROR_MESSAGES.get(error.errno)
    if message is not None:
        return message
    if error.errno is not None:
        return f"operační systém ohlásil chybu s kódem {error.errno}"
    return "operační systém operaci odmítl"
