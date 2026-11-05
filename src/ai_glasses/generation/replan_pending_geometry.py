"""Replace unfinished conditions atomically while keeping the original job records."""
import json
from ai_glasses.generation import tryon_lab as lab
from ai_glasses.generation.multiview_references import prompt_for_views,wearing_prompt

def migrate(c,waiting_only=False):
 states="('waiting_reference')" if waiting_only else "('pending','interrupted','failed','blocked_dependency','waiting_reference')"
 rows=c.execute("SELECT DISTINCT j.* FROM jobs j WHERE j.kind='tryon' AND j.status IN "+states+" AND (j.id IN (SELECT job_id FROM batch_jobs WHERE batch IN ('korean_students_v1','user_people_v1','public_regeneration')) OR j.id IN (SELECT child_job FROM regeneration_requests))").fetchall();changed=0
 for row in rows:
  con=json.loads(row['condition']);s=c.execute('SELECT metadata FROM sources WHERE id=?',(con.get('source_id'),)).fetchone()
  if not s:continue
  meta=json.loads(s['metadata'])
  if row['status']=='waiting_reference' and not meta.get('extra_references'):continue
  new=dict(con)
  if meta.get('extra_references'):
   new.update(extra_references=meta['extra_references'],reference_resolution=768,reference_count=3)
   if 'Reference image roles:' not in new['prompt']:new['prompt']=prompt_for_views(new['prompt'],new['extra_references'])
  new['prompt']=wearing_prompt(new['prompt']);new['open_temple_required']=True
  key=lab.uid(new)
  if key==row['id']:continue
  c.execute('BEGIN IMMEDIATE')
  try:
   fresh=c.execute('SELECT status FROM jobs WHERE id=?',(row['id'],)).fetchone()
   if fresh['status']=='running' or fresh['status']=='success':c.rollback();continue
   c.execute('INSERT OR IGNORE INTO jobs(id,kind,condition) VALUES(?,?,?)',(key,'tryon',json.dumps(new,ensure_ascii=False)))
   for b in c.execute('SELECT * FROM batch_jobs WHERE job_id=?',(row['id'],)).fetchall():
    c.execute('DELETE FROM batch_jobs WHERE batch=? AND job_id=?',(b['batch'],row['id']));c.execute('INSERT OR IGNORE INTO batch_jobs VALUES(?,?,?)',(b['batch'],key,b['priority']))
   c.execute('UPDATE regeneration_requests SET child_job=? WHERE child_job=?',(key,row['id']));c.execute("UPDATE jobs SET status='superseded',error='Replaced with verified open-side references and unfolded wearing geometry' WHERE id=?",(row['id'],));c.commit();changed+=1
  except Exception:c.rollback();raise
 return changed
if __name__=='__main__':
 c=lab.connect();print(json.dumps({'updated_conditions':migrate(c)}));lab.export(c)
