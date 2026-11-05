"""Loopback-only review screen with persistent decisions and adjustable crops."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import functools
import json
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
from ai_glasses.generation import tryon_lab as lab

HTML='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>안경을 비교하고 검수하기</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f4f3f0;color:#202927;font:15px/1.5 system-ui,sans-serif}header{padding:16px 4vw;background:#183e36;color:#fff}h1{font-size:22px;margin:0 0 5px}header p{margin:0;color:#dce8e1}.wrap{max-width:1500px;margin:auto;padding:20px}button,select,input,textarea{font:inherit;padding:9px 12px;border:1px solid #b8c5bd;border-radius:7px;background:white}button{cursor:pointer}button:disabled{opacity:.45;cursor:default}button:focus-visible,select:focus-visible{outline:3px solid #db9334}.bar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:15px}.count{margin-left:auto}.panel{background:white;border:1px solid #d8ded9;border-radius:10px;padding:15px;margin-bottom:16px}.images{display:grid;grid-template-columns:1fr 1fr;gap:16px}.image img{display:block;width:100%;height:260px;object-fit:contain;background:#eaece8;border-radius:6px;cursor:crosshair}.image h2{font-size:17px;margin:0 0 8px}.image canvas{width:100%;height:155px;background:#eaece8;object-fit:contain;margin-top:6px}.sub{font-size:12px;color:#56645d}.info{display:grid;grid-template-columns:1fr 1fr;gap:8px 24px}.badge{display:inline-block;background:#e5eee9;border-radius:20px;padding:3px 12px}.check{display:flex;justify-content:space-between;gap:12px;padding:8px 0;border-bottom:1px solid #e9eee9}.check select{min-width:110px}.actions{display:flex;gap:10px;margin-top:12px;flex-wrap:wrap;position:sticky;bottom:0;background:white;padding:12px 0}.pass{background:#246347;color:white}.exclude{background:#914738;color:white}.hold{background:#f1dbac}textarea{width:100%;height:75px;margin-top:8px}#message{min-height:25px;color:#883c23}a{color:#286950;overflow-wrap:anywhere}details pre{max-height:250px;overflow:auto;white-space:pre-wrap;font-size:12px}.note{border-left:4px solid #c88e38;padding:8px 12px;background:#fbf4e6}.muted{color:#52615b}.cropControls{display:flex;gap:5px}.cropControls input{width:23%;padding:4px}#diagnostic{color:#8b4d26} @media(max-width:620px){.images,.info{grid-template-columns:1fr}.image img{height:280px}.count{margin-left:0}.check{align-items:center}}
</style><header><h1>안경을 비교하고 검수하기</h1><p>실제 제품의 작은 특징을 확인하세요. 사람의 판정이 있어야 통과로 분류됩니다.</p></header><main class="wrap">
<div class="bar"><label>검수 상태 <select id="filter"><option value="all">전체</option><option value="unreviewed">검수 전</option><option value="pass">통과</option><option value="exclude">제외</option><option value="hold">판단 보류</option></select></label><button id="prev">← 이전 이미지</button><button id="next">다음 이미지 →</button><button id="reload">목록 새로고침</button><span id="count" class="count"></span></div>
<div id="summary" class="muted"></div><p class="note">생성 모델은 카메라와 프레임의 보존을 보장하지 않습니다. 자연스러운 사진도 제품과 다를 수 있습니다.</p>
<div id="empty" hidden>생성된 착용 이미지가 아직 없습니다. 생성이 끝난 뒤 목록을 새로고침하세요.</div><div id="content">
<div class="images panel"><section class="image"><h2>실제 안경의 원본</h2><img id="source" alt="실제 안경의 원본"><p class="sub">사진에서 확대할 부분을 클릭하세요. 드래그하면 영역을 지정할 수 있습니다.</p><details><summary>확대 영역의 좌표를 조절하기</summary><div id="sc" class="cropControls"></div></details><canvas id="sourceCrop" width="1200" height="300" aria-label="원본 안경의 확대"></canvas></section><section class="image"><h2>생성된 착용 이미지</h2><img id="generated" alt="가상 인물이 안경을 착용한 이미지"><p class="sub">확대 영역은 추정치입니다. 사진에서 클릭하거나 드래그해서 조절하세요.</p><details><summary>확대 영역의 좌표를 조절하기</summary><div id="gc" class="cropControls"></div></details><canvas id="generatedCrop" width="1200" height="300" aria-label="생성된 안경의 확대"></canvas></section></div>
<div class="panel"><h2 id="product" style="margin-top:0;font-size:19px"></h2><div id="info" class="info"></div><p id="diagnostic"></p><details><summary>생성 조건과 출처 기록 보기</summary><pre id="details"></pre></details></div>
<div class="panel"><div id="checks"></div><label>검수자 <input id="reviewer" placeholder="검수자의 이름" autocomplete="name"></label><label for="comment" style="display:block;margin-top:10px">검수 의견</label><textarea id="comment" placeholder="카메라, 프레임 또는 가림에 관해 기록하세요."></textarea><p id="message" role="status" aria-live="polite"></p><div class="actions"><button id="pass" class="pass">통과</button><button id="exclude" class="exclude">제외</button><button id="hold" class="hold">판단 보류</button><button id="prevBottom">이전 이미지</button><button id="nextBottom">다음 이미지</button><span id="saved"></span></div></div></div></main>
<script>
const $=s=>document.getElementById(s);let all=[],items=[],index=0,current=null,queue={},boxes={source:[0,0,1,1],generated:[.17,.28,.83,.58]};const labels=['실제 카메라가 생성 이미지에 남아 있는가?','카메라의 개수와 위치가 원본과 같은가?','일반 안경에 없던 카메라가 생기지 않았는가?','프레임과 렌즈의 형태가 원본과 크게 다르지 않은가?','안경이 얼굴에 자연스럽게 걸려 있는가?','머리카락이나 가림 때문에 판단이 어려운가?'];const status={unreviewed:'검수 전',pass:'통과',exclude:'제외',hold:'판단 보류'};
labels.forEach((label,i)=>{let d=document.createElement('label');d.className='check';d.append(document.createTextNode((i+1)+'. '+label));let s=document.createElement('select');s.id='c'+i;for(let [v,t] of [['unknown','미확인'],['yes','예'],['no','아니오'],['na','해당 없음']])s.add(new Option(t,v));d.append(s);$('checks').append(d)});
for(let [name,id] of [['source','sc'],['generated','gc']]){for(let i=0;i<4;i++){let a=document.createElement('input');a.type='number';a.min=0;a.max=1;a.step=.01;a.setAttribute('aria-label',name+' '+['왼쪽','위','오른쪽','아래'][i]);a.addEventListener('change',async()=>{boxes[name][i]=+a.value;draw(name);try{await api('/api/crops',{id:current.id,boxes})}catch(e){$('message').textContent=e.message}});$(id).append(a)}$(name).onload=()=>draw(name)}
async function api(url,body){let r=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});let d=await r.json();if(!r.ok)throw Error(d.error||r.statusText);return d}
for(let name of ['source','generated']){let start=null;function point(e){let im=$(name),r=im.getBoundingClientRect(),scale=Math.min(r.width/im.naturalWidth,r.height/im.naturalHeight),w=im.naturalWidth*scale,h=im.naturalHeight*scale;return [Math.max(0,Math.min(1,(e.clientX-r.left-(r.width-w)/2)/w)),Math.max(0,Math.min(1,(e.clientY-r.top-(r.height-h)/2)/h))]}$(name).onpointerdown=e=>{e.preventDefault();start=point(e);$(name).setPointerCapture(e.pointerId)};$(name).onpointerup=async e=>{if(!start||!current)return;let end=point(e),b=[Math.min(start[0],end[0]),Math.min(start[1],end[1]),Math.max(start[0],end[0]),Math.max(start[1],end[1])];if(b[2]-b[0]<.02||b[3]-b[1]<.02)b=[Math.max(0,end[0]-.12),Math.max(0,end[1]-.1),Math.min(1,end[0]+.12),Math.min(1,end[1]+.1)];start=null;boxes[name]=b;draw(name);try{await api('/api/crops',{id:current.id,boxes})}catch(err){$('message').textContent=err.message}}}
function draw(name){let im=$(name),cv=$(name+'Crop'),b=boxes[name];let ctx=cv.getContext('2d');ctx.clearRect(0,0,cv.width,cv.height);if(im.complete&&im.naturalWidth&&b[2]>b[0]&&b[3]>b[1]){let sw=(b[2]-b[0])*im.naturalWidth,sh=(b[3]-b[1])*im.naturalHeight;let scale=Math.min(cv.width/sw,cv.height/sh);ctx.drawImage(im,b[0]*im.naturalWidth,b[1]*im.naturalHeight,sw,sh,(cv.width-sw*scale)/2,(cv.height-sh*scale)/2,sw*scale,sh*scale)}let inputs=$(name==='source'?'sc':'gc').children;for(let i=0;i<4;i++)inputs[i].value=b[i]}
function filter(){let f=$('filter').value;items=all.filter(x=>f==='all'||(x.review?.decision||'unreviewed')===f);index=0;show()}
function textInfo(label,value){let d=document.createElement('div');let b=document.createElement('strong');b.textContent=label+' · ';d.append(b,document.createTextNode(value??'미확인'));$('info').append(d)}
function show(){current=items[index];$('empty').hidden=!!current;$('content').hidden=!current;$('prev').disabled=index===0;$('next').disabled=index>=items.length-1;$('prevBottom').disabled=index===0;$('nextBottom').disabled=index>=items.length-1;$('count').textContent=items.length?`${index+1} / ${items.length}`:'0 / 0';if(!current)return;let c=current.condition,s=current.source,r=current.review;$('product').textContent=s.product;$('info').replaceChildren();textInfo('카메라',s.camera==='present'?'있음 · 제품 근거 확인':'없음 · 제품 근거 확인');textInfo('확인 근거',s.evidence);textInfo('생성 조건',c.protocol==='v1'?'최초 시험 · 30단계':'보강한 조건 · 40단계');textInfo('인물 ID',c.person_id);textInfo('인물 출처',c.face_origin==='user_provided_reference'?'사용자 제공 사진을 참조한 생성본':'가상으로 생성');textInfo('머리 모양',({'short straight hair, no bangs':'짧은 직모 · 앞머리 없음','long curly hair, no bangs':'긴 곱슬머리 · 앞머리 없음','straight bob, bangs':'단발 직모 · 앞머리 있음','tied wavy hair, no bangs':'묶은 곱슬머리 · 앞머리 없음'})[c.hair]||c.hair);textInfo('요청한 얼굴 방향',({front:'정면',left_oblique:'왼쪽 사선',right_oblique:'오른쪽 사선',left_profile:'왼쪽 측면',right_profile:'오른쪽 측면'})[c.pose]||c.pose);textInfo('조명',({'bright indoor diffuse lighting':'밝은 실내','slightly dim indoor lighting':'약간 어두운 실내','soft side light coming from a window':'창가에서 들어오는 빛'})[c.light]||c.light);textInfo('검수 상태',status[r?.decision||'unreviewed']);textInfo('작업 ID',current.id);let a=document.createElement('a');a.textContent='원본의 출처 페이지';a.href=s.metadata['출처페이지'];a.target='_blank';a.rel='noopener';if(/^https?:/.test(a.href))$('info').append(a);textInfo('이용 조건',s.metadata.rights_status);textInfo('보이지 않은 부분','모델이 추정했으며 제품과의 일치는 미확인');$('details').textContent=JSON.stringify(current,null,2);$('diagnostic').textContent=current.diagnostic?'자동 작업자의 관찰: '+current.diagnostic:'';$('source').src='/api/image?id='+current.id+'&which=source';$('generated').src='/api/image?id='+current.id+'&which=generated';boxes=current.crops||{source:[0,0,1,1],generated:[.17,.28,.83,.58]};$('comment').value=r?.comment||'';$('reviewer').value=r?.reviewer||localStorage.getItem('reviewer')||'';for(let i=0;i<6;i++)$('c'+i).value=r?.checks?.[i]||'unknown';$('saved').textContent=r?'저장됨 · '+r.updated:'';$('message').textContent='';}
function refreshSummary(){let counts={unreviewed:0,pass:0,exclude:0,hold:0};all.forEach(x=>counts[x.review?.decision||'unreviewed']++);$('summary').textContent=`생성 완료 ${all.length}장 · 검수 전 ${counts.unreviewed}장 · 통과 ${counts.pass}장 · 제외 ${counts.exclude}장 · 보류 ${counts.hold}장 · 생성 중 ${queue.running||0}건 · 실패 ${queue.failed||0}건`;}
async function load(){try{let data=await api('/api/jobs');all=data.jobs;queue=data.queue||{};refreshSummary();filter()}catch(e){$('message').textContent=e.message}}
for(let decision of ['pass','exclude','hold'])$(decision).onclick=async()=>{if(!current)return;try{let review={id:current.id,decision,comment:$('comment').value,reviewer:$('reviewer').value,checks:labels.map((_,i)=>$('c'+i).value)};await api('/api/review',review);localStorage.setItem('reviewer',review.reviewer);current.review={...review,updated:new Date().toISOString()};refreshSummary();show();$('message').textContent='판정과 의견을 저장했습니다.';$('saved').textContent='저장됨 · '+status[decision]}catch(e){$('message').textContent=e.message}};
$('prev').onclick=()=>{if(index>0){index--;show()}};$('next').onclick=()=>{if(index<items.length-1){index++;show()}};$('prevBottom').onclick=()=>$('prev').click();$('nextBottom').onclick=()=>$('next').click();$('filter').onchange=filter;$('reload').onclick=load;load();
</script></html>'''

@functools.lru_cache(maxsize=256)
def source_crop(path):
    from PIL import Image
    import numpy as np
    with Image.open(path) as raw:
        im=raw.convert('RGB');a=np.asarray(im);ys,xs=np.where(np.min(a,axis=2)<170)
        if not len(xs):return [0,0,1,1]
        return [max(0,float(xs.min()/im.width)-.03),max(0,float(ys.min()/im.height)-.03),min(1,float((xs.max()+1)/im.width)+.03),min(1,float((ys.max()+1)/im.height)+.03)]

def get_jobs(c):
    jobs=[]
    for row in c.execute("SELECT * FROM jobs WHERE kind='tryon' AND status='success' ORDER BY rowid"):
        d=dict(row);d['condition']=json.loads(d['condition'])
        s=c.execute('SELECT * FROM sources WHERE id=?',(d['condition']['source_id'],)).fetchone();d['source']=dict(s);d['source']['metadata']=json.loads(s['metadata'])
        r=c.execute('SELECT * FROM reviews WHERE job_id=?',(row['id'],)).fetchone();d['review']=dict(r) if r else None
        if r:d['review']['checks']=json.loads(r['checks'])
        crop=c.execute('SELECT boxes FROM crops WHERE job_id=?',(row['id'],)).fetchone();d['crops']=json.loads(crop['boxes']) if crop else dict(source=source_crop(s['path']),generated=[.17,.28,.83,.58])
        diag=c.execute('SELECT comment FROM diagnostics WHERE job_id=?',(row['id'],)).fetchone();d['diagnostic']=diag['comment'] if diag else None
        jobs.append(d)
    return jobs

class Handler(BaseHTTPRequestHandler):
    def send(self,status,body,ctype='application/json'):
        if isinstance(body,(dict,list)):body=json.dumps(body,ensure_ascii=False).encode()
        if isinstance(body,str):body=body.encode()
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
    def do_GET(self):
        u=urlsplit(self.path);q=parse_qs(u.query)
        with lab.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS crops(job_id TEXT PRIMARY KEY,boxes TEXT)')
            if u.path=='/':return self.send(200,HTML,'text/html; charset=utf-8')
            if u.path=='/api/jobs':return self.send(200,dict(jobs=get_jobs(c),queue=dict(c.execute('SELECT status,count(*) FROM jobs GROUP BY status').fetchall())))
            if u.path=='/api/image':
                j=c.execute('SELECT * FROM jobs WHERE id=?',(q.get('id',[''])[0],)).fetchone()
                if not j:return self.send(404,dict(error='Unknown image'))
                path=j['output']
                if q.get('which',[''])[0]=='source':
                    con=json.loads(j['condition']);s=c.execute('SELECT path FROM sources WHERE id=?',(con['source_id'],)).fetchone();path=s['path']
                if not path or not Path(path).is_file():return self.send(404,dict(error='Image unavailable'))
                from PIL import Image
                im=Image.open(path).convert('RGB');b=io.BytesIO();im.save(b,'PNG');return self.send(200,b.getvalue(),'image/png')
        self.send(404,dict(error='Not found'))
    def do_POST(self):
        # Loopback binding plus exact Origin checking prevents cross-site mutation.
        origin=self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'):return self.send(403,dict(error='Origin rejected'))
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length>100000:return self.send(413,dict(error='Request too large'))
            d=json.loads(self.rfile.read(length))
            with lab.connect() as c:
                if self.path=='/api/review':lab.review(c,d['id'],d['decision'],d['comment'],d['checks'],d['reviewer'])
                elif self.path=='/api/crops':
                    if not c.execute('SELECT 1 FROM jobs WHERE id=?',(d['id'],)).fetchone():raise ValueError('Unknown job')
                    for name in ('source','generated'):
                        b=d['boxes'][name]
                        if len(b)!=4 or not all(isinstance(v,(float,int)) and 0<=v<=1 for v in b) or b[0]>=b[2] or b[1]>=b[3]:raise ValueError('확대 영역의 좌표를 확인하세요.')
                    c.execute('INSERT INTO crops VALUES(?,?) ON CONFLICT(job_id) DO UPDATE SET boxes=excluded.boxes',(d['id'],json.dumps(d['boxes'])));c.commit()
                else:return self.send(404,dict(error='Not found'))
            self.send(200,dict(ok=True))
        except (ValueError,KeyError,TypeError) as e:self.send(400,dict(error=str(e)))
def serve(port):
    with lab.connect() as c:c.execute('CREATE TABLE IF NOT EXISTS crops(job_id TEXT PRIMARY KEY,boxes TEXT)')
    print(f'http://127.0.0.1:{port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()
