from pathlib import Path
from PIL import Image,ImageDraw,ImageOps
from ai_glasses.generation import tryon_lab as l,json
c=l.connect();root=l.ROOT/'source_snapshot/AI안경_이미지/01_Meta/Meta_Oakley_Vanguard';paths=sorted(root.glob('*'));canvas=Image.new('RGB',(1200,440),'#ddd');d=ImageDraw.Draw(canvas)
for i,p in enumerate(paths):
 try:im=Image.open(p).convert('RGB');im.thumbnail((190,180))
 except Exception:continue
 x=(i%6)*200;y=(i//6)*220;canvas.paste(im,(x+(200-im.width)//2,y));d.text((x+5,y+185),p.name,fill='black')
canvas.save(l.ROOT/'work/vanguard_views.jpg')
print('K04 finished', [dict(r) for r in c.execute("SELECT id,output FROM jobs WHERE kind='tryon' AND status='success' AND json_extract(condition,'$.person_id')='K04' AND json_extract(condition,'$.composition')='tight_face_closeup' ORDER BY rowid DESC")])
print('Vanguard source', [dict(r) for r in c.execute("SELECT id,path,metadata FROM sources WHERE product='Oakley Meta Vanguard'")])
