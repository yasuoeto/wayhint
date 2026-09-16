import json
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from wayhint import ipc
from wayhint.config import EditorConfig
from wayhint.editor import EditorError, open_in_editor
from wayhint.models import DisplayConfig, Margin, OutputInfo, Size
from wayhint.ui.geometry import placement, resolve_size


class EditorTest(unittest.TestCase):
    def test_popen_gets_argv_list_and_no_shell(self) -> None:
        ed = EditorConfig(("gvim", "--remote-silent", "+{line}", "{file}"))
        with (
            mock.patch("wayhint.editor.shutil.which", return_value="/usr/bin/gvim"),
            mock.patch("wayhint.editor.subprocess.Popen") as popen,
        ):
            argv = open_in_editor(ed, Path("/c/h.yaml"), 12, "x")
        self.assertEqual(argv, ["gvim", "--remote-silent", "+12", "/c/h.yaml"])
        args, kwargs = popen.call_args
        self.assertEqual(args[0], argv)
        self.assertIs(kwargs["shell"], False)

    def test_missing_editor(self) -> None:
        with mock.patch("wayhint.editor.shutil.which", return_value=None):
            with self.assertRaises(EditorError):
                open_in_editor(EditorConfig(("nope-editor", "{file}")), Path("/f"), 1, "x")


class IpcTest(unittest.TestCase):
    def test_handle_request(self) -> None:
        seen = []
        reply = ipc.handle_request(
            b'{"cmd":"toggle"}\n', lambda c: seen.append(c) or {"visible": True}
        )
        self.assertEqual(reply, {"ok": True, "visible": True})
        self.assertEqual(seen, ["toggle"])
        self.assertFalse(ipc.handle_request(b"garbage", lambda c: {})["ok"])
        self.assertFalse(ipc.handle_request(b'{"cmd":"rm -rf"}', lambda c: {})["ok"])
        self.assertFalse(ipc.handle_request(b'["toggle"]', lambda c: {})["ok"])
        self.assertFalse(ipc.handle_request(b"x" * 5000, lambda c: {})["ok"])
        boom = ipc.handle_request(b'{"cmd":"show"}', lambda c: 1 / 0)
        self.assertFalse(boom["ok"])
        self.assertIn("ZeroDivisionError", boom["error"])

    def test_client_roundtrip_with_minimal_server(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "s.sock"
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(str(path))
            srv.listen(1)

            def serve():
                conn, _ = srv.accept()
                with conn:
                    data = b""
                    while not data.endswith(b"\n"):
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    conn.sendall(ipc.encode(ipc.handle_request(data, lambda c: {"echo": c})))

            t = threading.Thread(target=serve)
            t.start()
            try:
                self.assertEqual(ipc.send_command("ping", path), {"ok": True, "echo": "ping"})
            finally:
                t.join(timeout=2)
                srv.close()
            with self.assertRaises(ipc.DaemonUnavailable):
                ipc.send_command("ping", Path(d) / "missing.sock")
        with self.assertRaises(ValueError):
            ipc.send_command("rm", path)

    def test_socket_path_uses_runtime_dir(self) -> None:
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/user/1"}):
            self.assertEqual(ipc.socket_path(), Path("/run/user/1/wayhint.sock"))
        self.assertEqual(json.loads(ipc.encode({"cmd": "ping"})), {"cmd": "ping"})


class GeometryTest(unittest.TestCase):
    OUT = OutputInfo("DP-1", 2000, 1000)

    def test_resolve_size(self) -> None:
        self.assertEqual(resolve_size(Size(30, "%"), 2000), 600)
        self.assertEqual(resolve_size(Size(420, "px"), None), 420)
        self.assertIsNone(resolve_size(Size(30, "%"), None))
        self.assertIsNone(resolve_size(None, 100))

    def test_anchor_edges(self) -> None:
        d = DisplayConfig(
            anchor="top-right", width=Size(420, "px"), height=Size(60, "%"), margin=Margin(24, 24)
        )
        p = placement(d, self.OUT)
        self.assertEqual(p.edges, frozenset({"top", "right"}))
        self.assertEqual((p.width, p.height), (420, 600))
        self.assertEqual(p.margins, Margin(24, 24))
        self.assertEqual(placement(DisplayConfig(anchor="center"), None).edges, frozenset())
        self.assertEqual(placement(DisplayConfig(), None).edges, frozenset({"top", "right"}))

    def test_clamped_to_output(self) -> None:
        d = DisplayConfig(anchor="left", width=Size(100, "%"), margin=Margin(left=100, right=100))
        p = placement(d, self.OUT)
        self.assertEqual(p.width, 1900)  # only the anchored (left) margin is subtracted
        d = DisplayConfig(anchor="bottom", height=Size(5000, "px"), margin=Margin(bottom=10))
        self.assertEqual(placement(d, self.OUT).height, 990)
