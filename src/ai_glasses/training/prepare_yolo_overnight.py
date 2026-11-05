"""Freeze approved A/B data before any YOLO experiment or test inspection."""
import collections,hashlib,json,os,random,sqlite3
from pathlib import Path
import numpy as np
import cv2
from PIL import Image,ImageOps

from ai_glasses.config import DATA_ROOT as ROOT, YOLO_RUN_ROOT as OUT

def dump(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2))

def main():
 OUT.mkdir(exist_ok=True,parents=True)
 if (OUT/'dataset.json').exists():print('Existing split preserved');return
 src=sqlite3.connect(f'file:{ROOT}/experiment.sqlite?mode=ro',uri=True)
 with sqlite3.connect(OUT/'approved_snapshot.sqlite') as dst:src.backup(dst)
 src.close();c=sqlite3.connect(OUT/'approved_snapshot.sqlite');c.row_factory=sqlite3.Row
 previous={r['id'] for r in json.loads((ROOT/'work/quick_classifier_20261104/dataset.json').read_text())['selected_pool']}
 rows=[];seen=set()
 for row in c.execute("SELECT j.id,j.output,j.output_sha256,j.condition,s.product,s.category,s.sha256 source_sha256,r.updated,n.number FROM jobs j JOIN sources s ON s.id=json_extract(j.condition,'$.source_id') JOIN reviews r ON r.job_id=j.id LEFT JOIN review_item_numbers n ON n.job_id=j.id WHERE j.kind='tryon' AND j.status='success' AND r.decision='pass' AND s.category IN ('A','B') ORDER BY j.id"):
  r=dict(row);con=json.loads(r.pop('condition'));r.update(person_id=con['person_id'],label=int(r['category']=='A'),previous_resnet_used=r['id'] in previous)
  if r['output_sha256'] in seen:continue
  assert hashlib.sha256(Path(r['output']).read_bytes()).hexdigest()==r['output_sha256']
  seen.add(r['output_sha256']);rows.append(r)
 people=sorted({r['person_id'] for r in rows});products={cat:sorted({r['product'] for r in rows if r['category']==cat}) for cat in ('A','B')}
 all_products=products['A']+products['B'];pi={p:i for i,p in enumerate(people)};qi={p:i for i,p in enumerate(all_products)}
 pindex=np.array([pi[r['person_id']] for r in rows]);qindex=np.array([qi[r['product']] for r in rows]);labels=np.array([r['label'] for r in rows]);rng=np.random.default_rng(420511)
 for attempt in range(300000):
  ps=np.zeros(len(people),dtype=int);porder=rng.permutation(len(people));ps[porder[:9]]=2;ps[porder[9:13]]=1
  qs=np.zeros(len(all_products),dtype=int)
  for cat,ntest,nval in [('A',8,0),('B',14,0)]:
   order=rng.permutation([qi[p] for p in products[cat]]);qs[order[:ntest]]=2;qs[order[ntest:ntest+nval]]=1
  split=np.where((ps[pindex]==2)&(qs[qindex]==2),2,np.where((ps[pindex]<2)&(qs[qindex]==0),ps[pindex],3))
  counts=np.bincount(split*2+labels,minlength=8).reshape(4,2)
  if counts[0].min()>=100 and counts[1].min()>=15 and counts[2].min()>=100:break
 else:raise ValueError('Cannot create 200 independent test images with the available groups')
 take=random.Random(420511);assignments={};parts={}
 for name,code,limit in [('train',0,int(counts[0].min())),('val',1,15),('test',2,100)]:
  parts[name]=[]
  for label in [0,1]:
   eligible=[r for i,r in enumerate(rows) if split[i]==code and r['label']==label];take.shuffle(eligible)
   for row in eligible[:limit]:assignments[row['id']]=name;parts[name].append(row)
 for key in ['person_id','product','source_sha256','output_sha256']:
  groups=[{r[key] for r in parts[name]} for name in ['train','val','test']]
  assert not groups[2]&(groups[0]|groups[1]),key
  if key in ['person_id','output_sha256']:assert not groups[0]&groups[1],key
 # Preserve image bytes on the HDD even if a later review changes the live path.
 raw=OUT/'raw';raw.mkdir(exist_ok=True)
 face=cv2.CascadeClassifier(cv2.data.haarcascades+'haarcascade_frontalface_default.xml');profile=cv2.CascadeClassifier(cv2.data.haarcascades+'haarcascade_profileface.xml')
 for name,part in parts.items():
  for row in part:
   original=Path(row['output']);target=raw/(row['id']+'.png')
   if not target.exists():os.link(original,target)
   row['raw_path']=str(target)
   with Image.open(target) as opened:im=ImageOps.exif_transpose(opened).convert('RGB')
   w,h=im.size;small=im.copy();small.thumbnail((640,640));gray=cv2.cvtColor(np.array(small),cv2.COLOR_RGB2GRAY)
   boxes=list(face.detectMultiScale(gray,1.1,4,minSize=(50,50)))+list(profile.detectMultiScale(gray,1.1,4,minSize=(50,50)))
   reverse=profile.detectMultiScale(cv2.flip(gray,1),1.1,4,minSize=(50,50))
   boxes.extend([(small.width-x-bw,y,bw,bh) for x,y,bw,bh in reverse])
   if boxes:
    x,y,bw,bh=max(boxes,key=lambda b:b[2]*b[3]);scale=w/small.width;x,y,bw,bh=[v*scale for v in (x,y,bw,bh)]
    facebox=(max(0,int(x-.45*bw)),max(0,int(y-.25*bh)),min(w,int(x+1.45*bw)),min(h,int(y+1.12*bh)))
    # Full image width protects the temples and hinges on either side.
    bandbox=(0,max(0,int(y-.05*bh)),w,min(h,int(y+.62*bh)))
    row['crop_method']='haar_face_or_profile'
   else:
    facebox=(0,0,w,h);bandbox=(0,int(.16*h),w,int(.64*h));row['crop_method']='documented_fixed_band_fallback'
   row['crop_boxes']={'full':(0,0,w,h),'face':facebox,'band':bandbox};row['views']={}
   for view,box in row['crop_boxes'].items():
    folder=OUT/'views'/view/name/('camera' if row['label'] else 'ordinary');folder.mkdir(parents=True,exist_ok=True)
    path=folder/(row['id']+'.jpg');im.crop(box).save(path,quality=97,subsampling=0);row['views'][view]=str(path)
 manifest=dict(seed=420511,selection_attempt=attempt,created_from='human-pass snapshot; counts only; no model scores used',task='YOLO classification',test_policy='200 sealed images; absent from every YOLO train/val run; evaluate chosen model once after selection',prior_resnet_warning='Some test images were used by a separate earlier ResNet. No ResNet weights or predictions enter these YOLO experiments.',parts=parts,unused=[dict(id=r['id'],category=r['category']) for r in rows if r['id'] not in assignments],counts={name:dict(collections.Counter(r['category'] for r in part)) for name,part in parts.items()},group_overlap={'test_vs_train_val':{'people':0,'products':0,'source_hash':0,'image_hash':0},'validation_vs_train':'people and exact images disjoint; products may overlap'})
 dump(OUT/'dataset.json',manifest)
 print(json.dumps(dict(counts=manifest['counts'],attempt=attempt,unused=len(manifest['unused'])),ensure_ascii=False),flush=True)

if __name__=='__main__':main()
