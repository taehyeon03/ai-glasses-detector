"""Replace only unstarted frontal jobs that have a product-side reference."""
import json,collections,fcntl
from ai_glasses.generation import tryon_lab as lab
BATCH='diversity_20261102_v1'
PREVIEW='pose_preview_20261103'
POSES=[('left_oblique','Turn the head about 35 degrees so the nose points toward image left. Keep a clear three-quarter face with the far side narrower.'),('right_oblique','Turn the head about 35 degrees so the nose points toward image right. Keep a clear three-quarter face with the far side narrower.'),('left_profile','Create a strict near-90-degree left-facing side profile: the nose points toward image left and is seen in silhouette. Show only the near eye and near ear. The far eye and far ear must be hidden.'),('right_profile','Create a strict near-90-degree right-facing side profile: the nose points toward image right and is seen in silhouette. Show only the near eye and near ear. The far eye and far ear must be hidden.')]
def main():
 from ai_glasses.generation.multiview_references import prompt_for_views,wearing_prompt
 c=lab.connect()
 if c.execute('SELECT 1 FROM batches WHERE name=?',(PREVIEW,)).fetchone():print('Already prepared');return
 rows=c.execute("SELECT * FROM jobs WHERE kind='tryon' AND status='pending' AND json_extract(condition,'$.batch')=? AND json_array_length(json_extract(condition,'$.extra_references'))>0 ORDER BY rowid",(BATCH,)).fetchall()
 counters=collections.Counter();parents={};changes=[]
 with open(lab.ROOT/'public_review.lock','w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX);c.execute('BEGIN IMMEDIATE')
  try:
   for row in rows:
    if c.execute('SELECT status FROM jobs WHERE id=?',(row['id'],)).fetchone()[0]!='pending':continue
    con=json.loads(row['condition']);pid=con['person_id'];pose,guide=POSES[counters[pid]%4];counters[pid]+=1
    if (pid,pose) not in parents:
     base=c.execute('SELECT condition FROM jobs WHERE id=?',(con['portrait_job'],)).fetchone();pc=json.loads(base[0]);parent=con['portrait_job']
     pc.update(portrait_parent=parent,pose=pose,protocol='diversity_side_faces_v1',pose_verified=False,pose_convention='direction the nose points in the image',seed=int(lab.uid([parent,pose,'20261103'])[:8],16)%(2**31))
     pc['prompt']='Use image 1 as the adult identity reference. Preserve this exact fictional adult identity, natural skin tone, hairstyle and visible clothing neckline. '+guide+' Keep a tight face-only square crop with the complete head, forehead, chin and visible ear, and a small margin. Show at most a thin neckline below the chin. No shoulders, chest, arms or hands. Neutral diffuse indoor daylight. No glasses, eyewear, text or collage. Do not return the original frontal head direction.'
     key=lab.uid(pc);parents[(pid,pose)]=key;c.execute('INSERT INTO jobs(id,kind,condition) VALUES(?,?,?)',(key,'portrait',json.dumps(pc,ensure_ascii=False)));c.execute('INSERT INTO batch_jobs VALUES(?,?,?)',(BATCH,key,-100-len(parents)))
    new=dict(con);new.update(portrait_job=parents[(pid,pose)],pose=pose,protocol='diversity_side_faces_v1',pose_verified=False,pose_convention='direction the nose points in the image',replaces_unstarted_job=row['id'],seed=int(lab.uid([row['id'],pose])[:8],16)%(2**31))
    source=c.execute('SELECT metadata FROM sources WHERE id=?',(con['source_id'],)).fetchone();meta=json.loads(source[0])
    prompt='Edit image 1 and keep the exact same adult identity, natural skin tone, hair and clothing neckline. Preserve the reference head direction. '+guide+' Keep a tight face close-up; show the whole visible head and chin with no shoulders, chest, arms or hands. Put the exact physical glasses from image 2 on this person. Use image 3 to preserve the real temple, hinge, curvature and side components. Show only the glasses surfaces that are physically visible at this head angle. Do not force the far lens, far camera or far ear into a side profile. Preserve frame shape, material, color, lens tint and the true camera/light positions. Never invent or duplicate a camera. Keep real nose support and near-ear support. Do not produce a product-only image. No text, montage or comparison panels. '+meta['detail_prompt']
    new['prompt']=wearing_prompt(prompt_for_views(prompt,new['extra_references']));key=lab.uid(new)
    c.execute('INSERT INTO jobs(id,kind,condition) VALUES(?,?,?)',(key,'tryon',json.dumps(new,ensure_ascii=False)))
    for batchrow in c.execute('SELECT * FROM batch_jobs WHERE job_id=?',(row['id'],)).fetchall():
     c.execute('DELETE FROM batch_jobs WHERE batch=? AND job_id=?',(batchrow['batch'],row['id']));c.execute('INSERT INTO batch_jobs VALUES(?,?,?)',(batchrow['batch'],key,batchrow['priority']))
    c.execute("UPDATE jobs SET status='superseded',error='Replaced before generation with the user-requested side-face composition' WHERE id=?",(row['id'],));changes.append(dict(old=row['id'],new=key,person=pid,pose=pose))
   # One profile sample runs before the larger regeneration queue.
   first=next((r for r in changes if r['pose'].endswith('profile')),changes[0] if changes else None)
   if first:
    c.execute('INSERT INTO batch_jobs VALUES(?,?,?)',(PREVIEW,first['new'],0));c.execute('INSERT INTO batches VALUES(?,?,?,?,?)',(PREVIEW,lab.now(),None,'prepared',json.dumps(first)))
   c.commit()
  except Exception:c.rollback();raise
 result=dict(created=lab.now(),converted=len(changes),portrait_views=len(parents),poses=dict(collections.Counter(r['pose'] for r in changes)),changes=changes,preview=first)
 (lab.ROOT/lab.FOLDERS[9]/'side_face_views_20261103.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));lab.export(c);print(json.dumps({k:v for k,v in result.items() if k!='changes'},ensure_ascii=False))
if __name__=='__main__':main()
