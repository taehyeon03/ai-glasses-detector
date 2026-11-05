"""Record a revised protocol without overwriting any existing result."""
import json
import argparse
from ai_glasses.generation import tryon_lab as lab

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--expand',action='store_true');args=parser.parse_args()
    c=lab.connect()
    # Four identities, all five head directions, all three lighting settings.
    keep={('P01','front'),('P01','left_oblique'),('P01','right_oblique'),('P01','right_profile'),('P02','front'),('P02','left_oblique'),('P02','right_oblique'),('P03','front'),('P03','left_oblique'),('P03','right_oblique'),('P04','front'),('P04','left_oblique'),('P04','right_oblique'),('P04','left_profile')}
    rows=list(c.execute("SELECT * FROM jobs WHERE kind='tryon' AND json_extract(condition,'$.protocol')='v1' ORDER BY rowid"))
    existing=set()
    for r in c.execute("SELECT condition FROM jobs WHERE kind='tryon' AND status!='superseded'"):
        item=json.loads(r['condition'])
        if item.get('protocol','').startswith('v2'):existing.add((item['person_id'],item['pose'],item['source_id']))
    for r in rows:
        con=json.loads(r['condition'])
        if (con['person_id'],con['pose'],con['source_id']) in existing:continue
        if not args.expand and (con['person_id'],con['pose']) not in keep:continue
        con['protocol']='v2_lens_and_geometry';con['steps']=40
        con['prompt']+=' Treat the frame as one rigid manufactured object. Its bridge contour, outer perimeter, rim thickness, and lens-to-frame proportions must not be redesigned. Preserve the source lens opacity: when the product lenses are dark opaque, do not reveal the eyes through them. Preserve every visible aperture as it appears, without making the LED look more like a glass camera lens. Do not symmetrize the two corner apertures.'
        con['batch']='expansion_24' if args.expand else 'first_56';con['previous_protocol_job']=r['id'];lab.add_job(c,con,'tryon')
    c.execute("UPDATE jobs SET status='superseded',error='Protocol v2 prepared; original condition retained' WHERE kind='tryon' AND status='pending' AND json_extract(condition,'$.protocol')='v1'")
    c.commit();lab.export(c)
    print([tuple(x) for x in c.execute('SELECT kind,status,count(*) FROM jobs GROUP BY kind,status')])
if __name__=='__main__':main()
