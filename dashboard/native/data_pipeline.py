"""Shared, non-modal history → finite probe → continuous collection lifecycle."""
from collections import deque
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import time
import uuid

from PySide6.QtCore import QObject,QThreadPool,QTimer,Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QPlainTextEdit

from dashboard.refresh_evidence import utc_now
from dashboard.marketdata.bars import _atomic_bytes,_json_bytes
from .history_maintenance import HistoryMaintenance


class DataPipeline(QObject):
    changed=Signal()

    def __init__(self,window,*,enabled=True,auto_inspect=True):
        super().__init__(window);self.window=window;self.model=window.model;self.collection=window.collection
        self.history=HistoryMaintenance(self.model);self.pool=QThreadPool(self);self.pool.setMaxThreadCount(1)
        self.task=None;self.phase='cache';self.message='读取已有数据';self.quick={};self.credentials={};self.probe={}
        self.enabled=enabled;self.closing=False;self.action=None;self.deep=False;self.once=False;self.force=False;self.pending_reference=None;self.force_reference=False
        self.shutdown_started=None;self.shutdown_finished=None
        self.next_retry=0;self.history_retry=0;self.history_not_before=0;self.quick_due=0;self.last_day=None
        self.latest_snapshot={};self.reference_started=False;self.completed_target=None
        from dashboard.marketdata.overview_sessions import latest_completed_session
        try:self.completed_target=latest_completed_session()
        except ValueError:pass
        self.run_id=uuid.uuid4().hex;self.samples=deque(maxlen=900);self.applied={}
        self.realtime_dialog=None;self.prompted_key=None;self.awaiting_realtime=False
        from .overview_reference_job import ReferenceJob
        self.overview_reference=ReferenceJob(self.model.local_root) if getattr(window,'market_mode',False) else None
        from .overview_dividend_job import DividendJob
        self.overview_dividends=DividendJob(self.model.local_root) if getattr(window,'market_mode',False) else None
        self.report_path=Path(__file__).resolve().parents[1]/'runtime/app_sessions'/self.run_id/'status.json'
        self.timer=QTimer(self);self.timer.setInterval(1000);self.timer.timeout.connect(self.tick);self.timer.start()
        if auto_inspect:QTimer.singleShot(0,self.inspect)

    def set_state(self,phase,message):
        self.phase=phase;self.message=message;self.changed.emit()

    def instance_ready(self):
        instance=getattr(self.window,'instance_lease',None)
        if instance is not None and not instance.owned:
            self.set_state('waiting_previous_app','旧看板尚未安全退出或启动协调受限；此窗口只读，请待旧任务完成后重新打开。不会强杀或删除锁。')
            return False
        return True

    def submit(self,fn,done):
        if self.task is not None or self.closing:return False
        from .app import Task
        self.task=Task(fn)
        def finish(value):
            self.task=None
            if not self.closing:done(value)
        self.task.signals.completed.connect(finish)
        self.task.signals.failed.connect(lambda error:finish(dict(failed=True,error_type=error.split(':')[0])))
        self.pool.start(self.task);return True

    def inspect(self):
        from dashboard.marketdata.history_quick import quick_check
        from dashboard.app_config import credential_state
        config=deepcopy(self.model.config)
        def work():
            from dashboard.app_preview import load
            pending=None
            try:
                from dashboard.marketdata.overview_daily import requests
                from dashboard.marketdata.overview_sessions import latest_completed_session
                from dashboard.marketdata.contract_reference import latest_contracts
                from dashboard.marketdata.repository import ReferenceBook
                jobs=requests(config,self.model.local_root,latest_completed_session(),latest_contracts(ReferenceBook(config.get('reference_file')).data))
                pending=sum(len(j['symbols']) for j in jobs)
            except (OSError,ValueError,TypeError,KeyError):pass
            return dict(quick=quick_check(config),overview_pending=pending,credentials=credential_state(config,self.model.local_root),preview=load(config))
        def done(result):
            self.quick=result.get('quick',{});self.credentials=result.get('credentials',{})
            if result.get('preview') and self.window.state is None and not self.window.generation:
                self.window.quotes.render(result['preview'])
                self.window.status.setText('先显示同一配置的启动缓存；实际源时见卡片，等待本轮计算。')
            self.quick_due=time.monotonic()+30
            if not self.instance_ready():return
            if self.enabled and not self.action:
                if self.model.config.get('history_maintenance_enabled',True) and (result.get('overview_pending') or 0)>0:
                    self.request_history(force=False)
                else:self.request_realtime()
            elif not self.enabled:self.set_state('cache','只读缓存；自动更新已关闭')
        self.submit(work,done)

    def request_history(self,deep=False,*,force=True):
        if self.closing or not self.instance_ready():return
        self.dismiss_realtime_prompt();self.awaiting_realtime=False;self.prompted_key=None
        self.enabled=True;self.action='history';self.deep=deep;self.force=force;self.history_retry=time.monotonic()+300
        self.collection.stop();self.model.realtime_verified=False
        self.set_state('draining_realtime','等待本轮实时请求与落库安全结束，再开始'+('后台深核' if deep else '日期增量维护'))

    def one_click(self,*,force_reference=True,force_history=True):
        """Reference first, then one owned DDB cycle; never entered by HTTP retry."""
        if self.closing or not self.instance_ready():return
        if self.history.process is not None:
            self.set_state('history','DDB补齐正在运行；不重复启动，请等待或在数据更新页取消');return
        self.enabled=True;self.dismiss_realtime_prompt();self.awaiting_realtime=False
        if self.overview_reference is None or self.model.config.get('overview_wind_enabled',True) is False:
            self.request_history(force=force_history);return
        self.action='reference_before_history';self.force=force_history;self.reference_started=False
        self.force_reference=force_reference
        self.set_state('reference_before_history','先复核Wind低频成分/权重及ETF规模，再用DDB补齐最近收盘；现有数据保持可读')

    def request_realtime(self,once=False,*,force_reference=False):
        if self.closing or not self.instance_ready():return
        self.dismiss_realtime_prompt();self.awaiting_realtime=False
        self.enabled=True;self.action='realtime';self.once=once;self.next_retry=0
        if self.overview_reference is not None and self.overview_reference.closed and not self.overview_reference.running():
            from .overview_reference_job import ReferenceJob
            self.overview_reference=ReferenceJob(self.model.local_root)
        self.force_reference=force_reference
        self.history.pause()
        self.collection.stop();self.model.realtime_verified=False
        self.set_state('draining_history','等待历史会话和本轮采集安全退出，再验证当前网络；公司网络能直连时无需另连VPN')

    def readonly(self):
        self.dismiss_realtime_prompt();self.awaiting_realtime=False
        self.enabled=False;self.action=None;self.history.pause();self.collection.stop()
        if self.overview_reference is not None:self.overview_reference.stop()
        if self.overview_dividends is not None:self.overview_dividends.stop()
        self.set_state('draining','正在安全停止本轮后台；保留已发布数据')

    def refresh_dividends(self):
        if self.closing or not self.instance_ready() or self.overview_dividends is None:return
        if self.overview_dividends.closed and not self.overview_dividends.running():
            from .overview_dividend_job import DividendJob
            self.overview_dividends=DividendJob(self.model.local_root)
        self.overview_dividends.tick(self.model.config,enabled=True,force=True)
        self.changed.emit()

    def start_probe(self):
        if not self.instance_ready() or self.history.process is not None or self.task or self.collection.running():return
        from dashboard.session_guard import probe_realtime
        from dashboard.session_clock import session_policy
        policy=session_policy()
        if not policy['allowed']:
            self.start_snapshot();return
        self.set_state('probing','正在有限验证实时接口；尚未证明持续采集或新行情到达')
        config=deepcopy(self.model.config)
        force_reference=self.force_reference;self.force_reference=False
        def done(result):
            self.probe=result;self.next_retry=time.monotonic()+30
            if not self.enabled or self.action is not None:return
            if result.get('ok'):
                self.model.realtime_verified=True
                from .instruments import UNDERLYINGS
                indexes={v[0] for v in UNDERLYINGS.values()}
                try:
                    self.collection.start(config.get('realtime_root'),list(indexes),indexes,config.get('reference_file'),
                                          once=self.once,auto_roll=True,config=config)
                    self.set_state('collecting','有限验证成功；已请求持续采集，等待首批有效行情落库')
                    if self.once:self.enabled=False;self.once=False
                except Exception as exc:self.set_state('failed','采集启动失败：'+type(exc).__name__)
            else:
                is_lock=(result.get('error') or {}).get('stage')=='network_lock'
                self.set_state('waiting_lock' if is_lock else 'waiting_network',result.get('message','有限验证失败；保留缓存，30秒后重试')+
                    (' 当前窗口没有启动采集；仍可读取其他采集者写入的行情，ETF可能尚未订阅。' if is_lock else ''))
                self.offer_realtime_prompt(result)
        def work():
            result=probe_realtime(config,timeouts=(1,2))
            if force_reference or not result.get('ok') and result.get('diagnostics',{}).get('stage')=='reference_read':
                from dashboard.session_guard import network_lease
                from dashboard.marketdata.contract_reference import synchronize
                with network_lease(config):
                    reference=synchronize(config.get('reference_file'),self.model.local_root/'contract_reference',quote_checker=None,force=force_reference)
                config['reference_file']=reference['reference_file'];self.pending_reference=reference['reference_file']
                result=probe_realtime(config,timeouts=(1,2))
            return result
        self.submit(work,done)

    def start_snapshot(self):
        from .latest_snapshot import collect
        config=deepcopy(self.model.config);self.next_retry=time.monotonic()+60
        self.set_state('market_snapshot','盘前盘后：有限获取最新快照；不视为实时，不自动操作实时VPN')
        def done(result):
            self.latest_snapshot=result;self.next_retry=time.monotonic()+60
            if not self.enabled or self.action is not None:return
            self.set_state('market_closed','盘前盘后快照已获取；源时间及日期依据见卡片' if result.get('status')=='snapshot_received' else
                           '盘前盘后快照未取得；保留已有源时间，60秒后重试，不自动切回DDB')
            if hasattr(self.window,'refresh'):self.window.refresh()
        self.submit(lambda:collect(config,self.model.local_root,stop=lambda:self.closing or not self.enabled),done)

    def dismiss_realtime_prompt(self):
        dialog=self.realtime_dialog;self.realtime_dialog=None
        if dialog is not None:
            dialog.blockSignals(True);dialog.close();dialog.deleteLater()

    def offer_realtime_prompt(self,result):
        from dashboard.session_clock import realtime_prompt_policy
        policy=realtime_prompt_policy()
        diagnostics=result.get('diagnostics') or {}
        stage=diagnostics.get('stage','')
        # A held lock or bad contract reference is not a request to switch VPN.
        network_failure=stage=='http_request' and diagnostics.get('status') in (
            'timeout','connection_error','proxy_error','request_error','tls_error','http_error')
        if not (self.enabled and not self.closing and policy['allowed'] and network_failure):return
        if self.history.process is not None or self.collection.running() or self.realtime_dialog is not None:return
        if self.prompted_key==policy['key']:return
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QMessageBox
        self.prompted_key=policy['key'];self.awaiting_realtime=True
        dialog=QMessageBox(self.window);self.realtime_dialog=dialog
        dialog.setWindowTitle('请手动连接实时行情 VPN')
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating,True)
        history=self.history.state()
        note=history.get('message') or '历史任务已退出；已有数据保持可读。'
        dialog.setText('当前处于盘中，当前网络尚未连通行情源。\n本轮历史会话和登录辅助任务已退出。\n公司网络可直连时可直接重试；需要实时VPN时请手动连接。')
        dialog.setInformativeText(note+'\n连接完成后点击“已连接，验证并开始”。程序不会自动登录实时 VPN 或自动退出 DDB VPN。')
        connected=dialog.addButton('已连接，验证并开始',QMessageBox.ButtonRole.AcceptRole)
        later=dialog.addButton('稍后连接（只读）',QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(later)
        def finished(_):
            if self.realtime_dialog is not dialog:return
            accepted=dialog.clickedButton() is connected
            self.dismiss_realtime_prompt();self.awaiting_realtime=False
            if accepted:self.request_realtime()
            else:self.readonly()
        dialog.finished.connect(finished)
        self.set_state('waiting_realtime_vpn','请手动连接实时行情VPN；连接后确认，或选择稍后只读')
        dialog.show()

    def tick(self):
        code=self.history.tick()
        if self.overview_dividends is not None:
            owner=getattr(self.window,'instance_lease',None)
            eligible=self.enabled and not self.closing and self.task is None and self.action!='history' and (owner is None or owner.owned)
            if eligible and self.overview_dividends.closed and not self.overview_dividends.running():
                from .overview_dividend_job import DividendJob
                self.overview_dividends=DividendJob(self.model.local_root)
            self.overview_dividends.tick(self.model.config,enabled=eligible)
        if self.overview_reference is not None:
            eligible=(self.enabled and not self.closing and
                self.action is None and self.history.process is None and self.task is None and
                self.phase in ('collecting','market_closed','waiting_network','waiting_lock','history_wait'))
            reason=('看板正在关闭' if self.closing else '当前为只读或已暂停后台' if not self.enabled else
                    '等待历史任务安全结束' if self.history.process is not None or self.action=='history' else
                    '等待当前验证任务完成' if self.task is not None else '等待数据流程就绪：'+self.phase)
            if eligible and self.overview_reference.closed and not self.overview_reference.running():
                from .overview_reference_job import ReferenceJob
                self.overview_reference=ReferenceJob(self.model.local_root)
            if self.action!='reference_before_history':
                self.overview_reference.tick(self.model.config,enabled=eligible,blocked_reason=reason)
        if self.realtime_dialog is not None:
            from dashboard.session_clock import realtime_prompt_policy
            if not realtime_prompt_policy()['allowed']:
                self.dismiss_realtime_prompt();self.awaiting_realtime=False
        reference=self.collection.state().get('reference',{}).get('reference_file') or self.pending_reference
        if reference and reference!=self.model.config.get('reference_file') and not self.window.busy:
            self.model.config['reference_file']=reference;self.pending_reference=None
            self.window.generation=getattr(self.window,'generation',0)+1
        if self.closing:
            self.set_state('closing',self.shutdown_message())
        elif not self.instance_ready():pass
        elif self.action=='reference_before_history':
            if not self.task and self.history.process is None:
                job=self.overview_reference
                if not self.reference_started:
                    if job.closed:
                        if job.running():
                            self.set_state('reference_before_history','等待先前Wind只读查询安全结束，再开始本轮补齐')
                            self.write_report();return
                        from .overview_reference_job import ReferenceJob
                        job=self.overview_reference=ReferenceJob(self.model.local_root)
                    job.tick(self.model.config,enabled=True,force=self.force_reference)
                    self.reference_started=True
                if not job.running():self.request_history(force=self.force)
                else:self.set_state('reference_before_history','Wind低频资料复核中；完成后自动开始DDB补齐，不重复下载或切换实时VPN')
        elif self.action=='history':
            if not self.collection.running() and not self.task and self.history.process is None and time.monotonic()>=self.history_not_before:
                self.history.authorized=True
                if self.history.start(deep=self.deep,force=self.force):
                    self.action=None;self.set_state('history','正在后台'+('完整深核' if self.deep else '增量维护'))
                else:
                    self.action=None;self.set_state('history_wait',self.history.state().get('message','历史配置待处理'))
                    self.next_retry=time.monotonic()+1
        elif self.action=='realtime':
            if self.history.process is None and not self.task and not self.collection.running():
                self.action=None;self.start_probe()
        elif self.history.process is not None:
            s=self.history.state();side=s.get('overview_daily') or {}
            note=('；概览收盘 '+str(side.get('target'))+'，剩余 '+str(side.get('pending_rows',0))+' 条') if side else ''
            self.set_state('history',s.get('message','历史任务运行中')+note+'；旧结果继续可读')
        elif code is not None:
            self.history.authorized=False
            self.history_retry=time.monotonic()+300
            self.set_state('history_finished',self.history.state().get('message','历史进程已退出'))
            # Re-inspect metadata without relaunching maintenance.
            from dashboard.marketdata.history_quick import quick_check
            self.submit(lambda:quick_check(deepcopy(self.model.config)),lambda value:setattr(self,'quick',value))
            self.next_retry=time.monotonic()+1
            state=self.history.state()
            progress=state.get('inserted',0)+state.get('overview_daily',{}).get('inserted',0)
            if self.enabled and state.get('state')=='partial' and progress>0 and (state.get('next_retry') or 0)<=time.time()+30:
                self.request_history(force=False)
                self.history_not_before=time.monotonic()+max(1,(state.get('next_retry') or time.time())-time.time())
        elif self.collection.running():
            s=self.collection.state()
            if s.get('status')=='disconnected':message='请求失败/超时；持续采集会退避后重连，缓存保持原源时'
            elif s.get('data_sequence'):message='持续采集运行中；行情有效性与各腿源时仍逐行核验'
            else:message='采集任务运行中；尚未收到有效新行情'
            if s.get('status')=='running' and self.applied.get('source_times'):
                sources=self.applied['source_times'].values()
                if not any(v.get('quality',{}).get('usable') for v in sources):
                    message='请求及落库在推进；当前已显示版本无新鲜有效行情，展开诊断查看源延迟/计算延迟'
            self.set_state('collecting',message)
        elif self.awaiting_realtime:
            self.set_state('waiting_realtime_vpn','等待你手动连接实时VPN；程序不会自动切回DDB网络')
        elif not self.enabled:
            self.set_state('cache','只读缓存；未把计算时间当作行情时间')
        elif not self.task and time.monotonic()>=self.next_retry:
            self.next_retry=time.monotonic()+30;self.start_probe()
        if not self.closing and self.enabled and not self.awaiting_realtime and not self.task and self.history.process is None and not self.action:
            from dashboard.session_clock import session_policy
            from zoneinfo import ZoneInfo
            day=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
            if self.last_day is None:self.last_day=day
            elif self.last_day!=day:
                self.last_day=day
                if self.model.config.get('history_maintenance_enabled',True):self.request_history(force=False)
            from dashboard.marketdata.overview_sessions import latest_completed_session
            try:target=latest_completed_session()
            except ValueError:target=None
            if self.completed_target is None:self.completed_target=target
            elif target and self.completed_target!=target:
                self.completed_target=target
                if self.model.config.get('history_maintenance_enabled',True):self.request_history(force=False)
            # Realtime retries must never reconnect the DDB VPN behind the user.
            # Further history work starts only for a calendar boundary (including
            # a newly completed close) or an explicit request, never an HTTP retry.
        self.write_report();self.changed.emit()

    def record_applied(self,value):
        self.applied=value;self.write_report()

    def report(self):
        config=self.model.config
        state=self.collection.state()
        collection={k:state.get(k) for k in ('status','stage','polls','rows','data_sequence','valid_rows','validation_status',
            'invalid_symbols','request_started_at','request_seconds','received_at','storage_finished_at','storage_seconds',
            'last_result','missing_symbols','diagnostics','last_success_at','last_failure_at','last_failure_status',
            'interval_seconds','request_timeouts','equities')}
        h=self.history.state()
        history={k:h.get(k) for k in ('state','message','target','scan_id','scan_groups','scan_total','unknown_groups',
            'pending_symbol_days','missing_bars','scan_complete','verification_scope','scan_metrics','error_type','exit_code','ddb_vpn','overview_daily','overview_continuous',
            'scope','research_downloads_enabled')}
        vpn=h.get('ddb_vpn') or {}
        instance=getattr(self.window,'instance_lease',None)
        overview=(getattr(self.window,'state',None) or {}).get('market_overview') or {}
        coverage={key:dict(total=len(overview.get(key,[])),valid=sum(bool(r.get('quality',{}).get('usable')) for r in overview.get(key,[])),
                          observed=sum(r.get('source_at') is not None for r in overview.get(key,[]))) for key in ('indices','etfs','futures')}
        return dict(schema='app-update-evidence-v1',run_id=self.run_id,pid=os.getpid(),observed_at=utc_now(),python=sys.executable,
            phase=self.phase,message=self.message,closing=self.closing,history_worker_running=self.history.process is not None,
            shutdown=self.shutdown_state(),
            history_pid=self.history.process.pid if self.history.process else None,
            collection_worker_running=self.collection.running(),quick=self.quick,credentials=self.credentials,
            finite_probe=self.probe,collection=collection,history=history,applied=self.applied,
            calculation=getattr(self.model,'refresh_trace',{}),queue=dict(active=int(self.window.busy),pending=int(self.window.pending)),
            paths={k:config.get(k) for k in ('history_roots','reference_file','realtime_root')},
            local_root=str(self.model.local_root),network_policy='auto_ddb_manual_realtime',
            vpn_changed=None if vpn.get('state') in ('connecting','failed','cancelled') else vpn.get('mode')=='native_login',
            realtime_vpn_automatic=False,awaiting_realtime_vpn=self.awaiting_realtime,
            instance_handover=instance.summary() if instance is not None else None,overview_coverage=coverage,
            overview_runtime=dict(schema='overview-runtime-v2',pipeline_enabled=self.enabled,
                latest_snapshot=self.latest_snapshot,
                dividend_scheduler=self.overview_dividends.state() if self.overview_dividends is not None else None,
                reference_scheduler=self.overview_reference.state() if self.overview_reference is not None else None))

    def write_report(self):
        try:
            value=self.report();_atomic_bytes(self.report_path,_json_bytes(value))
        except (OSError,ValueError,TypeError):return

    def export(self):
        path=self.report_path.parent/('report-'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.json')
        _atomic_bytes(path,_json_bytes(self.report()))
        self.set_state(self.phase,'诊断已保存：'+str(path))
        return path

    def stop(self):
        if self.closing:return
        self.dismiss_realtime_prompt();self.awaiting_realtime=False
        self.shutdown_started=time.monotonic()
        self.closing=True;self.enabled=False;self.history.stop();self.collection.stop();self.write_report()
        if self.overview_reference is not None:self.overview_reference.stop()
        if self.overview_dividends is not None:self.overview_dividends.stop()

    def shutdown_state(self):
        if self.shutdown_started is None:return dict(requested=False)
        waiting=[]
        for active,label in ((self.window.busy,'页面计算'),(self.collection.running(),'行情采集/归档'),
                (self.history.process is not None,'历史写入'),(self.task is not None,'后台检查'),
                (self.overview_reference is not None and self.overview_reference.running(),'Wind资料'),
                (self.overview_dividends is not None and self.overview_dividends.running(),'分红同步'),
                (getattr(getattr(self.window,'query_page',None),'busy',False),'行情查询')):
            if active:waiting.append(label)
        return dict(requested=True,complete=self.shutdown_finished is not None,waiting=waiting,
            elapsed_seconds=round((self.shutdown_finished or time.monotonic())-self.shutdown_started,3),
            equities=self.collection.state().get('equities'))

    def shutdown_message(self):
        state=self.shutdown_state();parts=['正在安全关闭']
        archive=(state.get('equities') or {}).get('archive') or {}
        if archive.get('status')=='archiving':
            parts.append('成分数据归档 '+str(archive.get('symbols_finished',0))+'/'+str(archive.get('symbols_total',0)))
        elif state.get('waiting'):parts.append('等待'+ '、'.join(state['waiting']))
        if state.get('elapsed_seconds') is not None:parts.append('已等待 '+str(int(state['elapsed_seconds']))+' 秒')
        return ' · '.join(parts)

    def finish_shutdown(self):
        self.shutdown_finished=time.monotonic();self.phase='closed';self.message='已安全关闭，写入已结束'
        self.write_report()

    def drained(self):
        self.history.tick()
        return self.history.process is None and self.task is None and not self.collection.running() and not (
            self.overview_reference is not None and self.overview_reference.running() or
            self.overview_dividends is not None and self.overview_dividends.running())


class PipelinePage(QWidget):
    def __init__(self,pipeline):
        super().__init__();self.pipeline=pipeline;layout=QVBoxLayout(self);row=QHBoxLayout()
        for title,fn in [('DDB一键补齐',pipeline.one_click),('更新分红',pipeline.refresh_dividends),('概览日线核验',lambda:pipeline.request_history(True)),
                         ('验证并开始实时',pipeline.request_realtime),('取消 / 只读缓存',pipeline.readonly),('导出诊断',self.export)]:
            button=QPushButton(title);button.clicked.connect(lambda checked=False,f=fn:f());row.addWidget(button)
        layout.addLayout(row)
        self.head=QLabel();self.head.setWordWrap(True);layout.addWidget(self.head)
        from .inline_settings import InlineSettings
        self.settings=InlineSettings(pipeline);layout.addWidget(self.settings)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);layout.addWidget(self.details,1)
        pipeline.changed.connect(self.refresh);self.refresh()

    def export(self):
        try:path=self.pipeline.export();self.head.setText('诊断已保存：'+str(path))
        except OSError as exc:self.head.setText('导出失败：'+type(exc).__name__)

    def refresh(self):
        p=self.pipeline;report=p.report()
        self.head.setText(p.message+'\n'+p.quick.get('message','日期快检进行中；不阻塞现有数据显示'))
        self.details.setPlainText(json.dumps(report,ensure_ascii=False,indent=2,default=str))
