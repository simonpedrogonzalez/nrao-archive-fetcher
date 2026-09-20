import json

from nrao_archive_fetcher.email import (
    MailMessage,
    extract_wget_commands,
    gather_json_messages,
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
