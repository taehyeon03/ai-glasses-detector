"""Process the public regeneration outbox first, then the new adult portrait cohort."""
import contextlib
import json
import sqlite3
import time
import signal
import threading
import traceback
from ai_glasses.review import public_review_store as store
from ai_glasses.generation import tryon_lab as lab

original_loader=lab.load_pipe
cached=[]
stop_event=threading.Event()
signal.signal(signal.SIGTERM,lambda *_:stop_event.set())
signal.signal(signal.SIGINT,lambda *_:stop_event.set())
def cached_loader():
 if not cached:cached.append(original_loader())
 return cached[0]
lab.load_pipe=cached_loader

def main():
 c=lab.connect();store.init(c);last_work=time.monotonic();last_balance=0
 while not stop_event.is_set():
  try:
   from ai_glasses.generation.replan_pending_geometry import migrate
   migrate(c,waiting_only=True)
   from ai_glasses.generation.face_framing import migrate_pending
   migrate_pending(c)
   if (lab.ROOT/'STOP').exists():time.sleep(10);continue
   for r in c.execute('SELECT child_job FROM regeneration_requests'):
    c.execute('INSERT OR IGNORE INTO batch_jobs VALUES(?,?,?)',('public_regeneration',r[0],0))
   for row in c.execute("SELECT id,condition FROM jobs WHERE status IN ('pending','blocked_dependency') AND json_extract(condition,'$.batch')='public_regeneration'"):
    con=json.loads(row['condition']);parent=c.execute('SELECT status,attempts FROM jobs WHERE id=?',(con.get('portrait_job'),)).fetchone()
    if parent and parent['status']=='failed' and parent['attempts']>=3:
     c.execute("UPDATE jobs SET status='failed',attempts=3,error='기준 얼굴을 생성하지 못했습니다. 다른 얼굴을 선택해 다시 요청하세요.' WHERE id=?",(row['id'],))
   c.commit()
   from ai_glasses.generation.balance_generation import reconcile,next_batch,settings
   if settings() and time.monotonic()-last_balance>60:
    reconcile(c);last_balance=time.monotonic()
   selected=next_batch(c)
   if selected:
    lab.run(c,'all',1,True,selected,max_attempts=3);last_work=time.monotonic()
   else:
    if cached and time.monotonic()-last_work>300:
     cached.clear()
     import gc,torch;gc.collect();torch.cuda.empty_cache()
    time.sleep(10)
   with open(lab.ROOT/'public_review.lock','w') as lock:
    import fcntl;fcntl.flock(lock,fcntl.LOCK_EX);store.reconcile(c)
   (lab.ROOT/lab.FOLDERS[9]/'review_worker_status.json').write_text(json.dumps(dict(updated=lab.now(),batch=selected,status='running' if selected else 'waiting'),ensure_ascii=False))
  except BlockingIOError:time.sleep(15)
  except sqlite3.OperationalError as error:
   if not getattr(error,'sqlite_errorname','').startswith(('SQLITE_BUSY','SQLITE_LOCKED')):
    raise
   traceback.print_exc()
   c.close()
   time.sleep(3)
   c=lab.connect()
  except Exception:
   c.rollback()
   traceback.print_exc();time.sleep(20)
if __name__=='__main__':main()
