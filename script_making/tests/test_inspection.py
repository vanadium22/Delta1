"""Read-only task inventory failures, with synthetic subprocesses and COM fixtures."""
import base64
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from script_making import inspect_automation as inspection


class InspectionTests(unittest.TestCase):
    def fake_query(self, value=None, code=0, waits=None):
        process = Mock()
        process.poll.return_value = code if waits is None else None
        process.wait.side_effect = waits if waits is not None else None
        process.wait.return_value = code
        def start(_command, **kwargs):
            self.assertNotEqual(kwargs['stdout'], subprocess.PIPE)
            self.assertEqual(kwargs['stderr'], subprocess.DEVNULL)
            if value is not None:
                raw = value if isinstance(value, bytes) else json.dumps(value).encode('utf-8')
                kwargs['stdout'].write(raw)
                kwargs['stdout'].flush()
            return process
        return process, patch.object(inspection.subprocess, 'Popen', side_effect=start)

    def test_timeout_kills_only_query_and_bounds_cleanup(self):
        process, context = self.fake_query(waits=[subprocess.TimeoutExpired('probe', 20), 1])
        with context:
            result = inspection.capture_task_query(['synthetic-probe'])
        self.assertEqual(result['reason_code'], 'timeout')
        self.assertFalse(result['complete'])
        self.assertTrue(result['query_process_stopped'])
        process.kill.assert_called_once_with()
        self.assertEqual([call.kwargs for call in process.wait.call_args_list], [{'timeout':20}, {'timeout':2}])
        process.communicate.assert_not_called()

    def test_interrupt_retains_project_json_in_daily_cli(self):
        from script_making.daily_job import main
        process, context = self.fake_query(waits=[KeyboardInterrupt(), 1])
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, context, redirect_stdout(output), redirect_stderr(io.StringIO()):
            root = Path(directory) / 'missing' / 'script_making'
            code = main(['--inspect','--windows-tasks','--root',str(root)])
            self.assertFalse(root.exists())
        report = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(report['mode'], 'inspection_only')
        self.assertEqual(report['windows_tasks']['reason_code'], 'interrupted')
        self.assertFalse(report['windows_tasks']['complete'])
        process.kill.assert_called_once()

    def test_cleanup_failure_is_not_hidden_or_waited_forever(self):
        process, context = self.fake_query(waits=[subprocess.TimeoutExpired('probe', 20),
                                                subprocess.TimeoutExpired('probe', 2)])
        with context:
            result = inspection.capture_task_query(['synthetic-probe'])
        self.assertFalse(result['query_process_stopped'])
        self.assertEqual(process.wait.call_count, 2)

    def test_failed_or_missing_command_is_unknown_not_no_tasks(self):
        _, context = self.fake_query(code=1)
        with context:
            self.assertEqual(inspection.capture_task_query(['fake'])['reason_code'], 'query_failed')
        with patch.object(inspection.subprocess, 'Popen', side_effect=OSError('private path')):
            result = inspection.capture_task_query(['fake'])
        self.assertFalse(result['complete'])
        self.assertNotIn('private path', json.dumps(result))

    def test_invalid_output_never_becomes_empty_success(self):
        for value in (b'', b'\xff', [], {'tasks':[]}, b'x' * (2 * 1024 * 1024 + 1),
                      {'status':'read_only','complete':False,'tasks':[]}):
            with self.subTest(value_type=type(value).__name__):
                _, context = self.fake_query(value)
                with context:
                    result = inspection.capture_task_query(['fake'])
                self.assertEqual(result['reason_code'], 'invalid_output')
                self.assertFalse(result['complete'])

    def test_partial_results_preserve_unknown_coverage(self):
        value = {'status':'partial','complete':False,'tasks':[{'id':'synthetic'}], 'unreadable_count':1}
        _, context = self.fake_query(value)
        with context:
            self.assertEqual(inspection.capture_task_query(['fake']), value)

    def test_tasks_only_does_not_read_project_config(self):
        output = io.StringIO()
        with patch.object(inspection, 'inspect_project', side_effect=AssertionError('must not read config')), \
                patch.object(inspection, 'inspect_windows_tasks', return_value=inspection.unavailable('timeout')) as query, \
                redirect_stdout(output):
            self.assertEqual(inspection.main(['--tasks-only','--match','synthetic wrapper']), 0)
        query.assert_called_once_with(['synthetic wrapper'], progress=False)
        self.assertFalse(json.loads(output.getvalue())['complete'])

    def test_real_harmless_child_timeout_finishes(self):
        started = time.monotonic()
        result = inspection.capture_task_query([sys.executable,'-B','-s','-c','import time; time.sleep(60)'], timeout=.2)
        self.assertEqual(result['reason_code'], 'timeout')
        self.assertTrue(result['query_process_stopped'])
        self.assertLess(time.monotonic() - started, 5)

    @unittest.skipUnless(os.name == 'nt', 'PowerShell mock COM')
    def test_powershell_enumerates_mock_folders_and_redacts_actions(self):
        # This function shadows COM creation; no real Task Scheduler is queried.
        fixture = r'''
function New-Object([string]$ComObject) {
    if ($ComObject -ne 'Schedule.Service') { throw 'unexpected COM object' }
    $xml = '<Task><Principals><Principal><UserId>synthetic-user</UserId></Principal></Principals><Triggers><CalendarTrigger><StartBoundary>2026-10-21T16:30:00</StartBoundary><ScheduleByWeek><DaysOfWeek><Monday/></DaysOfWeek></ScheduleByWeek></CalendarTrigger></Triggers><Actions><Exec><Command>C:\synthetic\renamed.cmd</Command><Arguments>PRIVATE-SHOULD-NOT-PRINT</Arguments></Exec></Actions></Task>'
    $task = [pscustomobject]@{Name='unrelated-name'; Path='\Nested\unrelated-name'; Xml=$xml;
        State=3; Enabled=$false; NextRunTime='2026-10-21'; LastRunTime='2026-10-20'; LastTaskResult=0}
    $child = [pscustomobject]@{Path='\Nested'; SavedTask=$task}
    $child | Add-Member ScriptMethod GetTasks {param($flags) if ($flags -ne 1) { throw 'hidden tasks missing' }; return @($this.SavedTask)}
    $child | Add-Member ScriptMethod GetFolders {param($flags) return @()}
    $root = [pscustomobject]@{Path='\'; Child=$child}
    $root | Add-Member ScriptMethod GetTasks {param($flags) return @()}
    $root | Add-Member ScriptMethod GetFolders {param($flags) return @($this.Child)}
    $service = [pscustomobject]@{Root=$root}
    $service | Add-Member ScriptMethod Connect {}
    $service | Add-Member ScriptMethod GetFolder {param($path) return $this.Root}
    return $service
}
'''
        script = fixture + inspection.task_query_script([r'C:\synthetic\renamed.cmd'])
        command = ['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',
                   base64.b64encode(script.encode('utf-16le')).decode('ascii')]
        result = inspection.capture_task_query(command)
        self.assertTrue(result['complete'], result)
        self.assertEqual(result['searched_folders'], 2)
        self.assertEqual(len(result['tasks']), 1)
        self.assertFalse(result['tasks'][0]['enabled'])
        self.assertEqual(result['tasks'][0]['triggers'][0]['days_of_week'], ['Monday'])
        self.assertNotIn('PRIVATE-SHOULD-NOT-PRINT', json.dumps(result))
