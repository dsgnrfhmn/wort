"""Compact word card: principal forms, translations, IPA and a small grammar table."""

from __future__ import annotations

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from wort.dictionary import grammar as g
from wort.dictionary.lookup import Entry

# Monochrome: bold/italic plus one mid grey for secondary text.
# Underline is used only for the changing parts of verb forms (conjugation endings).
# Colors: the nominative singular article (der blue, die red, das green) and the main line of a card,
# which takes the word class color (noun: its article's color, verb: terminal text color (black on light), adj/adv: dark purple).
ENDING = "bold"  # inflection endings stand out in bold against the plain stem
VERB_ENDING = "bold underline"  # verb conjugation endings: bold and underlined
STEM = ""
MUTED = "grey42"  # secondary text; darker than the terminal's "dim" attribute
HEAD = "bold"
# Fixed 256-color indices, not the terminal theme's ANSI palette (a theme can turn that grey).
ARTICLE_COLORS = {"der": "color(33)", "die": "color(160)", "das": "color(34)"}  # blue, red, green
POS_COLORS = {"verb": "default", "adj": "color(54)", "adv": "color(54)"}  # verb: the terminal's own text color (black on a light theme), not grey; dark purple


def pos_color(entry: Entry) -> str:
    """Color of the card's main line: a noun takes its article's color, other classes their own."""
    if entry.pos == "noun":
        return ARTICLE_COLORS.get(g.GENDER_ARTICLE.get(entry.gender, ""), "")
    return POS_COLORS.get(entry.pos, "")

POS_LABELS = {
    "noun": "Substantiv", "verb": "Verb", "adj": "Adjektiv", "adv": "Adverb", "prep": "Präposition",
    "conj": "Konjunktion", "pron": "Pronomen", "num": "Numerale", "intj": "Interjektion",
    "phrase": "Wendung", "particle": "Partikel",
}
GENDER_LABELS = {"m": "maskulin", "f": "feminin", "n": "neutrum"}
CONJ_LABELS = {"weak": "regelmäßig", "strong": "unregelmäßig (stark)", "irregular": "unregelmäßig"}


def prefix_text(prefix: str, tint: str = "", colored: bool = True) -> Text:
    """Small italic words before a form ('des', 'ich bin'); der/die/das get their color.

    Only the nominative singular article is colored (`colored=True`); the articles of the
    plural and of genitive, dative and accusative are plain grey.
    """
    text = Text()
    for word in prefix.split():
        color = ARTICLE_COLORS.get(word, tint or MUTED) if colored else MUTED
        text.append(word + " ", style=f"italic {color}")
    return text


def highlight(form: str, stem: str, prefix: str = "", ending: str = ENDING, color: str = "", colored: bool = True) -> Text:
    """Render a form with its ending highlighted, e.g. beabsichtig[te].

    With `color` the whole form is tinted and the stem is bold (the card's main line).
    """
    text = prefix_text(prefix, color, colored)
    stem_style = f"bold {color}" if color else STEM
    ending = f"{ending} {color}".strip()
    words = form.split(" ")
    for i, word in enumerate(words):
        if i:
            text.append(" ")
        if i == 0:
            common, rest = g.split_ending(word, stem)
            text.append(common, style=stem_style)
            text.append(rest, style=ending)
        else:
            text.append(word, style=ending)
    return text


def _meta_line(entry: Entry) -> str:
    bits = [POS_LABELS.get(entry.pos, entry.pos)]
    if entry.pos == "noun" and entry.gender:
        bits.append(GENDER_LABELS[entry.gender])
    if entry.pos == "verb":
        if entry.conj:
            bits.append(CONJ_LABELS.get(entry.conj, entry.conj))
        if entry.aux:
            bits.append(entry.aux)
        bits.append("trennbar" if entry.separable else "untrennbar")
    return " · ".join(bits)


def _joined(parts: list[Text]) -> Text:
    line = Text()
    for i, part in enumerate(parts):
        if i:
            line.append(" · ", style=MUTED)
        line.append_text(part)
    return line


def _header(entry: Entry, stem: str) -> Text:
    color = pos_color(entry)
    main = f"bold {color}".strip()
    if entry.pos == "verb":
        parts = []
        for part in g.principal_parts(entry):
            if part.startswith(("hat ", "ist ")):
                aux, form = part.split(" ", 1)
                parts.append(highlight(form, stem, aux, ending=VERB_ENDING, color=color))
            else:
                parts.append(highlight(part, stem, ending=VERB_ENDING, color=color))
        return _joined(parts)
    if entry.pos == "noun":
        parts = [prefix_text(g.GENDER_ARTICLE.get(entry.gender, ""), color) + Text(entry.lemma, style=main)]
        if (gen := g.noun_form(entry, "genitive", "singular")) and entry.gender:
            parts.append(highlight(gen, stem, g.ARTICLES[entry.gender]["genitive"], color=color, colored=False))
        if pl := g.plural(entry):
            parts.append(highlight(pl, stem, "die", color=color, colored=False))
        return _joined(parts)
    if entry.pos == "adj":
        parts = [Text(entry.lemma, style=main)]
        if comp := g.comparative(entry):
            parts.append(highlight(comp, stem, color=color))
        if sup := g.superlative(entry):
            am, _, form = sup.rpartition(" ")
            parts.append(highlight(form, stem, am, color=color))
        return _joined(parts)
    return Text(entry.lemma, style=main or "bold")


def _verb_table(entry: Entry, stem: str) -> RenderableType | None:
    table = Table.grid(padding=(0, 2))
    for _ in range(4):
        table.add_column()
    table.add_row(*(Text(h, style=HEAD) for h in ("Präsens", "Präteritum", "Perfekt", "Futur I")))
    rows = 0
    for person in g.PERSONS:
        pres, past, perf = g.present(entry, person), g.preterite(entry, person), g.perfect(entry, person)
        if not (pres or past or perf):
            continue
        rows += 1
        perf_cell = highlight(g.participle2(entry), stem, f"{person} {g.perfect_aux(entry, person)}", ending=VERB_ENDING) if perf else Text("")
        table.add_row(
            highlight(pres, stem, person, ending=VERB_ENDING) if pres else Text(""),
            highlight(past, stem, person, ending=VERB_ENDING) if past else Text(""),
            perf_cell,
            highlight(entry.lemma, stem, f"{person} {g.WERDEN[person]}", ending=VERB_ENDING),
        )
    if not rows:
        return None
    side = []
    if imp := g.imperative(entry, "singular"):
        side.append(highlight(imp + "!", stem, "Imperativ (du)", ending=VERB_ENDING))
    if imp := g.imperative(entry, "plural"):
        side.append(highlight(imp + "!", stem, "(ihr)", ending=VERB_ENDING))
    if not side:
        return table
    return Group(table, Text(""), _joined(side))


def _noun_table(entry: Entry, stem: str) -> Table | None:
    table = Table.grid(padding=(0, 3))
    table.add_column(style=HEAD)
    table.add_column()
    table.add_column()
    table.add_row("", Text("Singular", style=HEAD), Text("Plural", style=HEAD))
    rows = 0
    for case in g.CASES:
        sg, pl = g.noun_form(entry, case, "singular"), g.noun_form(entry, case, "plural")
        if not sg and not pl:
            continue
        rows += 1
        art_sg = g.ARTICLES[entry.gender][case] if entry.gender in g.ARTICLES else ""
        table.add_row(
            g.CASE_LABELS[case],
            highlight(sg, stem, art_sg, colored=case == "nominative") if sg else Text("—", style=MUTED),
            highlight(pl, stem, g.ARTICLES["pl"][case], colored=False) if pl else Text("—", style=MUTED),
        )
    return table if rows > 1 else None


def _title(entry: Entry) -> Text:
    return Text.assemble((entry.lemma, f"{HEAD} {pos_color(entry)}".strip()), (f"  {_meta_line(entry)}", MUTED))


def _lead(entry: Entry, max_glosses: int) -> list[RenderableType]:
    """Everything above the first rule: the forms line and the translations."""
    first = _header(entry, g.stem_of(entry))
    if entry.ipa:
        first.append("   ")
        first.append(entry.ipa, style=MUTED)
    return [first, Text("; ".join(entry.glosses[:max_glosses]))]


def render_compact(entry: Entry, number: int, selected: bool, *, max_glosses: int = 4) -> RenderableType:
    """A result in a list of several: numbered, forms line and translations only (no tables, no examples)."""
    title = Text()  # built by appending: a base style on the first Text would leak onto the word
    title.append(f" [{number}] ", style="bold" if selected else f"bold {MUTED}")
    title.append_text(_title(entry))
    title.stylize(f"not bold {MUTED}", len(title) - len(f"  {_meta_line(entry)}"))  # a bold border must not bold the meta
    return Panel(
        Group(*_lead(entry, max_glosses)),
        title=title,
        title_align="left",
        box=box.HEAVY if selected else box.SQUARE,  # heavy lines make the selection visible in any theme
        border_style="bold" if selected else MUTED,
        padding=(0, 1),
    )


def render_card(entry: Entry, *, max_glosses: int = 4, footer: str | None = None, selected: bool = False) -> RenderableType:
    stem = g.stem_of(entry)
    parts: list[RenderableType] = _lead(entry, max_glosses)

    table = None
    if entry.pos == "verb":
        table = _verb_table(entry, stem)
    elif entry.pos == "noun":
        table = _noun_table(entry, stem)
    if table is not None:
        parts.append(Rule(style=MUTED))
        parts.append(table)

    if entry.examples:
        parts.append(Rule(style=MUTED))
        for de, en in entry.examples:
            parts.append(Text("» ", style=MUTED) + Text(de, style="italic"))
            if en:
                parts.append(Text(f"  {en}", style=MUTED))

    title = _title(entry)
    if selected:  # the cursor is on this card: heavy, bold border (as for a selected result); keep the meta grey
        title.stylize(f"not bold {MUTED}", len(title) - len(f"  {_meta_line(entry)}"))
    return Panel(
        Group(*parts),
        title=title,
        title_align="left",
        subtitle=Text(footer, style=MUTED) if footer else None,
        subtitle_align="right",
        box=box.HEAVY if selected else box.SQUARE,
        border_style="bold" if selected else MUTED,
        padding=(0, 1),
    )
