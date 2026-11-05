"""Public review HTTP service. Only explicitly selected images and review data are exposed."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from http.cookies import SimpleCookie
import collections
import contextlib
import io
import json
import os
from ai_glasses.config import REVIEWERS
from pathlib import Path
import re
import secrets
import uuid
import concurrent.futures
import threading
import time
from urllib.parse import parse_qs,urlsplit
from ai_glasses.review import public_review_store as store
from ai_glasses.generation import tryon_lab as lab

PUBLIC_ORIGIN=os.environ.get('REVIEW_PUBLIC_ORIGIN','http://127.0.0.1:8790')
LIMITS=collections.defaultdict(collections.deque);RATE_LOCK=threading.Lock()
CACHE_EXECUTOR=concurrent.futures.ThreadPoolExecutor(max_workers=2)
def image_bytes(path,sha):
    cache=lab.ROOT/'work'/'review_image_cache';cache.mkdir(parents=True,exist_ok=True)
    key=sha or lab.digest(path);target=cache/(key+'.jpg')
    if not target.is_file():
        from PIL import Image,ImageOps
        im=ImageOps.exif_transpose(Image.open(path)).convert('RGB');im.thumbnail((1600,1600))
        tmp=target.with_suffix('.'+uuid.uuid4().hex+'.tmp');im.save(tmp,'JPEG',quality=94);os.replace(tmp,target)
    return target.read_bytes()

def warm_batch(c,ids):
    for key in ids:
        row=c.execute('SELECT output,output_sha256,condition FROM jobs WHERE id=?',(key,)).fetchone()
        if not row:continue
        source=c.execute('SELECT path,sha256 FROM sources WHERE id=?',(json.loads(row['condition'])['source_id'],)).fetchone()
        paths=[(row['output'],row['output_sha256'])]
        if source:paths.append((source['path'],source['sha256']))
        for path,sha in paths:
            if path and Path(path).is_file():CACHE_EXECUTOR.submit(image_bytes,path,sha)

class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,fmt,*args):pass
    def session(self):
        cookie=SimpleCookie()
        try:cookie.load(self.headers.get('Cookie',''))
        except Exception:pass
        value=cookie['review_session'].value if 'review_session' in cookie else ''
        self.new_cookie=not bool(re.fullmatch('[a-f0-9]{48}',value))
        return secrets.token_hex(24) if self.new_cookie else value
    def actor(self):
        token=self.headers.get('X-Review-Tab','')
        return self.sid+':'+token if re.fullmatch('[a-f0-9]{32}',token) else self.sid
    def send(self,status,value,ctype='application/json; charset=utf-8',etag=None):
        raw=value if isinstance(value,bytes) else (value.encode() if isinstance(value,str) else json.dumps(value,ensure_ascii=False).encode())
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(raw)))
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','same-origin')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.send_header('Cache-Control','private, max-age=3600' if etag else 'no-store')
        if etag:self.send_header('ETag','"'+etag+'"')
        if getattr(self,'new_cookie',False):
            secure='; Secure' if self.headers.get('Host','').startswith('rtx-') else ''
            self.send_header('Set-Cookie','review_session='+self.sid+'; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000'+secure)
        self.end_headers()
        if self.command!='HEAD':self.wfile.write(raw)
    def do_GET(self):
        self.sid=self.session();url=urlsplit(self.path);q=parse_qs(url.query)
        try:
            if url.path=='/review-settings.js':
                settings=json.dumps(dict(reviewers=REVIEWERS),ensure_ascii=True)
                return self.send(200,'window.reviewSettings = '+settings+';', 'text/javascript; charset=utf-8')
            if url.path in ('/','/app.js','/app.css'):
                name={'/':'public_review.html','/app.js':'public_review.js','/app.css':'public_review.css'}[url.path]
                ct={'/':'text/html; charset=utf-8','/app.js':'text/javascript; charset=utf-8','/app.css':'text/css; charset=utf-8'}[url.path]
                return self.send(200,(Path(__file__).parent/name).read_bytes(),ct)
            with contextlib.closing(lab.connect()) as c:
                if url.path=='/api/catalog':
                    jobs=store.catalog(c);requests=store.request_rows(c)
                    portraits=[]
                    for r in c.execute("SELECT j.id,j.condition FROM jobs j WHERE j.kind='portrait' AND j.status='success' AND j.rowid=(SELECT max(x.rowid) FROM jobs x WHERE x.kind='portrait' AND x.status='success' AND json_extract(x.condition,'$.person_id')=json_extract(j.condition,'$.person_id'))"):
                        con=json.loads(r['condition'])
                        if con.get('cohort') in ('korean_students_v1','user_people_v1'):portraits.append(dict(id=r['id'],person_id=con['person_id'],hair=con['hair'],description=con.get('description',''),cohort=con.get('cohort'),face_origin=con.get('face_origin')))
                    pending=c.execute("SELECT count(*) FROM jobs WHERE status IN ('pending','running','interrupted','blocked_dependency') AND (json_extract(condition,'$.cohort')='korean_students_v1' OR json_extract(condition,'$.batch')='public_regeneration')").fetchone()[0]
                    return self.send(200,dict(jobs=jobs,requests=requests,portraits=portraits,pending=pending,review_stats=store.review_stats(c),dataset_stats=store.dataset_stats(c),last_reviewed=store.last_reviewed(c),claims=store.active_claims(c,self.actor()),updated=lab.now()))
                if url.path=='/api/detail':
                    key=q.get('id',[''])[0];j=store.valid_job(c,key)
                    row=c.execute('SELECT data,updated FROM review_drafts WHERE job_id=? AND session=?',(key,self.actor())).fetchone()
                    reviewed=c.execute('SELECT updated FROM reviews WHERE job_id=?',(key,)).fetchone()
                    draft=json.loads(row['data']) if row and (not reviewed or row['updated']>reviewed['updated']) else None
                    history=[dict(x) for x in c.execute("SELECT e.id,e.decision,e.comment,e.reviewer,e.updated,coalesce(m.method,'detailed') AS method FROM review_events e LEFT JOIN review_methods m ON m.event_id=e.id WHERE e.job_id=? ORDER BY e.id DESC",(key,))]
                    return self.send(200,dict(draft=draft,history=history,version=store.version(c,key)))
                if url.path=='/api/image':
                    key=q.get('id',[''])[0];which=q.get('which',['result'])[0]
                    j=c.execute("SELECT * FROM jobs WHERE id=? AND status='success'",(key,)).fetchone()
                    if not j:return self.send(404,dict(error='이미지가 없습니다.'))
                    con=json.loads(j['condition']);path=j['output'];sha=j['output_sha256']
                    if j['kind']=='portrait' and con.get('cohort') not in ('korean_students_v1','user_people_v1'):return self.send(404,dict(error='이미지가 없습니다.'))
                    if which=='source' and j['kind']=='tryon':
                        s=c.execute('SELECT path,sha256 FROM sources WHERE id=?',(con['source_id'],)).fetchone();path=s['path'];sha=s['sha256']
                    elif which=='portrait' and j['kind']=='tryon':
                        p=c.execute("SELECT output,output_sha256 FROM jobs WHERE id=? AND status='success'",(con['portrait_job'],)).fetchone()
                        if not p:return self.send(404,dict(error='인물 이미지가 없습니다.'))
                        path=p['output'];sha=p['output_sha256']
                    elif which=='side' and j['kind']=='tryon':
                        refs=con.get('extra_references',[])
                        if not refs:return self.send(404,dict(error='이 결과는 옆면 사진을 사용하지 않았습니다.'))
                        path=refs[0]['path'];sha=refs[0]['sha256']
                    elif which not in ('result','source'):return self.send(400,dict(error='이미지 종류를 확인하세요.'))
                    if not path or not Path(path).is_file():return self.send(404,dict(error='이미지가 없습니다.'))
                    return self.send(200,image_bytes(path,sha),'image/jpeg',sha)
                if url.path=='/api/health':return self.send(200,dict(ok=True,time=lab.now()))
            self.send(404,dict(error='페이지가 없습니다.'))
        except (ValueError,KeyError,TypeError) as e:self.send(400,dict(error=str(e)))
        except Exception:
            import traceback;traceback.print_exc();self.send(500,dict(error='처리하지 못했습니다. 잠시 후 다시 시도하세요.'))
    def do_POST(self):
        self.sid=self.session()
        allowed=(PUBLIC_ORIGIN,f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}')
        if self.headers.get('Origin') not in allowed:return self.send(403,dict(error='허용되지 않은 요청입니다.'))
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.send(415,dict(error='JSON 요청이 필요합니다.'))
        with RATE_LOCK:
            times=LIMITS[self.sid];now=time.monotonic()
            while times and times[0]<now-60:times.popleft()
            if len(times)>=90:return self.send(429,dict(error='요청이 많습니다. 잠시 후 다시 시도하세요.'))
            times.append(now)
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n<1 or n>12000:return self.send(413,dict(error='요청 크기를 확인하세요.'))
            data=json.loads(self.rfile.read(n))
            with contextlib.closing(lab.connect()) as c:
                if self.path=='/api/batch':
                    result=store.claim_batch(c,self.actor(),data.get('reviewer'),data.get('filters'),data.get('preferred'),data.get('skip'));warm_batch(c,result['ids'])
                elif self.path=='/api/claim':result=store.claim(c,self.actor(),data.get('reviewer'),data.get('filters'),data.get('preferred'),data.get('skip'),data.get('completed') is True)
                elif self.path=='/api/heartbeat':result=store.heartbeat(c,data['id'],self.actor(),data.get('activity'))
                elif self.path=='/api/release':result=store.release(c,data['id'],self.actor(),data.get('all_reserved') is True)
                elif self.path=='/api/draft':
                    store.assert_claim(c,data['id'],self.actor());result=store.draft(c,data['id'],self.actor(),data)
                elif self.path=='/api/submit':result=store.submit(c,data['id'],self.actor(),data,require_claim=True)
                else:return self.send(404,dict(error='페이지가 없습니다.'))
            self.send(200,result)
        except store.Conflict as e:self.send(409,dict(error=str(e)))
        except (ValueError,KeyError,TypeError) as e:self.send(400,dict(error=str(e)))
        except Exception:
            import traceback;traceback.print_exc();self.send(500,dict(error='저장 결과를 확인하지 못했습니다. 새로고침 후 이력을 확인하세요.'))
def main():
    with contextlib.closing(lab.connect()) as c:store.init(c);store.reconcile(c)
    server=ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('REVIEW_PORT','8790'))),Handler);server.daemon_threads=True
    print('Public review ready on loopback 8790',flush=True);server.serve_forever()
if __name__=='__main__':main()
