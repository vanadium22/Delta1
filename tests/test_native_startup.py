"""Normal entry point coverage, including denied local IPC and window reuse."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock

from dashboard.native.bootstrap import configure_qt
from dashboard.native.startup import instance_name,start_instance

PROJECT=Path(__file__).resolve().parents[1]


class StartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): configure_qt()

    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.socket=Mock();self.socket.waitForConnected.return_value=False
        self.server=Mock();self.server.listen.return_value=True

    def start(self,**kwargs):
        return start_instance(self.root,server_factory=lambda:self.server,socket_factory=lambda:self.socket,**kwargs)

    def test_channel_name_is_scoped_by_user_session_and_settings_root(self):
        self.assertNotEqual(instance_name(self.root,"user_a|1"),instance_name(self.root,"user_b|1"))
        self.assertNotEqual(instance_name(self.root,"user_a|1"),instance_name(self.root,"user_a|2"))
        self.assertNotEqual(instance_name(self.root,"user_a|1"),instance_name(self.root/"another","user_a|1"))

    def test_first_instance_listens_without_removing_other_servers(self):
        result=self.start()
        self.assertIs(result.server,self.server);self.assertFalse(result.forwarded)
        self.socket.abort.assert_called_once()

    def test_repeat_launch_exits_only_after_window_activation_acknowledgement(self):
        self.socket.waitForConnected.return_value=True
        self.socket.waitForReadyRead.return_value=True
        self.socket.readAll.return_value=b"delta1-v2:ok\n"
        result=self.start(demo=True)
        self.assertTrue(result.forwarded);self.assertIsNone(result.server)
        self.socket.write.assert_called_once_with(b"delta1-v2:demo\n")
        self.server.listen.assert_not_called()

    def test_denied_channel_returns_fallback_and_does_not_raise(self):
        self.server.listen.return_value=False;self.server.errorString.return_value="Access is denied"
        result=self.start()
        self.assertFalse(result.forwarded);self.assertIsNone(result.server)
        self.assertIn("Access is denied",result.warning);self.server.close.assert_called_once()

    def test_unresponsive_other_instance_does_not_swallow_startup(self):
        self.socket.waitForConnected.return_value=True;self.socket.waitForReadyRead.return_value=False
        result=self.start()
        self.assertFalse(result.forwarded);self.assertIn("未确认",result.warning)
        self.server.listen.assert_not_called()

    def test_recovery_mode_skips_network_objects(self):
        result=self.start(enabled=False)
        self.assertFalse(result.forwarded);self.server.listen.assert_not_called()
        self.socket.connectToServer.assert_not_called()

    def test_denied_ipc_still_renders_first_frame_through_real_main(self):
        script="""
import sys
from unittest.mock import patch
from dashboard.native.bootstrap import configure_qt
configure_qt()
from dashboard.native.__main__ import main
with patch('PySide6.QtNetwork.QLocalServer.listen',return_value=False), patch('PySide6.QtNetwork.QLocalServer.errorString',return_value='mock access denied'):
    raise SystemExit(main(['--local-root',sys.argv[1],'--startup-check']))
"""
        environment={**os.environ,"QT_QPA_PLATFORM":"offscreen"}
        result=subprocess.run([sys.executable,"-B","-s","-X","utf8","-c",script,str(self.root)],
            cwd=PROJECT,env=environment,capture_output=True,text=True,encoding="utf-8",timeout=25)
        self.assertEqual(result.returncode,0,result.stderr)
        logs=[p for p in (PROJECT/"dashboard/runtime/startup").glob("native_*.log") if str(self.root) in p.read_text(encoding="utf-8")]
        self.assertTrue(logs)
        log=logs[-1].read_text(encoding="utf-8")
        self.assertIn("mock access denied",log);self.assertIn("First frame ready",log)

    def test_normal_first_and_repeat_launch_share_a_live_ui(self):
        environment={**os.environ,"QT_QPA_PLATFORM":"offscreen"}
        command=[sys.executable,"-B","-s","-X","utf8","-m","dashboard","--no-realtime","--local-root",str(self.root)]
        first=subprocess.Popen(command,cwd=PROJECT,env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        log_path=PROJECT/"dashboard/runtime/startup"/f"native_{first.pid}.log"
        try:
            end=time.monotonic()+15
            while time.monotonic()<end:
                if first.poll() is not None: self.fail("first startup exited before rendering")
                if log_path.is_file() and "Startup wizard ready" in log_path.read_text(encoding="utf-8"): break
                time.sleep(.05)
            else: self.fail("startup wizard was not ready")
            result=subprocess.run([*command,"--startup-check"],cwd=PROJECT,env=environment,capture_output=True,text=True,encoding="utf-8",timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIsNone(first.poll())
            self.assertIn("Existing window activation handled",log_path.read_text(encoding="utf-8"))
        finally:
            if first.poll() is None: first.terminate()
            first.wait(timeout=5)


if __name__=="__main__": unittest.main()
