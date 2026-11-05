"""Prepare a broad product queue without duplicating completed conditions."""
import argparse
import json
from pathlib import Path
from ai_glasses.generation import tryon_lab as lab

BATCH='overnight_10h'
FIELDS=('model','revision','portrait_job','source_sha256','prompt','seed','width','height','steps','kv_cache')
def semantic(con):return lab.uid({k:con.get(k) for k in FIELDS})
def pose_prompt(pose,light):
    direction='left' if pose.startswith('left') else 'right'
    if pose.endswith('profile'):
        return f'Create a strict 90-degree side-profile photograph. The nose points to image {direction}. Show only the near eye and near ear. The far eye and far ear must be hidden by the head. Show the nose in silhouette. This is not a three-quarter view. {light}.'
    if pose.endswith('oblique'):
        return f'Rotate the head 35 degrees so the nose points to image {direction}. Show a clear three-quarter view with the farther side of the face narrower. {light}.'
    return f'Look straight at the camera. {light}.'
def face_views(c):
    views=[]
    for k,(pid,desc,hair) in enumerate(lab.PERSONAS):
        base=c.execute("SELECT * FROM jobs WHERE kind='portrait' AND json_extract(condition,'$.person_id')=? AND json_extract(condition,'$.pose')='front' ORDER BY rowid LIMIT 1",(pid,)).fetchone()
        for a,(pose,_) in enumerate(lab.POSES):
            existing=c.execute("SELECT * FROM jobs WHERE kind='portrait' AND status!='superseded' AND json_extract(condition,'$.person_id')=? AND json_extract(condition,'$.pose')=? ORDER BY CASE WHEN json_extract(condition,'$.protocol')='v2_profile' THEN 0 ELSE 1 END,rowid",(pid,pose)).fetchall()
            selected=next((r for r in existing if not pose.endswith('profile') or json.loads(r['condition']).get('protocol')=='v2_profile'),None)
            if selected:con=json.loads(selected['condition']);key=selected['id']
            else:
                con=dict(json.loads(base['condition']));con.update(pose=pose,light=lab.LIGHTS[(k+a)%3],portrait_parent=base['id'],protocol='v2_profile',steps=40,seed=44000+k*100+a,pose_convention='direction the nose points in the image',pose_verified=False)
                con['prompt']='Use image 1 as the identity reference. Keep the exact same fictional adult identity, natural skin and hair. '+pose_prompt(pose,con['light'])+' Plain neutral indoor background. Hair stays clear of the temples. No glasses, eyewear, text or graphics.'
                key=lab.add_job(c,con,'portrait')
            con.setdefault('face_origin','fictional_generated');views.append((key,con))
    reference=lab.ROOT/'user_provided_references/U01_original.jpg'
    if not reference.is_file():raise FileNotFoundError('User-provided reference is required')
    original_hash=lab.digest(reference);base_key=None
    for a,(pose,_) in enumerate(lab.POSES):
        con=dict(model=lab.MODEL,revision=lab.REVISION,person_id='U01',hair='short wavy hair with centre-parted bangs',pose=pose,light=lab.LIGHTS[a%3],width=1024,height=1024,steps=40,seed=55100+a,kv_cache=True,protocol='user_reference_v1',synthetic=True,face_origin='user_provided_reference',source_face_real=True,occlusion='none',pose_verified=False,pose_convention='direction the nose points in the image',source_face_sha256=original_hash)
        if pose=='front':con.update(face_reference_path=str(reference),face_reference_sha256=original_hash)
        else:con['portrait_parent']=base_key
        con['prompt']='Use image 1 as the identity reference for the same adult person supplied by the user. Preserve the exact facial anatomy, identity, natural skin texture and hairstyle. Do not beautify, change age, or invent a different person. '+pose_prompt(pose,con['light'])+' Replace the background with a plain neutral indoor room. Head and shoulders with the entire head visible. Keep the temples clear of hair. No glasses, sunglasses, eyewear, text or graphics.'
        key=lab.add_job(c,con,'portrait')
        if pose=='front':base_key=key
        views.append((key,con));c.execute('INSERT OR REPLACE INTO batch_jobs VALUES(?,?,?)',(BATCH,key,-100+a))
    c.commit();return views
def main():
    p=argparse.ArgumentParser();p.add_argument('--hours',type=float,default=10);p.add_argument('--target',type=int,default=800);a=p.parse_args();c=lab.connect()
    state=c.execute('SELECT status FROM batches WHERE name=?',(BATCH,)).fetchone()
    if state and state['status']=='running':raise ValueError('Stop the overnight service before changing its queue')
    c.execute('DELETE FROM batch_jobs WHERE batch=?',(BATCH,));c.commit()
    sources=[dict(r) for r in c.execute("SELECT * FROM sources WHERE category IN ('A','B') AND json_extract(metadata,'$.selected')=1 ORDER BY product")]
    positive=[s for s in sources if s['category']=='A'];negative=[s for s in sources if s['category']=='B']
    if len(positive)!=10 or len(negative)!=10:raise ValueError('Expected 10 verified camera products and 10 ordinary products')
    ordered=[s for pair in zip(positive,negative) for s in pair]
    views=face_views(c);views.sort(key=lambda item: item[1]['person_id']!='U01');existing={};pair_templates={};product_templates={}
    for row in c.execute("SELECT * FROM jobs WHERE kind='tryon' AND status!='superseded' ORDER BY CASE WHEN status='success' THEN 0 ELSE 1 END,rowid"):
        con=json.loads(row['condition'])
        if con.get('steps')!=40:continue
        existing.setdefault(semantic(con),row['id']);pair_templates.setdefault((con['portrait_job'],con['source_id']),con);product_templates.setdefault(con['source_id'],con)
    count=0;priority=0;round_index=0
    while count<a.target:
        for portrait_key,pc in views:
            for source in ordered:
                if count>=a.target:break
                meta=json.loads(source['metadata']);pair=pair_templates.get((portrait_key,source['id']));product=product_templates.get(source['id'])
                prompt=product['prompt'] if product else ('Edit image 1 and keep the same adult person, head direction, hair, skin, clothing, background and lighting. Put only the physical glasses from image 2 onto this person. Preserve the exact manufactured frame outline, material, colour, thickness, lens shape and tint, bridge, nose pads, temples, cameras, indicator LEDs, sensors and buttons that are visible in image 2. Do not add, delete or symmetrize a camera. Never turn a decorative rivet or capture LED into a camera. Fit the frame naturally on the nose and behind the ears. Keep hair away from the glasses. Do not add text or comparison panels. Treat the glasses as a rigid object. Preserve lens opacity and do not redesign frame proportions. '+meta['detail_prompt'])
                seed=pair['seed'] if pair else int(lab.uid([portrait_key,source['id']])[:8],16)%(2**31)
                con={k:pc[k] for k in ('model','revision','person_id','hair','pose','light','width','height','occlusion')}
                con.update(kind='tryon',portrait_job=portrait_key,source_id=source['id'],source_sha256=source['sha256'],product=source['product'],camera=source['camera'],camera_confirmation='official_product_documentation_and_source_inspection',prompt=prompt,seed=(seed+round_index*1000003)%(2**31),steps=40,kv_cache=True,synthetic=True,face_origin=pc.get('face_origin','fictional_generated'),unseen_geometry='inferred_not_verified',reference_pose=meta.get('pose','front'),protocol='broad_products_v1',batch=BATCH,replicate=round_index,pose_verified=False)
                key=existing.get(semantic(con))
                if not key:key=lab.add_job(c,con,'tryon');existing[semantic(con)]=key
                # U01 and new products receive early coverage, while each complete view stays balanced.
                c.execute('INSERT OR REPLACE INTO batch_jobs VALUES(?,?,?)',(BATCH,key,priority));priority+=1;count+=1
        round_index+=1
    prior=c.execute('SELECT * FROM batches WHERE name=?',(BATCH,)).fetchone()
    metadata=dict(hours=a.hours,planned_tryons=count,camera_products=len(positive),ordinary_products=len(negative),people=5,fictional_people=4,user_provided_identity=1,face_views=len(views),products=[dict(name=s['product'],category=s['category'],source_id=s['id']) for s in ordered])
    if not prior:c.execute('INSERT INTO batches VALUES(?,?,?,?,?)',(BATCH,None,None,'prepared',json.dumps(metadata,ensure_ascii=False)))
    else:c.execute('UPDATE batches SET metadata=? WHERE name=?',(json.dumps(metadata,ensure_ascii=False),BATCH))
    c.commit();lab.export(c);(lab.ROOT/lab.FOLDERS[9]/'overnight_plan.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2));print(json.dumps(metadata,ensure_ascii=False))
if __name__=='__main__':main()
