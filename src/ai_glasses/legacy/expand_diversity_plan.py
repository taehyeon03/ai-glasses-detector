"""Expand inspected product references and cross them with diverse fictional adults."""
import json,shutil
from pathlib import Path
from PIL import Image,ImageOps
from ai_glasses.generation import tryon_lab as lab
from ai_glasses.generation.multiview_references import prompt_for_views,wearing_prompt
BATCH='diversity_20261102_v1'
PEOPLE=[
('K09','man',22,'light neutral beige skin','short textured black crop with a light fringe','white cotton T-shirt'),
('K10','woman',23,'light warm beige skin','chin-length straight black bob tucked behind ears','navy collared shirt'),
('K11','man',24,'medium warm beige skin','black six-four side part with neat short sides','muted green polo shirt'),
('K12','woman',21,'medium neutral beige skin','dark brown low ponytail with a natural side part','cream knit crewneck'),
('K13','man',25,'naturally sun-tanned medium brown skin','short black two-block haircut with forehead visible','burgundy crewneck sweatshirt'),
('K14','woman',24,'naturally sun-tanned medium brown skin','shoulder-length black layers tucked behind ears','light blue denim shirt'),
('K15','man',23,'naturally deep tan warm brown skin','short wavy black hair with a loose center part','charcoal zip-up stand collar'),
('K16','woman',22,'naturally deep tan neutral brown skin','long dark brown hair tied back with light separated bangs','muted lavender round-neck top')]
DETAILS={
 '01_뿔테':'Preserve the thick acetate frame, exact contour, color pattern and clear lenses. Decorative rivets are not cameras.',
 '02_메탈테':'Preserve the thin metallic frame, bridge bars, separate nose pads and clear lenses. Never thicken it into an acetate frame.',
 '03_반무테':'Preserve the partial upper rim and the rimless lower lens edges. Preserve the nose pads and slender temples.',
 '04_무테':'Preserve the rimless lens edges, small mounting screws, narrow bridge and slim temples. Never add a surrounding rim.',
 '05_투명테':'Preserve the translucent colored plastic frame and its actual transparency. Keep clear lenses and visible small hinges.',
 '06_브로우라인':'Preserve the strong upper browline and thin lower lens rim. Decorative corner rivets are not cameras.',
 '07_선글라스_일반':'Preserve the exact fashion-sunglass silhouette, frame pattern and lens tint including gradients.',
 '08_선글라스_스포츠':'Preserve the actual sports frame, lens shape, reflective tint and temple curvature. Never turn the bridge or logo into a camera.',
 'Meta_RayBan_Gen2_Skyler':'Black cat-eye Skyler frame with green lenses. Preserve the real corner camera and separate opposite indicator light; the light is not a second camera.',
 'BrilliantLabs_Halo':'Preserve the black rounded rectangular Halo frame, clear lenses and actual camera and display optics. Do not mirror or duplicate its asymmetric electronic components.',
 'HTC_VIVE_Eagle':'Preserve the charcoal rounded pantos VIVE Eagle frame and dark lenses. Keep the camera and separate indicator at their exact visible positions.',
 'Xiaomi_AI_Glasses':'Preserve the black angular Xiaomi AI frame with clear lenses, one real camera and separate opposite light. Do not copy the camera to both corners.',
 'INMO_GO3':'Preserve the black GO3 frame, clear lenses, actual camera housing and physical privacy cover in their exact reference configuration. Do not turn its display optics into additional cameras.',
 'Rokid_Glasses_Display':'Preserve the black Rokid display-glasses frame, clear lenses, real camera and distinct display optics. Keep sensors, indicators and camera apertures separate.'}
EVIDENCE={
 'Meta_RayBan_Gen2_Skyler':'https://www.ray-ban.com/usa/l/discover-ray-ban-meta-ai-glasses',
 'BrilliantLabs_Halo':'https://github.com/brilliantlabsAR/docs/blob/main/halo/hardware.md',
 'HTC_VIVE_Eagle':'https://www.vive.com/us/product/vive-eagle/overview/',
 'Xiaomi_AI_Glasses':'https://new.c.mi.com/bd/post/201946',
 'INMO_GO3':'https://www.inmo.com/products/inmo-go3',
 'Rokid_Glasses_Display':'https://global.rokid.com/en-jp/products/rokid-glasses'}
NAMES={'Meta_RayBan_Gen2_Skyler':'Ray-Ban Meta Gen 2 Skyler','BrilliantLabs_Halo':'Brilliant Labs Halo','HTC_VIVE_Eagle':'HTC VIVE Eagle','Xiaomi_AI_Glasses':'Xiaomi AI Glasses','INMO_GO3':'INMO GO3','Rokid_Glasses_Display':'Rokid Glasses With Display'}

def normalize(src,dst):
 im=ImageOps.exif_transpose(Image.open(src)).convert('RGBA');bg=Image.new('RGBA',im.size,'white');bg.alpha_composite(im);bg.convert('RGB').save(dst)
 return lab.digest(dst)

def main():
 c=lab.connect()
 if c.execute('SELECT 1 FROM batches WHERE name=?',(BATCH,)).fetchone():print('Already prepared');return
 selection=json.loads((lab.ROOT/'work/diversity/selected.json').read_text());assert len(selection)==28
 prepared=[]
 for item in selection:
  frontindex=item['front_index'];original=Path(item['paths'][frontindex]);record=item['records'][frontindex];category=item['category'];camera='present' if category=='A' else 'absent';folder=lab.ROOT/lab.FOLDERS[0 if category=='A' else 1];dst=folder/(BATCH+'_'+str(item['selection_index'])+'_front.png');sha=normalize(original,dst)
  product=NAMES.get(item['style'],record.get('출처','')+' '+item['product']);key=lab.uid(['source',sha]);sideindex=item['side_index'];extras=[]
  if sideindex is not None:
   sideoriginal=Path(item['paths'][sideindex]);side=folder/(BATCH+'_'+str(item['selection_index'])+'_side.png');side_sha=normalize(sideoriginal,side)
   extras=[dict(path=str(side),sha256=side_sha,role='left_side',product=product,temple_state='open',source_page=item['records'][sideindex]['출처페이지'],original_path=str(sideoriginal),original_sha256=lab.digest(sideoriginal),inspection='Same exact listing title/color and complete open temples visually inspected; side or three-quarter view, not necessarily strict 90 degrees')]
  metadata=dict(record,selected=True,model=product,style=item['style'],detail_prompt=DETAILS[item['style']],extra_references=extras,reference_resolution=768 if extras else 1024,original_path=str(original),original_sha256=lab.digest(original),derivation='EXIF orientation and transparent background composited on white; no product geometry edited',camera_evidence_url=EVIDENCE.get(item['style'],record['출처페이지']),camera_evidence=('manufacturer documentation and source inspection' if category=='A' else 'identified ordinary optical/reading/sunglass listing and source inspection; human fidelity review still required'),rights_status='권리 확인 필요',image_inspection='assistant_inspected_not_human_approved',diversity_batch=BATCH)
  prepared.append((key,str(dst),sha,product,category,camera,metadata['camera_evidence_url'],json.dumps(metadata,ensure_ascii=False)))
 assert len({s[0] for s in prepared})==28,'Duplicate source bytes'
 c.execute('BEGIN IMMEDIATE')
 try:
  for values in prepared:c.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)',values)
  sources=[dict(s) for s in c.execute("SELECT * FROM sources WHERE category IN ('A','B') AND json_extract(metadata,'$.selected')=1 ORDER BY product")];assert len(sources)==48
  created=[]
  for i,(pid,gender,age,skin,hair,clothes) in enumerate(PEOPLE):
   prompt=f'A natural unretouched photographic FACE CLOSE-UP of a completely fictional adult Korean {gender}, age {age}, who looks like an everyday university student. Natural {skin}; preserve this skin tone without whitening, beauty filters or heavy makeup. Hairstyle: {hair}. Realistic individual facial anatomy and skin texture. Neutral relaxed expression, looking directly into the camera. Both ears and temples unobstructed. Frame the complete hair, forehead, face and chin with a small margin; the face fills most of the square image. Only a tiny strip of the {clothes} neckline may appear below the chin. No shoulders, torso, chest, arms or hands. Bright neutral diffuse daylight and plain light gray background. No glasses, eyewear, jewelry, text or collage.'
   pc=dict(kind='portrait',model=lab.MODEL,revision=lab.REVISION,person_id=pid,description=f'Fictional Korean {gender}, {age}; {skin}; {clothes}',hair=hair,skin_tone=skin,clothing=clothes,pose='front',light='neutral diffuse indoor daylight',width=1024,height=1024,steps=40,seed=692000+i,kv_cache=True,protocol=BATCH,cohort='korean_students_v1',composition='tight_face_closeup',synthetic=True,face_origin='fictional_generated',occlusion='none',batch=BATCH,prompt=prompt)
   parent=lab.uid(pc);c.execute('INSERT INTO jobs(id,kind,condition) VALUES(?,?,?)',(parent,'portrait',json.dumps(pc,ensure_ascii=False)));c.execute('INSERT INTO batch_jobs VALUES(?,?,?)',(BATCH,parent,-100+i))
   # All products are crossed with every identity so appearance never determines the label.
   sources.sort(key=lambda s:(json.loads(s['metadata']).get('diversity_batch')!=BATCH,s['category'],s['product']))
   for k,source in enumerate(sources):
    meta=json.loads(source['metadata']);con={key:pc[key] for key in pc if key not in ('kind','prompt','seed','description')}
    prompt='Edit image 1 while preserving the exact same adult identity, natural skin tone, hairstyle, expression and visible clothing neckline. Keep the tight FACE-ONLY square composition with complete hair, forehead, chin and both ears. The face and glasses fill most of the image. Show at most a narrow neckline below the chin; no shoulders, torso, chest, arms or hands. Put one pair of the exact physical glasses from image 2 naturally on this face. Preserve the manufactured contour, thickness, color, lens tint and opacity, bridge, nose pads, camera apertures and separate lights. Never invent electronic parts or copy a camera to another corner. Never produce only a product photograph. Do not copy unrelated stands, people, price labels, text or background objects from product references. '+meta['detail_prompt']
    con.update(kind='tryon',portrait_job=parent,source_id=source['id'],source_sha256=source['sha256'],product=source['product'],camera=source['camera'],camera_confirmation=meta.get('camera_evidence','existing registered product evidence'),seed=int(lab.uid([BATCH,parent,source['id']])[:8],16)%(2**31),reference_count=2,open_temple_required=True,unseen_geometry='inferred_not_verified')
    if meta.get('extra_references'):
     con.update(extra_references=meta['extra_references'],reference_resolution=768,reference_count=3);prompt=prompt_for_views(prompt,con['extra_references'])
    con['prompt']=wearing_prompt(prompt);job=lab.uid(con);c.execute('INSERT INTO jobs(id,kind,condition) VALUES(?,?,?)',(job,'tryon',json.dumps(con,ensure_ascii=False)));c.execute('INSERT INTO batch_jobs VALUES(?,?,?)',(BATCH,job,k*8+i));created.append(job)
  manifest=dict(created=lab.now(),new_products=28,total_products=48,camera_products=16,ordinary_products=32,new_faces=8,tryons=len(created),skin_tones=[p[3] for p in PEOPLE],people=[p[0] for p in PEOPLE],new_source_ids=[s[0] for s in prepared],jobs=created,human_review_required=True,clothing_visibility='neckline only; face close-up retained')
  assert len(created)==384
  c.execute('INSERT INTO batches VALUES(?,?,?,?,?)',(BATCH,lab.now(),None,'prepared',json.dumps(manifest,ensure_ascii=False)));c.commit()
 except Exception:c.rollback();raise
 (lab.ROOT/lab.FOLDERS[9]/(BATCH+'.json')).write_text(json.dumps(manifest,ensure_ascii=False,indent=2));lab.export(c);print(json.dumps({k:v for k,v in manifest.items() if k not in ('jobs','new_source_ids')},ensure_ascii=False))
if __name__=='__main__':main()
