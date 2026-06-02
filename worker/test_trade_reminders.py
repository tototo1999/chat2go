from datetime import date
import trade_reminders as trem


def _r(**kw):
    base = {"id": "x", "status": "pending", "due_date": "2026-06-10",
            "lead_days": 2, "last_fired_on": None, "fire_count": 0,
            "kind": "尾款", "note": "催 ACME 尾款 $5000"}
    base.update(kw)
    return base


def test_select_due_within_lead_window():
    assert trem.select_due([_r()], date(2026, 6, 8)) == [_r()]


def test_select_due_before_window_skips():
    assert trem.select_due([_r()], date(2026, 6, 7)) == []


def test_select_due_overdue_hits():
    assert len(trem.select_due([_r()], date(2026, 6, 15))) == 1


def test_select_due_already_fired_today_skips():
    r = _r(last_fired_on="2026-06-09")
    assert trem.select_due([r], date(2026, 6, 9)) == []


def test_select_due_fired_yesterday_hits_again():
    r = _r(last_fired_on="2026-06-08")
    assert len(trem.select_due([r], date(2026, 6, 9))) == 1


def test_select_due_non_pending_skips():
    assert trem.select_due([_r(status="done")], date(2026, 6, 15)) == []


def test_select_due_lead_days_missing_defaults_2():
    r = _r(lead_days=None)
    assert len(trem.select_due([r], date(2026, 6, 8))) == 1
    assert trem.select_due([r], date(2026, 6, 7)) == []


def test_format_message_upcoming():
    msg = trem.format_reminder_message(_r(), date(2026, 6, 8))
    assert "🔔" in msg and "还有 2 天" in msg and "尾款" in msg


def test_format_message_today():
    msg = trem.format_reminder_message(_r(), date(2026, 6, 10))
    assert "今天" in msg


def test_format_message_overdue():
    msg = trem.format_reminder_message(_r(), date(2026, 6, 13))
    assert "🔴" in msg and "逾期 3 天" in msg


def test_format_for_prompt_empty():
    assert trem.format_reminders_for_prompt([]) == ""
    assert trem.format_reminders_for_prompt([_r(status="done")]) == ""


def test_format_for_prompt_sorts_by_due():
    rows = [_r(due_date="2026-06-20", kind="船期", note="问船期"),
            _r(due_date="2026-06-10", kind="尾款", note="催尾款")]
    out = trem.format_reminders_for_prompt(rows)
    assert out.index("2026-06-10") < out.index("2026-06-20")
    assert "待催事项" in out


def test_set_reminder_missing_fields_errors_before_db():
    out = trem.dispatch_reminder_tool(None, "room1", "exp1", "set_reminder",
                                      {"kind": "尾款"})
    assert out["ok"] is False and "due_date" in out["error"]


def test_set_reminder_bad_date_errors_before_db():
    out = trem.dispatch_reminder_tool(None, "room1", "exp1", "set_reminder",
                                      {"kind": "尾款", "note": "催", "due_date": "6月10"})
    assert out["ok"] is False and "YYYY-MM-DD" in out["error"]


def test_unknown_tool_errors():
    out = trem.dispatch_reminder_tool(None, "room1", "exp1", "nope", {})
    assert out["ok"] is False
