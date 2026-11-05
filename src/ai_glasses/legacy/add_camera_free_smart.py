"""Register verified camera-free smart eyewear and generate diverse face views."""
import csv,json,collections
from pathlib import Path
from PIL import Image,ImageOps
from ai_glasses.generation import tryon_lab as lab
from ai_glasses.generation.multiview_references import prompt_for_views,wearing_prompt
BATCH='camera_free_smart_20261103'
SPECS=[
 ('Solos AirGo A5 Hydro 11','Solos_AirGoA5_Hydro11_002.png','Solos_AirGoA5_Hydro11_003.png','https://solosglasses.com/pages/general-frequently-asked-questions','Grey translucent rectangular frame with clear lenses and black audio temples. Preserve the actual SmartHinge, button, microphone openings and status lights. None is a camera.'),
 ('Solos AirGo A5 Hydro 15','Solos_AirGoA5_Hydro15_006.jpg','Solos_AirGoA5_Hydro15_007.jpg','https://solosglasses.com/pages/general-frequently-asked-questions','Black and gold rounded titanium frame with clear lenses and black audio temples. Preserve the gold bridge, nose pads and actual side controls. No camera exists on this frame.'),
 ('Lucyd Lark','Lucyd_Lark_004.jpg','Lucyd_Lark_001.jpg','https://lucyd.co/en-fr/blogs/news-media/ray-ban-meta-vs-lucyd-smart-glasses-an-honest-2026-comparison','Black narrow cat-eye optical frame with clear lenses and audio temples. Preserve real logos, hinges and controls. Do not convert decoration or microphone openings into cameras.'),
 ('Lucyd Phantom','Lucyd_Phantom_006.jpg','Lucyd_Phantom_001.jpg','https://lucyd.co/products/phantom','Black angular rectangular optical frame with clear lenses and audio temples. Preserve the exact frame corners, bridge and temples; no camera apertures.')]
def normalized(source,target,crop=None):
 im=ImageOps.exif_transpose(Image.open(source)).convert('RGBA')
 if crop:im=im.crop(crop)
 bg=Image.new('RGBA',im.size,'white');bg.alpha_composite(im);bg.convert('RGB').save(target);return lab.digest(target)
def main():
 c=lab.connect()
 if c.execute('SELECT 1 FROM batches WHERE name=?',(BATCH,)).fetchone():print('Already prepared');return
 with (lab.ROOT/'work/ai_sources.csv').open(encoding='utf-8-sig') as f:csvrows={r['파일']:r for r in csv.DictReader(f)}
 index={p.name:p for p in (lab.ROOT/'source_snapshot').rglob('*') if p.is_file()};items=[]
 for product,front,side,evidence,detail in SPECS:
  items.append(dict(product=product,front=index[front],side=index[side],front_url=csvrows[front]['이미지URL'],side_url=csvrows[side]['이미지URL'],page=csvrows[front]['출처페이지'],evidence=evidence,detail=detail))
 extras=json.loads((lab.ROOT/'work/no_camera/new_assets/manifest.json').read_text())
 for name,product,evidence,detail in [('even','Even G2 A Grey 1','https://hub.evenrealities.com/docs/get-started/overview','Grey rounded Even G2 A frame with clear waveguide display lenses and real slim temples. Keep the camera-free front and actual hinge/temple shape. Do not copy folded temples over the face; use the open side view to unfold them.'),('halliday','Halliday G2 Black','https://support.hallidayglobal.com/hc/en-us/articles/60154389484825-General-FAQs','Black rounded rectangular Halliday G2 with clear display lenses. Preserve its real waveguide optics, frame and open temples. No camera, recording lens or camera LED may be added.')]:
  front=next(r for r in extras if r['label']==name and r['role']=='front');side=next(r for r in extras if r['label']==name and r['role']=='side');item=dict(product=product,front=Path(front['path']),side=Path(side['path']),front_url=front['url'],side_url=side['url'],page=front['page'],evidence=evidence,detail=detail)
  if name=='halliday':
   w,h=Image.open(item['front']).size;item['crop']=[0,0,w,int(h*.75)]
  items.append(item)
 sources=[]
 for i,item in enumerate(items):
  front=lab.ROOT/lab.FOLDERS[2]/f'camera_free_{i}_front.png';side=front.with_name(f'camera_free_{i}_side.png');sha=normalized(item['front'],front,item.get('crop'));side_sha=normalized(item['side'],side);key=lab.uid(['source',sha])
  ref=dict(path=str(side),sha256=side_sha,role='left_side',product=item['product'],temple_state='open',source_image_url=item['side_url'],source_page=item['page'],reference_angle='side_or_three_quarter',original_sha256=lab.digest(item['side']))
  meta=dict(selected=True,model=item['product'],camera_count=0,camera_evidence_url=item['evidence'],evidence_checked_at=lab.now(),camera_evidence_basis='Manufacturer camera-free specification; audio A5 distinguished from Vision V/V2; exact frame and product images inspected',detail_prompt=item['detail'],extra_references=[ref],reference_resolution=768,source_page=item['page'],source_image_url=item['front_url'],original_path=str(item['front']),original_sha256=lab.digest(item['front']),source_crop=item.get('crop'),derivation='Original image composited on white; Halliday price banner cropped below the product',image_inspection='assistant_inspected_not_human_training_approved',rights_status='권리 확인 필요',source_batch=BATCH)
  sources.append((key,str(front),sha,item['product'],'C','absent',item['evidence'],json.dumps(meta,ensure_ascii=False)))
 assert len(sources)==6 and len({s[0] for s in sources})==6
 poses=['front','front','left_oblique','left_oblique','right_oblique','right_oblique','left_profile','right_profile'];jobs=[]
 c.execute('BEGIN IMMEDIATE')
 try:
  for source in sources:c.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)',source)
  for k,source in enumerate(sources):
   meta=json.loads(source[7])
   for i,pid in enumerate([f'K{n:02}' for n in range(9,17)]):
    pose=poses[(i+k)%8];parent=c.execute("SELECT * FROM jobs WHERE kind='portrait' AND status IN ('success','pending','running','interrupted') AND json_extract(condition,'$.person_id')=? AND json_extract(condition,'$.pose')=? ORDER BY rowid DESC LIMIT 1",(pid,pose)).fetchone();assert parent,(pid,pose)
    pc=json.loads(parent['condition']);con={n:pc[n] for n in ('model','revision','person_id','hair','skin_tone','clothing','pose','light','width','height','steps','kv_cache','cohort','synthetic','face_origin','occlusion','composition') if n in pc}
    prompt='Edit image 1 and keep this exact adult identity, natural skin tone, hair, clothing neckline and head direction. Preserve the tight face-only composition and the visible ear region. Do not turn a side-facing head back to the front. Put only the exact physical SMART GLASSES WITHOUT A CAMERA from image 2 onto the face. This product contains ZERO cameras. Preserve real display optics, speaker/microphone openings, charging contacts, touchpads, indicators, hinges and logos, but never invent or reinterpret any of them as a camera. Keep the exact frame contour, thickness, color, lens transparency and side components. Use image 3 to unfold the real temples and support the frame naturally on the nose and ears. Show only components physically visible from this head angle. No shoulders, chest, arms, hands, text, product advertisements, digital HUD overlays or comparison panels. '+meta['detail_prompt']
    con.update(kind='tryon',portrait_job=parent['id'],source_id=source[0],source_sha256=source[2],product=source[3],camera='absent',camera_count=0,camera_confirmation='manufacturer_documentation_camera_free_smart_eyewear',protocol=BATCH,batch=BATCH,seed=int(lab.uid([BATCH,pid,source[0]])[:8],16)%(2**31),extra_references=meta['extra_references'],reference_count=3,reference_resolution=768,open_temple_required=True,unseen_geometry='inferred_not_verified',pose_verified=False)
    con['prompt']=wearing_prompt(prompt_for_views(prompt,con['extra_references']));key=lab.uid(con);c.execute('INSERT INTO jobs(id,kind,condition) VALUES(?,?,?)',(key,'tryon',json.dumps(con,ensure_ascii=False)));c.execute('INSERT INTO batch_jobs VALUES(?,?,?)',(BATCH,key,k*8+i));jobs.append(dict(id=key,product=source[3],person=pid,pose=pose))
  # The first camera-free sample runs through the existing preview priority.
  c.execute('INSERT INTO batch_jobs VALUES(?,?,?)',('pose_preview_20261103',jobs[0]['id'],3))
  manifest=dict(created=lab.now(),batch=BATCH,models=[s[3] for s in sources],people=8,tryons=len(jobs),poses=dict(collections.Counter(j['pose'] for j in jobs)),jobs=jobs,category='C',camera='absent',human_review_required=True)
  c.execute('INSERT INTO batches VALUES(?,?,?,?,?)',(BATCH,lab.now(),None,'prepared',json.dumps(manifest,ensure_ascii=False)));c.commit()
 except Exception:c.rollback();raise
 (lab.ROOT/lab.FOLDERS[9]/(BATCH+'.json')).write_text(json.dumps(manifest,ensure_ascii=False,indent=2));lab.export(c);print(json.dumps({k:v for k,v in manifest.items() if k!='jobs'},ensure_ascii=False))
if __name__=='__main__':main()
