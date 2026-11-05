"""Add the two explicitly provided real-person references without exposing raw originals."""
import json
from PIL import Image,ImageOps
from ai_glasses.generation import tryon_lab as lab
from ai_glasses.generation.multiview_references import prompt_for_views,wearing_prompt
BATCH='user_people_v1'

def main():
 c=lab.connect();sources=[dict(r) for r in c.execute("SELECT * FROM sources WHERE category IN ('A','B') AND json_extract(metadata,'$.selected')=1 ORDER BY product")];ordered=[s for pair in zip([s for s in sources if s['category']=='A'],[s for s in sources if s['category']=='B']) for s in pair];manifest=[]
 people=json.loads((lab.ROOT/'user_provided_references'/'people.json').read_text())
 for index,person in enumerate(people):
  pid,filename,drive_id,pose=(person[k] for k in ('person_id','filename','drive_id','pose'))
  raw=lab.ROOT/'user_provided_references'/(pid+'_original.jpg')
  with Image.open(raw) as opened:image=ImageOps.exif_transpose(opened).convert('RGB')
  box=person['crop_box'];face_bbox=None;crop_method='manually inspected face region; aspect-preserving padding'
  pc=dict(model=lab.MODEL,revision=lab.REVISION,person_id=pid,description='Adult reference explicitly provided by the user',hair='as in supplied photograph',pose=pose,light='lighting from the supplied photograph',width=1024,height=1024,steps=40,kv_cache=True,protocol='user_face_crop_v1',cohort=BATCH,composition='tight_face_closeup',synthetic=False,face_origin='user_provided_reference',source_face_real=True,source_drive_id=drive_id,source_filename=filename,source_sha256=lab.digest(raw),derivation='deterministic_face_crop_of_user_provided_photo',crop_box=box,face_bbox=face_bbox,crop_method=crop_method,occlusion='as_in_reference')
  key=lab.add_job(c,pc,'portrait');out=lab.ROOT/lab.FOLDERS[4]/(key+'.png');ImageOps.pad(image.crop(box),(1024,1024),method=Image.Resampling.LANCZOS,color=(225,225,220)).save(out)
  c.execute("UPDATE jobs SET status='success',output=?,output_sha256=?,finished=?,environment=? WHERE id=?",(str(out),lab.digest(out),lab.now(),json.dumps({'derivation':'crop of supplied real photo'}),key));c.execute('INSERT OR IGNORE INTO batch_jobs VALUES(?,?,?)',(BATCH,key,index));c.commit()
  for k,s in enumerate(ordered):
   meta=json.loads(s['metadata']);prompt='Edit image 1, which is a real adult identity reference supplied by the user. Preserve the exact facial anatomy, identity, natural skin texture, hair, expression, head direction and camera view. Keep this tight face close-up; show the complete glasses and ears while excluding shoulders, chest and arms. Put only the physical glasses from image 2 onto this person. Match the actual frame outline, dimensions, thickness, material, color, lens shape and opacity, bridge, nose support, temples, cameras and separate indicator lights. Do not invent cameras or copy a status light as a camera. Do not add comparison panels or text. '+meta['detail_prompt']
   con={k:pc[k] for k in ('model','revision','person_id','hair','pose','light','width','height','steps','kv_cache','protocol','cohort','composition','face_origin','source_face_real','occlusion')};con.update(synthetic=True,kind='tryon',portrait_job=key,source_id=s['id'],source_sha256=s['sha256'],product=s['product'],camera=s['camera'],camera_confirmation='official_documentation_and_source_image_inspection',seed=int(lab.uid([key,s['id']])[:8],16)%(2**31),batch=BATCH,unseen_geometry='inferred_where_not_visible_in_references',open_temple_required=True)
   if meta.get('extra_references'):con.update(extra_references=meta['extra_references'],reference_resolution=768,reference_count=3);prompt=prompt_for_views(prompt,con['extra_references'])
   con['prompt']=wearing_prompt(prompt);job=lab.add_job(c,con,'tryon');c.execute('INSERT OR IGNORE INTO batch_jobs VALUES(?,?,?)',(BATCH,job,k*2+index))
  manifest.append(dict(person_id=pid,source_drive_id=drive_id,source_filename=filename,reference_job=key,crop_box=box,pose=pose))
 c.execute('INSERT OR IGNORE INTO batches VALUES(?,?,?,?,?)',(BATCH,lab.now(),None,'prepared',json.dumps({'people':len(people),'tryons':len(people)*len(ordered),'face_origin':'user_provided_reference'})));c.commit();lab.export(c);(lab.ROOT/lab.FOLDERS[9]/'user_people_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2));print(json.dumps(dict(people=manifest,tryons=len(people)*len(ordered))))
if __name__=='__main__':main()
