"""Finite human-rejected regeneration batch; bounded by the requested KST window."""
import argparse,collections,datetime,fcntl,json,os,signal,sqlite3,time,uuid
from pathlib import Path
from ai_glasses.generation import tryon_lab as lab
from ai_glasses.review import public_review_store as store
from ai_glasses.generation.product_fidelity import apply_fidelity,VERSION

BATCH='quality_regeneration_20261105'
from ai_glasses.config import YOLO_RUN_ROOT as OUT
START=datetime.datetime.fromisoformat(os.environ.get('TRYON_GENERATION_START','2026-11-05T08:00:00+09:00')).timestamp()
END=datetime.datetime.fromisoformat(os.environ.get('TRYON_GENERATION_END','2026-11-05T15:00:00+09:00')).timestamp()
STOP=OUT/'generation_stop'
stopping=False
def stop(*args):
 global stopping
 stopping=True
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)

def dump(name,value):
 path=OUT/name;tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2));tmp.replace(path)

def prepare():
 c=lab.connect();store.init(c)
 c.execute('CREATE TABLE IF NOT EXISTS quality_regeneration_20261105(parent_job TEXT PRIMARY KEY,child_job TEXT,reason TEXT,created TEXT)');c.commit()
 if not (OUT/'before_quality_regeneration.sqlite').exists():
  with sqlite3.connect(OUT/'before_quality_regeneration.sqlite') as dst:c.backup(dst)
 sources={}
 for row in c.execute("SELECT * FROM sources WHERE category IN ('A','B') ORDER BY rowid"):
  meta=json.loads(row['metadata'])
  if meta.get('selected') is False or meta.get('generation_excluded'):continue
  old=sources.get(row['product'])
  if old is None or bool(meta.get('extra_references'))>=bool(json.loads(old['metadata']).get('extra_references')):sources[row['product']]=dict(row)
 candidates=c.execute("SELECT j.*,s.product,s.category,r.comment FROM jobs j JOIN sources s ON s.id=json_extract(j.condition,'$.source_id') JOIN reviews r ON r.job_id=j.id WHERE j.kind='tryon' AND j.status='success' AND r.decision='exclude' AND s.category IN ('A','B') ORDER BY s.category DESC,s.product,j.rowid").fetchall()
 created=[];skipped=[];c.execute('BEGIN IMMEDIATE')
 try:
  for row in candidates:
   if c.execute('SELECT 1 FROM quality_regeneration_20261105 WHERE parent_job=?',(row['id'],)).fetchone():continue
   source=sources.get(row['product'])
   if not source:skipped.append(dict(id=row['id'],reason='source excluded or unavailable'));continue
   con=json.loads(row['condition']);meta=json.loads(source['metadata']);con.update(source_id=source['id'],source_sha256=source['sha256'],camera=source['camera'])
   con.pop('extra_references',None)
   if meta.get('extra_references'):con['extra_references']=meta['extra_references']
   if con.get('pose')!='front' and not con.get('extra_references'):
    portrait=c.execute("SELECT * FROM jobs WHERE kind='portrait' AND status='success' AND json_extract(condition,'$.person_id')=? AND json_extract(condition,'$.pose')='front' ORDER BY rowid DESC LIMIT 1",(con.get('person_id'),)).fetchone()
    if not portrait:skipped.append(dict(id=row['id'],reason='side reference and matching front portrait missing'));continue
    pc=json.loads(portrait['condition']);con.update(portrait_job=portrait['id'],pose='front')
   parent=c.execute('SELECT output,status FROM jobs WHERE id=?',(con.get('portrait_job'),)).fetchone()
   if not parent or parent['status']!='success' or not parent['output'] or not Path(parent['output']).is_file():skipped.append(dict(id=row['id'],reason='portrait unavailable'));continue
   last=c.execute('SELECT reason,notes FROM regeneration_requests WHERE parent_job=? ORDER BY created DESC LIMIT 1',(row['id'],)).fetchone()
   reason=last['reason'] if last and last['reason'] in store.REASONS else 'other';notes=last['notes'] if last else ''
   con['prompt']=apply_fidelity(con)['prompt'];con['base_prompt']=con['prompt']
   child,request=store.enqueue_regeneration(c,row['id'],con,reason,notes,None,'원래 검수 결과에 따른 자동 재생성','quality_regeneration_20261105')
   old=c.execute('SELECT condition,status FROM jobs WHERE id=?',(child,)).fetchone();new=json.loads(old['condition']);new.update(batch=BATCH,quality_batch=BATCH,protocol=BATCH,seed=int(uuid.uuid4().hex[:8],16)%(2**31))
   new=apply_fidelity(new);key=lab.uid(new)
   c.execute('INSERT OR IGNORE INTO jobs(id,kind,condition,status) VALUES(?,?,?,?)',(key,'tryon',json.dumps(new,ensure_ascii=False),'pending'))
   c.execute('UPDATE regeneration_requests SET child_job=? WHERE id=?',(key,request))
   c.execute("UPDATE jobs SET status='superseded',error='Prepared the audited class-specific prompt before generation' WHERE id=? AND status<>'success'",(child,))
   c.execute('INSERT INTO quality_regeneration_20261105 VALUES(?,?,?,?)',(row['id'],key,'reference geometry and aperture fidelity',lab.now()));created.append(dict(parent=row['id'],child=key,category=row['category'],product=row['product'],pose=new.get('pose'),side_reference=bool(new.get('extra_references'))))
  # Round robin across models, with the currently deficient ordinary class first.
  all_rows=c.execute("SELECT q.child_job,j.condition,s.category,s.product FROM quality_regeneration_20261105 q JOIN jobs j ON j.id=q.child_job JOIN sources s ON s.id=json_extract(j.condition,'$.source_id')").fetchall();groups=collections.defaultdict(list)
  for row in all_rows:groups[(row['category'],row['product'])].append(row)
  priority=0
  for category in ['B','A']:
   while any(items for (cat,_),items in groups.items() if cat==category):
    for (cat,product),items in sorted(groups.items()):
     if cat!=category or not items:continue
     row=items.pop(0);c.execute('INSERT OR REPLACE INTO batch_jobs VALUES(?,?,?)',(BATCH,row['child_job'],priority));priority+=1
  c.commit()
 except Exception:c.rollback();raise
 dump('regeneration_plan.json',dict(batch=BATCH,version=VERSION,created_this_pass=created,skipped_this_pass=skipped,total=priority,start_kst='2026-11-05 08:00',end_kst='2026-11-05 15:00',reviews_changed=False));c.close()

def main():
 if time.time()<START or time.time()>=END or STOP.exists():return
 lock=open(OUT/'generation.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 prepare();c=lab.connect();original=lab.load_pipe;cached=[]
 def loader():
  if not cached:cached.append(original())
  return cached[0]
 lab.load_pipe=loader
 c.execute("UPDATE jobs SET status='interrupted' WHERE status='running' AND id IN (SELECT job_id FROM batch_jobs WHERE batch=?)",(BATCH,));c.commit()
 while not stopping and not STOP.exists() and time.time()<END:
  # A parent that is later approved by a person no longer needs this replacement.
  c.execute("UPDATE jobs SET status='cancelled_review_changed' WHERE status IN ('pending','interrupted','failed','blocked_dependency') AND id IN (SELECT q.child_job FROM quality_regeneration_20261105 q JOIN reviews r ON r.job_id=q.parent_job WHERE r.decision<>'exclude')");c.commit()
  count=c.execute("SELECT count(*) FROM jobs j JOIN batch_jobs b ON b.job_id=j.id WHERE b.batch=? AND j.status IN ('pending','interrupted','failed') AND j.attempts<3",(BATCH,)).fetchone()[0]
  if not count:break
  lab.run(c,'tryon',1,True,BATCH,max_attempts=3)
  store.reconcile(c);stats=dict(c.execute('SELECT j.status,count(*) FROM jobs j JOIN batch_jobs b ON b.job_id=j.id WHERE b.batch=? GROUP BY j.status',(BATCH,)).fetchall());dump('generation_status.json',dict(phase='generating',counts=stats,updated=lab.now()))
 stats=dict(c.execute('SELECT j.status,count(*) FROM jobs j JOIN batch_jobs b ON b.job_id=j.id WHERE b.batch=? GROUP BY j.status',(BATCH,)).fetchall());store.reconcile(c);dump('generation_status.json',dict(phase='stopped_at_deadline' if time.time()>=END or STOP.exists() or stopping else 'batch_complete',counts=stats,updated=lab.now(),human_review_required=True));c.close()

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true');parser.add_argument('--stop',action='store_true');args=parser.parse_args()
 if args.stop:STOP.touch();dump('generation_deadline.json',dict(stopped_at=lab.now(),reason='15:00 KST deadline'))
 elif args.prepare:prepare()
 else:main()
