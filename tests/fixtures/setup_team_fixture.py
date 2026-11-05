import json
from pathlib import Path
import shutil
from ai_glasses.generation import tryon_lab as lab
src=lab.connect();row=src.execute("SELECT * FROM jobs WHERE kind='tryon' AND status='success' ORDER BY rowid LIMIT 1").fetchone();con=json.loads(row['condition']);parent=src.execute('SELECT * FROM jobs WHERE id=?',(con['portrait_job'],)).fetchone();source=src.execute('SELECT * FROM sources WHERE id=?',(con['source_id'],)).fetchone()
root=lab.ROOT/'work'/'team_review_e2e_v1';root.mkdir(exist_ok=True);lab.ROOT=root;c=lab.connect()
for table,record in [('sources',source),('jobs',parent)]:
 d=dict(record);keys=list(d);c.execute('INSERT OR IGNORE INTO '+table+'('+','.join(keys)+') VALUES('+','.join('?' for _ in keys)+')',[d[k] for k in keys])
c.commit()
for i in range(5):
 cond=dict(con,seed=780000+i,test_only='isolated_team_fixture');key=lab.add_job(c,cond,'tryon');out=root/lab.FOLDERS[5]/(key+'.png');shutil.copy2(row['output'],out)
 c.execute("UPDATE jobs SET status='success',output=?,output_sha256=?,finished=? WHERE id=?",(str(out),lab.digest(out),lab.now(),key))
c.commit();print(root)
