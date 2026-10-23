"""English and Ukrainian for the German labels of the web UI's buttons, shown as their tooltips.

The page embeds this as JSON; app.js matches each button's label against it (exact labels first, then the
patterns for labels with a number or a name in them) and sets the tooltip text. Fixed strings only: nothing
here comes from a user or the dictionary.
"""

from __future__ import annotations

# German label -> (English, Ukrainian)
LABELS: dict[str, tuple[str, str]] = {
    "Wörter": ("words", "слова"),
    "Üben": ("practise", "вправи"),
    "Texte": ("texts", "тексти"),
    "Abmelden": ("log out", "вийти"),
    "Anmelden": ("log in", "увійти"),
    "Importieren": ("import", "імпортувати"),
    "Sätze bilden": ("make sentences", "складати речення"),
    "Abfrage": ("quiz", "опитування"),
    "Auswahl aufheben": ("clear the selection", "скасувати вибір"),
    "Aufheben": ("clear the selection", "скасувати вибір"),
    "10 schwächste": ("the 10 weakest", "10 найслабших"),
    "Letzte 20": ("the last 20", "останні 20"),
    "20 weitere laden": ("load 20 more", "завантажити ще 20"),
    "Mehr laden": ("load more", "завантажити ще"),
    "Suche schließen": ("close the search", "закрити пошук"),
    "Zu Wörtern hinzufügen": ("add to your words", "додати до слів"),
    "Schließen": ("close", "закрити"),
    "Speichern": ("save", "зберегти"),
    "Wort entfernen": ("remove the word", "видалити слово"),
    "Lernen": ("learn", "вивчати"),
    "Zu den Wörtern": ("to the words", "до слів"),
    "Aus Verlauf hinzufügen": ("add from the history", "додати з історії"),
    "Wörter auswählen": ("choose words", "вибрати слова"),
    "Wörter ändern": ("change the words", "змінити слова"),
    "Senden": ("send", "надіслати"),
    "Hinweis": ("hint", "підказка"),
    "Beenden": ("finish", "завершити"),
    "Fehler erklären": ("explain the mistakes", "пояснити помилки"),
    "Diese Regel üben": ("practise this rule", "тренувати це правило"),
    "Ergebnis ansehen": ("see the result", "переглянути результат"),
    "Noch eine Runde": ("one more round", "ще один раунд"),
    "Wort": ("word", "слово"),
    "Erstellt": ("created", "створено"),
    "Score": ("score", "бал"),
}

# (regular expression over the whole label, English, Ukrainian); $1 is the first group.
PATTERNS: list[tuple[str, str, str]] = [
    (r"Alle (\d+) laden", "load all $1", "завантажити всі $1"),
    (r"Weiter mit Aufgabe (\d+)", "go on to task $1", "далі до завдання $1"),
    (r"Abmelden \((.+)\)", "log out ($1)", "вийти ($1)"),
    (r"Doch richtig\?.*", "it is right after all?", "усе ж правильно?"),
    (r"(?:Sätze bilden|Abfrage) mit den 5 schwächsten", "with the 5 weakest words", "з 5 найслабшими словами"),
]


def glossary() -> dict:
    return {"labels": LABELS, "patterns": PATTERNS}
