"""Inventory Drive originals and register only inspected source references."""
import collections
import csv
import hashlib
import json
from pathlib import Path
import shutil
from ai_glasses.generation import tryon_lab as lab

SELECTED=[
('Meta_RayBan_Gen2_Wayfarer_016.jpg','work/meta_wayfarer/Meta_RayBan_Gen2_Wayfarer_016.jpg','A','Ray-Ban / Meta','Ray-Ban Meta Gen 2 Wayfarer','present','https://www.ray-ban.com/usa/c/frequently-asked-questions-ray-ban-meta-smart-glasses','The official FAQ confirms the camera and distinguishes the capture LED. The inspected front product photograph shows the frame and its apertures.','Black Wayfarer frame, dark grey lenses. One camera aperture and a separate capture LED at opposite upper outer frame corners. The capture LED is not a second camera.'),
('Meta_Oakley_HSTN_014.jpg','work/meta_hstn/Meta_Oakley_HSTN_014.jpg','A','Oakley / Meta','Oakley Meta HSTN','present','https://www.oakley.com/en-us/product/W0OO9438','The official comparison section explicitly lists the HSTN hands-free camera. The inspected front product photograph matches HSTN.','Black rounded angular HSTN frame, dark grey lenses. Preserve camera aperture and opposite capture LED without treating both as cameras.'),
('09_웨이페어러_닮은꼴_RayBan_003.jpg','work/rb2140_front.jpg','B','Ray-Ban','Ray-Ban RB2140 Original Wayfarer Classic 901','absent','https://www.ray-ban.com/usa/sunglasses/RB2140original%20wayfarer%20classic-black/805289126577','The official product identifies standard RB2140 optical sunglasses. The inspected photograph has ordinary decorative elongated silver rivets; these are not camera apertures. Classification is based on the identified standard product, not visual absence alone.','Black acetate Wayfarer frame, green G-15 lenses. Preserve the elongated silver decorative rivets. This is standard optical eyewear with zero cameras, zero sensors and zero electronic buttons.'),
('09_웨이페어러_닮은꼴_Oakley_002.png','work/eye_jacket_front.png','B','Oakley','Oakley Eye Jacket Redux OO9438-0158','absent','https://www.oakley.com/en-us/product/W0OO9438','The official Product Info identifies OO9438-0158, O Matter frame, Unobtainium pads and Prizm lenses as ordinary optical sunglasses. The inspected front image matches this product. The separate HSTN recommendation on the same page is not this product.','Matte black strongly oval wraparound frame, grey-purple tinted Prizm lenses. Preserve the small white bridge logo. This ordinary optical product has zero cameras, zero electronic sensors and zero buttons.')]

def main():
    root=lab.ROOT;c=lab.connect();rec=root/lab.FOLDERS[9]
    inv=json.loads((root/'work/drive_inventory.json').read_text())
    images=[x for x in inv if not x['IsDir'] and x['MimeType'].startswith('image/')]
    csvrows={}
    for name in ('ai','normal'):
        for row in csv.DictReader(open(root/'work'/f'{name}_sources.csv',encoding='utf-8-sig')):csvrows[row['파일']]=row
    selected={}
    extra=('EvenRealities_G2_004.jpg','work/even_g2_004.jpg','C','Even Realities','Even G2','absent','https://www.evenrealities.com/privacy-center','The manufacturer explicitly states that Even G2 has no camera. This existing photograph shows the identified round-frame product worn by a person. It is kept as a source record only and is never used as a face reference.','No camera; display-based smart glasses. Not standard optical eyewear.')
    additions=json.loads((root/'additional_sources.json').read_text()) if (root/'additional_sources.json').exists() else []
    entries=SELECTED+([extra] if (root/extra[1]).exists() else [])+additions
    for filename,path,category,maker,product,camera,url,evidence,detail in entries:
        original=root/path
        if not original.exists():raise FileNotFoundError(original)
        file_hash=lab.digest(original);key=lab.uid(['source',file_hash]);dst=root/lab.FOLDERS[{'A':0,'B':1,'C':2}[category]]/filename
        if not dst.exists():shutil.copy2(original,dst)
        elif lab.digest(dst)!=file_hash:raise ValueError('Existing copy differs')
        drive=next(x for x in images if x['Name']==filename)
        if hashlib.md5(dst.read_bytes()).hexdigest()!=drive['Hashes']['MD5']:raise ValueError('Drive original hash mismatch')
        meta=dict(csvrows[filename]);meta.update(manufacturer=maker,model=product,selected=category in ('A','B'),pose='front' if category!='C' else 'oblique',camera_evidence_url=url,evidence_checked_at=lab.now(),detail_prompt=detail,rights_status='권리 확인 필요',author='제조사 또는 판매자; 개별 촬영자 미확인',license='학습 및 재배포 허용을 확인하지 못함',drive_original_id=drive['ID'],drive_original_path=drive['Path'],file_sha256=file_hash,image_inspection='inspected_by_assistant_not_human_review',reference_geometry='only visible reference geometry is verified; hidden surfaces are inferred',camera_count=(1 if category=='A' and filename in {x[0] for x in SELECTED} else (0 if category in ('B','C') else None)))
        c.execute('INSERT OR IGNORE INTO sources VALUES(?,?,?,?,?,?,?,?)',(key,str(dst),file_hash,product,category,camera,evidence+' '+url,json.dumps(meta,ensure_ascii=False)));c.commit();selected[filename]=dict(id=key,category=category,metadata=meta)
    md5groups=collections.defaultdict(list)
    for x in images:
        if x.get('Hashes',{}).get('MD5'):md5groups[x['Hashes']['MD5']].append(x['Path'])
    duplicates=[dict(md5=h,paths=p) for h,p in md5groups.items() if len(p)>1]
    (rec/'exact_duplicates.json').write_text(json.dumps(duplicates,ensure_ascii=False,indent=2))
    catalog=[]
    for x in images:
        m=csvrows.get(x['Name'],{});chosen=selected.get(x['Name'])
        verified=chosen['metadata'] if chosen else {}
        catalog.append(dict(drive_id=x['ID'],original_path=x['Path'],name=x['Name'],md5=x.get('Hashes',{}).get('MD5'),category=chosen['category'] if chosen else 'D',manufacturer=verified.get('manufacturer','확인 필요'),model_name=verified.get('model',m.get('상품명',m.get('폴더','확인 필요'))),product_confirmation='verified_from_product_documentation' if chosen else 'unverified_collection_label',camera_status=('present' if chosen['category']=='A' else 'absent') if chosen else 'unknown',camera_evidence_url=verified.get('camera_evidence_url',''),image_url=m.get('이미지URL',''),product_page=m.get('출처페이지',''),collection_date=m.get('수집일',''),author=verified.get('author','확인 필요'),license=verified.get('license','확인 필요'),reason='Product documentation and source photograph inspected' if chosen else ('기존 제외 기록이 있음; 개별 사진과 제품의 근거를 다시 확인해야 함' if '_제외_' in x['Path'] else '개별 사진의 적합성 또는 제품의 카메라 유무를 아직 확인하지 못함'),source_metadata=m,rights_status='권리 확인 필요',perceptual_check='not_checked',local_sha256=chosen['metadata']['file_sha256'] if chosen else None))
    (rec/'source_catalog.jsonl').write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in catalog))
    with open(rec/'source_catalog.csv','w',encoding='utf-8-sig',newline='') as f:
        fields=list(catalog[0]);w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(dict(row,source_metadata=json.dumps(row['source_metadata'],ensure_ascii=False)) for row in catalog)
    (root/lab.FOLDERS[3]/'확인필요_원본목록.jsonl').write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in catalog if x['category']=='D'))
    summary=dict(inventory_images=len(images),groups=dict(collections.Counter(x['category'] for x in catalog)),md5_checked=sum('MD5' in x.get('Hashes',{}) for x in images),exact_duplicate_groups=len(duplicates),duplicate_extra_files=sum(len(d['paths'])-1 for d in duplicates),selected_sources=selected)
    (rec/'intake_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in summary.items() if k!='selected_sources'},ensure_ascii=False))
    lab.export(c)
if __name__=='__main__':main()
