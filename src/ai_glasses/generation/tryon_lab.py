"""Local, resumable Qwen try-on experiment. No detection-model training."""
import argparse
import contextlib
import csv
import datetime as dt
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time
import traceback
import uuid

from ai_glasses.config import DATA_ROOT, QWEN_LOADER, QWEN_SNAPSHOTS

ROOT = DATA_ROOT
FOLDERS = ['01_카메라있는안경_원본','02_일반안경_원본','03_카메라없는스마트안경','04_분류확인필요','05_가상인물_원본','06_생성결과_검수전','07_생성결과_통과','08_생성결과_제외','09_생성결과_보류','10_출처_설정_검수기록']
MODEL = 'Qwen/Qwen-Image-2.1'
REVISION = 'd26bb61231c349cf6b7896fa83353113880e1ba3'
def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def digest(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1048576),b''): h.update(b)
    return h.hexdigest()
def uid(v): return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()[:24]
def connect():
    ROOT.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(ROOT/'experiment.sqlite',timeout=30)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.executescript('''
    CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,path TEXT UNIQUE,sha256 TEXT,product TEXT,category TEXT,camera TEXT,evidence TEXT,metadata TEXT);
    CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,kind TEXT,condition TEXT,status TEXT DEFAULT 'pending',output TEXT,output_sha256 TEXT,seconds REAL,peak_gb REAL,error TEXT,attempts INTEGER DEFAULT 0,started TEXT,finished TEXT);
    CREATE TABLE IF NOT EXISTS reviews(job_id TEXT PRIMARY KEY,decision TEXT,comment TEXT,checks TEXT,reviewer TEXT,updated TEXT);
    CREATE TABLE IF NOT EXISTS review_events(id INTEGER PRIMARY KEY,job_id TEXT,decision TEXT,comment TEXT,checks TEXT,reviewer TEXT,updated TEXT);
    CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY,job_id TEXT,started TEXT,finished TEXT,status TEXT,error TEXT,seconds REAL,peak_gb REAL);
    CREATE TABLE IF NOT EXISTS diagnostics(job_id TEXT PRIMARY KEY,comment TEXT,updated TEXT);
    CREATE TABLE IF NOT EXISTS batches(name TEXT PRIMARY KEY,started TEXT,deadline TEXT,status TEXT,metadata TEXT);
    CREATE TABLE IF NOT EXISTS batch_jobs(batch TEXT,job_id TEXT,priority INTEGER,PRIMARY KEY(batch,job_id));
    ''')
    if 'environment' not in {r[1] for r in c.execute('PRAGMA table_info(jobs)')}:c.execute('ALTER TABLE jobs ADD COLUMN environment TEXT')
    c.commit()
    for name in FOLDERS: (ROOT/name).mkdir(exist_ok=True)
    return c
def add_job(c,condition,kind):
    from ai_glasses.generation.face_framing import apply_condition
    condition=apply_condition(dict(condition,kind=kind))
    key=uid(condition)
    c.execute('INSERT OR IGNORE INTO jobs(id,kind,condition) VALUES(?,?,?)',(key,kind,json.dumps(condition,ensure_ascii=False)))
    c.commit()
    return key
PERSONAS=[
    ('P01','adult man age 29, East Asian appearance, broad rectangular face, warm medium tan skin, short straight black hair without bangs','short straight hair, no bangs'),
    ('P02','adult woman age 34, East Asian appearance, oval face, light olive skin, long gently curly dark brown hair tied behind ears, no bangs','long curly hair, no bangs'),
    ('P03','adult woman age 45, East Asian appearance, round face, medium brown skin with freckles, straight chin-length black bob with short bangs above eyebrows','straight bob, bangs'),
    ('P04','adult man age 41, East Asian appearance, long narrow face, light warm skin with visible pores, wavy black hair tied back, no bangs','tied wavy hair, no bangs')]
POSES=[('front','looking straight at camera'),('left_oblique','head turned 30 degrees to the subject\'s left'),('right_oblique','head turned 30 degrees to the subject\'s right'),('left_profile','head turned 80 degrees to the subject\'s left, left profile'),('right_profile','head turned 80 degrees to the subject\'s right, right profile')]
LIGHTS=['bright indoor diffuse lighting','slightly dim indoor lighting','soft side light coming from a window']
def plan_portraits(c):
    for k,(pid,desc,hair) in enumerate(PERSONAS):
        for a,(pose,direction) in enumerate(POSES):
            # All angles retain the same identity through the first generated face.
            prompt=f'Create a realistic photograph of a completely fictional {desc}. This person does not depict any real individual. Korean facial diversity is a reference, not a specific real person. Natural unretouched skin, no makeup. {direction}. {LIGHTS[(k+a)%3]}. Plain neutral indoor background. Head and shoulders, entire head visible, eyes and ears unobstructed. Hair stays away from the temples and eyebrows. Absolutely no glasses, sunglasses, eyewear or head accessories. No text or collage.'
            cond=dict(model=MODEL,revision=REVISION,person_id=pid,description=desc,hair=hair,pose=pose,light=LIGHTS[(k+a)%3],prompt=prompt,seed=2100+k*100+a,width=1024,height=1024,steps=30,kv_cache=True,protocol='v1',synthetic=True,occlusion='none')
            if a:
                base=c.execute("SELECT id FROM jobs WHERE kind='portrait' AND json_extract(condition,'$.person_id')=? AND json_extract(condition,'$.pose')='front'",(pid,)).fetchone()
                cond['portrait_parent']=base['id']
                cond['prompt']='Use image 1 as the identity reference. Preserve the exact identity and facial structure. '+prompt
            add_job(c,cond,'portrait')
    return dict(c.execute('SELECT kind,count(*) FROM jobs GROUP BY kind').fetchall())
def plan_tryons(c):
    sources=c.execute("SELECT * FROM sources WHERE json_extract(metadata,'$.selected')=1 AND category IN ('A','B') ORDER BY id").fetchall()
    if len([x for x in sources if x['category']=='A'])<2 or len([x for x in sources if x['category']=='B'])<2: raise ValueError('Need at least two inspected A products and two inspected B products')
    portraits=c.execute("SELECT * FROM jobs WHERE kind='portrait' ORDER BY rowid").fetchall()
    for p in portraits:
        pc=json.loads(p['condition'])
        for s in sources:
            meta=json.loads(s['metadata'])
            prompt='Edit image 1. Keep the exact fictional adult, identity, head direction, hair, skin texture, clothing, camera distance, background and lighting of image 1. Put ONLY the physical glasses shown in image 2 onto this person. Match the complete frame outline, material, color, thickness, lens shape and tint, bridge, nose pads and temples of image 2. Preserve the exact camera count, camera aperture location, shape and size, sensors and buttons that are actually visible in image 2. Do not invent any camera or sensor. Do not delete an existing camera. Never turn a status LED or a decorative rivet into a camera. Fit the glasses naturally on the nose and behind ears. Keep hair clear of glasses. Do not add text, logos that are absent, or comparison panels. '+meta['detail_prompt']
            cond={k:pc[k] for k in ('model','revision','person_id','hair','pose','light','width','height','steps','protocol','occlusion')}
            cond.update(kind='tryon',portrait_job=p['id'],source_id=s['id'],source_sha256=s['sha256'],product=s['product'],camera=s['camera'],camera_confirmation='product_documentation_and_manual_image_inspection',prompt=prompt,seed=int(uid([p['id'],s['id']])[:8],16)%(2**31),kv_cache=True,synthetic=True,unseen_geometry='inferred_not_verified',reference_pose=meta.get('pose','oblique'))
            add_job(c,cond,'tryon')
    return dict(c.execute('SELECT kind,count(*) FROM jobs GROUP BY kind').fetchall())
def load_pipe():
    # Reuse the verified loader without starting its Gradio UI or idle-exit thread.
    import ast
    import gc
    import torch
    from diffusers import QwenImage21Pipeline,QwenImage21Transformer2DModel
    from diffusers.hooks import apply_layerwise_casting
    from transformers import Qwen3VLForConditionalGeneration
    old=QWEN_LOADER
    tree=ast.parse(old.read_text())
    loader=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='load_pipe')
    cache=str(QWEN_SNAPSHOTS/REVISION)
    scope=dict(gc=gc,torch=torch,QwenImage21Pipeline=QwenImage21Pipeline,QwenImage21Transformer2DModel=QwenImage21Transformer2DModel,apply_layerwise_casting=apply_layerwise_casting,Qwen3VLForConditionalGeneration=Qwen3VLForConditionalGeneration,MODEL_ID=cache)
    exec(compile(ast.Module(body=[loader],type_ignores=[]),str(old),'exec'),scope)
    (ROOT/FOLDERS[9]/'reused_loader.py').write_text(ast.unparse(loader))
    return scope['load_pipe']()
def run(c,kind,limit,retry=False,batch=None,deadline=None,max_attempts=3):
    import torch
    from PIL import Image,ImageOps
    lock=open(ROOT/'worker.lock','w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    # Only the sole worker holding this lock may recover an interrupted run.
    c.execute("UPDATE jobs SET status='interrupted',error='worker exited before commit' WHERE status='running'")
    c.execute("UPDATE attempts SET status='interrupted',finished=? WHERE status='running'",(now(),))
    c.commit()
    statuses=('pending','interrupted','blocked_dependency','failed') if retry else ('pending','interrupted','blocked_dependency')
    query='SELECT * FROM jobs WHERE status IN ('+','.join('?'*len(statuses))+')'
    params=list(statuses)
    if kind!='all':query+=' AND kind=?';params.append(kind)
    query+=' AND attempts<?';params.append(max_attempts)
    rows=c.execute(query+" ORDER BY CASE WHEN kind='portrait' THEN 0 ELSE 1 END,rowid",params).fetchall()
    if batch:
        planned=[dict(r) for r in c.execute("SELECT id,condition FROM jobs WHERE kind='tryon' AND (json_extract(condition,'$.batch')=? OR id IN (SELECT job_id FROM batch_jobs WHERE batch=?))",(batch,batch))]
        tryons={r['id'] for r in planned};portraits={json.loads(r['condition'])['portrait_job'] for r in planned}
        for p in list(portraits):
            row=c.execute('SELECT condition FROM jobs WHERE id=?',(p,)).fetchone()
            if row:
                parent=json.loads(row['condition']).get('portrait_parent')
                if parent:portraits.add(parent)
        rows=[r for r in rows if r['id'] in (tryons|portraits)]
        priorities={r['job_id']:r['priority'] for r in c.execute('SELECT * FROM batch_jobs WHERE batch=?',(batch,))}
        rows.sort(key=lambda r:(0 if r['kind']=='portrait' else 1,priorities.get(r['id'],0)))
    if not rows: print('No pending jobs',flush=True); return
    try:pipe=load_pipe()
    except Exception:
        (ROOT/FOLDERS[9]/'worker_error.json').write_text(json.dumps(dict(stage='load_model',error=traceback.format_exc(),updated=now()),ensure_ascii=False,indent=2));raise
    env=dict(torch=torch.__version__,cuda=torch.version.cuda,gpu=torch.cuda.get_device_name(),model=MODEL,revision=REVISION,precision='FP8 weights / BF16 computation / CPU offload',started=now())
    import diffusers,transformers
    env.update(diffusers=diffusers.__version__,transformers=transformers.__version__)
    (ROOT/FOLDERS[9]/'environment.json').write_text(json.dumps(env,ensure_ascii=False,indent=2))
    count=0
    for row in rows:
        if count>=limit or (ROOT/'STOP').exists() or (deadline and now()>=deadline): break
        fresh=c.execute('SELECT status FROM jobs WHERE id=?',(row['id'],)).fetchone()
        if fresh['status'] not in statuses:continue
        jobkind=row['kind']
        con=json.loads(row['condition']); images=[];face_path=None;reference_crop=None
        deps=[con.get('portrait_job') or con.get('portrait_parent')]
        for dep in filter(None,deps):
            parent=c.execute('SELECT * FROM jobs WHERE id=?',(dep,)).fetchone()
            if not parent or parent['status']!='success' or not Path(parent['output']).exists():
                c.execute("UPDATE jobs SET status='blocked_dependency',error=? WHERE id=?",('Required portrait is unavailable: '+dep,row['id']));c.commit();break
            if parent['output_sha256'] and digest(parent['output'])!=parent['output_sha256']:
                c.execute("UPDATE jobs SET status='blocked_dependency',error=? WHERE id=?",('Required portrait hash changed: '+dep,row['id']));c.commit();break
            face_path=parent['output'];images.append(Image.open(face_path).convert('RGB'))
        else:
            if con.get('face_reference_path'):
                if digest(con['face_reference_path'])!=con['face_reference_sha256']:raise ValueError('User-provided face reference bytes changed')
                face=ImageOps.exif_transpose(Image.open(con['face_reference_path'])).convert('RGB');face.thumbnail((1024,1024));images.append(face)
                face_path=con['face_reference_path']
            if face_path:
                from ai_glasses.generation.face_framing import prepare_closeup_reference
                cropped_path,reference_crop=prepare_closeup_reference(face_path,con)
                images[0]=Image.open(cropped_path).convert('RGB')
            if jobkind=='tryon':
                src=c.execute('SELECT * FROM sources WHERE id=?',(con['source_id'],)).fetchone()
                if digest(src['path'])!=con['source_sha256']: raise ValueError('Source bytes changed')
                if (ROOT/'product_fidelity_enabled.json').exists():
                    from ai_glasses.generation.product_fidelity import apply_fidelity
                    con = apply_fidelity(dict(con, kind=jobkind, product=src['product'], camera=src['camera']))
                im=Image.open(src['path']).convert('RGB');im.thumbnail((1024,1024));images.append(im)
                if con.get('extra_references'):
                    from ai_glasses.generation.multiview_references import append_references
                    append_references(images,con)
            started=now();t=time.monotonic()
            job_env=dict(env,face_reference_crop=reference_crop)
            if con.get('product_fidelity_version'):
                job_env.update(product_fidelity_version=con['product_fidelity_version'], effective_prompt=con['prompt'])
            c.execute("UPDATE jobs SET status='running',started=?,attempts=attempts+1,error=NULL,environment=? WHERE id=?",(started,json.dumps(job_env,ensure_ascii=False),row['id']))
            aid=c.execute("INSERT INTO attempts(job_id,started,status) VALUES(?,?,'running')",(row['id'],started)).lastrowid;c.commit()
            try:
                torch.cuda.reset_peak_memory_stats()
                out=ROOT/FOLDERS[4 if jobkind=='portrait' else 5]/(row['id']+'.png')
                def on_step(p,i,t,kw):
                    (ROOT/'progress.json').write_text(json.dumps(dict(job_id=row['id'],kind=jobkind,step=i+1,steps=con['steps'],updated=now())))
                    return kw
                im=pipe(prompt=con['prompt'],image=images or None,width=con['width'],height=con['height'],output_resolution=con.get('reference_resolution',1024),num_inference_steps=con['steps'],use_kv_cache=con['kv_cache'],generator=torch.Generator('cuda').manual_seed(con['seed']),callback_on_step_end=on_step).images[0]
                tmp=out.with_suffix('.tmp');im.save(tmp,format='PNG');os.replace(tmp,out)
                elapsed=time.monotonic()-t;peak=torch.cuda.max_memory_allocated()/1e9
                c.execute("UPDATE jobs SET status='success',output=?,output_sha256=?,seconds=?,peak_gb=?,finished=? WHERE id=?",(str(out),digest(out),elapsed,peak,now(),row['id']))
                c.execute("UPDATE attempts SET finished=?,status='success',seconds=?,peak_gb=? WHERE id=?",(now(),elapsed,peak,aid));c.commit()
                print(json.dumps(dict(job=row['id'],kind=jobkind,status='success',seconds=elapsed,peak_gb=peak),ensure_ascii=False),flush=True)
            except Exception:
                error=traceback.format_exc();elapsed=time.monotonic()-t
                c.execute("UPDATE jobs SET status='failed',error=?,seconds=?,finished=? WHERE id=?",(error,elapsed,now(),row['id']))
                c.execute("UPDATE attempts SET finished=?,status='failed',error=?,seconds=? WHERE id=?",(now(),error,elapsed,aid));c.commit();print(error,flush=True)
                pipe.maybe_free_model_hooks();torch.cuda.empty_cache()
            export(c);count+=1
    print('Worker finished',count,flush=True)
def review(c,key,decision,comment,checks,reviewer):
    if decision not in ('pass','exclude','hold'): raise ValueError('Invalid decision')
    if not reviewer.strip(): raise ValueError('검수자 이름을 입력하세요.')
    row=c.execute("SELECT * FROM jobs WHERE id=? AND kind='tryon' AND status='success'",(key,)).fetchone()
    if not row: raise ValueError('Only successful try-on results can be reviewed')
    if not Path(row['output']).is_file():raise ValueError('생성 파일을 찾을 수 없습니다.')
    if row['output_sha256'] and digest(row['output'])!=row['output_sha256']:raise ValueError('생성 파일의 해시가 달라졌습니다. 파일을 확인하세요.')
    if len(checks)!=6 or any(v not in ('yes','no','unknown','na') for v in checks): raise ValueError('Six review answers required')
    if decision=='pass':
        con=json.loads(row['condition']);needed=[0,1,3,4] if con['camera']=='present' else [2,3,4]
        if any(checks[i]!='yes' for i in needed) or checks[5]!='no':raise ValueError('통과하려면 카메라와 형태를 확인하고 가림 여부를 아니오로 기록하세요.')
    when=now();packed=json.dumps(checks)
    with c:
        c.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET decision=excluded.decision,comment=excluded.comment,checks=excluded.checks,reviewer=excluded.reviewer,updated=excluded.updated',(key,decision,comment,packed,reviewer,when))
        c.execute('INSERT INTO review_events(job_id,decision,comment,checks,reviewer,updated) VALUES(?,?,?,?,?,?)',(key,decision,comment,packed,reviewer,when))
    materialize(c);export(c)
def materialize(c):
    with open(ROOT/'materialize.lock','w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        c.commit();c.execute('BEGIN IMMEDIATE')
        try:
            for row in c.execute("SELECT j.id,j.output,r.decision FROM jobs j JOIN reviews r ON r.job_id=j.id WHERE j.status NOT IN ('quarantined_lens_tint','quarantined_category_scope')").fetchall():
                target=ROOT/FOLDERS[{'pass':6,'exclude':7,'hold':8}[row['decision']]]/(row['id']+'.png')
                original=Path(row['output'])
                if not original.exists():
                    original=next((ROOT/FOLDERS[ix]/(row['id']+'.png') for ix in (5,6,7,8) if (ROOT/FOLDERS[ix]/(row['id']+'.png')).exists()),original)
                if original!=target:os.replace(original,target)
                c.execute('UPDATE jobs SET output=? WHERE id=?',(str(target),row['id']))
            c.commit()
        except Exception:c.rollback();raise
def export(c):
    rows=[]
    for r in c.execute('SELECT j.*,r.decision,r.comment,r.checks,r.reviewer,r.updated FROM jobs j LEFT JOIN reviews r ON j.id=r.job_id ORDER BY j.rowid'):
        d=dict(r);d.update(json.loads(d.pop('condition')))
        if d.get('source_id'):
            s=c.execute('SELECT * FROM sources WHERE id=?',(d['source_id'],)).fetchone()
            if s: d.update(source_path=s['path'],source_metadata=s['metadata'],camera_evidence=s['evidence'])
        d['review_status']=d['decision'] or 'unreviewed';rows.append(d)
    tag=uuid.uuid4().hex
    path=ROOT/FOLDERS[9]/'jobs.jsonl';tmp=path.with_name(path.name+'.'+tag+'.tmp');tmp.write_text('\n'.join(json.dumps(d,ensure_ascii=False) for d in rows));os.replace(tmp,path)
    if rows:
        cols=sorted(set().union(*(r.keys() for r in rows)))
        path=ROOT/FOLDERS[9]/'jobs.csv';tmp=path.with_name(path.name+'.'+tag+'.tmp')
        with open(tmp,'w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=cols);w.writeheader();w.writerows(rows)
        os.replace(tmp,path)
    path=ROOT/FOLDERS[9]/'experiment_snapshot.sqlite';tmp=path.with_name(path.name+'.'+tag+'.tmp')
    with contextlib.closing(sqlite3.connect(tmp)) as dst:c.backup(dst)
    os.replace(tmp,path)
def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['init','plan','run','export','serve']);p.add_argument('--kind',default='portrait',choices=['portrait','tryon','all']);p.add_argument('--limit',type=int,default=1);p.add_argument('--retry-failed',action='store_true');p.add_argument('--batch');p.add_argument('--deadline');p.add_argument('--max-attempts',type=int,default=3);p.add_argument('--port',type=int,default=8787);a=p.parse_args();c=connect()
    if a.command=='init': print(plan_portraits(c));export(c)
    elif a.command=='plan': print(plan_tryons(c));export(c)
    elif a.command=='run': run(c,a.kind,a.limit,a.retry_failed,a.batch,a.deadline,a.max_attempts)
    elif a.command=='export': materialize(c);export(c)
    elif a.command=='serve':
        from ai_glasses.review.review_server import serve
        serve(a.port)
if __name__=='__main__': main()
