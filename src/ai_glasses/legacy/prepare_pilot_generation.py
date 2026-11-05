"""Replace the large balancing run with exactly 24 camera-free smart samples."""
import fcntl,json,sqlite3
from ai_glasses.generation import tryon_lab as lab
from ai_glasses.generation import balance_generation as balance

BATCH='quick_pilot_24_20261104'
def main():
    c=lab.connect();existing=c.execute('SELECT metadata FROM batches WHERE name=?',(BATCH,)).fetchone()
    if existing:print(existing[0]);return
    config_path=lab.ROOT/balance.SETTINGS;config=json.loads(config_path.read_text())
    with open(lab.ROOT/'public_review.lock','w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        backup=lab.ROOT/'work'/'before_small_pilot_20261104.sqlite'
        with sqlite3.connect(backup) as dst:c.backup(dst)
        (lab.ROOT/'work'/'balance_settings_before_pilot_20261104.json').write_text(json.dumps(config,ensure_ascii=False,indent=2))
        c.execute('BEGIN IMMEDIATE')
        try:
            assert not c.execute("SELECT 1 FROM jobs WHERE status='running'").fetchone()
            rows=c.execute("SELECT j.*,s.product FROM jobs j JOIN sources s ON s.id=json_extract(j.condition,'$.source_id') WHERE j.kind='tryon' AND s.category='C' AND j.status='pending' AND json_extract(j.condition,'$.protocol')=? ORDER BY j.rowid",(balance.BATCH,)).fetchall()
            products=sorted({r['product'] for r in rows});assert len(products)==6
            selected=[]
            for index,product in enumerate(products):
                poses=['front','left_oblique' if index%2==0 else 'right_oblique','left_profile','right_profile'];people=set()
                for pose in poses:
                    options=[r for r in rows if r['product']==product and json.loads(r['condition']).get('pose')==pose and r['id'] not in {x['id'] for x in selected}]
                    assert options,(product,pose)
                    row=next((r for r in options if json.loads(r['condition']).get('person_id') not in people),options[0]);con=json.loads(row['condition']);people.add(con.get('person_id'))
                    parent=c.execute('SELECT status,output FROM jobs WHERE id=?',(con['portrait_job'],)).fetchone();assert parent and parent['status']=='success'
                    selected.append(dict(id=row['id'],product=product,pose=pose,person=con.get('person_id')))
            assert len(selected)==24
            deferred=c.execute("SELECT id,status FROM jobs WHERE kind='tryon' AND json_extract(condition,'$.protocol')=? AND status IN ('pending','interrupted','blocked_dependency','failed')",(balance.BATCH,)).fetchall()
            c.execute('CREATE TABLE IF NOT EXISTS pilot_deferred_jobs(job_id TEXT PRIMARY KEY,previous_status TEXT,created TEXT)')
            ids={r['id'] for r in selected}
            for row in deferred:
                if row['id'] in ids:continue
                c.execute('INSERT OR IGNORE INTO pilot_deferred_jobs VALUES(?,?,?)',(row['id'],row['status'],lab.now()))
                c.execute("UPDATE jobs SET status='deferred_pilot',error='Large balancing run paused by user; only the fixed 24-image pilot is scheduled' WHERE id=?",(row['id'],))
            for index,row in enumerate(selected):c.execute('INSERT INTO batch_jobs VALUES(?,?,?)',(BATCH,row['id'],(index%4)*6+index//4))
            manifest=dict(created=lab.now(),batch=BATCH,additional_images=24,products=6,per_product=4,category='C',other_categories_added=0,deferred=len(deferred)-24,stop_after_batch=True,items=selected)
            c.execute('INSERT INTO batches VALUES(?,?,?,?,?)',(BATCH,lab.now(),None,'prepared',json.dumps(manifest,ensure_ascii=False)));c.commit()
        except Exception:c.rollback();raise
    config.update(enabled=False,mode='pilot',active_batch=BATCH,reason='User requested a small quick training pilot, not 500 per category',pilot_size=24)
    temp=config_path.with_suffix('.tmp');temp.write_text(json.dumps(config,ensure_ascii=False,indent=2));temp.replace(config_path)
    (lab.ROOT/lab.FOLDERS[9]/'quick_pilot_24_20261104.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2));lab.export(c)
    print(json.dumps({k:v for k,v in manifest.items() if k!='items'},ensure_ascii=False))

if __name__=='__main__':main()
