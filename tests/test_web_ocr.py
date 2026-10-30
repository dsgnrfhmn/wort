"""Texte, the photo pipeline: the upload checks (app/uploads.py), text recognition (app/ocr.py) and the translation
preview (app/mt.py, /texte/neu/uebersetzung). Tesseract and the translation models are not needed: the program is
replaced by a fake that returns what it would, except in the one test that runs the real program when it is installed.
Tests that build images need Pillow (the optional "ocr" group) and are skipped without it."""

import html as htmllib
import io
import re
import shutil
import tempfile
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app import auth, mt, ocr, texts, uploads
from app.db import WebStore
from app.main import create_app

pytestmark = pytest.mark.english_ui
PASSWORD = "correct horse battery"
HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
FAKE = ocr.Recognition("Bitte Unterlaqen einreichen.\n\nMit Grüßen", 87,
                       (ocr.Doubt("Unterlaqen", 1, 41, 20.0, 10.0, 12.0, 4.0),))


def word(block, par, line, n, left, top, conf, text, w=80, h=20):
    return f"5\t1\t{block}\t{par}\t{line}\t{n}\t{left}\t{top}\t{w}\t{h}\t{conf}\t{text}"


def tsv(*rows):
    return HEADER + "\n".join(rows) + "\n"


def image_bytes(fmt="PNG", size=(60, 40), mode="RGB", color="white", **save):
    Image = pytest.importorskip("PIL.Image")
    out = io.BytesIO()
    Image.new(mode, size, color).save(out, fmt, **save)
    return out.getvalue()


@pytest.fixture
def make_env(tmp_path, dict_path, monkeypatch):
    def make(cap=None):
        if cap:
            monkeypatch.setenv("WORT_OCR_DAILY_CAP", str(cap))
        app = create_app(db_path=tmp_path / "web.db", dict_path=dict_path, secure_cookies=False, checker=lambda s: [])
        store = WebStore(tmp_path / "web.db")
        uid = store.create_user("anna", auth.hash_password(PASSWORD)).id
        c = TestClient(app, follow_redirects=False, client=("127.0.0.1", 50000))
        c.get("/login")
        c.post("/login", data={"csrf": c.cookies.get("wort_csrf"), "name": "anna", "password": PASSWORD})
        return c, store, uid
    return make


@pytest.fixture
def env(make_env):
    return make_env()


@pytest.fixture
def fake_ocr(monkeypatch):
    """The recognition replaced by a fake; `calls` records what it was given."""
    calls = []
    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocr, "recognize", lambda image: calls.append(image.size) or FAKE)
    return calls


def upload(c, raw=None, content_type="image/png", title="Brief", csrf=None, field="photo", name="photo.png"):
    data = {"csrf": csrf or c.cookies.get("wort_csrf"), "title": title}
    files = {field: (name, raw if raw is not None else image_bytes(), content_type)}
    return c.post("/texte/neu", data=data, files=files)


def _post(c, path, **fields):
    return c.post(path, data={"csrf": c.cookies.get("wort_csrf"), **fields})


def today_count(store, uid):
    from datetime import datetime
    return store.ocr_uploads_today(uid, datetime.now().date().isoformat())


# --- Tesseract's output ---------------------------------------------------------------------------------------------

def test_tsv_becomes_paragraphs_with_a_broken_word_joined_and_the_unsure_words_marked():
    found = ocr.parse_tsv(tsv(
        "1\t1\t0\t0\t0\t0\t0\t0\t1000\t500\t-1\t",  # a page row: no text
        word(1, 1, 1, 1, 100, 50, 96, "bitte"), word(1, 1, 1, 2, 200, 50, 41, "Unterlaqen", w=120),
        word(1, 1, 2, 1, 100, 80, 95, "Verwal-"), word(1, 1, 3, 1, 100, 110, 95, "tung"),
        word(1, 2, 1, 1, 100, 300, 90, "Mit"), word(1, 2, 1, 2, 200, 300, 90, "Grüßen"),
        "5\t1\t1\t1\t4\t1\t0\t0\t10\t10\t30\t.",  # unsure but only punctuation: no doubt
        "5\t1\t1\t1\t4\t2\t0\t0\t10\t10\t-1\tnoconf", "garbage", "5\tx\ty",
    ), 1000, 500)
    assert found.text == "bitte Unterlaqen Verwaltung .\n\nMit Grüßen"  # the text is what was read, the stray full stop too
    assert found.percent == 77  # mean of 96, 41, 95, 95, 90, 90 and the full stop's 30
    assert [(d.found, d.line, d.sure) for d in found.doubts] == [("Unterlaqen", 1, 41)]
    assert found.doubts[0].region == {"x": 20.0, "y": 10.0, "w": 12.0, "h": 4.0, "kind": "uncertain", "label": "Unterlaqen"}


def test_an_empty_or_textless_result_is_an_empty_recognition():
    assert ocr.parse_tsv("", 10, 10) == ocr.Recognition("", 0)
    assert ocr.parse_tsv(HEADER + "1\t1\t0\t0\t0\t0\t0\t0\t10\t10\t-1\t\n", 10, 10) == ocr.Recognition("", 0)


def test_only_the_least_sure_words_are_marked_and_in_reading_order(monkeypatch):
    rows = [word(1, 1, i + 1, 1, 10, 10 * i, conf, f"Wort{i}") for i, conf in enumerate([50 + i for i in range(10)])]
    monkeypatch.setattr(ocr, "MAX_DOUBTS", 3)
    found = ocr.parse_tsv(tsv(*rows), 1000, 1000)
    assert [d.found for d in found.doubts] == ["Wort0", "Wort1", "Wort2"]
    found = ocr.parse_tsv(tsv(*reversed(rows)), 1000, 1000)  # reading order, not confidence order
    assert [d.found for d in found.doubts] == ["Wort2", "Wort1", "Wort0"]


def test_what_tesseract_returns_is_cleaned_and_capped(monkeypatch):
    monkeypatch.setattr(ocr, "MAX_TEXT", 12)
    found = ocr.parse_tsv(tsv(word(1, 1, 1, 1, 0, 0, 90, "\x1b[31mRot\x07"), word(1, 1, 1, 2, 90, 0, 90, "und‮grün"),
                              word(1, 1, 1, 3, 190, 0, 90, "und weiter")), 1000, 100)
    assert "\x1b" not in found.text and "\x07" not in found.text and "‮" not in found.text and len(found.text) <= 12


@pytest.mark.parametrize("lines, joined", [
    (["Die Verwal-", "tung ist"], "Die Verwaltung ist"),
    (["Ein- und", "Ausgang"], "Ein- und Ausgang"),
    (["Ein-", "und Ausgang"], "Ein- und Ausgang"),  # the hyphen belongs to the word before "und"
    (["Süd-", "West"], "Süd- West"),  # a capital letter next: a compound, not a broken word
    (["Seite 3 -", "tung"], "Seite 3 - tung"),  # a lonely hyphen is not a break
    (["eins", "zwei", "drei"], "eins zwei drei"),
])
def test_lines_are_joined_into_running_text(lines, joined):
    assert ocr.join_lines(lines) == joined


# --- the translation preview ------------------------------------------------------------------------------------------

def test_a_paragraph_is_cut_into_sentences_without_cutting_numbers_and_abbreviations():
    text = "Bitte reichen Sie die Unterlagen bis zum 15. November ein. Dazu gehört z. B. eine Bescheinigung. Fragen? Ja!  Dr. Müller ruft an."
    assert mt.sentences(text) == ["Bitte reichen Sie die Unterlagen bis zum 15. November ein.",
                                  "Dazu gehört z. B. eine Bescheinigung.", "Fragen?", "Ja!", "Dr. Müller ruft an."]
    assert mt.sentences("   ") == [] and mt.sentences("Kein Punkt") == ["Kein Punkt"]


def test_a_sentence_that_is_too_long_is_cut_at_commas_then_at_spaces():
    commas = ", ".join(["Dies ist ein langer Satzteil mit vielen Wörtern"] * 20) + "."
    pieces = mt.sentences(commas)
    assert len(pieces) > 1 and all(len(p) <= mt.CHUNK for p in pieces) and " ".join(pieces).replace(", ", ",") .count("Satzteil") == 20
    spaces = mt.sentences(" ".join(["Wort"] * 400))
    assert all(len(p) <= mt.CHUNK for p in spaces) and sum(p.count("Wort") for p in spaces) == 400


def test_a_paragraph_is_translated_whole_or_not_at_all(monkeypatch):
    monkeypatch.setattr(mt, "translate", lambda text, target: f"[{target}] {text}")
    assert mt.paragraph("Eins. Zwei.", "en") == "[en] Eins. [en] Zwei."
    monkeypatch.setattr(mt, "translate", lambda text, target: "" if text == "Zwei." else text.upper())
    assert mt.paragraph("Eins. Zwei.", "en") == ""  # one sentence without a translation: nothing half-made
    assert mt.paragraph("", "en") == ""


def test_the_preview_gives_english_and_ukrainian_per_paragraph(env, monkeypatch):
    c, *_ = env
    monkeypatch.setattr(mt, "translate", lambda text, target: f"[{target}] {text}")
    r = c.post("/texte/neu/uebersetzung", data={"csrf": c.cookies.get("wort_csrf"), "text": "Das Haus ist alt."})
    assert r.json() == {"lines": [{"lang": "en", "text": "[en] Das Haus ist alt."}, {"lang": "uk", "text": "[uk] Das Haus ist alt."}],
                        "message": ""}


def test_the_preview_without_a_model_says_so_and_never_invents_a_line(env, monkeypatch):
    c, *_ = env
    asked = []
    monkeypatch.setattr(mt, "translate", lambda text, target: asked.append(target) or "")
    r = c.post("/texte/neu/uebersetzung", data={"csrf": c.cookies.get("wort_csrf"), "text": "Das Haus ist alt."})
    assert r.json() == {"lines": [], "message": "No translation available here."}
    assert asked == ["en"]  # Ukrainian goes through English: no point asking without it
    monkeypatch.setattr(mt, "translate", lambda text, target: "the house" if target == "en" else "")  # no Ukrainian model
    r = c.post("/texte/neu/uebersetzung", data={"csrf": c.cookies.get("wort_csrf"), "text": "Das Haus."})
    assert r.json() == {"lines": [{"lang": "en", "text": "the house"}], "message": ""}


def test_the_preview_checks_the_token_the_size_and_an_empty_paragraph(env, monkeypatch):
    c, *_ = env
    monkeypatch.setattr(mt, "translate", lambda text, target: "x")
    csrf = c.cookies.get("wort_csrf")
    assert c.post("/texte/neu/uebersetzung", data={"csrf": "forged", "text": "Haus."}).status_code == 403
    too_long = c.post("/texte/neu/uebersetzung", data={"csrf": csrf, "text": "a" * (texts.MAX_PARAGRAPH + 1)})
    assert too_long.status_code == 400 and "at most" in too_long.json()["detail"]
    assert c.post("/texte/neu/uebersetzung", data={"csrf": csrf, "text": " \n "}).json() == {"lines": [], "message": ""}
    assert c.post("/texte/neu/uebersetzung", data={"csrf": csrf}).json() == {"lines": [], "message": ""}


def test_a_busy_translator_answers_503_with_a_message(env, monkeypatch):
    c, *_ = env

    def busy(text, target):
        raise mt.Busy()
    monkeypatch.setattr(mt, "paragraph", busy)
    r = c.post("/texte/neu/uebersetzung", data={"csrf": c.cookies.get("wort_csrf"), "text": "Haus."})
    assert r.status_code == 503 and r.json()["lines"] == [] and "busy" in r.json()["message"]


def test_the_preview_is_in_the_check_step_of_a_saved_text_too(env):
    c, store, uid = env
    store.add_text(uid, "Brief", "Das Haus ist alt.", 90)
    html = c.get("/texte/1/bearbeiten").text
    assert "data-translation" in html and "Translation (preview)" in html and "Update translation" in html
    assert 'data-photo="' not in html  # no photo for a saved text


# --- the upload ---------------------------------------------------------------------------------------------------------

def test_a_photo_opens_the_check_step_with_what_was_read(env, fake_ocr):
    c, store, uid = env
    html = upload(c, title="<b>Brief</b> {{ 7 * 7 }}").text
    assert fake_ocr == [(60, 40)]
    assert "Check text — &lt;b&gt;Brief&lt;/b&gt; {{ 7 * 7 }}" in html and "<b>Brief" not in html
    assert 'data-popup-open="wort-texts-check" data-autoopen data-close-href="/texte"' in html
    assert "Bitte Unterlaqen einreichen." in html and "Mit Grüßen" in html  # in the field to correct
    assert "Recognized · 87 % · 5 words" in html and "1 uncertain spot" in html
    assert "Unterlaqen · line 1 · 41 % sure" in html
    assert 'data-kind="uncertain" data-x="20.0" data-y="10.0" data-w="12.0" data-h="4.0"' in html
    assert 'data-photo="data:image/jpeg;base64,' in html and "data-translation" in html
    # what "Save text" needs travels with the form: the title of the upload step and how sure the recognition was
    assert 'action="/texte/neu/speichern"' in html and 'name="title" value="&lt;b&gt;Brief&lt;/b&gt; {{ 7 * 7 }}"' in html
    assert 'name="recognized" value="87"' in html
    assert today_count(store, uid) == 1
    assert upload(c, title="  ").text.count("Check text — Untitled") == 1


def test_from_the_photo_to_a_saved_text_in_the_sidebar(env, fake_ocr):
    c, store, uid = env
    html = upload(c, title="Brief vom Jobcenter").text
    fields = {k: v for k, v in re.findall(r'<input type="hidden" name="(title|recognized)" value="([^"]*)"', html)}
    text = html.split('name="text"')[1].split(">", 1)[1].split("</textarea>")[0]  # what the field holds
    r = _post(c, "/texte/neu/speichern", text=htmllib.unescape(text), **fields)
    assert r.status_code == 303 and r.headers["location"] == "/texte/1"
    assert store.text(uid, 1).title == "Brief vom Jobcenter" and store.text(uid, 1).recognized == 87
    assert "Bitte Unterlaqen einreichen." in store.text(uid, 1).body
    page = c.get(r.headers["location"]).text
    assert "Brief vom Jobcenter" in page and 'href="/texte/1"' in page and "recognized 87 %" in page
    assert "Brief vom Jobcenter" in c.get("/texte").text  # in the sidebar of every Texte page


def test_what_the_recognition_returns_is_data_in_the_page(env, monkeypatch):
    c, *_ = env
    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocr, "recognize", lambda image: ocr.Recognition("<script>alert(1)</script> {{ 7 * 7 }}", 50,
                                                                       (ocr.Doubt("<img src=x>", 1, 10, 1, 1, 1, 1),)))
    html = upload(c).text
    assert "<script>alert" not in html and "&lt;script&gt;alert(1)&lt;/script&gt; {{ 7 * 7 }}" in html
    assert "<img src=x>" not in html and "&lt;img src=x&gt;" in html


def test_a_forged_token_is_refused_before_anything_is_read(env, fake_ocr):
    c, store, uid = env
    assert upload(c, csrf="forged").status_code == 403
    assert fake_ocr == [] and today_count(store, uid) == 0


def test_a_missing_photo_goes_back_to_the_upload_step(env, fake_ocr):
    c, *_ = env
    r = c.post("/texte/neu", data={"csrf": c.cookies.get("wort_csrf"), "title": "x"})
    assert r.status_code == 400 and "Choose a photo first." in r.text and fake_ocr == []


@pytest.mark.parametrize("raw, content_type, message, status", [
    (b"just some text, renamed to .png", "image/png", "This file is not a PNG photo.", 400),
    (b"\x89PNG\r\n\x1a\n" + b"\x00" * 50, "image/jpeg", "This file is not a JPG photo.", 400),  # PNG bytes, declared JPEG
    (b"GIF89a" + b"\x00" * 50, "image/gif", "Only JPG and PNG photos are accepted.", 400),
    (b"\x00\x00\x00\x18ftypheic" + b"\x00" * 50, "image/heic", "Only JPG and PNG photos are accepted.", 400),
    (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml", "Only JPG and PNG photos are accepted.", 400),
    (b"", "image/png", "The file is empty.", 400),
])
def test_a_file_that_is_not_a_jpg_or_png_photo_is_refused_without_recognition(env, fake_ocr, raw, content_type, message, status):
    pytest.importorskip("PIL")
    c, store, uid = env
    r = upload(c, raw=raw, content_type=content_type)
    assert r.status_code == status and message in r.text
    assert 'data-flash="error"' in r.text and 'data-popup-open="wort-texts-upload" data-autoopen' in r.text  # back to the upload step
    assert fake_ocr == [] and today_count(store, uid) == 0  # nothing was recognised, nothing was counted


def test_a_refusal_keeps_the_title_the_user_typed(env, fake_ocr):
    c, *_ = env
    html = upload(c, raw=b"not a picture", title="Brief <b>vom</b> Amt").text
    assert 'name="title"' in html and 'value="Brief &lt;b&gt;vom&lt;/b&gt; Amt"' in html


def test_a_damaged_photo_is_refused_with_a_message_and_no_trace(env, fake_ocr):
    c, store, uid = env
    whole = image_bytes("PNG", (200, 200), color="red")
    r = upload(c, raw=whole[: len(whole) // 2])
    assert r.status_code == 400 and "could not be read" in r.text and fake_ocr == []
    assert "Traceback" not in r.text and "PIL" not in r.text
    header_only = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + b"\x00" * 30  # a valid-looking start, nothing behind it
    assert "could not be read" in upload(c, raw=header_only).text and fake_ocr == []


def test_a_photo_over_the_size_cap_is_refused_before_it_is_decoded(env, fake_ocr, monkeypatch):
    pytest.importorskip("PIL")
    c, *_ = env
    monkeypatch.setattr(uploads, "MAX_BYTES", 500)
    decoded = []
    real = uploads.Image.open if uploads.Image else None
    if real:
        monkeypatch.setattr(uploads.Image, "open", lambda *a, **k: decoded.append(1) or real(*a, **k))
    r = upload(c, raw=b"\x89PNG\r\n\x1a\n" + b"\x00" * 600)
    assert r.status_code == 413 and "larger than 20 MB" in r.text and decoded == [] and fake_ocr == []


def test_a_photo_with_too_many_pixels_is_refused_from_its_header(env, fake_ocr, monkeypatch):
    c, *_ = env
    monkeypatch.setattr(uploads, "MAX_PIXELS", 100)
    r = upload(c, raw=image_bytes("PNG", (20, 20)))  # 400 pixels
    assert r.status_code == 413 and "too large" in r.text and fake_ocr == []


def test_a_jpeg_and_a_png_are_accepted(env, fake_ocr):
    c, store, uid = env
    assert "Check text" in upload(c, raw=image_bytes("JPEG"), content_type="image/jpeg", name="p.jpg").text
    assert "Check text" in upload(c, raw=image_bytes("PNG")).text
    assert "Check text" in upload(c, raw=image_bytes("JPEG"), content_type="image/jpeg; charset=binary").text
    assert len(fake_ocr) == 3 and today_count(store, uid) == 3


def test_the_upload_is_closed_before_the_slow_recognition_starts_and_no_named_file_is_left(env, monkeypatch, tmp_path):
    """A large upload is spooled by the server to an unnamed temporary file (it does not show in a directory listing, so
    only the order of events can be checked): it is closed as soon as it is read, not when the request ends. Anything our
    own code wrote under the temporary directory would show, and does not."""
    Image = pytest.importorskip("PIL.Image")
    import os
    from starlette.datastructures import UploadFile
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    events = []
    close = UploadFile.close

    async def closing(self):
        events.append("close")
        await close(self)
    monkeypatch.setattr(UploadFile, "close", closing)
    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocr, "recognize", lambda image: events.append("recognize") or FAKE)
    noise = Image.frombytes("RGB", (700, 700), os.urandom(700 * 700 * 3))
    out = io.BytesIO()
    noise.save(out, "PNG")
    assert len(out.getvalue()) > 1024 * 1024  # over the 1 MiB the server keeps in memory
    c, *_ = env
    assert "Check text" in upload(c, raw=out.getvalue()).text
    assert events[:2] == ["close", "recognize"] and list(scratch.iterdir()) == []


def test_recognition_that_is_not_installed_says_so_and_costs_nothing(env, monkeypatch):
    c, store, uid = env
    monkeypatch.setattr(ocr, "available", lambda: False)
    r = upload(c)
    assert r.status_code == 503 and "Text recognition is not set up on this server." in r.text and today_count(store, uid) == 0
    assert "Text recognition is not set up" in c.get("/texte/neu").text  # the upload step says so up front


def test_a_recognition_that_fails_counts_but_shows_a_message_not_a_stack(env, monkeypatch):
    c, store, uid = env
    monkeypatch.setattr(ocr, "available", lambda: True)

    def slow(image):
        raise ocr.OcrFailed("Text recognition took too long. Try a smaller or sharper photo.", 504)
    monkeypatch.setattr(ocr, "recognize", slow)
    r = upload(c)
    assert r.status_code == 504 and "took too long" in r.text and "Traceback" not in r.text
    assert 'data-popup-open="wort-texts-upload" data-autoopen' in r.text and today_count(store, uid) == 1


def test_a_photo_without_text_goes_back_to_the_upload_step(env, monkeypatch):
    c, *_ = env
    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocr, "recognize", lambda image: ocr.Recognition("", 0))
    r = upload(c)
    assert r.status_code == 422 and "No text was found" in r.text and 'data-popup-open="wort-texts-upload"' in r.text


def test_the_daily_cap_stops_the_next_photo_before_it_is_read(make_env, fake_ocr):
    c, store, uid = make_env(cap=2)
    assert "Check text" in upload(c).text and "Check text" in upload(c).text
    r = upload(c)
    assert r.status_code == 429 and "daily limit for photos is reached (2)" in r.text
    assert len(fake_ocr) == 2 and today_count(store, uid) == 2
    store.conn.execute("UPDATE ocr_usage SET day = '2000-01-01'")  # a new day
    store.conn.commit()
    assert "Check text" in upload(c).text


def test_the_daily_cap_must_be_a_positive_number(tmp_path, dict_path, monkeypatch):
    monkeypatch.setenv("WORT_OCR_DAILY_CAP", "0")
    with pytest.raises(ValueError, match="WORT_OCR_DAILY_CAP"):
        create_app(db_path=tmp_path / "web.db", dict_path=dict_path, secure_cookies=False, checker=lambda s: [])


def test_the_usage_is_counted_per_user_and_day(tmp_path):
    store = WebStore(tmp_path / "web.db")
    a = store.create_user("anna", "x").id
    b = store.create_user("ben", "x").id
    assert store.ocr_uploads_today(a, "2026-10-30") == 0
    assert store.ocr_count_upload(a, "2026-10-30") == 1 and store.ocr_count_upload(a, "2026-10-30") == 2
    assert store.ocr_uploads_today(b, "2026-10-30") == 0 and store.ocr_uploads_today(a, "2026-10-31") == 0


# --- the photo itself ---------------------------------------------------------------------------------------------------

def test_a_photo_taken_sideways_is_turned_upright():
    Image = pytest.importorskip("PIL.Image")
    sideways = Image.new("RGB", (80, 30), "white")
    exif = Image.Exif()
    exif[0x0112] = 6  # the camera was turned: rotate 90 degrees to show it upright
    out = io.BytesIO()
    sideways.save(out, "JPEG", exif=exif)
    assert uploads.read_image(out.getvalue(), "image/jpeg").size == (30, 80)


def test_a_transparent_png_is_put_on_white():
    pytest.importorskip("PIL")
    clear = uploads.read_image(image_bytes("PNG", (4, 4), mode="RGBA", color=(0, 0, 0, 0)), "image/png")
    assert clear.mode == "RGB" and clear.getpixel((1, 1)) == (255, 255, 255)
    palette = uploads.read_image(image_bytes("PNG", (4, 4), mode="P", color=3), "image/png")
    assert palette.mode in ("RGB", "L")


def test_the_check_step_gets_a_small_jpeg_copy():
    import base64
    Image = pytest.importorskip("PIL.Image")
    url = uploads.thumbnail(uploads.read_image(image_bytes("PNG", (3000, 2000)), "image/png"))
    assert url.startswith("data:image/jpeg;base64,")
    small = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    assert small.format == "JPEG" and max(small.size) == uploads.THUMB_SIDE and not small.getexif()


def test_without_pillow_the_upload_is_refused_cleanly(monkeypatch):
    monkeypatch.setattr(uploads, "Image", None)
    assert not uploads.available() and not ocr.available()
    with pytest.raises(uploads.UploadRejected) as e:
        uploads.read_image(b"\x89PNG\r\n\x1a\n", "image/png")
    assert e.value.status == 503


# --- the real program ---------------------------------------------------------------------------------------------------

def _font():
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"):
        try:
            from PIL import ImageFont
            return ImageFont.truetype(path, 44)
        except (OSError, ImportError):
            continue
    return None


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract is not installed")
def test_tesseract_reads_a_generated_page(env):
    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")
    if not ocr.available():
        pytest.skip("tesseract has no German data")
    font = _font()
    if font is None:
        pytest.skip("no TrueType font to draw with")
    page = Image.new("RGB", (1400, 360), "white")
    draw = ImageDraw.Draw(page)
    draw.text((40, 40), "Das Haus ist alt und schön.", font=font, fill="black")
    draw.text((40, 160), "Die Katze schläft im Garten.", font=font, fill="black")
    found = ocr.recognize(page)
    assert {"Haus", "alt", "Katze", "Garten"} <= set(found.text.replace(".", " ").split()), found.text
    assert found.percent > 80
    c, *_ = env
    out = io.BytesIO()
    page.save(out, "PNG")
    html = upload(c, raw=out.getvalue()).text
    assert "Check text" in html and "Katze" in html
    assert unquote(html).count("data-photo=") == 1
