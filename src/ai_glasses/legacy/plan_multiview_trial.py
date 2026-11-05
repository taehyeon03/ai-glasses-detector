import json,shutil
from pathlib import Path
from ai_glasses.generation import tryon_lab as lab
from ai_glasses.generation.multiview_references import prompt_for_views
c=lab.connect();source=c.execute("SELECT * FROM sources WHERE product='Mentra Live' AND category='A'").fetchone()
side=lab.ROOT/'source_snapshot/AI안경_이미지/07_Mentra/Mentra_Live/Mentra_Live_005.png'
root=lab.ROOT/'work'/'multiview_trial';root.mkdir(exist_ok=True)
base=c.execute("SELECT * FROM jobs WHERE kind='tryon' AND status='success' AND json_extract(condition,'$.source_id')=? AND json_extract(condition,'$.protocol')='korean_students_facecrop_v3' ORDER BY rowid LIMIT 1",(source['id'],)).fetchone()
if not base:raise ValueError('Need a completed face-closeup baseline')
con=json.loads(base['condition']);parent=c.execute('SELECT * FROM jobs WHERE id=?',(con['portrait_job'],)).fetchone()
lab.ROOT=root;t=lab.connect()
for table,row in [('sources',source),('jobs',parent)]:
 d=dict(row);keys=list(d);t.execute('INSERT OR IGNORE INTO '+table+'('+','.join(keys)+') VALUES('+','.join('?' for _ in keys)+')',[d[k] for k in keys])
t.commit();extra=dict(path=str(side),sha256=lab.digest(side),role='left_side',product='Mentra Live',reference_inspection='same black product; manufacturer URL and image visually checked')
con.update(extra_references=[extra],protocol='front_side_trial_v1',batch='multiview_trial',reference_count=3,front_only_baseline=base['id'])
con['prompt']=prompt_for_views(con['prompt'],[extra]);key=lab.add_job(t,con,'tryon');t.execute('INSERT OR IGNORE INTO batch_jobs VALUES(?,?,?)',('multiview_trial',key,0));t.commit();print(json.dumps({'root':str(root),'job':key,'baseline':base['id']}))
