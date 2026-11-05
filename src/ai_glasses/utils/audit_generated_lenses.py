import json,collections,concurrent.futures
from pathlib import Path
from PIL import Image,ImageOps,ImageDraw,ImageFont
import cv2,numpy as np
from ai_glasses.generation import tryon_lab as lab
root=lab.ROOT;out=root/'work/lens_audit';out.mkdir(exist_ok=True);c=lab.connect();rows=[]
for r in c.execute("SELECT j.id,j.output,j.status,j.condition,s.product,s.category,s.metadata FROM jobs j JOIN sources s ON s.id=json_extract(j.condition,'$.source_id') WHERE j.kind='tryon' AND j.output IS NOT NULL ORDER BY s.product,j.rowid"):
 if not Path(r['output']).is_file():continue
 con=json.loads(r['condition']);meta=json.loads(r['metadata']);rows.append(dict(id=r['id'],output=r['output'],status=r['status'],product=r['product'],category=r['category'],source_id=con['source_id'],pose=con.get('pose'),detail=meta.get('detail_prompt','')))
for i,r in enumerate(rows):r['index']=i
(out/'inventory.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2));font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',13)
# Detection chooses only the crop for visual inspection; it never decides lens color.
cascade_path=cv2.data.haarcascades+'haarcascade_frontalface_default.xml'
def crop(row):
 im=ImageOps.exif_transpose(Image.open(row['output'])).convert('RGB');w,h=im.size;small=ImageOps.contain(im,(512,512));gray=cv2.cvtColor(np.array(small),cv2.COLOR_RGB2GRAY);faces=cv2.CascadeClassifier(cascade_path).detectMultiScale(gray,1.12,4,minSize=(55,55));box=None
 if len(faces):
  x,y,fw,fh=max(faces,key=lambda a:a[2]*a[3]);scale=w/small.width;x,y,fw,fh=[a*scale for a in (x,y,fw,fh)];box=(max(0,int(x-.18*fw)),max(0,int(y+.12*fh)),min(w,int(x+1.18*fw)),min(h,int(y+.64*fh)))
 if not box:box=(int(.05*w),int(.22*h),int(.95*w),int(.65*h))
 return ImageOps.pad(im.crop(box),(232,122),color='white'),list(box)
for start in range(0,len(rows),48):
 group=rows[start:start+48];sheet=Image.new('RGB',(1440,((len(group)+5)//6)*158),'white');d=ImageDraw.Draw(sheet)
 with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
  for n,(tile,box) in enumerate(ex.map(crop,group)):
   r=group[n];r['crop_box']=box;x=(n%6)*240;y=(n//6)*158;sheet.paste(tile,(x,y+28));d.text((x+2,y+1),f"{r['index']} {r['id'][:6]} {r['category']}",fill='black',font=font);d.text((x+2,y+15),r['product'][:29],fill='black',font=font)
 sheet.save(out/f'sheet_{start//48:03}.jpg',quality=90);print('sheet',start//48,'rows',len(group),flush=True)
(out/'inventory.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2));print('TOTAL',len(rows),dict(collections.Counter(r['status'] for r in rows)),flush=True)
