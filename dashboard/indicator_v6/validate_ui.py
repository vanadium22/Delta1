"""Offscreen native validation with actual widgets and no VPN / realtime access."""
import os,time,json
from pathlib import Path
os.environ['QT_QPA_PLATFORM']='offscreen'
from dashboard.native.bootstrap import configure_qt
configure_qt()
from PySide6.QtWidgets import QApplication,QPushButton
from dashboard.native.app import configure_style
from dashboard.native.research_v6_view import ResearchV6Page
from dashboard.indicator_v6.service import Service


def main():
    app=QApplication([]);configure_style(app);service=Service();out=Path(__file__).resolve().parents[1]/'outputs/2026-10-23/app_v6_validation';out.mkdir(parents=True,exist_ok=True)
    results=[]
    for group,code,width in [('A','A02',1440),('B','B08',1100),('C','C04',1440)]:
        page=ResearchV6Page(group,service);page.resize(width,1000);page.show();page.indicator.setCurrentIndex(page.indicator.findData(code))
        deadline=time.monotonic()+60
        while page.result is None and time.monotonic()<deadline:app.processEvents();time.sleep(.02)
        assert page.result is not None,page.note.text()
        for _ in range(10):app.processEvents()
        assert page.result['id']==code
        assert len(page.charts)==len({(f['frequency'],'pct' if f['key']=='K' else f['unit']) for f in page.result['fields']})
        for chart in page.charts:
            hint=chart.hover_text(0);assert hint and '202' in hint
        page.grab().save(str(out/f'native_{code}_{width}.png'))
        toggle=next(b for b in page.findChildren(QPushButton) if b.text().startswith('展开'))
        toggle.click();app.processEvents();page.grab().save(str(out/f'native_{code}_formula.png'))
        results.append(dict(code=code,width=width,fields=len(page.result['fields']),charts=len(page.charts),status=page.result['status']))
        saved=page.result;page.freeze(saved);app.processEvents()
        assert not page.variant.isEnabled() and page.result['cache_key']==saved['cache_key']
        page.pool.waitForDone();page.close();app.processEvents()
    (out/'native_validation.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(results,ensure_ascii=False))
if __name__=='__main__':main()
