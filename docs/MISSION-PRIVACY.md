# Mission privacy

The controller redacts registered credential values, credential-shaped strings, authorization
headers, credential assignments, URL user information and PEM private keys **before** writing
new mission goals, tool events, questions, errors and results to SQLite. Its backend token is
registered in memory at startup. Observer health responses use the same redactor. Unexpected
control errors journal a fixed event rather than a traceback containing input data.

This is a defense against accidental disclosure, not a classifier for all personal information.
Unknown secrets without a recognizable shape, screenshots, historical database rows and the
upstream agent's own files/journal still require separate controls. Do not paste credentials
into conversations: use authenticated provider setup. Redaction does not encrypt data or set
retention. Provider/gateway credentials must be registered as they are provisioned; their values
must never be written to general mission history.

`linux/haos/tests/test_redaction.py` tests nested terminal payloads, URLs/private keys,
on-disk SQLite bytes after restart, pre-dispatch errors and preservation of actual usage metrics.
The complete ordinary service suite passes locally: 123 tests. Installed-guest and CI results
must be linked to the resulting source commit separately.
