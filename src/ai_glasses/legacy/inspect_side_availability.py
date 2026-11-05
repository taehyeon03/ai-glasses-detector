import csv,json,re
from pathlib import Path
from urllib.parse import urlsplit
from PIL import Image,ImageOps,ImageDraw
from ai_glasses.generation import tryon_lab as lab
c=lab.connect();normal=list(csv.DictReader(open('work/normal_sources.csv',encoding='utf-8-sig')));ai=list(csv.DictReader(open('work/ai_sources.csv',encoding='utf-8-sig')));files={p.name:p for p in (lab.ROOT/'source_snapshot').rglob('*') if p.is_file()}
records=[];tiles=[]
for s in c.execute("SELECT * FROM sources WHERE category='B' AND json_extract(metadata,'$.selected')=1 ORDER BY product"):
 m=json.loads(s['metadata']);front=next(r for r in normal if r['파일']==Path(s['path']).name);stem=Path(urlsplit(front['이미지URL']).path).name;code='__'.join(stem.split('__')[:2])
 matching=[r for r in normal if Path(urlsplit(r['이미지URL']).path).name.startswith(code+'__')]
 sides=[r for r in matching if re.search(r'(?:__shad__(?:lt|rt)|_(?:090|270)A)',Path(urlsplit(r['이미지URL']).path).name,re.I) or re.search(r'\((?:Left|Right|Side)',r.get('상품명',''),re.I)]
 record={'product':s['product'],'sku_prefix':code,'same_variant_images':len(matching),'side_candidates':[r['파일'] for r in sides]};records.append(record)
 for r in sides[:1]:
  path=files.get(r['파일'])
  if path:
   tile=Image.new('RGB',(360,210),'white');im=Image.open(path).convert('RGB');im.thumbnail((350,165));tile.paste(im,((360-im.width)//2,12));ImageDraw.Draw(tile).text((8,178),s['product'],fill='black');tiles.append(tile)
canvas=Image.new('RGB',(360*5,210*2),'#ddd')
for i,tile in enumerate(tiles):canvas.paste(tile,((i%5)*360,(i//5)*210))
canvas.save(lab.ROOT/'work/ordinary_side_availability.jpg');(lab.ROOT/'work/side_availability.json').write_text(json.dumps(records,ensure_ascii=False,indent=2));print(json.dumps(records,ensure_ascii=False))
