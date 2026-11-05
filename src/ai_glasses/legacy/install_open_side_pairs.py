"""Attach the ten inspected ordinary-glasses side views to their exact front SKU."""
import csv,json,shutil
from pathlib import Path
from ai_glasses.generation import tryon_lab as lab

def main():
 c=lab.connect();availability=json.loads((lab.ROOT/'work/side_availability.json').read_text());rows=list(csv.DictReader(open(lab.ROOT/'work/normal_sources.csv',encoding='utf-8-sig')));by_name={r['파일']:r for r in rows};files={p.name:p for p in (lab.ROOT/'source_snapshot').rglob('*') if p.is_file()};result=[]
 for pair in availability:
  source=c.execute("SELECT * FROM sources WHERE product=? AND category='B'",(pair['product'],)).fetchone()
  side_name=pair['side_candidates'][0];side=files[side_name];target=lab.ROOT/lab.FOLDERS[1]/side_name
  if target.exists() and lab.digest(target)!=lab.digest(side):raise ValueError('Side copy differs from original')
  if not target.exists():shutil.copy2(side,target)
  provenance=by_name[side_name];extra=dict(path=str(target),sha256=lab.digest(target),role='left_side',product=source['product'],temple_state='open',source_image_url=provenance['이미지URL'],source_page=provenance['출처페이지'],sku_prefix=pair['sku_prefix'],inspection='SKU and color matched to front asset; side/open-temple geometry visually inspected by assistant, not a human review decision')
  meta=json.loads(source['metadata']);meta.update(extra_references=[extra],reference_resolution=768,temple_reference_state='open',reference_geometry='front_and_open_side; hidden interior surfaces remain unverified')
  c.execute('UPDATE sources SET metadata=? WHERE id=?',(json.dumps(meta,ensure_ascii=False),source['id']));result.append(dict(product=source['product'],front=source['path'],side=str(target),sha256=extra['sha256']))
 c.commit();(lab.ROOT/lab.FOLDERS[9]/'ordinary_open_side_pairs.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));lab.export(c);print(json.dumps(dict(verified_ordinary_pairs=len(result))))
if __name__=='__main__':main()
