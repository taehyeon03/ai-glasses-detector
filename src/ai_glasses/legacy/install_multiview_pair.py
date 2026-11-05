"""Install an inspected same-product front/side pair without changing originals."""
import csv,json,shutil
from pathlib import Path
from ai_glasses.generation import tryon_lab as lab

def main():
 c=lab.connect();s=c.execute("SELECT * FROM sources WHERE product='Mentra Live' AND category='A'").fetchone()
 relative='AI안경_이미지/07_Mentra/Mentra_Live/Mentra_Live_005.png';source=lab.ROOT/'source_snapshot'/relative;target=lab.ROOT/lab.FOLDERS[0]/source.name
 if target.exists() and lab.digest(target)!=lab.digest(source):raise ValueError('An existing side copy differs from the source')
 if not target.exists():shutil.copy2(source,target)
 with (lab.ROOT/'work/ai_sources.csv').open(encoding='utf-8-sig') as f:record=next(r for r in csv.DictReader(f) if r.get('파일')==source.name)
 ref=dict(path=str(target),sha256=lab.digest(target),role='left_side',product='Mentra Live',source_image_url=record['이미지URL'],source_page=record['출처페이지'],original_relative_path=relative,inspection='black front and black left view from the same manufacturer product listing; visually inspected by assistant; human review still required')
 meta=json.loads(s['metadata']);meta.update(extra_references=[ref],reference_resolution=768,reference_geometry='front_and_left_side; unseen inner/opposite surfaces remain unverified')
 c.execute('UPDATE sources SET metadata=? WHERE id=?',(json.dumps(meta,ensure_ascii=False),s['id']));c.commit()
 (lab.ROOT/lab.FOLDERS[9]/'front_side_pairs.json').write_text(json.dumps([dict(product=s['product'],front_path=s['path'],front_sha256=s['sha256'],extra_references=[ref],reference_resolution=768)],ensure_ascii=False,indent=2));lab.export(c);print(json.dumps({'product':s['product'],'side':source.name}))
if __name__=='__main__':main()
