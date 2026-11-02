"""Offscreen validation of new parameter pages and local interactive pair charts."""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
from time import monotonic, sleep
from urllib.request import urlopen


def browser_evidence(study,output,executable):
    """Use a separate headless browser profile; never attach to a user's browser."""
    import websocket
    profile=output/"browser_profile"
    profile.mkdir()
    errors,requests,pictures=[],[],[]
    with (output/"browser.stderr.log").open("wb") as log:
        process=subprocess.Popen([str(executable),"--headless=new","--disable-gpu","--no-first-run","--disable-extensions",
            "--disable-background-networking","--remote-debugging-port=0",f"--user-data-dir={profile}","about:blank"],
            stdout=subprocess.DEVNULL,stderr=log,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        connection=None
        try:
            active=profile/"DevToolsActivePort"
            deadline=monotonic()+25
            while not active.exists() and monotonic()<deadline:
                if process.poll() is not None:
                    raise AssertionError("Headless browser stopped before local validation")
                sleep(.05)
            assert active.exists(),"Headless browser did not start"
            port=int(active.read_text().splitlines()[0])
            with urlopen(f"http://127.0.0.1:{port}/json/list",timeout=5) as handle:
                pages=json.load(handle)
            page=next(p for p in pages if p["type"]=="page")
            connection=websocket.create_connection(page["webSocketDebuggerUrl"],timeout=15,suppress_origin=True)
            counter=0
            def call(method,params=None):
                nonlocal counter
                counter+=1
                connection.send(json.dumps(dict(id=counter,method=method,params=params or {})))
                while True:
                    message=json.loads(connection.recv())
                    if message.get("method")=="Runtime.exceptionThrown":
                        errors.append(message["params"]["exceptionDetails"])
                    if message.get("method")=="Network.requestWillBeSent":
                        url=message["params"]["request"]["url"]
                        if url.startswith(("http:","https:")):
                            requests.append(url)
                    if message.get("id")==counter:
                        assert "error" not in message,message
                        return message.get("result",{})
            def js(code):
                result=call("Runtime.evaluate",dict(expression=code,returnByValue=True))
                assert "exceptionDetails" not in result,result
                return result["result"].get("value")
            call("Page.enable")
            call("Runtime.enable")
            call("Network.enable")
            call("Network.setBlockedURLs",dict(urls=["http://*","https://*"]))
            call("Emulation.setDeviceMetricsOverride",dict(width=1920,height=1080,deviceScaleFactor=1,mobile=False))
            call("Page.navigate",dict(url=(study/"report.html").resolve().as_uri()))
            deadline=monotonic()+30
            while monotonic()<deadline:
                if js("document.readyState==='complete' && typeof DATA!=='undefined'"):
                    break
                sleep(.05)
            else:
                raise AssertionError("Local report did not finish loading")
            counts=js("({cases:Object.keys(DATA.cases).length,pairs:$('pair').options.length,structure:$('structure').children.length})")
            assert counts["structure"]>0
            checked=js("""(()=>{let checked=0;for(const key of Object.keys(DATA.cases)){
                $('case').value=key;caseChanged();for(const r of Object.keys(DATA.cases[key].roots)){
                $('root').value=r;rootChanged();for(const d of [0,Math.floor(+$('day').max/2),+$('day').max]){
                $('day').value=d;updateDay();if($('date').textContent!==DATA.cases[key].dates[d])throw Error('Wrong date');
                if(!Number.isFinite(DATA.cases[key].curves[r][d]))throw Error('Invalid return');checked++;}}}
                $('case').value=Object.keys(DATA.cases).find(k=>k==='quantile_pairs_0_9')||Object.keys(DATA.cases)[0];caseChanged();return checked;})()""")
            assert checked>0
            for anchor,name in (("window.scrollTo(0,0)","report_summary"),("$('case').closest('section').scrollIntoView()","report_pairs")):
                js(anchor)
                capture=call("Page.captureScreenshot",dict(format="png",captureBeyondViewport=False))
                file=output/(name+".png")
                file.write_bytes(base64.b64decode(capture["data"]))
                pictures.append(str(file))
            assert not errors,errors
            assert not requests,requests
            call("Browser.close")
            return dict(browser=counts,case_root_date_combinations=checked,js_errors=errors,network_requests=requests),pictures
        finally:
            if connection is not None:
                connection.close()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=10)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--browser",type=Path,default=Path("C:/Program Files/Google/Chrome/Application/chrome.exe"))
    args=parser.parse_args(argv)
    os.environ["QT_QPA_PLATFORM"]="offscreen"
    from PySide6.QtWidgets import QApplication
    from dashboard.backtest.__main__ import load_job
    from dashboard.backtest.desktop import BacktestWindow, configure_style
    from dashboard.backtest.io import write_json
    from dashboard.backtest.synthetic import write_inputs

    output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=False)
    app=QApplication.instance() or QApplication([])
    configure_style(app)
    job=load_job(write_inputs(output/"synthetic_inputs")/"structure.local.json")
    write_json(output/"job.local.json",job)
    window=BacktestWindow(config_path=output/"job.local.json")
    window.show()
    pictures=[]
    for width,height in ((1920,1080),(3840,2160)):
        window.resize(width,height)
        for tab in range(4):
            window.forms.setCurrentIndex(tab)
            app.processEvents()
            app.processEvents()
            assert window.forms.currentWidget().horizontalScrollBar().maximum()==0
            file=output/f"parameters_{width}_{tab}.png"
            assert window.grab().save(str(file))
            pictures.append(str(file))
    recovered=window.job()
    for key in ("window_days","degree","min_training_samples","quantiles"):
        assert list(recovered["factor"]["parameters"][key])==list(job["factor"]["parameters"][key]) if key=="quantiles" else recovered["factor"]["parameters"][key]==job["factor"]["parameters"][key]
    assert recovered["backtest"]["preserve_pair_lots"]
    window.close()
    app.processEvents()

    browser,browser_pictures=browser_evidence(args.study,output,args.browser)
    write_json(output/"validation.local.json",dict(status="passed",pictures=pictures+browser_pictures,**browser,
        desktop="four parameter pages, 1080p/4K"))
    print(output/"validation.local.json")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
