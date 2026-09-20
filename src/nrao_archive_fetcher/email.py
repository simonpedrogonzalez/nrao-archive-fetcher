from __future__ import annotations

import json
import imaplib
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from html import unescape
from pathlib import Path

from .manifest import read_manifest, write_manifest
from .utils import now_iso, print_status


PRODUCT_VIEWER_RE = re.compile(r"/#/(?:productViewer|productviewer)/([^/?#\s]+)")
SDM_ID_RE = re.compile(r"\b\d{2}[AB]-[A-Za-z0-9_.-]+\b")
URL_TOKEN_RE = re.compile(r"https?://dl-dsoc\.nrao\.edu/[^/\s]+/(\d+)/([a-f0-9]{16,64})/?", re.IGNORECASE)
REQUEST_NAME_RE = re.compile(r"your\s+([A-Za-z0-9][A-Za-z0-9+\-_.]*)\s+is\s+complete\b", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class MailMessage:
    message_id: str
    subject: str
    received_at: str
    content: str


def normalize_wget_command(command):
    text = (command or "").replace("\\\r\n", " ").replace("\\\n", " ").replace("\\\r", " ")
    text = re.sub(r"\s\\\s*", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")


def extract_wget_commands(text):
    commands = []
    lines = (text or "").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not re.match(r"^\s*wget2?\b", line, re.IGNORECASE):
            index += 1
            continue
        parts = [line.strip()]
        while index + 1 < len(lines):
            current = lines[index].rstrip()
            nxt = lines[index + 1]
            if current.endswith("\\") or re.match(r"^\s+https?://", nxt):
                parts.append(nxt.strip())
                index += 1
            else:
                break
        command = normalize_wget_command(" ".join(parts))
        if "dl-dsoc.nrao.edu" in command:
            commands.append(command)
        index += 1
    seen = set()
    deduped = []
    for command in commands:
        if command in seen:
            continue
        seen.add(command)
        deduped.append(command)
    return deduped


def extract_message_tokens(text):
    tokens = set()
    if not text:
        return tokens
    for match in PRODUCT_VIEWER_RE.finditer(text):
        tokens.add(match.group(1).lower())
    for match in SDM_ID_RE.finditer(text):
        tokens.add(match.group(0).lower())
    for match in URL_TOKEN_RE.finditer(text):
        tokens.add(match.group(1).lower())
        tokens.add(match.group(2).lower())
    for match in REQUEST_NAME_RE.finditer(text):
        tokens.add(match.group(1).lower())
    return tokens


def _entry_tokens(entry):
    tokens = set()
    for key in ("entry_id", "request_name", "project_code", "obs_id", "viewer_url"):
        value = str(entry.get(key) or "").strip()
        if not value:
            continue
        tokens.add(value.lower())
        for match in PRODUCT_VIEWER_RE.finditer(value):
            tokens.add(match.group(1).lower())
        for match in SDM_ID_RE.finditer(value):
            tokens.add(match.group(0).lower())
    row = entry.get("row") or {}
    for key in ("project_code", "obs_publisher_did", "access_url", "target_name"):
        value = str(row.get(key) or "").strip()
        if value:
            tokens.add(value.lower())
    return tokens


def _message_from_mapping(item, index=0):
    return MailMessage(
        message_id=str(item.get("message_id") or item.get("id") or index),
        subject=str(item.get("subject") or ""),
        received_at=str(item.get("received_at") or item.get("date") or ""),
        content=str(item.get("content") or item.get("body") or ""),
    )


def gather_json_messages(path):
    payload = json.loads(Path(path).read_text())
    items = payload.get("messages", []) if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError("messages JSON must be a list or an object containing a messages list")
    return [_message_from_mapping(item, index) for index, item in enumerate(items) if isinstance(item, dict)]


def _email_content(message):
    parts = []
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_disposition() == "attachment":
                continue
            if part.get_content_type() == "text/plain":
                parts.append(part.get_content())
        if not parts:
            for part in message.walk():
                if part.get_content_disposition() != "attachment" and part.get_content_type() == "text/html":
                    parts.append(unescape(HTML_TAG_RE.sub(" ", part.get_content())))
    else:
        content = message.get_content()
        if message.get_content_type() == "text/html":
            content = unescape(HTML_TAG_RE.sub(" ", content))
        parts.append(content)
    return "\n".join(str(part) for part in parts)


def gather_imap_messages(host, port=993, username=None, password=None, mailbox="INBOX", sender_filter="do-not-reply@nrao.edu", days_back=14):
    if not host or not username or not password:
        raise ValueError("IMAP host, username, and password are required")
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(days_back))
    criteria = ["SINCE", cutoff.strftime("%d-%b-%Y")]
    if sender_filter:
        criteria.extend(["FROM", sender_filter])
    messages = []
    with imaplib.IMAP4_SSL(host, int(port)) as client:
        client.login(username, password)
        status, _ = client.select(mailbox, readonly=True)
        if status != "OK":
            raise RuntimeError("Could not select IMAP mailbox %r" % (mailbox,))
        status, data = client.search(None, *criteria)
        if status != "OK":
            raise RuntimeError("IMAP message search failed")
        for message_id in (data[0].split() if data else []):
            status, response = client.fetch(message_id, "(RFC822)")
            if status != "OK":
                continue
            raw = next((item[1] for item in response if isinstance(item, tuple) and len(item) > 1), None)
            if not raw:
                continue
            parsed = BytesParser(policy=policy.default).parsebytes(raw)
            messages.append(
                MailMessage(
                    message_id=str(parsed.get("Message-ID") or message_id.decode()),
                    subject=str(parsed.get("Subject") or ""),
                    received_at=str(parsed.get("Date") or ""),
                    content=_email_content(parsed),
                )
            )
    return messages


def _contains_exact(text, value):
    value = str(value or "").strip()
    if not value:
        return False
    return re.search(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(value), text, re.IGNORECASE) is not None


def _unique_match(entries, pending, body):
    for keys in (("request_name", "entry_id"), ("obs_id",)):
        matches = [idx for idx in pending if any(_contains_exact(body, entries[idx].get(key)) for key in keys)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            return None

    message_tokens = extract_message_tokens(body)
    scores = [(len(message_tokens & _entry_tokens(entries[idx])), idx) for idx in pending]
    best_score = max((score for score, _ in scores), default=0)
    matches = [idx for score, idx in scores if score == best_score and score > 0]
    return matches[0] if len(matches) == 1 else None


def parse_applescript_messages(raw_text, debug=False):
    messages = []
    debug_block = ""
    if "<<<DEBUG>>>\n" in raw_text and "\n<<<ENDDEBUG>>>\n" in raw_text:
        debug_block = raw_text.split("<<<DEBUG>>>\n", 1)[1].split("\n<<<ENDDEBUG>>>\n", 1)[0]
        raw_text = raw_text.split("\n<<<ENDDEBUG>>>\n", 1)[1]
    if debug and debug_block:
        print_status("[EMAIL DEBUG]\n%s" % (debug_block,))
    for chunk in raw_text.split("<<<MSG>>>\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            message_id, rest = chunk.split("\n<<<SUBJECT>>>\n", 1)
            subject, rest = rest.split("\n<<<TIME>>>\n", 1)
            received_at, rest = rest.split("\n<<<CONTENT>>>\n", 1)
            content, _ = rest.split("\n<<<END>>>", 1)
        except ValueError:
            continue
        messages.append(MailMessage(message_id.strip(), subject.strip(), received_at.strip(), content.strip()))
    return messages


def gather_mac_mail_messages(days_back=14, account_name="Google", mailbox_name="INBOX", sender_filter="do-not-reply@nrao.edu", debug=False):
    sender_clause = ""
    sender_label = "any"
    if sender_filter:
        sender_value = sender_filter.replace('"', '\\"')
        sender_clause = ' whose sender contains "%s"' % (sender_value,)
        sender_label = sender_filter
    account_value = account_name.replace('"', '\\"')
    mailbox_value = mailbox_name.replace('"', '\\"')
    applescript = """
set cutoffDate to (current date) - (%d * days)
set outText to ""
set scannedCount to 0
set includedCount to 0
set errorCount to 0

tell application "Mail"
    set targetMailbox to mailbox "%s" of account "%s"
    set candidateMessages to (messages of targetMailbox%s)
    repeat with m in candidateMessages
        try
            set scannedCount to scannedCount + 1
            set msgDate to date received of m
            set includeMsg to (msgDate is greater than or equal to cutoffDate)
            if includeMsg then
                set includedCount to includedCount + 1
                set outText to outText & "<<<MSG>>>\\n"
                set outText to outText & (id of m as string) & "\\n"
                set outText to outText & "<<<SUBJECT>>>\\n"
                set outText to outText & (subject of m as string) & "\\n"
                set outText to outText & "<<<TIME>>>\\n"
                set outText to outText & (msgDate as string) & "\\n"
                set outText to outText & "<<<CONTENT>>>\\n"
                set outText to outText & (content of m as string) & "\\n"
                set outText to outText & "<<<END>>>\\n"
            end if
        on error errMsg
            set errorCount to errorCount + 1
        end try
    end repeat
end tell

return "<<<DEBUG>>>\\nsource=mail_app\\naccount=%s\\nmailbox=%s\\nsender_filter=%s\\nscanned=" & scannedCount & "\\nincluded=" & includedCount & "\\nerrors=" & errorCount & "\\n<<<ENDDEBUG>>>\\n" & outText
""" % (int(days_back), mailbox_value, account_value, sender_clause, account_value, mailbox_value, sender_label)
    try:
        proc = subprocess.run(["osascript", "-e", applescript], check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        detail = stderr or stdout or str(exc)
        raise RuntimeError(
            "Failed to read messages from Mail. "
            "Check the Mail account name, mailbox name, and macOS Automation permissions. "
            "Mail error: %s" % (detail,)
        ) from exc
    return parse_applescript_messages(proc.stdout, debug=debug)


def update_manifest_from_messages(manifest, messages):
    entries = manifest.get("entries", [])
    pending = [idx for idx, entry in enumerate(entries) if not str(entry.get("download_command") or "").strip()]
    updates = 0
    for message in messages:
        commands = extract_wget_commands(message.content)
        if not commands:
            continue
        body = (message.subject or "") + "\n" + (message.content or "")
        best_index = _unique_match(entries, pending, body)
        if best_index is None:
            continue
        entries[best_index]["download_command"] = commands[0]
        entries[best_index]["request_status"] = "request_ready"
        entries[best_index]["request_finished_at"] = now_iso()
        pending = [idx for idx in pending if idx != best_index]
        updates += 1
        print_status("[EMAIL] matched %s -> %s" % (entries[best_index].get("project_code"), commands[0]))
    return updates


def import_email_commands(
    manifest_path,
    gather_mode="mac_mail_app",
    days_back=14,
    account_name="Google",
    mailbox_name="INBOX",
    sender_filter="do-not-reply@nrao.edu",
    dry_run=False,
    debug=False,
    messages_json=None,
    imap_host=None,
    imap_port=None,
    imap_username=None,
    imap_password=None,
):
    manifest = read_manifest(manifest_path)
    if messages_json:
        messages = gather_json_messages(messages_json)
    elif gather_mode == "imap":
        messages = gather_imap_messages(
            host=imap_host or os.environ.get("NRAO_IMAP_HOST"),
            port=imap_port or os.environ.get("NRAO_IMAP_PORT", "993"),
            username=imap_username or os.environ.get("NRAO_IMAP_USERNAME"),
            password=imap_password or os.environ.get("NRAO_IMAP_PASSWORD"),
            mailbox=mailbox_name or os.environ.get("NRAO_IMAP_MAILBOX", "INBOX"),
            sender_filter=sender_filter,
            days_back=days_back,
        )
    elif gather_mode in ("mac_mail_app", "mac-mail"):
        messages = gather_mac_mail_messages(
            days_back=days_back,
            account_name=account_name,
            mailbox_name=mailbox_name,
            sender_filter=sender_filter,
            debug=debug,
        )
    else:
        raise ValueError("Unknown email backend %r" % (gather_mode,))
    print_status("[EMAIL] loaded %d message(s)" % (len(messages),))
    updates = update_manifest_from_messages(manifest, messages)
    if dry_run:
        print_status("[EMAIL] dry run, would update %d entries" % (updates,))
        return manifest
    write_manifest(manifest, manifest_path)
    print_status("[EMAIL] updated %d entrie(s)" % (updates,))
    return manifest
