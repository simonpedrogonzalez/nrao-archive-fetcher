import json

from nrao_archive_fetcher.email import (
    MailMessage,
    extract_wget_commands,
    gather_json_messages,
    import_email_commands,
    update_manifest_from_messages,
)


def test_extract_wget_commands():
    text = """
Hello
wget -r -l 10 https://dl-dsoc.nrao.edu/user/123/abcdef1234567890/
"""
    commands = extract_wget_commands(text)
    assert len(commands) == 1
    assert commands[0].startswith("wget")


def test_update_manifest_from_messages():
    manifest = {
        "entries": [
            {
                "project_code": "24B-465",
                "obs_id": "24B-465.sb47226343.eb47329790.60643.9672167824",
                "viewer_url": "https://data.nrao.edu/portal/#/productViewer/24B-465.sb47226343.eb47329790.60643.9672167824",
                "download_command": "",
            }
        ]
    }
    message = MailMessage(
        message_id="1",
        subject="Your NRAO data request is ready",
        received_at="2026-04-29 12:00:00",
        content="wget -r -l 10 https://dl-dsoc.nrao.edu/user/123/abcdef1234567890/\n24B-465.sb47226343.eb47329790.60643.9672167824",
    )
    updates = update_manifest_from_messages(manifest, [message])
    assert updates == 1
    assert manifest["entries"][0]["download_command"].startswith("wget")
    assert manifest["entries"][0]["request_status"] == "request_ready"


def test_json_messages_use_mail_message_representation(tmp_path):
    path = tmp_path / "messages.json"
    path.write_text(json.dumps({"messages": [{"id": "m1", "subject": "ready", "date": "today", "body": "command"}]}))
    assert gather_json_messages(path) == [MailMessage("m1", "ready", "today", "command")]


def test_exact_entry_id_wins_over_token_overlap():
    manifest = {
        "entries": [
            {"entry_id": "cal-first", "project_code": "same", "obs_id": "obs-1", "download_command": ""},
            {"entry_id": "cal-second", "project_code": "same", "obs_id": "obs-2", "download_command": ""},
        ]
    }
    message = MailMessage("1", "Your cal-second is complete", "", "wget https://dl-dsoc.nrao.edu/u/123/abcdef1234567890/")
    assert update_manifest_from_messages(manifest, [message]) == 1
    assert not manifest["entries"][0]["download_command"]
    assert manifest["entries"][1]["download_command"]


def test_ambiguous_email_match_is_not_applied():
    manifest = {
        "entries": [
            {"project_code": "24B-465", "obs_id": "obs-1", "download_command": ""},
            {"project_code": "24B-465", "obs_id": "obs-2", "download_command": ""},
        ]
    }
    message = MailMessage("1", "24B-465 ready", "", "wget https://dl-dsoc.nrao.edu/u/123/abcdef1234567890/")
    assert update_manifest_from_messages(manifest, [message]) == 0
    assert not any(entry["download_command"] for entry in manifest["entries"])


def test_imap_settings_can_come_from_environment(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"entries": []}')
    captured = {}

    def fake_gather(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setenv("NRAO_IMAP_HOST", "imap.example")
    monkeypatch.setenv("NRAO_IMAP_PORT", "1993")
    monkeypatch.setenv("NRAO_IMAP_USERNAME", "user")
    monkeypatch.setenv("NRAO_IMAP_PASSWORD", "secret")
    monkeypatch.setenv("NRAO_IMAP_MAILBOX", "Archive")
    monkeypatch.setenv("NRAO_IMAP_SENDER_FILTER", "archive@example")
    monkeypatch.setenv("NRAO_IMAP_DAYS_BACK", "30")
    monkeypatch.setattr("nrao_archive_fetcher.email.gather_imap_messages", fake_gather)
    import_email_commands(manifest_path, gather_mode="imap", dry_run=True)
    assert captured == {
        "host": "imap.example",
        "port": "1993",
        "username": "user",
        "password": "secret",
        "mailbox": "Archive",
        "sender_filter": "archive@example",
        "days_back": 30,
    }


def _failure_manifest():
    return {
        "entries": [
            {
                "calibrator_id": "1051-316",
                "obs_id": "16B-069_sb32991151_1.57709.66087045139",
                "viewer_url": "https://data.nrao.edu/portal/#/productViewer/16B-069_sb32991151_1.57709.66087045139",
                "download_command": "",
            },
            {
                "calibrator_id": "1051+213",
                "obs_id": "18B-316.sb37532172.eb37535740_000.58806.759674016204",
                "viewer_url": "https://data.nrao.edu/portal/#/productViewer/18B-316.sb37532172.eb37535740_000.58806.759674016204",
                "download_command": "",
            },
        ]
    }


FAILURE_BODY = """Hello,
Your request for 16B-069_sb32991151_1.57709.66087045139 could not be processed.
Details: CASA restore failed:
missing calibration tables
Best regards,
NRAO Archive"""


def test_failure_email_marks_entry_failed_with_details():
    manifest = _failure_manifest()
    message = MailMessage("1", "NRAO request Failure", "", FAILURE_BODY)
    assert update_manifest_from_messages(manifest, [message]) == 1
    failed, other = manifest["entries"]
    assert failed["request_status"] == "request_failed"
    assert failed["request_error"] == "CASA restore failed: missing calibration tables"
    assert not failed["download_command"]
    assert "request_status" not in other


def test_repeated_failure_email_is_not_counted_twice():
    manifest = _failure_manifest()
    message = MailMessage("1", "NRAO request Failure", "", FAILURE_BODY)
    update_manifest_from_messages(manifest, [message])
    assert update_manifest_from_messages(manifest, [message]) == 0


def test_completion_after_failure_clears_error():
    manifest = _failure_manifest()
    failure = MailMessage("1", "NRAO request Failure", "", FAILURE_BODY)
    complete = MailMessage(
        "2",
        "NRAO request Complete",
        "",
        "16B-069_sb32991151_1.57709.66087045139\nwget -r https://dl-dsoc.nrao.edu/u/123/abcdef1234567890/",
    )
    assert update_manifest_from_messages(manifest, [failure, complete]) == 2
    entry = manifest["entries"][0]
    assert entry["request_status"] == "request_ready"
    assert entry["download_command"].startswith("wget")
    assert "request_error" not in entry


def test_show_pending_hides_failed_and_failed_option_shows_them(tmp_path, capsys):
    from nrao_archive_fetcher.manifest import print_pending, write_manifest

    manifest = _failure_manifest()
    update_manifest_from_messages(manifest, [MailMessage("1", "Failure", "", FAILURE_BODY)])
    path = tmp_path / "manifest.json"
    write_manifest(manifest, path)
    capsys.readouterr()

    print_pending(path)
    out = capsys.readouterr().out
    assert "1051+213" in out and "1051-316" not in out

    print_pending(path, failed=True)
    out = capsys.readouterr().out
    assert "1051-316" in out and "1051+213" not in out
    assert "CASA restore failed: missing calibration tables" in out


def test_real_nrao_failure_email_matches_by_request_name():
    manifest = _failure_manifest()
    body = """Dear Simon Gonzalez:

Thank you for using the NRAO archive.

Unfortunately, there was a problem processing your download request (no. 295701976, 1051+213).

Details:
No further information found. 

Best regards,

The NRAO Archive"""
    message = MailMessage("1", "NRAO Archive Request 295701976: Failure", "", body)
    assert update_manifest_from_messages(manifest, [message]) == 1
    entry = manifest["entries"][1]
    assert entry["request_status"] == "request_failed"
    assert entry["request_error"] == "No further information found."
    assert "request_status" not in manifest["entries"][0]


def test_show_pending_limit(tmp_path, capsys):
    from nrao_archive_fetcher.manifest import print_pending, write_manifest

    path = tmp_path / "manifest.json"
    write_manifest(_failure_manifest(), path)
    capsys.readouterr()
    print_pending(path, limit=1)
    out = capsys.readouterr().out
    assert "1051-316" in out and "1051+213" not in out
    assert "showing 1 of 2 pending entries" in out


def _submitted(request_id, name, received="2026-11-11 19:52"):
    body = "Dear Simon Gonzalez:\n\nYour %s has been submitted.\n\nBest regards,\n\nThe NRAO Archive" % name
    return MailMessage(str(request_id), "NRAO Archive Request %d: Submitted" % request_id, received, body)


def _failure(request_id, name):
    body = (
        "Unfortunately, there was a problem processing your download request (no. %d, %s).\n\n"
        "Details:\nNo further information found. \n\nBest regards,\n\nThe NRAO Archive" % (request_id, name)
    )
    return MailMessage("f%d" % request_id, "NRAO Archive Request %d: Failure" % request_id, "", body)


def _complete(request_id, name, obs_id):
    body = "Your %s is complete.\n%s\nwget -r https://dl-dsoc.nrao.edu/u/%d/abcdef1234567890/" % (name, obs_id, request_id)
    return MailMessage("c%d" % request_id, "NRAO Archive Request %d: Complete" % request_id, "", body)


def test_submitted_email_marks_entry_requested():
    manifest = _failure_manifest()
    assert update_manifest_from_messages(manifest, [_submitted(298510484, "1051+213")]) == 1
    entry = manifest["entries"][1]
    assert entry["request_status"] == "request_submitted" and entry["request_id"] == 298510484
    assert "request_status" not in manifest["entries"][0]


def test_outcome_wins_over_submitted_in_any_order():
    for order in (lambda s, f: [s, f], lambda s, f: [f, s]):
        manifest = _failure_manifest()
        update_manifest_from_messages(manifest, order(_submitted(100, "1051+213"), _failure(100, "1051+213")))
        assert manifest["entries"][1]["request_status"] == "request_failed"


def test_resubmitted_request_overrides_older_failure_in_any_order():
    for order in (lambda f, s: [f, s], lambda f, s: [s, f]):
        manifest = _failure_manifest()
        update_manifest_from_messages(manifest, order(_failure(100, "1051+213"), _submitted(200, "1051+213")))
        entry = manifest["entries"][1]
        assert entry["request_status"] == "request_submitted" and entry["request_id"] == 200


def test_failure_recorded_before_request_ids_is_not_undone_by_its_submitted_email():
    manifest = _failure_manifest()
    manifest["entries"][1].update(request_status="request_failed", request_error="No further information found.")
    update_manifest_from_messages(manifest, [_failure(100, "1051+213"), _submitted(100, "1051+213")])
    assert manifest["entries"][1]["request_status"] == "request_failed"


def test_completion_after_submitted_sets_link():
    manifest = _failure_manifest()
    obs_id = manifest["entries"][1]["obs_id"]
    update_manifest_from_messages(manifest, [_complete(100, "1051+213", obs_id), _submitted(100, "1051+213")])
    entry = manifest["entries"][1]
    assert entry["request_status"] == "request_ready" and entry["download_command"].startswith("wget")


def test_show_pending_requested_option(tmp_path, capsys):
    from nrao_archive_fetcher.manifest import print_pending, write_manifest

    manifest = _failure_manifest()
    update_manifest_from_messages(manifest, [_submitted(298510484, "1051+213")])
    path = tmp_path / "manifest.json"
    write_manifest(manifest, path)
    capsys.readouterr()
    print_pending(path)
    out = capsys.readouterr().out
    assert "1051-316" in out and "1051+213" not in out
    print_pending(path, requested=True)
    out = capsys.readouterr().out
    assert "1051+213" in out and "1051-316" not in out and "298510484" in out
