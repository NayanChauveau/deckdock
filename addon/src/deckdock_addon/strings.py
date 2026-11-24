"""Interface copy. French when Anki is in French, English otherwise."""

from __future__ import annotations

from deckdock_addon.store import Subscription

FR: dict[str, str] = {
    "MENU": "DeckDock",
    "WINDOW_TITLE": "DeckDock",
    "COLUMN_DECK": "Deck",
    "COLUMN_EDITION": "Édition",
    "COLUMN_VERSION": "Version",
    "COLUMN_STATUS": "État",
    "ADD": "Ajouter",
    "CHECK": "Vérifier",
    "APPLY": "Appliquer",
    "OPEN_SOURCE": "Ouvrir la source",
    "REMOVE": "Retirer",
    "CANCEL": "Annuler",
    "LATER": "Plus tard",
    "OK": "OK",
    "CONFIRM_APPLY": "Confirmer et appliquer",
    "CONTINUE": "Continuer",
    "ADD_TITLE": "Ajouter un deck",
    "ADD_HELP": (
        "Collez l'URL d'un dépôt GitHub (https://github.com/propriétaire/dépôt) "
        "ou l'URL de base HTTPS d'une édition (elle se termine par /)."
    ),
    "ADD_PLACEHOLDER": "https://github.com/propriétaire/dépôt",
    "PICK_EDITION": "Choisissez l'édition à suivre :",
    "EDITION_ITEM": "{name} ({edition}) · {language} · {version}",
    "NO_EDITIONS": "Ce dépôt ne propose aucune édition.",
    "EMPTY": "Aucun deck suivi.",
    "NO_PROFILE": "Ouvrez un profil Anki pour utiliser DeckDock.",
    "NO_SELECTION": "Sélectionnez un deck.",
    "NOTHING_TO_APPLY": "Aucune mise à jour à appliquer.",
    "CATALOG_ERROR": (
        "Les abonnements enregistrés dans cette collection sont illisibles. "
        "DeckDock n'y touche pas."
    ),
    "DUPLICATE": "Ce deck est déjà suivi dans cette édition.",
    "CONFLICTING_EDITION": (
        "Une autre édition de ce deck est déjà suivie. Un deck ne peut être suivi "
        "que dans une seule édition à la fois (un GUID est unique dans une "
        "collection). Retirez l'abonnement existant, puis ajoutez celui-ci pour le "
        "remplacer."
    ),
    "REMOVE_ONE": "Retirer le suivi de « {name} » ? Le deck reste dans Anki.",
    "REMOVE_MANY": "Retirer le suivi de ces decks ? Les decks restent dans Anki.",
    "STATUS_NOT_INSTALLED": "Pas encore installé",
    "STATUS_UP_TO_DATE": "À jour",
    "STATUS_UPDATE_AVAILABLE": "Mise à jour disponible",
    "SUMMARY_TITLE": "Mise à jour de decks",
    "SUMMARY_TITLE_INSTALL": "Installation d'un deck",
    "SKIPPED_TOGGLE": "Notes ignorées ({count})",
    "OPEN_IN_BROWSER": "Ouvrir dans le navigateur",
    "CLEARS_UNDO": (
        "L'historique d'annulation d'Anki sera effacé par cette mise à jour."
    ),
    "UPDATED": "{name} : mise à jour appliquée.",
    "CHANGED_SINCE_SUMMARY": (
        "Le deck a changé depuis le résumé : rien n'a été appliqué. "
        "Relancez la mise à jour pour voir le nouveau résumé."
    ),
    "ERROR": "Erreur",
    "ERROR_DETAIL": "Erreur : {detail}",
    "ERR_invalid_url": "Adresse refusée (HTTPS requis, dépôt GitHub ou base finissant par /)",
    "ERR_https_required": "Adresse refusée (HTTPS requis)",
    "ERR_redirect_rejected": "Redirection refusée",
    "ERR_http_error": "Hors ligne ou erreur réseau",
    "ERR_too_large": "Fichier trop volumineux",
    "ERR_not_found": "Introuvable (404)",
    "ERR_invalid_json": "Fichier JSON invalide",
    "ERR_invalid_deck": "deck.json invalide",
    "ERR_sha_mismatch": "Média corrompu (empreinte différente)",
    "ERR_cancelled": "Annulé",
    "ERR_deck_name_conflict": (
        "Un deck filtré porte déjà le nom d'un deck à créer. Renommez-le puis "
        "relancez la mise à jour. Rien n'a été modifié."
    ),
    "ERR_collection_changed": (
        "La collection a changé pendant la préparation (note ou type de note "
        "disparu). Rien n'a été modifié : vérifiez à nouveau."
    ),
    "ERR_partial_apply": (
        "La mise à jour a été appliquée en partie et n'a pas pu être annulée. "
        "Relancez Vérifier puis Appliquer pour la terminer."
    ),
    "SKIP_modified_locally": "modifiée par toi",
    "SKIP_deleted_locally": "supprimée par toi",
    "SKIP_foreign_note": "déjà présente ailleurs",
    "SKIP_no_base_conflict": "différente d'une note déjà présente",
    "UNDO_LABEL": "DeckDock : mise à jour de {name}",
}

EN: dict[str, str] = {
    "MENU": "DeckDock",
    "WINDOW_TITLE": "DeckDock",
    "COLUMN_DECK": "Deck",
    "COLUMN_EDITION": "Edition",
    "COLUMN_VERSION": "Version",
    "COLUMN_STATUS": "Status",
    "ADD": "Add",
    "CHECK": "Check",
    "APPLY": "Apply",
    "OPEN_SOURCE": "Open source",
    "REMOVE": "Remove",
    "CANCEL": "Cancel",
    "LATER": "Later",
    "OK": "OK",
    "CONFIRM_APPLY": "Confirm and apply",
    "CONTINUE": "Continue",
    "ADD_TITLE": "Add a deck",
    "ADD_HELP": (
        "Paste a GitHub repository URL (https://github.com/owner/repo) or the "
        "HTTPS base URL of an edition (it ends with /)."
    ),
    "ADD_PLACEHOLDER": "https://github.com/owner/repo",
    "PICK_EDITION": "Choose the edition to follow:",
    "EDITION_ITEM": "{name} ({edition}) · {language} · {version}",
    "NO_EDITIONS": "This repository offers no edition.",
    "EMPTY": "No deck followed.",
    "NO_PROFILE": "Open an Anki profile to use DeckDock.",
    "NO_SELECTION": "Select a deck.",
    "NOTHING_TO_APPLY": "No update to apply.",
    "CATALOG_ERROR": (
        "The subscriptions stored in this collection are unreadable. "
        "DeckDock leaves them untouched."
    ),
    "DUPLICATE": "This deck is already followed in this edition.",
    "CONFLICTING_EDITION": (
        "Another edition of this deck is already followed. A deck can only be "
        "followed in one edition at a time (a GUID is unique in a collection). "
        "Remove the existing subscription, then add this one to replace it."
    ),
    "REMOVE_ONE": 'Stop following "{name}"? The deck stays in Anki.',
    "REMOVE_MANY": "Stop following these decks? The decks stay in Anki.",
    "STATUS_NOT_INSTALLED": "Not installed",
    "STATUS_UP_TO_DATE": "Up to date",
    "STATUS_UPDATE_AVAILABLE": "Update available",
    "SUMMARY_TITLE": "Deck updates",
    "SUMMARY_TITLE_INSTALL": "Deck installation",
    "SKIPPED_TOGGLE": "Skipped notes ({count})",
    "OPEN_IN_BROWSER": "Open in browser",
    "CLEARS_UNDO": ("Anki's Undo history will be cleared by this update."),
    "UPDATED": "{name}: update applied.",
    "CHANGED_SINCE_SUMMARY": (
        "The deck changed since the summary: nothing was applied. "
        "Run the update again to see the new summary."
    ),
    "ERROR": "Error",
    "ERROR_DETAIL": "Error: {detail}",
    "ERR_invalid_url": "Address refused (HTTPS required, GitHub repository or base ending with /)",
    "ERR_https_required": "Address refused (HTTPS required)",
    "ERR_redirect_rejected": "Redirect refused",
    "ERR_http_error": "Offline or network error",
    "ERR_too_large": "File too large",
    "ERR_not_found": "Not found (404)",
    "ERR_invalid_json": "Invalid JSON file",
    "ERR_invalid_deck": "Invalid deck.json",
    "ERR_sha_mismatch": "Corrupted media (checksum mismatch)",
    "ERR_cancelled": "Cancelled",
    "ERR_deck_name_conflict": (
        "A filtered deck already has the name of a deck to create. Rename it, "
        "then run the update again. Nothing was changed."
    ),
    "ERR_collection_changed": (
        "The collection changed while preparing (a note or note type "
        "disappeared). Nothing was changed: check again."
    ),
    "ERR_partial_apply": (
        "The update was partially applied and could not be undone. "
        "Run Check then Apply again to finish it."
    ),
    "SKIP_modified_locally": "modified by you",
    "SKIP_deleted_locally": "deleted by you",
    "SKIP_foreign_note": "already present elsewhere",
    "SKIP_no_base_conflict": "different from an existing note",
    "UNDO_LABEL": "DeckDock: update {name}",
}


def language() -> str:
    """ "fr" when Anki's language starts with fr, "en" otherwise.

    Outside Anki, or before Anki has chosen a language (tests), the copy is French.
    """
    try:
        from anki import lang
    except ImportError:
        return "fr"
    if lang.current_i18n is None:
        return "fr"
    return "fr" if lang.current_lang.lower().startswith("fr") else "en"


def text(key: str, lang: str | None = None) -> str:
    return (FR if (lang or language()) == "fr" else EN)[key]


def __getattr__(name: str) -> str:
    if name not in FR:
        raise AttributeError(name)
    return text(name)


def error_text(code: str | None, lang: str | None = None) -> str:
    key = f"ERR_{code}"
    return text(key if key in FR else "ERROR", lang)


def skip_text(reason: str) -> str:
    key = f"SKIP_{reason}"
    return text(key if key in FR else "ERROR")


def version_text(sub: Subscription) -> str:
    if sub.installed_version and sub.available_version:
        if sub.installed_version == sub.available_version:
            return sub.installed_version
        return f"{sub.installed_version} → {sub.available_version}"
    return sub.installed_version or sub.available_version or "—"


def has_update(sub: Subscription) -> bool:
    """An installed subscription whose server version differs (versions are opaque)."""
    return (
        sub.installed_version is not None
        and sub.available_version is not None
        and sub.available_version != sub.installed_version
    )


def status_text(sub: Subscription) -> str:
    if sub.last_error:
        return error_text(sub.last_error)
    if sub.installed_version is None:
        return text("STATUS_NOT_INSTALLED")
    if has_update(sub):
        return text("STATUS_UPDATE_AVAILABLE")
    return text("STATUS_UP_TO_DATE")


def undo_label(name: str) -> str:
    return text("UNDO_LABEL").format(name=name)


def removal_message(names: list[str]) -> str:
    if len(names) == 1:
        return text("REMOVE_ONE").format(name=names[0])
    return text("REMOVE_MANY")
