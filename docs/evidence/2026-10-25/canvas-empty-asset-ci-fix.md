The Linux shell job 121271271346 in CI run 40227298093 failed on source
9b696921d40ba5889bab50a527f33ca689f37c74: the package-directory replacement
test observed asset size zero instead of the completed PNG size 78.

The reader previously accepted zero-length referenced assets. An external
in-place write can expose this truncation state to polling, even when the
manifest is valid. The fix rejects empty assets and preserves the watcher's
last usable digest until a subsequent event or poll reads the completed file.
It does not claim to detect every possible nonempty partial file.

Validation of the accompanying source change:

- Ten package I/O tests passed, including a deterministic regression that
  explicitly truncates an image, calls the watcher, verifies no notification
  and a reader error, completes the write, and verifies the final notification.
- Full desktop suite: 842 tests across 115 files passed.
- Electron downloader suite: twelve tests passed.
- Desktop renderer and Electron TypeScript checks passed.

This is local Linux validation, not a successful rerun of the GitHub job or
installed desktop/boot acceptance. No gateway or provider live acceptance is
implied.
