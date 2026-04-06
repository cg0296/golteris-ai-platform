"""
backend/email/ — Email provider abstraction layer.

All email operations (fetch, send, thread lookup) go through provider
implementations in this package. Agents and services never import IMAP
or Gmail libraries directly — they use the abstract MailboxProvider interface.

This matches REQUIREMENTS.md §2.6: email-provider-agnostic architecture.

Providers:
    FileMailboxProvider — reads JSON seed files for dev/demo
    IMAPMailboxProvider — connects to any IMAP mailbox (Gmail, Outlook, etc.)
    (Future: GmailProvider, MicrosoftGraphProvider for push notifications)
"""
