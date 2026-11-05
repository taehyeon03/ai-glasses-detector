"""Create a reproducible, blinded evaluation set; never edit human reviews."""
import collections,hashlib,json,random,shutil
from pathlib import Path
from PIL import Image,ImageOps,ImageDraw
from ai_glasses.generation import tryon_lab as lab

DEST=lab.ROOT/'work'/'blind_review_pilot_20261104'
def trimmed(path):
    image=ImageOps.exif_transpose(Image.open(path)).convert('RGBA')
    base=Image.new('RGBA',image.size,'white');image=Image.alpha_composite(base,image).convert('RGB')
    import numpy as np
    mask=np.min(np.asarray(image),axis=2)<220
    ys,xs=np.where(mask)
    if len(xs):
        margin=12;image=image.crop((max(0,int(xs.min())-margin),max(0,int(ys.min())-margin),min(image.width,int(xs.max())+margin+1),min(image.height,int(ys.max())+margin+1)))
    return image

def main():
    assert not DEST.exists(),'Do not overwrite an existing blinded pilot'
    (DEST/'panels').mkdir(parents=True)
    c=lab.connect()
    rows=[dict(r) for r in c.execute("SELECT j.id,j.condition,j.output,j.output_sha256,r.decision,s.path,s.sha256,s.category,s.product FROM jobs j JOIN reviews r ON r.job_id=j.id JOIN sources s ON s.id=json_extract(j.condition,'$.source_id') WHERE j.kind='tryon' AND j.status='success' AND r.decision IN ('pass','exclude','hold')")]
    rng=random.Random(20261104);rng.shuffle(rows);chosen=[]
    for decision in ('pass','exclude','hold'):
        candidates=[r for r in rows if r['decision']==decision]
        counts=collections.Counter()
        for category,target in [('A',5),('B',5)]:
            for row in [r for r in candidates if r['category']==category]:
                if counts[category]>=target:break
                if sum(x['product']==row['product'] and x['decision']==decision for x in chosen)>=2:continue
                chosen.append(row);counts[category]+=1
        assert sum(counts.values())==10,(decision,counts)
    rng.shuffle(chosen);private=[];public=[]
    for index,row in enumerate(chosen,1):
        key=f'P{index:02d}';con=json.loads(row['condition'])
        assert lab.digest(row['output'])==row['output_sha256']
        assert lab.digest(row['path'])==row['sha256']
        front=trimmed(row['path']);result=ImageOps.exif_transpose(Image.open(row['output'])).convert('RGB')
        extra=con.get('extra_references',[]);side=None
        if extra:
            assert lab.digest(extra[0]['path'])==extra[0]['sha256'];side=trimmed(extra[0]['path'])
        panel=Image.new('RGB',(1440,520),'#eeeeee');draw=ImageDraw.Draw(panel)
        for column,(title,im) in enumerate([('REFERENCE FRONT',front),('REFERENCE SIDE',side),('GENERATED',result)]):
            draw.text((column*480+12,8),key+' | '+title,fill='black')
            if im is not None:
                fitted=ImageOps.contain(im,(472,480));panel.paste(fitted,(column*480+(480-fitted.width)//2,32+(480-fitted.height)//2))
            else:draw.text((column*480+12,70),'NO SIDE REFERENCE',fill='black')
        output=DEST/'panels'/(key+'.jpg');panel.save(output,quality=97)
        public.append(dict(sample_id=key,panel_sha256=lab.digest(output),reference_side=extra[0]['role'] if extra else None,pose=con.get('pose')))
        private.append(dict(sample_id=key,job_id=row['id'],human_decision=row['decision'],category=row['category'],product=row['product'],generation_sha256=row['output_sha256'],front_sha256=row['sha256']))
    (DEST/'blind_inputs.json').write_text(json.dumps(public,ensure_ascii=False,indent=2))
    (DEST/'human_labels_PRIVATE.json').write_text(json.dumps(private,ensure_ascii=False,indent=2))
    (DEST/'sampling.json').write_text(json.dumps(dict(seed=20261104,sample_size=30,design='10 per human decision, within each decision 5 A and 5 B; max 2 per product per decision; shuffled before sample IDs; no C in this pilot',population=dict(collections.Counter(r['decision'] for r in rows)),rule='Judge only visible product fidelity. Contralateral hinge and structural temple may be assumed symmetric. Do not mirror electronic parts. Pass only when all visible details are consistent; exclude clear mismatches; uncertain when evidence is insufficient. Do not read private labels until predictions are committed.'),ensure_ascii=False,indent=2))
    print(json.dumps(dict(folder=str(DEST),samples=len(public),panels=len(list((DEST/'panels').glob('*.jpg'))))))

if __name__=='__main__':main()
