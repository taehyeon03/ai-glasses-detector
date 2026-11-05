"""Exclude category C reversibly without changing any human decision."""
import fcntl,json,os,sqlite3
from pathlib import Path
from ai_glasses.generation import tryon_lab as lab
from ai_glasses.review import public_review_store as store

STATUS='quarantined_category_scope'
VAULT='14_카메라없는_스마트안경_보관'
REASON='사용자 요청: 카메라 없는 스마트·디지털 안경은 현재 실험에서 제외'

def exclude(c):
    store.init(c);vault=lab.ROOT/VAULT;vault.mkdir(exist_ok=True);manifest=vault/'exclusion_manifest.json'
    if manifest.exists():return json.loads(manifest.read_text())
    moved=[];archived=[];cancelled=[]
    with open(lab.ROOT/'public_review.lock','w') as lock,open(lab.ROOT/'materialize.lock','w') as materialize_lock:
        fcntl.flock(lock,fcntl.LOCK_EX);fcntl.flock(materialize_lock,fcntl.LOCK_EX)
        with sqlite3.connect(vault/'before_exclusion.sqlite') as dst:c.backup(dst)
        c.execute('BEGIN IMMEDIATE')
        try:
            before=[tuple(r) for r in c.execute('SELECT * FROM reviews ORDER BY job_id')]
            history=[tuple(r) for r in c.execute('SELECT * FROM review_events ORDER BY id')]
            sources=[dict(r) for r in c.execute("SELECT * FROM sources WHERE category='C'")]
            (vault/'source_records.json').write_text(json.dumps(sources,ensure_ascii=False,indent=2))
            rows=c.execute("SELECT j.* FROM jobs j JOIN sources s ON s.id=json_extract(j.condition,'$.source_id') WHERE j.kind='tryon' AND s.category='C'").fetchall()
            assert not any(r['status']=='running' for r in rows),'Finish current generation before exclusion'
            for source in sources:
                meta=json.loads(source['metadata']);meta.update(selected=False,generation_excluded=True,generation_excluded_reason=REASON,category_scope_excluded_at=lab.now())
                c.execute('UPDATE sources SET metadata=? WHERE id=?',(json.dumps(meta,ensure_ascii=False),source['id']))
            for row in rows:
                key=row['id']
                if row['status']=='success':
                    folder=vault/key;folder.mkdir(exist_ok=True);candidates=[];files=[]
                    for path in [Path(row['output'])]+[lab.ROOT/name/(key+'.png') for name in lab.FOLDERS[5:9]+[store.ARCHIVE]]:
                        if path.is_file() and path not in candidates:candidates.append(path)
                    assert candidates,'Missing completed output: '+key
                    for path in candidates:
                        sha=lab.digest(path);assert not row['output_sha256'] or sha==row['output_sha256']
                        target=folder/path.parent.name/path.name;target.parent.mkdir(exist_ok=True);assert not target.exists()
                        os.replace(path,target);moved.append((path,target));files.append(dict(original=str(path),archived=str(target),sha256=sha))
                    review=c.execute('SELECT * FROM reviews WHERE job_id=?',(key,)).fetchone()
                    record=dict(job=dict(row),review=dict(review) if review else None,history=[dict(r) for r in c.execute('SELECT * FROM review_events WHERE job_id=?',(key,))],files=files)
                    (folder/'record.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
                    output=next((x['archived'] for x in files if x['original']==row['output']),files[0]['archived'])
                    c.execute('UPDATE jobs SET status=?,output=?,error=? WHERE id=?',(STATUS,output,REASON,key));archived.append(dict(id=key,files=files))
                elif row['status'] in ('pending','interrupted','blocked_dependency','waiting_reference','failed','deferred_pilot','deferred_balance'):
                    cancelled.append(dict(job=dict(row)));c.execute("UPDATE jobs SET status='excluded_by_scope',error=? WHERE id=?",(REASON,key))
                for table in ('review_pool','review_claims'):c.execute('DELETE FROM '+table+' WHERE job_id=?',(key,))
            assert before==[tuple(r) for r in c.execute('SELECT * FROM reviews ORDER BY job_id')]
            assert history==[tuple(r) for r in c.execute('SELECT * FROM review_events ORDER BY id')]
            c.commit()
        except Exception:
            c.rollback()
            for original,target in reversed(moved):
                if target.exists() and not original.exists():os.replace(target,original)
            raise
    config=lab.ROOT/'generation_balance_settings.json'
    if config.exists():
        (vault/'generation_settings_before.json').write_text(config.read_text());value=json.loads(config.read_text());value.update(enabled=False,mode='pilot',active_batch='quick_pilot_24_20261104',excluded_categories=['C'],reason=REASON);config.write_text(json.dumps(value,ensure_ascii=False,indent=2))
    candidates=lab.ROOT/lab.FOLDERS[9]/'balanced_approved_candidates.json'
    if candidates.exists():
        (vault/'previous_approved_candidates.json').write_text(candidates.read_text());value=json.loads(candidates.read_text());value.get('categories',{}).pop('C',None);value.get('counts',{}).pop('C',None);value['excluded_categories']=['C'];candidates.write_text(json.dumps(value,ensure_ascii=False,indent=2))
    result=dict(created=lab.now(),reason=REASON,disabled_products=[s['product'] for s in sources],archived=archived,cancelled=cancelled,human_reviews_preserved=len(before),review_events_preserved=len(history),files_moved=len(moved))
    manifest.write_text(json.dumps(result,ensure_ascii=False,indent=2));lab.export(c);return result

if __name__=='__main__':
    result=exclude(lab.connect());print(json.dumps(dict(products=len(result['disabled_products']),archived=len(result['archived']),cancelled=len(result['cancelled']),human_reviews_preserved=result['human_reviews_preserved'],files_moved=result['files_moved']),ensure_ascii=False))
