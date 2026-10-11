"""Reviewer choice, verdict reading and the merge-request line (add-runner-review-step). No database."""

from runner import review


def test_code_and_security_always_ux_ui_only_for_messages():
    assert review.reviewers_for(["x = 1"]) == ["code", "security"]
    assert review.reviewers_for(['    await update.message.reply_text("hi")']) == ["code", "security", "ux", "ui"]
    assert review.reviewers_for(["kb = InlineKeyboardMarkup([])"]) == ["code", "security", "ux", "ui"]


def _write(tmp_path, name, text):
    (tmp_path / ".auto/review").mkdir(parents=True, exist_ok=True)
    (tmp_path / f".auto/review/review-{name}.md").write_text(text)


def test_verdicts_from_first_line(tmp_path):
    _write(tmp_path, "code", "VERDICT: PASS\nfine")
    _write(tmp_path, "security", "VERDICT: CHANGES\n- bot.py:3 SQL from strings")
    v = review.read_verdicts(tmp_path, ["code", "security"], fixed=False)
    assert {n: x["verdict"] for n, x in v.items()} == {
        "code": "PASS", "security": "CHANGES", "ux": "SKIPPED", "ui": "SKIPPED"}
    assert "SQL from strings" in v["security"]["findings"]
    assert review.read_verdicts(tmp_path, ["code", "security"], fixed=True)["security"]["verdict"] == "FIXED"


def test_missing_garbled_symlinked_or_huge_files_have_no_verdict(tmp_path):
    _write(tmp_path, "code", "Looks good to me")
    secret = tmp_path / "secret.md"
    secret.write_text("VERDICT: PASS\n")
    (tmp_path / ".auto/review/review-security.md").symlink_to(secret)
    _write(tmp_path, "ux", "VERDICT: PASS\n" + "x" * review.MAX_REVIEW_BYTES)
    v = review.read_verdicts(tmp_path, ["code", "security", "ux", "ui"], fixed=True)
    assert {n: x["verdict"] for n, x in v.items()} == {
        "code": "MISSING", "security": "MISSING", "ux": "MISSING", "ui": "MISSING"}


def test_clear_removes_the_previous_round(tmp_path):
    _write(tmp_path, "code", "VERDICT: PASS\n")
    review.clear(tmp_path)
    assert review.read_verdicts(tmp_path, ["code"], fixed=False)["code"]["verdict"] == "MISSING"


def test_summary_line():
    v = {"code": {"verdict": "PASS"}, "security": {"verdict": "FIXED"},
         "ux": {"verdict": "SKIPPED"}, "ui": {"verdict": "SKIPPED"}}
    assert review.summary_line(v) == (
        "Review: code ✅ · security 🔧 fixed (ux, ui not run: no bot messages or keyboards changed)")
    v["ux"] = {"verdict": "MISSING"}
    v["ui"] = {"verdict": "CHANGES"}
    assert review.summary_line(v) == (
        "Review: code ✅ · security 🔧 fixed · ux ❓ no verdict · ui ⚠️ changes not fixed")
