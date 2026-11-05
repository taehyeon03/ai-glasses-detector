"""Prepare the user-requested replacement batch and retain all human decisions."""
import fcntl,json
from ai_glasses.generation import tryon_lab as lab
from ai_glasses.review import public_review_store as store
from ai_glasses.generation.multiview_references import prompt_for_views,wearing_prompt
BATCH='k04_vanguard_rebuild_20261102'
PRODUCT='Oakley Meta Vanguard'

def main():
 c=lab.connect();store.init(c)
 if c.execute('SELECT 1 FROM batches WHERE name=?',(BATCH,)).fetchone():
  print('Batch already prepared');return
 assert not c.execute("SELECT 1 FROM jobs WHERE status='running'").fetchone(),'Stop worker gracefully before rebuilding'
 old=c.execute('SELECT * FROM sources WHERE product=? AND json_extract(metadata,\'$.selected\')=1',(PRODUCT,)).fetchone()
 front=lab.ROOT/lab.FOLDERS[0]/'Vanguard_800107_front.png';side=front.with_name('Vanguard_800107_left.png')
 meta=json.loads(old['metadata']);meta.update(selected=True,original_source_id=old['id'],source_page='https://www.oakley.com/en-us/product/W0OW8001',sku='0OW8001__800107',reference_resolution=768,detail_prompt='Black Oakley Meta Vanguard with Prizm Black single wraparound shield lens. Preserve the single camera on the central nose-bridge module exactly as shown in the front reference. The camera sits below the top rim, not at an outer corner. Preserve the two separate small light apertures near the top center as lights, not additional cameras. Preserve the open black temples and exact side silhouette shown in image 3.')
 meta['extra_references']=[dict(path=str(side),sha256=lab.digest(side),role='left_side',product=PRODUCT,temple_state='open',source_page=meta['source_page'],sku_prefix=meta['sku'],inspection='Official same SKU and color frontal and left-side images visually inspected; human output review still required')]
 sourceid=lab.uid(['official_vanguard_800107',lab.digest(front)])
 faces={}
 for pid in [f'K{i:02}' for i in range(1,9)]+['U02','U03']:
  protocol='korean_students_facecrop_v3' if pid.startswith('K') else None
  query="SELECT * FROM jobs WHERE kind='portrait' AND status='success' AND json_extract(condition,'$.person_id')=?"
  params=[pid]
  if protocol:query+=" AND json_extract(condition,'$.protocol')=?";params.append(protocol)
  face=c.execute(query+' ORDER BY rowid DESC LIMIT 1',params).fetchone();assert face,pid
  faces[pid]=(face['id'],json.loads(face['condition']))
 sources=[dict(s) for s in c.execute("SELECT * FROM sources WHERE category IN ('A','B') AND json_extract(metadata,'$.selected')=1") if s['product']!=PRODUCT]
 sources.append(dict(old,id=sourceid,path=str(front),sha256=lab.digest(front),metadata=json.dumps(meta,ensure_ascii=False)))
 assert len(sources)==20
 fresh={}; ordered=[]
 for pid in faces:
  for s in sources:
   if pid!='K04' and s['product']!=PRODUCT:continue
   parent,pc=faces[pid];sm=json.loads(s['metadata'])
   con={k:pc[k] for k in ('model','revision','person_id','hair','pose','light','width','height','steps','kv_cache','cohort','synthetic','face_origin','occlusion') if k in pc}
   prompt='Edit image 1 and preserve this exact adult identity, hair, expression and head direction. Produce a tight FACE-ONLY square close-up. The face and complete glasses occupy most of the image. Show the whole forehead, hair, chin and both ears with only a small margin. End the image just below the chin; exclude shoulders, chest, torso and arms. Put the single pair of glasses from image 2 naturally on the nose and over the ears. Preserve every visible manufactured frame contour, thickness, color, lens tint and opacity, bridge, camera aperture and separate indicator light. Never invent, relocate or duplicate a camera. Keep one pair of glasses on the face; never output a product-only photograph. No text or comparison panels. '+sm['detail_prompt']
   con.update(kind='tryon',portrait_job=parent,source_id=s['id'],source_sha256=s['sha256'],product=s['product'],camera=s['camera'],camera_confirmation='official_product_documentation_and_source_inspection',protocol=BATCH,composition='tight_face_closeup',batch=BATCH,seed=int(lab.uid([BATCH,pid,s['id']])[:8],16)%(2**31),unseen_geometry='inferred_not_verified',open_temple_required=True)
   if sm.get('extra_references'):
    con.update(extra_references=sm['extra_references'],reference_resolution=768,reference_count=3);prompt=prompt_for_views(prompt,sm['extra_references'])
   con['prompt']=wearing_prompt(prompt)
   key=lab.uid(con);fresh[(pid,s['product'])]=key;ordered.append((key,con))
 assert len(ordered)==29
 ordered.sort(key=lambda item:(item[1]['person_id']!='K04' or item[1]['product']!=PRODUCT,item[1]['product']!=PRODUCT,item[1]['person_id'],item[1]['product']))
 oldrows=c.execute("SELECT j.*,r.decision FROM jobs j LEFT JOIN reviews r ON r.job_id=j.id WHERE j.kind='tryon' AND (json_extract(j.condition,'$.person_id')='K04' OR json_extract(j.condition,'$.product')=?)",(PRODUCT,)).fetchall()
 manifest={'created':lab.now(),'batch':BATCH,'new_jobs':[k for k,_ in ordered],'retired':[],'preserved_reviewed':[],'first_job':ordered[0][0],'reference_source_id':sourceid}
 with open(lab.ROOT/'public_review.lock','w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX);c.execute('BEGIN IMMEDIATE')
  try:
   oldmeta=json.loads(old['metadata']);oldmeta['selected']=False
   c.execute('UPDATE sources SET metadata=? WHERE id=?',(json.dumps(oldmeta,ensure_ascii=False),old['id']))
   c.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)',(sourceid,str(front),lab.digest(front),PRODUCT,old['category'],old['camera'],old['evidence'],json.dumps(meta,ensure_ascii=False)))
   c.execute('INSERT INTO batches VALUES(?,?,?,?,?)',(BATCH,lab.now(),None,'prepared',json.dumps({'tryons':29,'K04_products':20,'Vanguard_people':10,'human_review_required':True})))
   for priority,(key,con) in enumerate(ordered):
    c.execute('INSERT INTO jobs(id,kind,condition) VALUES(?,?,?)',(key,'tryon',json.dumps(con,ensure_ascii=False)))
    c.execute('INSERT INTO batch_jobs VALUES(?,?,?)',(BATCH,key,priority))
   for row in oldrows:
    if row['decision']:
     manifest['preserved_reviewed'].append(row['id']);continue
    if row['status']=='superseded':continue
    c.execute("UPDATE jobs SET status='superseded',error=? WHERE id=?",('Replaced at user request: K04 face close-up and/or Vanguard verified frontal/side references; originals retained',row['id']))
    for table in ('review_pool','review_claims'):c.execute('DELETE FROM '+table+' WHERE job_id=?',(row['id'],))
    con=json.loads(row['condition']);replacement=fresh.get((con.get('person_id'),con.get('product')))
    if replacement:c.execute('UPDATE regeneration_requests SET child_job=? WHERE child_job=?',(replacement,row['id']))
    manifest['retired'].append({'id':row['id'],'previous_status':row['status'],'replacement':replacement})
   c.commit()
  except Exception:c.rollback();raise
 (lab.ROOT/lab.FOLDERS[9]/(BATCH+'.json')).write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
 lab.export(c)
 print(json.dumps({'batch':BATCH,'new':len(ordered),'retired':len(manifest['retired']),'preserved_reviewed':len(manifest['preserved_reviewed']),'first_job':ordered[0][0]}))
if __name__=='__main__':main()
