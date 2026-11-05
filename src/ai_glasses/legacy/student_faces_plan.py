"""Add adult Korean university-student portrait references without overwriting prior identities."""
import json
from ai_glasses.generation import tryon_lab as lab
BATCH='korean_students_v1'
PEOPLE=[
('K01','Korean man age 22, youthful oval face, natural light-medium skin, clean shaven','short black two-block dandy haircut with soft separated fringe above the eyebrows'),
('K02','Korean man age 24, softly angular face, natural warm medium skin, clean shaven','black hair with a natural 6:4 side part and comma fringe, neat short sides'),
('K03','Korean man age 21, rounded youthful face, natural light skin, clean shaven','short textured black crop with a light see-through fringe that leaves eyebrows visible'),
('K04','Korean man age 25, broad oval face, natural medium skin, clean shaven','medium-length black curtain hair with a natural center part, lightly wavy and tucked away from temples'),
('K05','Korean woman age 22, soft oval face, natural light-medium skin','long dark brown layered hair with a natural center part and soft C-curl ends, tucked behind ears'),
('K06','Korean woman age 24, gently angular face, natural warm medium skin','shoulder-length black layered hair with light see-through bangs above eyebrows, tucked behind ears'),
('K07','Korean woman age 21, round youthful face, natural light skin','straight chin-length dark brown bob with a side part, neat around ears and no heavy fringe'),
('K08','Korean woman age 25, long oval face, natural medium skin','black hair in a low ponytail with a natural side part and a few fine strands, temples unobstructed')]
def main():
 c=lab.connect()
 # Preserve completed outputs; replace only unstarted older composition jobs.
 c.execute("UPDATE jobs SET status='superseded',error='Replaced by tight face close-up conditions at user request' WHERE status IN ('pending','interrupted','blocked_dependency','failed') AND json_extract(condition,'$.cohort')='korean_students_v1' AND coalesce(json_extract(condition,'$.protocol'),'')!='korean_students_facecrop_v3'");c.commit()
 sources=[dict(s) for s in c.execute("SELECT * FROM sources WHERE category IN ('A','B') AND json_extract(metadata,'$.selected')=1 ORDER BY product")]
 ordered=[s for pair in zip([s for s in sources if s['category']=='A'],[s for s in sources if s['category']=='B']) for s in pair]
 for i,(pid,desc,hair) in enumerate(PEOPLE):
  prompt=f'A natural unretouched photograph of a completely fictional adult {desc}. This person is not a real individual. A contemporary Korean university student in their early to mid twenties. Hairstyle: {hair}. Everyday plain casual campus clothing, relaxed neutral expression, realistic skin texture and individual facial features. No beauty filter, no heavy makeup, no idol styling. Looking straight at camera. Bright diffuse indoor daylight. TIGHT FACE CLOSE-UP. The adult face fills most of the square photograph. Frame only the complete forehead, hair, face, chin and both ears. Keep the whole glasses area and temples visible. The bottom edge ends just below the chin. No shoulders, chest, torso, arms or hands in the image. Do not make a head-and-shoulders or upper-body portrait. Plain light gray room background. Temples and eyebrows visible for glasses fitting. No glasses, sunglasses, head accessories, text, collage or graphics.'
  reference=c.execute("SELECT id,condition FROM jobs WHERE kind='portrait' AND status='success' AND json_extract(condition,'$.person_id')=? AND json_extract(condition,'$.protocol')='korean_students_facecrop_v3' ORDER BY rowid DESC LIMIT 1",(pid,)).fetchone()
  if not reference:raise ValueError('Prepare the glasses-free cropped face reference first: '+pid)
  pc=json.loads(reference['condition']);pk=reference['id']
  c.execute('INSERT OR IGNORE INTO batch_jobs VALUES(?,?,?)',(BATCH,pk,i))
  for k,s in enumerate(ordered):
   meta=json.loads(s['metadata'])
   template=c.execute("SELECT condition FROM jobs WHERE kind='tryon' AND json_extract(condition,'$.source_id')=? AND status='success' ORDER BY rowid DESC LIMIT 1",(s['id'],)).fetchone()
   prompt='Create a tight face close-up based on image 1. Keep the exact same fictional adult identity and hair. Crop the final square image to show only the entire forehead, hair, face, chin and both ears. The face must fill most of the image. No shoulders, chest, torso, arms or hands. The bottom edge ends just below the chin. Put only the real physical glasses from image 2 on the face. The entire frame and temples must remain visible, with a small margin around the head. Preserve the exact frame geometry, thickness, color, lens tint and opacity. Preserve the exact number and positions of real cameras, sensors and separate indicator lights shown in image 2. Never add a camera or turn a rivet or LED into a camera. Fit the frame on the nose and behind the ears. Preserve a natural face with realistic skin texture. Do not add text or comparison panels. '+meta['detail_prompt']
   con={k:pc[k] for k in ('model','revision','person_id','hair','pose','light','width','height','steps','kv_cache','protocol','composition','cohort','synthetic','face_origin','occlusion')}
   con.update(kind='tryon',portrait_job=pk,source_id=s['id'],source_sha256=s['sha256'],product=s['product'],camera=s['camera'],camera_confirmation='official_product_documentation_and_source_inspection',prompt=prompt,seed=int(lab.uid([pk,s['id']])[:8],16)%(2**31),unseen_geometry='inferred_not_verified',batch=BATCH)
   if meta.get('extra_references'):
    from ai_glasses.generation.multiview_references import prompt_for_views
    con.update(extra_references=meta['extra_references'],reference_resolution=meta.get('reference_resolution',768),reference_count=2+len(meta['extra_references']))
    con['prompt']=prompt_for_views(con['prompt'],con['extra_references'])
   from ai_glasses.generation.multiview_references import wearing_prompt
   con['prompt']=wearing_prompt(con['prompt']);con['open_temple_required']=True
   key=lab.add_job(c,con,'tryon');c.execute('INSERT OR IGNORE INTO batch_jobs VALUES(?,?,?)',(BATCH,key,k*8+i))
 c.execute('INSERT OR IGNORE INTO batches VALUES(?,?,?,?,?)',(BATCH,lab.now(),None,'prepared',json.dumps(dict(people=8,men=4,women=4,age_range=[21,25],tryons=160),ensure_ascii=False)));c.commit();lab.export(c)
 print(json.dumps(dict(batch=BATCH,people=8,tryons=160)))
if __name__=='__main__':main()
