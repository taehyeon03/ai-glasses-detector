import json
from pathlib import Path
import shutil
import sqlite3
from ai_glasses.generation import tryon_lab as lab
src=lab.connect();row=src.execute("SELECT * FROM jobs WHERE kind='tryon' AND status='success' AND json_extract(condition,'$.camera')='present' ORDER BY rowid LIMIT 1").fetchone();con=json.loads(row['condition']);parent=src.execute('SELECT * FROM jobs WHERE id=?',(con['portrait_job'],)).fetchone();source=src.execute('SELECT * FROM sources WHERE id=?',(con['source_id'],)).fetchone()
root=lab.ROOT/'work'/'public_review_e2e';root.mkdir(exist_ok=True);lab.ROOT=root;c=lab.connect()
for table,record in [('sources',source),('jobs',parent),('jobs',row)]:
 d=dict(record)
 if table=='jobs' and d['id']==row['id']:
  out=root/lab.FOLDERS[5]/(row['id']+'.png');shutil.copy2(row['output'],out);d['output']=str(out)
 keys=list(d);c.execute('INSERT OR IGNORE INTO '+table+'('+','.join(keys)+') VALUES('+','.join('?' for _ in keys)+')',[d[k] for k in keys])
c.commit();from ai_glasses.review import public_review_store as store;store.init(c);print(json.dumps(dict(root=str(root),job=row['id'])))
