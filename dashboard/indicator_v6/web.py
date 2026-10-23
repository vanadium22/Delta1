"""Loopback browser view of the same desktop result service; no trading or network actions."""
import argparse,json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from .service import Service,CARDS,variants,CHOICE_LABELS,variant_label
from .presentation import detail_html


def server(service,port=0):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def do_GET(self):
            if self.headers.get('Host') not in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'):
                self.send_error(403);return
            route=urlsplit(self.path);q=parse_qs(route.query)
            try:
                if route.path=='/':body=(Path(__file__).parent/'web.html').read_bytes();mime='text/html; charset=utf-8'
                elif route.path.startswith('/formula/') and route.path[9:] in {c+'_public.png' for c in CARDS}:
                    body=(Path(__file__).parent/'formula_assets'/route.path[9:]).read_bytes();mime='image/png'
                elif route.path=='/api/catalog':
                    body=json.dumps([dict(id=c['id'],title=c['title'],group=c['group'],variants=[dict(id=v,label=variant_label(c['id'],v)) for v in variants(c['id'])]) for c in CARDS.values()],ensure_ascii=False).encode();mime='application/json'
                elif route.path=='/api/indicator':
                    r=service.query(q.get('id',['A01'])[0],q.get('x',[None])[0],q.get('source',['replay'])[0],json.loads(q['identity'][0]) if q.get('identity') else None,q.get('day',[None])[0])
                    r['detail_html']=detail_html(r,formula_url='/formula/'+r['id']+'_public.png');r['advanced_html']=detail_html(r,True)
                    body=json.dumps(r,ensure_ascii=False,allow_nan=False).encode();mime='application/json'
                else:self.send_error(404);return
                self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'");self.end_headers();self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError):pass
            except (ValueError,OSError,KeyError) as exc:
                body=json.dumps({'error':str(exc)},ensure_ascii=False).encode();self.send_response(400);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)


def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8766);p.add_argument('--config',type=Path);args=p.parse_args()
    config=json.loads(args.config.read_text(encoding='utf8')) if args.config else {}
    app=server(Service(config),args.port);print(f'http://127.0.0.1:{app.server_port}',flush=True)
    try:app.serve_forever()
    except KeyboardInterrupt:pass
    finally:app.server_close()
if __name__=='__main__':main()
