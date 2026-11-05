"""Apply the explicit product scope and backfill excluded images without editing reviews."""
import json,fcntl
from ai_glasses.generation import tryon_lab as lab
from ai_glasses.review import public_review_store as store

def main():
 c=lab.connect();store.init(c);disabled=[];changed=[]
 with open(lab.ROOT/'public_review.lock','w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX);c.execute('BEGIN IMMEDIATE')
  try:
   for source in c.execute("SELECT * FROM sources WHERE category='B'").fetchall():
    meta=json.loads(source['metadata'])
    if meta.get('style')!='08_선글라스_스포츠' and meta.get('종류')!='08_선글라스_스포츠' and source['product']!='Oakley Eye Jacket Redux OO9438-0158':continue
    meta.update(selected=False,generation_excluded=True,generation_excluded_reason='사용자 요청: 일반 안경의 컬러 렌즈 스포츠 선글라스는 생성 대상에서 제외',generation_excluded_at=lab.now())
    c.execute('UPDATE sources SET metadata=? WHERE id=?',(json.dumps(meta,ensure_ascii=False),source['id']));disabled.append(dict(id=source['id'],product=source['product']))
    rows=c.execute("SELECT id,status FROM jobs WHERE kind='tryon' AND json_extract(condition,'$.source_id')=? AND (status IN ('pending','interrupted','failed','blocked_dependency','waiting_reference') OR (status='success' AND NOT EXISTS(SELECT 1 FROM reviews r WHERE r.job_id=jobs.id)))",(source['id'],)).fetchall()
    assert not c.execute("SELECT id FROM jobs WHERE status='running' AND json_extract(condition,'$.source_id')=?",(source['id'],)).fetchone(),'Finish current sports image before applying scope'
    for row in rows:
     c.execute("UPDATE jobs SET status='excluded_by_scope',error=? WHERE id=?",(meta['generation_excluded_reason'],row['id']));changed.append(dict(id=row['id'],previous_status=row['status']))
     for table in ('review_pool','review_claims'):c.execute('DELETE FROM '+table+' WHERE job_id=?',(row['id'],))
   c.commit()
  except Exception:c.rollback();raise
 created=store.backfill_excluded(c)
 result=dict(created=lab.now(),disabled_sources=disabled,removed_generation_jobs=changed,backfilled_excluded=created)
 (lab.ROOT/lab.FOLDERS[9]/'scope_and_auto_exclude_20261103.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));lab.export(c);print(json.dumps(dict(disabled_products=disabled,removed_jobs=len(changed),backfilled=len(created)),ensure_ascii=False))
if __name__=='__main__':main()
