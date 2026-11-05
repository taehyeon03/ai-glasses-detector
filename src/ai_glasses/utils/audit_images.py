"""Compute exact hashes and flag similar photographs without deleting anything."""
import collections
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image,ImageOps
from ai_glasses.generation import tryon_lab as lab
DCT=np.cos(np.pi/32*(np.arange(32)[None,:]+.5)*np.arange(8)[:,None])*np.sqrt(2/32)
DCT[0]/=np.sqrt(2)

def phash(im):
    a=np.asarray(im.convert('L').resize((32,32)),dtype=float)
    b=(DCT@a@DCT.T).ravel();bits=b>np.median(b[1:]);return sum(int(v)<<i for i,v in enumerate(bits))
def fingerprints(path):
    with Image.open(path) as raw:
        rgba=ImageOps.exif_transpose(raw).convert('RGBA');background=Image.new('RGBA',rgba.size,'white');im=Image.alpha_composite(background,rgba).convert('RGB');a=np.asarray(im)
        # Trimming a plain background makes resized or padded product photos comparable.
        mask=np.min(a,axis=2)<230;ys,xs=np.where(mask)
        box=(int(xs.min()),int(ys.min()),int(xs.max())+1,int(ys.max())+1) if len(xs) else (0,0,im.width,im.height)
        crop=im.crop(box)
        return dict(phash=phash(im),trim_phash=phash(crop),trim_box=box,width=im.width,height=im.height)
def main():
    root=lab.ROOT;records=[];errors=[];exact_only=[]
    inv=json.loads((root/'work/drive_inventory.json').read_text());images=[x for x in inv if not x['IsDir'] and x['MimeType'].startswith('image/')]
    cache_path=root/'work/fingerprint_cache.json';cache=json.loads(cache_path.read_text()) if cache_path.exists() else {}
    c=lab.connect();selected={metadata['drive_original_id']:r['path'] for r in c.execute('SELECT * FROM sources') if (metadata:=json.loads(r['metadata'])).get('drive_original_id')}
    for x in images:
        path=root/'source_snapshot'/x['Path']
        if not path.exists() and x['ID'] in selected:path=Path(selected[x['ID']])
        if not path.exists():continue
        md5=x['Hashes'].get('MD5');old=cache.get(x['Path'])
        stat=path.stat()
        if old and old.get('md5')==md5 and old.get('size')==stat.st_size and old.get('mtime_ns')==stat.st_mtime_ns:records.append(old);continue
        try:
            content=path.read_bytes()
            if hashlib.md5(content).hexdigest()!=md5:raise ValueError('Drive MD5 mismatch; possibly incomplete download')
            record=dict(path=x['Path'],md5=md5,sha256=hashlib.sha256(content).hexdigest(),size=stat.st_size,mtime_ns=stat.st_mtime_ns,**fingerprints(path));cache[x['Path']]=record;records.append(record)
        except Exception as e:
            errors.append(dict(path=x['Path'],error=str(e)))
            try:
                raw=path.read_bytes()
                if hashlib.md5(raw).hexdigest()==md5:exact_only.append(dict(path=x['Path'],md5=md5,sha256=hashlib.sha256(raw).hexdigest(),perceptual_check='decode_failed'))
            except OSError:pass
    cache_path.write_text(json.dumps(cache,ensure_ascii=False))
    suspected=[]
    for i,a in enumerate(records):
        for b in records[i+1:]:
            if a['sha256']==b['sha256']:continue
            full=(a['phash']^b['phash']).bit_count();trim=(a['trim_phash']^b['trim_phash']).bit_count()
            if full<=6 or trim<=5:suspected.append(dict(a=a['path'],b=b['path'],full_phash_distance=full,trim_phash_distance=trim,status='similarity_suspected_not_confirmed'))
    rec=root/lab.FOLDERS[9]
    (rec/'perceptual_candidates.json').write_text(json.dumps(suspected,ensure_ascii=False))
    (rec/'image_fingerprints.jsonl').write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in records+exact_only))
    generated=[];new_candidates=[];old_hashes=collections.defaultdict(list);new_hashes=collections.defaultdict(list)
    for r in records+exact_only:old_hashes[r['sha256']].append(r['path'])
    for job in c.execute("SELECT * FROM jobs WHERE status='success'"):
        try:
            sha=lab.digest(job['output'])
            if sha!=job['output_sha256']:raise ValueError('Generated output differs from the recorded hash')
            fp=dict(id=job['id'],sha256=sha,kind=job['kind'],condition=json.loads(job['condition']),**fingerprints(job['output']));generated.append(fp);new_hashes[sha].append(job['id'])
            if sha in old_hashes:new_candidates.append(dict(generated=job['id'],originals=old_hashes[sha],status='exact_match'))
            for old in records:
                distance=(fp['phash']^old['phash']).bit_count()
                if distance<=6:new_candidates.append(dict(generated=job['id'],original=old['path'],phash_distance=distance,status='similarity_suspected_not_confirmed'))
        except Exception as e:errors.append(dict(path=job['output'],error=str(e)))
    for i,a in enumerate(generated):
        for b in generated[i+1:]:
            distance=(a['phash']^b['phash']).bit_count()
            if distance<=6:new_candidates.append(dict(a=a['id'],b=b['id'],phash_distance=distance,same_person_and_pose=all(a['condition'].get(k)==b['condition'].get(k) for k in ('person_id','pose')),status='similarity_suspected_not_confirmed',note='Same-person paired conditions are intentional; do not remove automatically.'))
    (rec/'generated_duplicate_candidates.json').write_text(json.dumps(new_candidates,ensure_ascii=False))
    (rec/'generated_fingerprints.jsonl').write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in generated))
    info=dict(total_drive_images=len(images),local_sha256_checked=len(records)+len(exact_only),downloaded_sha256_and_perceptual_checked=len(records),not_checked=len(images)-len(records),errors=errors,suspected_pairs=len(suspected),generated_checked=len(generated),generated_exact_duplicate_groups=sum(len(v)>1 for v in new_hashes.values()),generated_exact_original_matches=sum(r['sha256'] in old_hashes for r in generated),generated_similarity_candidates=len(new_candidates),method='Drive MD5 for whole inventory; local SHA-256; 64-bit DCT pHash for full image and background-trimmed image; candidate thresholds 6 and 5 bits; generated outputs are also compared against originals and each other',limits='Aspect changes, severe cropping, rotation, altered backgrounds, transparent content and similar product shapes can evade or confuse this screen. Similarity is not a duplicate decision. No files are removed.')
    (rec/'duplicate_audit_summary.json').write_text(json.dumps(info,ensure_ascii=False,indent=2));print(json.dumps(info,ensure_ascii=False))
if __name__=='__main__':main()
