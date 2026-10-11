# Actual private compositor fixture; no host display, disk or user profile binds.
FROM fedora:44@sha256:43b29f65a41eb9c35e1cd5323e3bdf3b655c2357a9f4f1ff2f9c2798e5045d80
# labwc 0.9.6 requires its optional Xwayland binary even for Wayland-only
# clients. It remains inside the private offline session; no host X socket binds.
RUN dnf install -y --setopt=install_weak_deps=False python3 python3-pillow labwc wlrctl wtype grim foot dejavu-sans-mono-fonts xorg-x11-server-Xwayland wayland-utils \
 && dnf clean all
ENTRYPOINT ["/usr/bin/python3", "/probe.py"]
