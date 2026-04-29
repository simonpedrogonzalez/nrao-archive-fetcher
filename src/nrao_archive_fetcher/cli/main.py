from __future__ import annotations

import argparse

from ..download import download_manifest
from ..email import import_email_commands
from ..manifest import print_pending


def build_parser():
    parser = argparse.ArgumentParser(prog="nrao-fetch")
    subparsers = parser.add_subparsers(dest="command", required=True)

    pending = subparsers.add_parser("show-pending", help="Print project code and viewer URL for pending entries.")
    pending.add_argument("manifest")

    email = subparsers.add_parser("import-email", help="Import wget commands from macOS Mail into a manifest.")
    email.add_argument("manifest")
    email.add_argument("--days-back", type=int, default=14)
    email.add_argument("--account-name", default="Google")
    email.add_argument("--mailbox-name", default="INBOX")
    email.add_argument("--sender-filter", default="do-not-reply@nrao.edu")
    email.add_argument("--dry-run", action="store_true")
    email.add_argument("--debug", action="store_true")

    download = subparsers.add_parser("download", help="Run downloads for manifest entries that have commands.")
    download.add_argument("manifest")
    download.add_argument("--download-root")

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "show-pending":
        print_pending(args.manifest)
        return 0
    if args.command == "import-email":
        import_email_commands(
            args.manifest,
            gather_mode="mac_mail_app",
            days_back=args.days_back,
            account_name=args.account_name,
            mailbox_name=args.mailbox_name,
            sender_filter=args.sender_filter,
            dry_run=args.dry_run,
            debug=args.debug,
        )
        return 0
    if args.command == "download":
        download_manifest(args.manifest, base_download_root=args.download_root)
        return 0
    return 1
