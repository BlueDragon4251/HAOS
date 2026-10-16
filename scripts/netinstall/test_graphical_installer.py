#!/usr/bin/env python3
"""Headless tests for actual graphical installer backend behavior."""
import threading
import unittest
from unittest import mock
import subprocess
import haos_install_core as core

class GraphicalInstallerCoreTests(unittest.TestCase):
    def test_usb_list_has_only_filesystem_partitions(self):
        sample = [{"path":"/dev/sda","type":"disk","tran":"usb","fstype":None,"children":[
            {"path":"/dev/sda1","type":"part","fstype":"vfat","size":120000000}]},
            {"path":"/dev/nbd0","type":"disk","size":100000000000,"fstype":"ext4"},
            {"path":"/dev/nvme0n1","type":"disk","tran":"nvme","children":[
                {"path":"/dev/nvme0n1p1","type":"part","fstype":"ext4"}]}]
        with mock.patch.object(core, "_lsblk", return_value=sample):
            self.assertEqual([d["path"] for d in core.token_partitions()], ["/dev/sda1"])

    def test_https_401_means_registry_reachable(self):
        with mock.patch.object(core, "execute", side_effect=["20.205.119.73", "401"]):
            self.assertIn("erreichbar", core.check_network())

    def test_tcp_timeout_has_useful_recovery(self):
        with mock.patch.object(core, "execute", side_effect=[
            "20.205.119.73", core.InstallerError("i/o timeout")]):
            with self.assertRaises(core.InstallerError) as captured:
                core.check_network()
        self.assertIn("Port 443", str(captured.exception))
        self.assertIn("PXE", str(captured.exception))
        self.assertIn("Gateway", str(captured.exception))

    def test_invalid_tokens_rejected(self):
        for token in ("", "a b", "\n", "x"*8193):
            with self.assertRaises(core.InstallerError):
                core.check_token(token)

    def test_digest_format_rejects_unpinned(self):
        self.assertIsNone(core.IMAGE_PATTERN.fullmatch("ghcr.io/bluedragon4251/haos:dev-test"))

    def test_cancellable_command_does_not_hang(self):
        canceled = threading.Event()
        canceled.set()
        with self.assertRaisesRegex(core.InstallerError, "abgebrochen"):
            core.execute(["/usr/bin/sleep", "5"], timeout=6, cancel_event=canceled)

    def test_actual_short_timeout(self):
        with self.assertRaisesRegex(core.InstallerError, "Zeitüberschreitung"):
            core.execute(["/usr/bin/sleep", "5"], timeout=0.15)


    def test_connected_wifi_filter(self):
        devices = ("eno1:ethernet:connected:Wired\n"
                   "wlp0s20f3:wifi:connected:Blue\n"
                   "wlan9:wifi:disconnected:--\n")
        with mock.patch.object(core, "execute", return_value=devices):
            self.assertEqual(core._wifi_devices(), ["wlp0s20f3"])

    def test_ghcr_wifi_route_does_not_break_iventoy(self):
        defaults = [
            {"dev": "eno1", "gateway": "192.168.50.1", "metric": 100},
            {"dev": "wlp0s20f3", "gateway": "192.168.0.1", "metric": 600},
        ]
        seen = []
        def execute(args, **kwargs):
            seen.append(args)
            if args[0] == "curl":
                self.assertIn("--interface", args)
                self.assertIn("wlp0s20f3", args)
                return "401"
            return ""
        with mock.patch.object(core, "_wifi_devices", return_value=["wlp0s20f3"]), \
             mock.patch.object(core, "_routes", return_value=defaults), \
             mock.patch.object(core, "_pxe_root_host", return_value="192.168.50.1"), \
             mock.patch.object(core, "_route_device", return_value="eno1"), \
             mock.patch.object(core, "check_network", return_value="GHCR HTTPS erreichbar"), \
             mock.patch.object(core, "execute", side_effect=execute):
            result = core.prefer_wifi_internet()
        self.assertIn("wlp0s20f3", result)
        self.assertTrue(any(cmd[:4] == ["ip", "-4", "route", "add"] for cmd in seen))
        self.assertFalse(any(cmd[:4] == ["ip", "-4", "route", "del"] for cmd in seen))
        self.assertFalse(any(cmd[:3] == ["nmcli", "device", "disconnect"] for cmd in seen))

    def test_wifi_repair_rollback_when_ghcr_still_fails(self):
        defaults = [
            {"dev": "eno1", "gateway": "192.168.50.1", "metric": 100},
            {"dev": "wlp0s20f3", "gateway": "192.168.0.1", "metric": 600},
        ]
        seen = []
        def execute(args, **kwargs):
            seen.append(args)
            if args[0] == "curl":
                return "401"
            return ""
        with mock.patch.object(core, "_wifi_devices", return_value=["wlp0s20f3"]), \
             mock.patch.object(core, "_routes", return_value=defaults), \
             mock.patch.object(core, "_pxe_root_host", return_value="192.168.50.1"), \
             mock.patch.object(core, "_route_device", return_value="eno1"), \
             mock.patch.object(core, "check_network", side_effect=core.InstallerError("Cannot reach GHCR")), \
             mock.patch.object(core, "execute", side_effect=execute):
            with self.assertRaisesRegex(core.InstallerError, "nicht"):
                core.prefer_wifi_internet()
        self.assertTrue(any(cmd[:4] == ["ip", "-4", "route", "add"] for cmd in seen))
        self.assertTrue(any(cmd[:4] == ["ip", "-4", "route", "del"] for cmd in seen))

    def test_no_wifi_refuses_route_change(self):
        with mock.patch.object(core, "_wifi_devices", return_value=[]), \
             mock.patch.object(core, "execute") as run:
            with self.assertRaisesRegex(core.InstallerError, "WLAN"):
                core.prefer_wifi_internet()
            run.assert_not_called()

    def test_http_root_host_is_discovered_dynamically(self):
        with mock.patch.object(core.Path, "read_text",
                               return_value="root=live:http://192.168.50.1:16000/eiso/id/1/LiveOS/squashfs.img ip=dhcp"):
            self.assertEqual(core._pxe_root_host(), "192.168.50.1")


    def test_published_dev_versions_sort_and_hide_token(self):
        releases = [
            {"created_at": "2026-10-15T01:00:00Z",
             "metadata": {"container": {"tags": ["dev-111111111111"]}}},
            {"created_at": "2026-10-16T22:00:00Z",
             "metadata": {"container": {"tags": ["dev-222222222222"]}}},
        ]
        import json
        with mock.patch.object(core, "execute", return_value=json.dumps(releases)) as run:
            # Avoid real /run writes when running unprivileged in CI.
            sess = object.__new__(core.RegistrySession)
            sess.cancel_event = None
            try:
                sess.api_token = "github_pat_TEST123"
                with mock.patch.object(sess, "tags", return_value=[
                        "dev-111111111111", "dev-222222222222"]):
                    found = sess.versions()
                self.assertEqual([x["tag"] for x in found],
                                 ["dev-222222222222", "dev-111111111111"])
                self.assertEqual(found[0]["published"], "2026-10-16T22:00:00Z")
                self.assertIsNone(sess.api_token)
                args = run.call_args.args[0]
                self.assertIn(["-K", "-"], [args[i:i+2] for i in range(len(args)-1)])
                self.assertNotIn("github_pat_TEST123", " ".join(args))
                self.assertIn(b"Authorization: Bearer github_pat_TEST123",
                              run.call_args.kwargs["input_data"])
            finally:
                sess.api_token = None

    def test_image_pull_progress_reports_real_lines(self):
        observed = []
        output = core.stream_execute(
            ["/usr/bin/python3", "-c",
             "import sys; print('Copying blob A', flush=True);"
             " print('Writing manifest', flush=True)"],
            timeout=10, progress=observed.append)
        self.assertIn("Writing manifest", output)
        self.assertTrue(any("Copying blob" in line for line in observed))

    def test_stream_timeout_is_bounded(self):
        with self.assertRaisesRegex(core.InstallerError, "Zeitüberschreitung"):
            core.stream_execute(["/usr/bin/sleep", "5"], timeout=0.2)

    def test_bootc_uses_local_storage_to_avoid_second_network_fetch(self):
        import inspect
        src = inspect.getsource(core.RegistrySession.install)
        self.assertIn("containers-storage:", src)
        self.assertIn("--source-imgref", src)
        self.assertIn("--target-imgref", src)
        self.assertIn("stream_execute", src)
        self.assertIn('"--filesystem", "ext4"', src)
        self.assertIn("command -v mkfs.ext4", src)
        self.assertIn("bootc install to-disk --help", src)

    def test_install_command_passes_explicit_ext4_and_preflights_image(self):
        # Simulate a valid target but never touch or erase any real disk.
        # We intentionally mock all host/storage subprocesses.
        from unittest.mock import patch
        import json
        session = object.__new__(core.RegistrySession)
        session.authfile = "/run/haos-test/auth.json"
        session.cancel_event = None
        image = "ghcr.io/bluedragon4251/haos@sha256:" + "a" * 64
        disk = "/dev/nvme0n1"
        executed = []
        def fake_execute(args, **kwargs):
            executed.append(args)
            if args[:3] == ["lsblk", "-nrpo", "NAME"]:
                return disk + "\\n"
            return ""
        def fake_stream(args, **kwargs):
            executed.append(args)
            return "ok"
        with patch.object(core, "internal_disks", return_value=[{"path": disk}]), \\
             patch.object(core, "execute", side_effect=fake_execute), \\
             patch.object(core, "stream_execute", side_effect=fake_stream), \\
             patch.object(core.subprocess, "run",
                          return_value=core.subprocess.CompletedProcess([], 1, "")):
            session.install(image, disk)
        command = next(args for args in executed if args[:2] == ["podman", "run"]
                       and "bootc" in args)
        self.assertEqual(command[command.index("--filesystem") + 1], "ext4")
        self.assertEqual(command[-1], disk)
        self.assertIn("--wipe", command)
        preflight = next(args for args in executed if args[:3] == ["podman", "run", "--rm"]
                         and "bootc" not in args)
        self.assertIn("mkfs.ext4", " ".join(preflight))

    def test_disk_selection_uses_existing_validator(self):
        with mock.patch.object(core, "ROOT", core.ROOT):
            # Real safety module (mock only the lsblk subprocess).
            with mock.patch("subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess(
                    args=["lsblk"], returncode=0,
                    stdout='{"blockdevices":[{"path":"/dev/nbd0","type":"disk","size":64000000000,"rm":0,"ro":0},'
                           '{"path":"/dev/nvme0n1","type":"disk","size":512000000000,"tran":"nvme","rm":0,"ro":0}]}'
                )
                self.assertEqual([d["path"] for d in core.internal_disks()], ["/dev/nvme0n1"])


if __name__ == "__main__":
    unittest.main()
