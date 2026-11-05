"""Soft-remove tinted-lens variants while preserving bytes and all human decisions."""
import json,fcntl,os
from pathlib import Path
from ai_glasses.generation import tryon_lab as lab
from ai_glasses.review import public_review_store as store
STATUS='quarantined_lens_tint'
VAULT='12_색렌즈_제외보관'
def quarantine(c,products):
 store.init(c)
 c.execute('CREATE TABLE IF NOT EXISTS lens_quarantine(job_id TEXT PRIMARY KEY,previous_status TEXT,previous_output TEXT,archive_output TEXT,sha256 TEXT,reason TEXT,created TEXT)');c.commit()
 vault=lab.ROOT/VAULT;vault.mkdir(exist_ok=True);source_vault=vault/'source_metadata';source_vault.mkdir(exist_ok=True);changed=[];moved=[];cancelled=[];disabled=[]
 with open(lab.ROOT/'public_review.lock','w') as lock,open(lab.ROOT/'materialize.lock','w') as materialize_lock:
  fcntl.flock(lock,fcntl.LOCK_EX);fcntl.flock(materialize_lock,fcntl.LOCK_EX);c.execute('BEGIN IMMEDIATE')
  try:
   sources=[r for r in c.execute('SELECT * FROM sources') if r['product'] in products]
   ids={s['id'] for s in sources}
   running=[r['id'] for r in c.execute("SELECT id,condition FROM jobs WHERE status='running'") if json.loads(r['condition']).get('source_id') in ids];assert not running,'Finish the running tinted image before quarantine'
   for source in sources:
    meta=json.loads(source['metadata']);backup=source_vault/(source['id']+'.json')
    if not backup.exists():backup.write_text(json.dumps(dict(source),ensure_ascii=False,indent=2))
    meta.update(selected=False,generation_excluded=True,generation_excluded_reason='사용자 요청: 알록달록한 컬러·미러 렌즈만 데이터에서 제외',lens_tint='vivid_or_mirrored',lens_excluded_at=lab.now());c.execute('UPDATE sources SET metadata=? WHERE id=?',(json.dumps(meta,ensure_ascii=False),source['id']));disabled.append(dict(id=source['id'],product=source['product']))
   rows=[r for r in c.execute("SELECT * FROM jobs WHERE kind='tryon'") if json.loads(r['condition']).get('source_id') in ids]
   for row in rows:
    key=row['id']
    if c.execute('SELECT 1 FROM lens_quarantine WHERE job_id=?',(key,)).fetchone():continue
    if row['output']:
     folder=vault/key;folder.mkdir(exist_ok=True);saved=folder/'record.json'
     review=c.execute('SELECT * FROM reviews WHERE job_id=?',(key,)).fetchone();history=[dict(r) for r in c.execute('SELECT * FROM review_events WHERE job_id=?',(key,))]
     candidates=[]
     for path in [Path(row['output'])]+[lab.ROOT/name/(key+'.png') for name in lab.FOLDERS[5:9]+[store.ARCHIVE]]:
      if path.is_file() and path not in candidates:candidates.append(path)
     snapshots=[];archive_output=None
     for original in candidates:
      sha=lab.digest(original)
      if row['output_sha256']:assert sha==row['output_sha256'],'Generated image hash changed: '+key
      destination=folder/original.parent.name/original.name;destination.parent.mkdir(exist_ok=True)
      assert not destination.exists(),'Archive target already exists; inspect before retry'
      os.replace(original,destination);moved.append((original,destination));snapshots.append(dict(original=str(original),archived=str(destination),sha256=sha))
      if str(original)==row['output']:archive_output=str(destination)
     if not archive_output and snapshots:archive_output=snapshots[0]['archived']
     saved.write_text(json.dumps(dict(job=dict(row),review=dict(review) if review else None,history=history,files=snapshots,reason='Tinted-lens source variant and generated outputs visually inspected; reversible dataset removal'),ensure_ascii=False,indent=2))
     c.execute('INSERT INTO lens_quarantine VALUES(?,?,?,?,?,?,?)',(key,row['status'],row['output'],archive_output,row['output_sha256'],'tinted_lens_variant',lab.now()))
     c.execute('UPDATE jobs SET status=?,output=?,error=? WHERE id=?',(STATUS,archive_output or row['output'],'사용자 요청으로 색 렌즈 결과를 복구 가능한 보관함으로 이동',key));changed.append(dict(id=key,previous_status=row['status'],files=len(snapshots)))
    elif row['status'] in ('pending','interrupted','failed','blocked_dependency','waiting_reference'):
     c.execute("UPDATE jobs SET status='excluded_by_scope',error='사용자 요청: 알록달록한 컬러·미러 렌즈 생성 제외' WHERE id=?",(key,));cancelled.append(key)
    for table in ('review_pool','review_claims'):c.execute('DELETE FROM '+table+' WHERE job_id=?',(key,))
   c.commit()
  except Exception:
   c.rollback()
   for original,destination in reversed(moved):
    if destination.exists() and not original.exists():os.replace(destination,original)
   raise
 result=dict(created=lab.now(),quarantined=changed,cancelled=cancelled,disabled_sources=disabled,files_moved=len(moved),restore='Per-image record.json preserves original paths, original job record and unchanged review history')
 report=vault/('operation_'+lab.now().replace(':','-')+'.json');report.write_text(json.dumps(result,ensure_ascii=False,indent=2));lab.export(c)
 return result
if __name__=='__main__':
 c=lab.connect();selection=json.loads((lab.ROOT/'work/lens_audit/selection.json').read_text());result=quarantine(c,set(selection['products']));print(json.dumps(dict(quarantined=len(result['quarantined']),cancelled=len(result['cancelled']),files_moved=result['files_moved'],sources=len(result['disabled_sources'])),ensure_ascii=False))
