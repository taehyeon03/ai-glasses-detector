"""Import a real completed trial as an unreviewed result; never import test reviews."""
import json,sqlite3,shutil
from pathlib import Path
from ai_glasses.generation import tryon_lab as lab

def main():
 c=lab.connect();trial=sqlite3.connect(lab.ROOT/'work/multiview_trial/experiment.sqlite');trial.row_factory=sqlite3.Row
 row=trial.execute("SELECT * FROM jobs WHERE kind='tryon' AND status='success' AND json_extract(condition,'$.reference_resolution')=768 ORDER BY rowid DESC LIMIT 1").fetchone()
 if not row:raise ValueError('No successful 3-reference trial yet')
 source=Path(row['output']);target=lab.ROOT/lab.FOLDERS[5]/(row['id']+'.png')
 if lab.digest(source)!=row['output_sha256']:raise ValueError('Trial output changed')
 if not target.exists():shutil.copy2(source,target)
 d=dict(row);d['output']=str(target);keys=list(d)
 c.execute('INSERT OR IGNORE INTO jobs('+','.join(keys)+') VALUES('+','.join('?' for _ in keys)+')',[d[k] for k in keys]);c.commit()
 for a in trial.execute('SELECT * FROM attempts WHERE job_id=?',(row['id'],)):
  if not c.execute('SELECT 1 FROM attempts WHERE job_id=? AND started=?',(row['id'],a['started'])).fetchone():
   values=dict(a);values.pop('id');cols=list(values);c.execute('INSERT INTO attempts('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+')',[values[k] for k in cols])
 c.commit();lab.export(c)
 from PIL import Image
 summary=dict(job=row['id'],status='success',input_images=3,reference_resolution=768,output_size=list(Image.open(target).size),seconds=row['seconds'],peak_torch_gb=row['peak_gb'],review_status='unreviewed',front_only_baseline=json.loads(row['condition'])['front_only_baseline'])
 (lab.ROOT/lab.FOLDERS[9]/'multiview_verified.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary))
if __name__=='__main__':main()
