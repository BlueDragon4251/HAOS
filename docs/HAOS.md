# Hermes Autonomous OS

HAOS uses Herald OS as its existing implementation base. The source and complete Git history were imported into the private, independent repository https://github.com/BlueDragon4251/HAOS on 8 October 2026. This repository is separate from GitHub's public Herald fork network.

The imported baseline is `3c891adcd1f5c3b6eeadf4d20472d10d9516a999`, pinned in `upstream/HERALD.lock`. The baseline contains 121 commits on `main` and 133 unique commits across all imported branches. Both upstream release tags and the `feature/herald-office` and `office/sheets-basic` branches are part of the import. `LICENSE`, `NOTICE` and upstream authorship remain intact.

## Project scope

The complete German project brief is in [the HAOS master prompt](requirements/HAOS-MASTER-PROMPT.md). Its target repository has been resolved to this repository. Requirements describe intended behavior; they are not claims that HAOS already implements or verifies every feature.

The machine is operated primarily by Hermes through the native Herald interface and authenticated gateways. Owners grant access to specific data volumes. Mission persistence, an independent Hermes service, technically enforced storage boundaries, safe theme development, installer verification and recovery are core requirements.

## Development branches

`main` retains the imported upstream baseline. `dev` is the integration branch, and `agent/haos-foundation` contains the HAOS foundation documentation. Future implementation changes should be committed on working branches and reviewed against `dev` before integration.

The local checkout uses `origin` for `BlueDragon4251/HAOS` and `upstream` for `iamlukethedev/Herald-OS`. Deliberate upstream updates use `git fetch upstream` followed by review, tests and a merge on a working branch. Hermes remains the separately maintained upstream dependency pinned by `upstream/UPSTREAM.lock`.

## Verified baseline

`git fsck --full` passed, and the local clone is not shallow. The existing bridge and Linux test command was executed without changing the implementation:

```sh
bash scripts/test-bridge.sh
```

Result: **293 passed, 1 skipped, 9 setup errors**. The nine errors are in `test_os_ui.py`: this execution environment denies creation of `AF_UNIX` sockets with `PermissionError: [Errno 1] Operation not permitted`. This is not a fully passing test suite. Those integration tests require another execution environment. Desktop build, TypeScript tests, installer boot and full HAOS acceptance scenarios were not executed in this foundation change.

See [the upstream inventory](architecture/upstream-inventory.md) for verified integration points and gaps.
