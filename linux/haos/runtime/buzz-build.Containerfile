# No moving package installs or dependency updates: exact Python and Rust images,
# the official source archive, both frozen Cargo locks and reviewed HAOS overlay.
FROM python@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89 AS python
FROM rust@sha256:ff521445a372125ed4f76e1453a1f8098f2d05332d1601d30db1c1f62757e730
COPY --from=python /usr/local /usr/local
COPY linux/haos/runtime /haos-runtime
RUN ldconfig && python3 /haos-runtime/build_buzz.py --output /output
