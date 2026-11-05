"""Keep failed pose attempts and replace only their unexecuted downstream jobs."""
import json
from ai_glasses.generation import tryon_lab as lab

def main():
    c=lab.connect();targets=[('P01','right_profile'),('P04','left_profile')]
    for pid,pose in targets:
        old=c.execute("SELECT * FROM jobs WHERE kind='portrait' AND json_extract(condition,'$.person_id')=? AND json_extract(condition,'$.pose')=? AND json_extract(condition,'$.protocol')='v1'",(pid,pose)).fetchone()
        con=json.loads(old['condition']);direction='right' if pose=='right_profile' else 'left';con['protocol']='v2_profile';con['steps']=40;con['pose_convention']='direction the nose points in the image';con['pose_verified']=False
        con['prompt']=f'Use image 1 as the identity reference for the same fictional adult. Create a strict 90-degree side-profile photograph. The nose must point to the image {direction}. The camera is directly at the side of the head. Show only one eye and only one ear. The far eye and far ear must be hidden by the head. The nose is visible in silhouette. This must be a complete side profile rather than a three-quarter view. Keep the identical facial anatomy, skin texture, hair and adult identity from image 1. {con["light"]}. Hair stays clear of the face. No eyewear, glasses or head accessories. Do not add text or graphics.'
        key=lab.add_job(c,con,'portrait')
        if old['status']!='success':c.execute("UPDATE jobs SET status='superseded',error='A stricter profile instruction is queued' WHERE id=?",(old['id'],))
        else:c.execute('INSERT OR REPLACE INTO diagnostics VALUES(?,?,?)',(old['id'],'요청한 측면보다 사선에 가깝게 생성됐습니다. 최초 결과를 보존하고 측면 조건을 보강했습니다.',lab.now()))
        children=list(c.execute("SELECT * FROM jobs WHERE kind='tryon' AND json_extract(condition,'$.portrait_job')=? AND json_extract(condition,'$.batch')='first_56' AND status IN ('pending','blocked_dependency')",(old['id'],)))
        for child in children:
            item=json.loads(child['condition']);item['portrait_job']=key;item['portrait_protocol']='v2_profile';item['pose_convention']=con['pose_convention'];item['previous_pose_job']=child['id'];lab.add_job(c,item,'tryon')
            c.execute("UPDATE jobs SET status='superseded',error='Updated portrait dependency; original condition retained' WHERE id=?",(child['id'],))
        c.commit()
    lab.export(c)
if __name__=='__main__':main()
