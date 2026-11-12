from __future__ import annotations

import argparse

from ..download import download_manifest
from ..email import import_email_commands
from ..manifest import print_pending
from ..sync import merge_shards, sync_requests


def build_parser():
    parser = argparse.ArgumentParser(prog="nrao-fetch")
    subparsers = parser.add_subparsers(dest="command", required=True)

    pending = subparsers.add_parser("show-pending", help="Print calibrator ID and viewer URL for pending entries.")
    pending.add_argument("manifest")
    pending.add_argument("--failed", action="store_true", help="Show only entries whose request failed, with the error.")
    pending.add_argument("--limit", type=int, help="Show only the first N entries.")

    email = subparsers.add_parser("import-email", help="Import wget commands from Mail, IMAP, or exported JSON.")
    email.add_argument("manifest")
    email.add_argument("--backend", choices=("mac-mail", "imap"), default="mac-mail")
    email.add_argument("--messages-json")
    email.add_argument("--days-back", type=int)
    email.add_argument("--account-name", default="Google")
    email.add_argument("--mailbox-name")
    email.add_argument("--sender-filter")
    email.add_argument("--host")
    email.add_argument("--port", type=int)
    email.add_argument("--username")
    email.add_argument("--password")
    email.add_argument("--dry-run", action="store_true")
    email.add_argument("--debug", action="store_true")

    sync = subparsers.add_parser(
        "sync-requests",
        help="Copy new download links and request failures from a local manifest copy into this manifest.",
    )
    sync.add_argument("local_manifest", help="Copy of the manifest where import-email was run.")
    sync.add_argument("manifest", help="Manifest to update (the one the download jobs use).")
    sync.add_argument("--dry-run", action="store_true")

    merge = subparsers.add_parser("merge-shards", help="Copy download/extraction progress from shard manifests into this manifest.")
    merge.add_argument("manifest")
    merge.add_argument("--dry-run", action="store_true")

    download = subparsers.add_parser("download", help="Run downloads for manifest entries that have commands.")
    download.add_argument("manifest")
    download.add_argument("--download-root")

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "show-pending":
        print_pending(args.manifest, failed=args.failed, limit=args.limit)
        return 0
    if args.command == "import-email":
        import_email_commands(
            args.manifest,
            gather_mode=args.backend,
            days_back=args.days_back,
            account_name=args.account_name,
            mailbox_name=args.mailbox_name,
            sender_filter=args.sender_filter,
            dry_run=args.dry_run,
            debug=args.debug,
            messages_json=args.messages_json,
            imap_host=args.host,
            imap_port=args.port,
            imap_username=args.username,
            imap_password=args.password,
        )
        return 0
    if args.command == "sync-requests":
        sync_requests(args.local_manifest, args.manifest, dry_run=args.dry_run)
        return 0
    if args.command == "merge-shards":
        merge_shards(args.manifest, dry_run=args.dry_run)
        return 0
    if args.command == "download":
        download_manifest(args.manifest, base_download_root=args.download_root)
        return 0
    return 1
