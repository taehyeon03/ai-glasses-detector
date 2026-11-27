"""Serve a private annotation queue on loopback. Never labels images automatically."""
import argparse
import csv
import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs,urlparse

from PIL import Image

from pipeline.camera_annotations import latest,validate_annotation

HTML='''<!doctype html><meta charset="utf-8"><title>카메라 부위 확인</title>
<style>body{font:16px system-ui;max-width:1300px;margin:24px auto;padding:0 16px}button,select,input{font:inherit;margin:4px;padding:6px}#view{overflow:auto;max-height:65vh;border:1px solid #aaa}canvas{touch-action:none}p{line-height:1.5}#status{white-space:pre-wrap}</style>
<h1>촬영용 렌즈를 확인하는 주석</h1><p>촬영용 카메라의 개구부와 안경의 광학 렌즈를 구분하세요. 제품 참고 자료와 비교한 뒤 확인을 표시하세요. 가려진 카메라의 위치를 추측해서 그리지 마세요.</p>
<div><button onclick="loadItem(i-1)">이전</button><button onclick="loadItem(i+1)">다음</button><span id="info"></span></div>
<div><label>표시할 대상 <select id="kind"><option value="camera_aperture">촬영용 렌즈의 개구부</option><option value="optical_lens">안경의 광학 렌즈</option><option value="decorative_rivet">장식용 리벳</option><option value="indicator_light">표시등</option></select></label><button onclick="objects.pop();draw()">마지막 박스 취소</button><button onclick="zoom(1.3)">확대</button><button onclick="zoom(1/1.3)">축소</button></div>
<div id="view"><canvas id="canvas"></canvas></div>
<div><label>카메라 상태 <select id="visibility"><option value="uncertain">확인이 필요함</option><option value="visible">보임</option><option value="occluded">가려졌거나 화면 밖에 있음</option><option value="not_applicable">카메라가 없는 제품임</option></select></label></div>
<div><input id="reviewer" placeholder="검토자 식별자"><input id="reference" placeholder="확인한 제품 자료의 주소 또는 메모" style="width:55%"></div>
<div><label><input type="checkbox" id="checked">제품 참고 자료와 위치를 비교했음</label><button onclick="save()">주석 저장</button></div><p id="status"></p>
<script>
let i=0,item,objects=[],start=null,temp=null,scale=1,baseWidth=1000;const c=document.getElementById('canvas'),ctx=c.getContext('2d'),im=new Image();
const el=x=>document.getElementById(x);function point(e){let r=c.getBoundingClientRect();return[(e.clientX-r.left)*c.width/r.width,(e.clientY-r.top)*c.height/r.height]}
function zoom(f){let v=el('view'),x=(v.scrollLeft+v.clientWidth/2)/c.clientWidth,y=(v.scrollTop+v.clientHeight/2)/c.clientHeight;scale*=f;c.style.width=(baseWidth*scale)+'px';v.scrollLeft=x*c.clientWidth-v.clientWidth/2;v.scrollTop=y*c.clientHeight-v.clientHeight/2}
function draw(){ctx.clearRect(0,0,c.width,c.height);ctx.drawImage(im,0,0);for(let o of objects.concat(temp?[temp]:[])){let b=o.box;ctx.strokeStyle=o.kind==='camera_aperture'?'red':o.kind==='optical_lens'?'lime':'orange';ctx.lineWidth=Math.max(2,c.width/400);ctx.strokeRect(b[0],b[1],b[2]-b[0],b[3]-b[1]);ctx.font=Math.max(14,c.width/65)+'px sans-serif';ctx.fillStyle=ctx.strokeStyle;ctx.fillText(o.kind,b[0],Math.max(18,b[1]-4))}}
c.onpointerdown=e=>{c.setPointerCapture(e.pointerId);start=point(e)};c.onpointermove=e=>{if(!start)return;let p=point(e);temp={kind:el('kind').value,box:[Math.min(start[0],p[0]),Math.min(start[1],p[1]),Math.max(start[0],p[0]),Math.max(start[1],p[1])]};draw()};c.onpointerup=e=>{if(temp&&temp.box[2]>temp.box[0]&&temp.box[3]>temp.box[1])objects.push(temp);temp=null;start=null;draw()};
async function loadItem(n){let r=await fetch('/api/item?i='+n);if(!r.ok)return;i=n;item=await r.json();objects=item.saved?.objects||[];el('visibility').value=item.saved?.visibility||'uncertain';el('checked').checked=item.saved?.reference_checked||false;el('reference').value=item.saved?.reference||'';if(item.saved?.reviewer)el('reviewer').value=item.saved.reviewer;el('info').textContent=(i+1)+'/'+item.total+' · '+item.product_name+' · 원래 라벨='+item.label;el('status').textContent='자동으로 추정한 위치를 정답으로 옮기지 마세요. 제품 참고 자료를 확인하세요.';im.onload=()=>{c.width=im.naturalWidth;c.height=im.naturalHeight;scale=1;baseWidth=Math.min(1000,c.width,innerWidth-60,innerHeight*.62*c.width/c.height);c.style.width=baseWidth+'px';draw()};im.src='/image?i='+i;}
async function save(){let value={index:i,reviewer:el('reviewer').value,visibility:el('visibility').value,objects:objects,reference_checked:el('checked').checked,reference:el('reference').value};let r=await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});let v=await r.json();el('status').textContent=r.ok?'저장됨: '+v.status:v.error;}
loadItem(0);
</script>'''


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--metadata",required=True)
    parser.add_argument("--selection",required=True)
    parser.add_argument("--product-manifest",required=True)
    parser.add_argument("--output",required=True)
    parser.add_argument("--port",type=int,default=17882)
    args=parser.parse_args()
    metadata=json.loads(Path(args.metadata).read_text())
    candidates=[r for r in metadata["rows"] if r["split"]=="validation"]
    selection=json.loads(Path(args.selection).read_text())["indices"]
    rows=[candidates[index] for index in selection]
    with Path(args.product_manifest).open() as stream:
        names={r["product_id"]:r["product_name"] for r in csv.DictReader(stream)}
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    class Handler(BaseHTTPRequestHandler):
        def reply(self,status,body,content_type="application/json"):
            if isinstance(body,dict):body=json.dumps(body,ensure_ascii=False).encode()
            if isinstance(body,str):body=body.encode()
            self.send_response(status);self.send_header("Content-Type",content_type)
            self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(body)
        def do_GET(self):
            url=urlparse(self.path)
            if url.path=="/":return self.reply(200,HTML,"text/html; charset=utf-8")
            try:
                index=int(parse_qs(url.query)["i"][0])
                if not 0<=index<len(rows):raise ValueError("index")
                row=rows[index]
                if url.path=="/image":return self.reply(200,Path(row["path"]).read_bytes(),"image/png")
                if url.path=="/api/item":
                    return self.reply(200,dict(total=len(rows),label=row["label"],sample_id=row["sample_id"],
                        product_name=names[row["product_id"]],saved=latest(output).get(row["sample_id"])))
            except (KeyError,ValueError,IndexError):pass
            self.reply(404,dict(error="Not found"))
        def do_POST(self):
            if self.path!="/api/save" or self.headers.get("Content-Type")!="application/json":
                return self.reply(400,dict(error="Expected JSON annotation"))
            try:
                length=int(self.headers.get("Content-Length","0"))
                if not 0<length<100000:raise ValueError("Invalid request size")
                value=json.loads(self.rfile.read(length));index=int(value["index"])
                if not 0<=index<len(rows):raise ValueError("Invalid index")
                with Image.open(rows[index]["path"]) as image:width,height=image.size
                record=validate_annotation(value,rows[index],width,height)
                with output.open("a") as stream:stream.write(json.dumps(record,ensure_ascii=False)+"\n")
                self.reply(200,dict(status=record["status"]))
            except (ValueError,KeyError,TypeError) as error:self.reply(400,dict(error=str(error)))
        def log_message(self,format,*args):pass
    print(f"Private review: http://127.0.0.1:{args.port}",flush=True)
    ThreadingHTTPServer(("127.0.0.1",args.port),Handler).serve_forever()


if __name__=="__main__":main()
