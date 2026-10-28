"""Tooltip texts for Üben: what a task's form means (with the word's own forms) and why a correction is right.

Plain text with line breaks only (dis-system's tooltip shows text, one line per line); a "table" is one line per
row. All of it comes from the dictionary and the fixed texts below, never from what the learner typed.
"""

from __future__ import annotations

from wort.dictionary import grammar as g
from wort.dictionary.lookup import Dictionary, Entry

PERSONS = ("ich", "du", "er", "wir", "ihr", "sie")
PERSON_LABEL = {"er": "er/sie/es", "sie": "sie/Sie"}

# What each task asks for, in one line, and one example sentence.
TASK_HELP = {
    "Präsens": ("Präsens: jetzt oder regelmäßig.", "Ich arbeite jeden Tag."),
    "Präteritum": ("Präteritum: Vergangenheit, vor allem geschrieben.", "Gestern arbeitete ich lange."),
    "Perfekt": ("Perfekt: Vergangenheit, vor allem gesprochen; haben/sein + Partizip II.",
                "Ich habe gestern lange gearbeitet."),
    "Plural": ("Plural: mehr als eins.", "Die Häuser in meiner Straße sind alt."),
    "Dativ Plural": ("Dativ Plural: nach mit, von, bei, zu, aus …; das Nomen bekommt meist -n.",
                     "Ich spreche oft mit den Kindern."),
    "Akkusativ Singular": ("Akkusativ: das direkte Objekt (wen oder was?).", "Ich sehe den Hund im Garten."),
    "Komparativ": ("Komparativ: zwei Dinge vergleichen, -er + als.", "Mein Rad ist schneller als deins."),
    "Superlativ": ("Superlativ: am meisten, am …-sten.", "Dieses Rad ist am schnellsten."),
}


def _verb_rows(entry: Entry, tense: str) -> list[str]:
    make = {"Präsens": g.present, "Präteritum": g.preterite, "Perfekt": g.perfect}[tense]
    rows = []
    for p in PERSONS:
        if form := make(entry, p):
            rows.append(f"{PERSON_LABEL.get(p, p)} {form}")
    return rows


def _noun_rows(entry: Entry) -> list[str]:
    rows = []
    for case in ("nominative", "accusative", "dative"):
        sg, pl = g.noun_form(entry, case, "singular"), g.noun_form(entry, case, "plural")
        cells = [g.with_article(entry, f, case, n) for f, n in ((sg, "singular"), (pl, "plural")) if f]
        if cells:
            rows.append(f"{g.CASE_LABELS[case]}. " + " — ".join(cells))
    return rows


def _adj_rows(entry: Entry) -> list[str]:
    parts = [entry.lemma, g.comparative(entry), g.superlative(entry)]
    return [" — ".join(p for p in parts if p)] if any(parts[1:]) else []


def word_table(entry: Entry, tense: str = "Präsens") -> list[str]:
    """The word's own forms as rows: a verb in `tense` by person, a noun by case, an adjective's degrees."""
    if entry.pos == "verb":
        return _verb_rows(entry, tense if tense in ("Präsens", "Präteritum", "Perfekt") else "Präsens")
    if entry.pos == "noun":
        return _noun_rows(entry)
    if entry.pos == "adj":
        return _adj_rows(entry)
    return []


def task_hint(entry: Entry, task: str, required: list[str]) -> str:
    """Tooltip for "Schreibe einen Satz mit «X»: <task>": the asked form, what it means, an example, the word's
    forms for that task."""
    kind = task.split(",")[0].strip()
    lines = [f"Gesucht: {' '.join(required)}"] if required else []
    if kind in TASK_HELP:
        meaning, example = TASK_HELP[kind]
        lines += [meaning, f"Beispiel: {example}"]
    table = word_table(entry, kind)
    if table:
        lines += ["", f"«{entry.lemma}»:", *table]
    return "\n".join(lines)


# Ukrainian, in brackets after LanguageTool's German message: by rule id (prefix), else by category.
RULE_UK = {
    "DE_VERBAGREEMENT": "підмет і дієслово не узгоджені за особою чи числом",
    "DE_SUBJECT_VERB_AGREEMENT": "підмет і дієслово не узгоджені за особою чи числом",
    "DE_AGREEMENT": "іменник і слова при ньому (артикль, прикметник) не узгоджені за родом, числом або відмінком",
    "DE_CASE": "велика чи мала літера",
    "GERMAN_SPELLER_RULE": "можлива друкарська помилка: такого слова немає",
    "UPPERCASE_SENTENCE_START": "речення починається з великої літери",
    "GERMAN_WORD_REPEAT_RULE": "одне слово стоїть двічі поспіль",
    "FLEKTIERTES_ADJEKTIV": "після sein прикметник стоїть без закінчення",
    "DE_PREPOSITION_CASE": "прийменник вимагає іншого відмінка",
    "PRAEP_": "прийменник вимагає іншого відмінка",
    "DE_COMMA": "кома",
    "KOMMA_": "кома",
}
CATEGORY_UK = {
    "GRAMMAR": "граматична помилка",
    "TYPOS": "друкарська помилка",
    "CASING": "велика чи мала літера",
    "PUNCTUATION": "розділові знаки",
    "REDUNDANCY": "зайве або повторене слово",
    "STYLE": "стиль",
    "CONFUSED_WORDS": "схожі слова, які легко сплутати",
    "COMPOUNDING": "разом чи окремо",
    "TYPOGRAPHY": "типографіка (лапки, тире, пробіли)",
    "COLLOCATIONS": "незвичне поєднання слів",
}


def rule_uk(rule: str, category: str) -> str:
    """A short Ukrainian gloss of a LanguageTool rule; "" when neither the rule nor its category is known."""
    for prefix, text in RULE_UK.items():
        if rule.startswith(prefix):
            return text
    return CATEGORY_UK.get(category, "")


def correction_table(dic: Dictionary | None, replacement: str, translate=None) -> list[str]:
    """Rows of forms for the first word of a correction that the dictionary knows as a verb or a noun, under its
    lemma and, from `translate(entry)`, the lemma's translation in brackets."""
    if dic is None:
        return []
    for word in replacement.split():
        for entry in dic.lookup_german(word, limit=1):
            if entry.pos in ("verb", "noun") and (rows := word_table(entry)):  # degrees don't explain an ending
                meaning = translate(entry) if translate else ""
                return [f"«{entry.lemma}»" + (f" ({meaning})" if meaning else "") + ":", *rows]
    return []


# --- "Fehler erklärt": one mistake explained locally (no AI) -------------------------------------------------

GENDERS = (("m", "maskulin"), ("f", "feminin"), ("n", "neutrum"))
CASE_ROWS = (("nominative", "Nom."), ("accusative", "Akk."), ("dative", "Dat."), ("genitive", "Gen."))
INDEFINITE = {
    "m": {"nominative": "ein", "accusative": "einen", "dative": "einem", "genitive": "eines"},
    "f": {"nominative": "eine", "accusative": "eine", "dative": "einer", "genitive": "einer"},
    "n": {"nominative": "ein", "accusative": "ein", "dative": "einem", "genitive": "eines"},
}
# Adjective endings after a definite article (weak) and after ein/kein/mein (mixed), by case and gender.
ADJ_WEAK = {"nominative": ("e", "e", "e"), "accusative": ("en", "e", "e"), "dative": ("en", "en", "en"),
            "genitive": ("en", "en", "en")}
ADJ_MIXED = {"nominative": ("er", "e", "es"), "accusative": ("en", "e", "es"), "dative": ("en", "en", "en"),
             "genitive": ("en", "en", "en")}
DEFINITE_WORDS = {"der", "die", "das", "den", "dem", "des"}
INDEFINITE_WORDS = {f"{p}{e}" for p in ("ein", "kein", "mein", "dein", "sein", "ihr", "unser", "euer")
                    for e in ("", "e", "en", "em", "er", "es")}

MERKE = {
    "verb": ("Das Verb richtet sich nach dem Subjekt: ich gehe, du gehst, er geht, wir gehen, ihr geht, sie gehen.",
             "Дієслово узгоджується з підметом за особою і числом: ich gehe, du gehst, er geht, wir gehen."),
    "article": ("Der Artikel richtet sich nach Genus, Numerus und Kasus des Nomens. Im Akkusativ ändert sich nur das "
                "Maskulinum: der → den, ein → einen, kein → keinen, mein → meinen.",
                "Артикль залежить від роду, числа й відмінка іменника. У знахідному (Akkusativ) змінюється лише "
                "чоловічий рід: der → den, ein → einen."),
    "adjective": ("Nach der/die/das endet das Adjektiv meist auf -e oder -en. Nach ein/kein/mein zeigt das Adjektiv "
                  "das Genus, wo der Artikel es nicht zeigt: ein schöner Tag, ein schönes Haus.",
                  "Після der/die/das прикметник закінчується на -e або -en. Після ein/kein/mein закінчення "
                  "прикметника показує рід: ein schöner Tag (ч. р.), ein schönes Haus (с. р.)."),
    "spelling": ("Dieses Wort gibt es so nicht. Prüfe die Schreibweise; das richtige Wort steht oben.",
                 "Такого слова немає. Перевір написання; правильне слово стоїть вище."),
    "casing": ("Ein Satz beginnt mit einem großen Buchstaben, und Nomen schreibt man im Deutschen immer groß.",
               "Речення починається з великої літери, а іменники в німецькій завжди пишуться з великої."),
    "predicative": ("Nach sein, werden und bleiben steht das Adjektiv ohne Endung: Das Haus ist schön (nicht: schöne).",
                    "Після sein, werden, bleiben прикметник стоїть без закінчення: Das Haus ist schön (не schöne)."),
    "form": ("Das Wort passt, aber hier braucht der Satz eine andere Form davon (Endung, Person oder Kasus).",
             "Слово правильне, але тут потрібна інша його форма (закінчення, особа чи відмінок)."),
    "repeat": ("Ein Wort steht zweimal hintereinander. Lösche eines davon.",
               "Одне слово стоїть двічі поспіль. Видали одне з них."),
}
TITLES = {"verb": "Regel: Verb und Subjekt", "article": "Regel: Artikel", "adjective": "Regel: Adjektivendung",
          "spelling": "Rechtschreibung", "casing": "Groß- und Kleinschreibung", "repeat": "Wiederholung",
          "predicative": "Regel: Adjektiv nach sein", "form": "Andere Form"}


def _kind(rule: str, category: str, fragment: str, right: str) -> str:
    if rule.startswith(("DE_VERBAGREEMENT", "DE_SUBJECT_VERB_AGREEMENT")):
        return "verb"
    if rule.startswith(("FLEKTIERTES_ADJEKTIV", "PRAEDIKATIV")):
        return "predicative"
    if rule.startswith("GERMAN_SPELLER_RULE"):
        return "spelling"
    if rule.startswith("GERMAN_WORD_REPEAT_RULE"):
        return "repeat"
    if rule.startswith(("UPPERCASE_SENTENCE_START", "DE_CASE")) or category == "CASING":
        return "casing"
    if rule.startswith("DE_AGREEMENT") or category in ("GRAMMAR", "TYPOS"):
        changed = [(a, b) for a, b in zip(fragment.split(), right.split()) if a.lower() != b.lower()]
        if changed and changed[0][1].lower() in DEFINITE_WORDS | INDEFINITE_WORDS:
            return "article"
        if changed and rule.startswith("DE_AGREEMENT"):
            return "adjective"
        if changed:
            return "form"
    return ""


def _noun_gender(dic: Dictionary | None, words: list[str]) -> str:
    if dic is None:
        return ""
    for w in reversed(words):
        if w[:1].isupper():
            for e in dic.lookup_german(w, limit=1):
                if e.pos == "noun" and e.gender in ("m", "f", "n"):
                    return e.gender
    return ""


def _article_table(right_words: list[str], gender: str) -> dict:
    indefinite = any(w.lower() in INDEFINITE_WORDS for w in right_words)
    source = INDEFINITE if indefinite else {g_: {c: g.ARTICLES[g_][c] for c, _ in CASE_ROWS} for g_, _ in GENDERS}
    art = next((w.lower() for w in right_words if w.lower() in DEFINITE_WORDS | INDEFINITE_WORDS), "")
    rows, hl = [], None
    for r, (case, label) in enumerate(CASE_ROWS):
        rows.append([label] + [source[g_][case] for g_, _ in GENDERS])
        for c, (g_, _) in enumerate(GENDERS, 1):
            if hl is None and art and source[g_][case] == art and (not gender or g_ == gender):
                hl = (r, c)
    title = "Regel: " + ("unbestimmter Artikel" if indefinite else "bestimmter Artikel")
    return {"title": title, "headers": ["Kasus"] + [n for _, n in GENDERS], "rows": rows, "hl": hl}


def _adjective_table(right_words: list[str], gender: str) -> dict:
    mixed = any(w.lower() in INDEFINITE_WORDS for w in right_words)
    source = ADJ_MIXED if mixed else ADJ_WEAK
    adj = next((w for w in right_words if w[:1].islower() and w.lower() not in DEFINITE_WORDS | INDEFINITE_WORDS), "")
    rows, hl = [], None
    for r, (case, label) in enumerate(CASE_ROWS):
        endings = source[case]
        rows.append([label] + ["-" + e for e in endings])
        for c, (g_, _) in enumerate(GENDERS, 1):
            if hl is None and adj and (not gender or g_ == gender) and adj.endswith(endings[c - 1]):
                hl = (r, c)
    title = "Regel: Adjektivendung nach " + ("ein/kein/mein" if mixed else "der/die/das")
    return {"title": title, "headers": ["Kasus"] + [n for _, n in GENDERS], "rows": rows, "hl": hl}


def _verb_table(dic: Dictionary | None, right_words: list[str]) -> dict | None:
    if dic is None:
        return None
    for w in right_words:
        for e in dic.lookup_german(w, limit=1):
            if e.pos == "verb":
                rows, hl = [], None
                for r, p in enumerate(PERSONS):
                    form = g.present(e, p) or ""
                    rows.append([PERSON_LABEL.get(p, p), form])
                    if hl is None and form and form.lower() == w.lower():
                        hl = (r, 1)
                return {"title": f"Präsens: {e.lemma}", "headers": ["Person", "Form"], "rows": rows, "hl": hl}
    return None


def explain(remark: dict, dic: Dictionary | None, translate=None) -> dict:
    """The local "Fehler erklärt" pane for one checker remark: caption, why, a rule table with the right cell
    marked, Merke (German) and Українською. Only dictionary data and the fixed texts above."""
    fragment = remark.get("fragment", "")
    right = (remark.get("replacements") or [""])[0]
    rule, category = remark.get("rule") or "", remark.get("category") or ""
    kind = _kind(rule, category, fragment, right)
    words = right.split()
    gender = _noun_gender(dic, words) if kind in ("article", "adjective") else ""
    table = None
    if kind == "article":
        table = _article_table(words, gender)
    elif kind == "adjective":
        table = _adjective_table(words, gender)
    elif kind == "verb":
        table = _verb_table(dic, words)
    elif kind == "spelling" and (rows := correction_table(dic, right, translate)):
        table = {"title": rows[0].rstrip(":"), "headers": [], "rows": [[r] for r in rows[1:]], "hl": None}
    caption = " · ".join(p for p in (TITLES.get(kind, "").removeprefix("Regel: "),
                                      dict(GENDERS).get(gender, "")) if p) or CATEGORY_UK.get(category, "")
    merke, uk = MERKE.get(kind, ("", ""))
    uk_rule = rule_uk(rule, category)
    return {"kind": kind, "caption": caption, "why": remark.get("message", ""), "right": right, "fragment": fragment,
            "table": table, "merke": merke, "uk": " ".join(p for p in (uk_rule.capitalize() + "." if uk_rule else "", uk) if p)}


# --- "Beispielantwort": the asked word in the asked form ------------------------------------------------------

SUBJECT = {"ich": "Ich", "du": "Du", "er/sie/es": "Er", "wir": "Wir"}


def _subject(task: str) -> str:
    person = task.split(",", 1)[1].strip() if "," in task else ""
    return SUBJECT.get(person, "")


def example_tooltip(entry: Entry, task: str, required: list[str], translate=None, word_uk: str = "",
                    word_en: str = "") -> str:
    """The "Beispielantwort" tooltip: the example, then its English and Ukrainian translation with the same tense,
    person and case (translate(text, "en"|"uk"), the offline model). A dictionary sentence keeps its own English.
    Without a model, the word's translations, marked as such."""
    de, dictionary_en = example_with_translation(entry, task, required)
    en = dictionary_en or (translate(de, "en") if translate else "")
    uk = translate(de, "uk") if translate else ""
    lines = [de,
             f"EN: {en}" if en else (f"EN (Wort): {entry.lemma} — {word_en}" if word_en else ""),
             f"UK: {uk}" if uk else (f"UK (Wort): {entry.lemma} — {word_uk}" if word_uk else "")]
    return "\n".join(line for line in lines if line)


def example_answer(entry: Entry, task: str, required: list[str]) -> str:
    """An example with the word in exactly the asked form: a dictionary sentence that has it, else the start of
    a sentence built around it ("Wir begleiten …"). Never a sentence without the form."""
    return example_with_translation(entry, task, required)[0]


def example_with_translation(entry: Entry, task: str, required: list[str]) -> tuple[str, str]:
    """(example, its English translation or "" for a built one)."""
    from wort.exercises.sentence import _tokens
    from wort.text import normalize
    wanted = [normalize(w) for w in required]
    kind, subj = task.split(",")[0].strip(), _subject(task)
    # The person's pronoun too, for a verb task: "gehen" alone may be an infinitive, not "wir gehen".
    pronouns = {"Ich": {"ich"}, "Du": {"du"}, "Er": {"er", "sie", "es", "man"}, "Wir": {"wir"}}.get(subj, set())
    for de, en in entry.examples:
        tokens = _tokens(de)
        if wanted and all(w in tokens for w in wanted) and (not pronouns or pronouns & set(tokens)):
            return de, en or ""
    form = " ".join(required)
    head, *rest = required or [entry.lemma]
    tail = (" " + " ".join(rest)) if rest else ""  # a separable verb's particle goes to the end
    end = f" …{tail}." if tail else " …"
    if kind == "Präsens" and subj:
        return f"{subj} {head}{end}", ""
    if kind == "Präteritum" and subj:
        return f"Gestern {head} {subj.lower()}{end}", ""
    if kind == "Perfekt" and subj and len(required) == 2:
        return f"{subj} {required[0]} gestern … {required[1]}.", ""
    if kind == "Plural":
        return f"Die {form} …", ""
    if kind == "Dativ Plural":
        return f"Ich spreche mit den {form} …", ""
    if kind == "Akkusativ Singular":
        return f"Ich brauche {form} …", ""
    if kind == "Komparativ":
        return f"… ist {form} als …", ""
    if kind == "Superlativ":
        return f"… ist {form}.", ""
    return f"… {form} …", ""
