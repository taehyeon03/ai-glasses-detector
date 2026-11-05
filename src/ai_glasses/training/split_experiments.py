"""Group generated relatives before assigning any experimental split."""
import argparse
import collections
import json
import random
from pathlib import Path
from ai_glasses.generation import tryon_lab as lab

def split(c,mode='strict',seed=42):
    if mode not in ('strict','joint'):raise ValueError('Use strict grouping or joint person/product assignment')
    rows=[dict(r) for r in c.execute("SELECT j.id,j.condition,r.decision FROM jobs j LEFT JOIN reviews r ON r.job_id=j.id WHERE j.kind='tryon' AND j.status='success'")]
    if mode=='joint':
        parsed={r['id']:json.loads(r['condition']) for r in rows};people=sorted({x['person_id'] for x in parsed.values()});rng=random.Random(seed);rng.shuffle(people)
        person_split={p:('train' if i<len(people)//2 else 'test') for i,p in enumerate(people)}
        product_split={}
        for camera in ('present','absent'):
            products=sorted({x['product'] for x in parsed.values() if x['camera']==camera});rng.shuffle(products)
            product_split.update({p:('train' if i<len(products)//2 else 'test') for i,p in enumerate(products)})
        assignments={}
        for r in rows:
            x=parsed[r['id']];a=person_split[x['person_id']];b=product_split[x['product']];which=a if a==b else 'excluded_cross_assignment'
            assignments[r['id']]=dict(split=which,eligible=r['decision']=='pass' and a==b,synthetic=True,person_id=x['person_id'],product=x['product'],source_sha256=x['source_sha256'])
        return dict(mode=mode,seed=seed,person_assignment=person_split,product_assignment=product_split,assignments=assignments,warning='인물과 제품을 각각 분리한 뒤 배정이 다른 조합은 제외합니다. 통과 판정이 없는 이미지는 학습에 사용할 수 없습니다. 현재 샘플만으로는 양쪽에 자료가 충분하지 않을 수 있습니다.',real_world_performance='not_evaluated')
    parents={r['id']:r['id'] for r in rows}
    def find(x):
        while parents[x]!=x:parents[x]=parents[parents[x]];x=parents[x]
        return x
    seen={}
    for r in rows:
        con=json.loads(r['condition']);r['parsed']=con
        # Exact source hash always stays together. Strict additionally joins identities and products.
        keys=[('source',con['source_sha256'])]
        keys.append(('person',con['person_id']))
        keys.append(('product',con['product']))
        for key in keys:
            if key in seen:parents[find(r['id'])]=find(seen[key])
            seen[key]=r['id']
    groups=collections.defaultdict(list)
    for r in rows:groups[find(r['id'])].append(r)
    ordered=sorted(groups);random.Random(seed).shuffle(ordered)
    assignments={}
    # One connected component cannot supply an independent test set.
    for i,key in enumerate(ordered):
        which='train' if len(ordered)<3 or i<round(len(ordered)*.7) else ('validation' if i<round(len(ordered)*.85) else 'test')
        for row in groups[key]:assignments[row['id']]=dict(component=key,split=which,eligible=row['decision']=='pass',synthetic=True)
    return dict(mode=mode,seed=seed,components=len(groups),warning='인물과 원본을 함께 묶으면 연결된 묶음이 하나가 될 수 있습니다. 이 경우 독립 시험 세트를 만들지 않습니다.',assignments=assignments,real_world_performance='not_evaluated')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=['strict','joint'],default='strict');a=p.parse_args();c=lab.connect();result=split(c,a.mode);out=lab.ROOT/lab.FOLDERS[9]/('split_'+a.mode+'.json');out.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(out)
