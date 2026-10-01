# DBX cloud sync selection checkbox reproduction

Before: unmodified CloudSyncSelectionDialog.vue from upstream main commit 5afe0b424812f757d78629682311e3f251a00bc0.
After: click.stop plus change-driven selection updates; empty categories disable their parent checkbox.

Both screenshots show the actual Vue dialog mounted with the same five synthetic connection entries and five synthetic SSH Tunnel Profile entries. Both category parent checkboxes were clicked once from the initial all-selected state. The original dialog displays 0/5 with a checked parent; the fixed dialog displays 0/5 with an unchecked parent. The screenshots were captured in Chromium on Windows in a component preview, not in a complete Tauri/WebDAV backend session.

All names and IDs are synthetic. No connection credentials, local database files, or client data are included.

The proof assets are hosted separately from the source fix so the pull request can stay limited to the dialog and its mounted component regression tests.
