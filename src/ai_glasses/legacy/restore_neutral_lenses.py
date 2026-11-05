"""Correct the lens scope and reverse the neutral-lens soft removals."""
import json,os,fcntl
from pathlib import Path
from ai_glasses.generation import tryon_lab as lab
from ai_glasses.review import public_review_store as store
from ai_glasses.legacy import quarantine_tinted_lenses as q

def restore(c,keep_products,override_previous_sports=()):
 root=lab.ROOT;vault=root/q.VAULT;moved=[];restored=[];reenabled=[];sources_restored=[];overrides=set(override_previous_sports)
 c.execute('CREATE TABLE IF NOT EXISTS lens_quarantine_restored(job_id TEXT PRIMARY KEY,record TEXT,restored_at TEXT)');c.commit()
 operations=[json.loads(p.read_text()) for p in vault.glob('operation_*.json')];cancelled={key for operation in operations for key in operation.get('cancelled',[])}
 with open(root/'public_review.lock','w') as lock,open(root/'materialize.lock','w') as materialize_lock:
  fcntl.flock(lock,fcntl.LOCK_EX);fcntl.flock(materialize_lock,fcntl.LOCK_EX);c.execute('BEGIN IMMEDIATE')
  try:
   for source in c.execute('SELECT * FROM sources').fetchall():
    product=source['product'];backup=vault/'source_metadata'/(source['id']+'.json')
    if product in keep_products:
     meta=json.loads(source['metadata']);meta.update(selected=False,generation_excluded=True,generation_excluded_reason='사용자 요청: 알록달록한 컬러·미러 렌즈만 제외',lens_tint='vivid_or_mirrored');c.execute('UPDATE sources SET metadata=? WHERE id=?',(json.dumps(meta,ensure_ascii=False),source['id']));continue
    if backup.exists():
     original=json.loads(backup.read_text());meta=json.loads(original['metadata'])
     if product in overrides:
      meta['selected']=True
      for name in ('generation_excluded','generation_excluded_reason','generation_excluded_at','lens_excluded_at','lens_tint'):meta.pop(name,None)
     c.execute('UPDATE sources SET metadata=? WHERE id=?',(json.dumps(meta,ensure_ascii=False),source['id']));sources_restored.append(source['id'])
   rows=c.execute('SELECT q.*,j.condition FROM lens_quarantine q JOIN jobs j ON j.id=q.job_id').fetchall()
   for row in rows:
    product=json.loads(row['condition'])['product']
    if product in keep_products:continue
    key=row['job_id'];record_file=vault/key/'record.json';record=json.loads(record_file.read_text())
    for item in record['files']:
     original=Path(item['original']);archived=Path(item['archived'])
     if not archived.exists():
      assert original.is_file() and lab.digest(original)==item['sha256'],'Missing archived bytes: '+key;continue
     assert not original.exists(),'Restore destination already exists: '+str(original)
     assert lab.digest(archived)==item['sha256'],'Archive hash changed: '+key
     original.parent.mkdir(parents=True,exist_ok=True);os.replace(archived,original);moved.append((archived,original))
    status=row['previous_status']
    if product in overrides and status=='excluded_by_scope':status='success'
    c.execute('UPDATE jobs SET status=?,output=?,error=? WHERE id=?',(status,row['previous_output'],record['job'].get('error'),key))
    c.execute('INSERT OR REPLACE INTO lens_quarantine_restored VALUES(?,?,?)',(key,json.dumps(dict(row),ensure_ascii=False),lab.now()));c.execute('DELETE FROM lens_quarantine WHERE job_id=?',(key,));restored.append(key)
   for row in c.execute("SELECT id,condition,attempts,output FROM jobs WHERE status='excluded_by_scope'").fetchall():
    product=json.loads(row['condition']).get('product')
    if product in keep_products or (row['id'] not in cancelled and product not in overrides) or row['output']:continue
    source=c.execute('SELECT metadata FROM sources WHERE id=?',(json.loads(row['condition'])['source_id'],)).fetchone()
    if json.loads(source['metadata']).get('generation_excluded'):continue
    status='pending' if row['attempts']<3 else 'failed';c.execute('UPDATE jobs SET status=?,error=NULL WHERE id=?',(status,row['id']));reenabled.append(row['id'])
   c.commit()
  except Exception:
   c.rollback()
   for archived,original in reversed(moved):
    if original.exists() and not archived.exists():os.replace(original,archived)
   raise
 result=dict(created=lab.now(),policy='Only vivid multicolor or bright mirrored lenses excluded; neutral black/grey/brown and muted green lenses allowed',restored=restored,reenabled_jobs=reenabled,restored_sources=sources_restored,files_restored=len(moved))
 (vault/('neutral_restore_'+lab.now().replace(':','-')+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2));lab.export(c)
 return result
if __name__=='__main__':
 c=lab.connect();spec=json.loads((lab.ROOT/'work/lens_audit/restore_neutral_lenses_spec.json').read_text());result=restore(c,set(spec['keep_quarantined_products']),spec['override_previous_sports_exclusion']);selection_path=lab.ROOT/'work/lens_audit/selection.json';selection=json.loads(selection_path.read_text());selection['products']=spec['keep_quarantined_products'];selection['basis']=spec['policy'];selection_path.write_text(json.dumps(selection,ensure_ascii=False,indent=2));print(json.dumps(dict(restored=len(result['restored']),files_restored=result['files_restored'],reenabled_jobs=len(result['reenabled_jobs'])),ensure_ascii=False))
