from nrao_archive_fetcher.email import MailMessage, extract_wget_commands, update_manifest_from_messages


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
