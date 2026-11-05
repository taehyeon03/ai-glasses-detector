"""Retire only unreviewed outputs and queue replacements without human decisions."""
import fcntl,json,os,sqlite3
from pathlib import Path
from ai_glasses.generation import tryon_lab as lab
from ai_glasses.review import public_review_store as store

RUN_ID='20261103_unreviewed_reset_v1'
BATCH='unreviewed_reset_20261103'
STATUS='archived_unreviewed_reset'
VAULT='13_미검수_교체보관'
NOTES='사용자 요청: 기존 미검수 결과를 교체합니다. 최신 얼굴 근접 구도와 안경 선명도 조건을 적용하세요. 힌지는 참고 사진과 일치시켜 주세요. 보이지 않는 반대편 힌지와 다리는 참고 쪽과 대칭으로 만드세요. 카메라와 버튼은 제품 정보의 위치와 개수를 유지하세요.'

def reset(c):
    store.init(c)
    c.execute('CREATE TABLE IF NOT EXISTS unreviewed_resets(id TEXT PRIMARY KEY,result TEXT)');c.commit()
    existing=c.execute('SELECT result FROM unreviewed_resets WHERE id=?',(RUN_ID,)).fetchone()
    if existing:return json.loads(existing[0])
    vault=lab.ROOT/VAULT;vault.mkdir(exist_ok=True)
    moved=[];items=[]
    with open(lab.ROOT/'public_review.lock','w') as lock,open(lab.ROOT/'materialize.lock','w') as materialize_lock:
        fcntl.flock(lock,fcntl.LOCK_EX);fcntl.flock(materialize_lock,fcntl.LOCK_EX)
        backup=vault/'before_reset.sqlite'
        if not backup.exists():
            with sqlite3.connect(backup) as dst:c.backup(dst)
        c.execute('BEGIN IMMEDIATE')
        try:
            assert not c.execute("SELECT 1 FROM jobs WHERE status='running'").fetchone(),'Stop generation gracefully before resetting'
            reviews_before=[tuple(r) for r in c.execute('SELECT * FROM reviews ORDER BY job_id')]
            events_before=[tuple(r) for r in c.execute('SELECT * FROM review_events ORDER BY id')]
            rows=c.execute("SELECT * FROM jobs j WHERE j.kind='tryon' AND j.status='success' AND NOT EXISTS(SELECT 1 FROM reviews r WHERE r.job_id=j.id)").fetchall()
            for priority,row in enumerate(rows):
                key=row['id'];folder=vault/key;folder.mkdir(exist_ok=True);con=json.loads(row['condition'])
                active=c.execute("SELECT r.child_job,r.id FROM regeneration_requests r JOIN jobs j ON j.id=r.child_job WHERE r.parent_job=? AND (j.status IN ('pending','interrupted','blocked_dependency','waiting_reference') OR (j.status='failed' AND j.attempts<3))",(key,)).fetchone()
                child,request=(active['child_job'],active['id']) if active else store.enqueue_regeneration(c,key,con,'other',NOTES,'','자동 교체','system:'+RUN_ID)
                c.execute('INSERT OR IGNORE INTO batch_jobs VALUES(?,?,?)',(BATCH,child,priority))
                snapshots=[];candidates=[]
                for path in [Path(row['output'])]+[lab.ROOT/name/(key+'.png') for name in lab.FOLDERS[5:9]+[store.ARCHIVE]]:
                    if path.is_file() and path not in candidates:candidates.append(path)
                assert candidates,'Missing original output: '+key
                for original in candidates:
                    sha=lab.digest(original)
                    assert not row['output_sha256'] or sha==row['output_sha256'],'Image hash changed: '+key
                    target=folder/original.parent.name/original.name;target.parent.mkdir(exist_ok=True)
                    assert not target.exists(),'Archive destination already exists: '+str(target)
                    os.replace(original,target);moved.append((original,target));snapshots.append(dict(original=str(original),archived=str(target),sha256=sha))
                record=dict(job=dict(row),drafts=[dict(r) for r in c.execute('SELECT * FROM review_drafts WHERE job_id=?',(key,))],files=snapshots,child_job=child,request_id=request)
                (folder/'record.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
                archive_output=next((x['archived'] for x in snapshots if x['original']==row['output']),snapshots[0]['archived'])
                c.execute('UPDATE jobs SET status=?,output=?,error=? WHERE id=?',(STATUS,archive_output,'사용자 요청으로 미검수 결과를 보관하고 최신 조건으로 재생성',key))
                for table in ('review_pool','review_claims'):c.execute('DELETE FROM '+table+' WHERE job_id=?',(key,))
                items.append(dict(id=key,child_job=child,request_id=request,files=snapshots))
            assert reviews_before==[tuple(r) for r in c.execute('SELECT * FROM reviews ORDER BY job_id')]
            assert events_before==[tuple(r) for r in c.execute('SELECT * FROM review_events ORDER BY id')]
            c.execute('INSERT OR IGNORE INTO batches VALUES(?,?,?,?,?)',(BATCH,lab.now(),None,'prepared',json.dumps(dict(reason=NOTES,run_id=RUN_ID),ensure_ascii=False)))
            result=dict(id=RUN_ID,created=lab.now(),archived=len(items),files_moved=len(moved),reviewed_preserved=len(reviews_before),review_events_preserved=len(events_before),batch=BATCH,items=items)
            c.execute('INSERT INTO unreviewed_resets VALUES(?,?)',(RUN_ID,json.dumps(result,ensure_ascii=False)));c.commit()
        except Exception:
            c.rollback()
            for original,target in reversed(moved):
                if target.exists() and not original.exists():os.replace(target,original)
            raise
    (vault/'reset_manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));lab.export(c)
    return result

if __name__=='__main__':
    result=reset(lab.connect());print(json.dumps({k:v for k,v in result.items() if k!='items'},ensure_ascii=False))
