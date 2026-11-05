"""Small, human-approved binary pilot with disjoint people and products."""
import argparse
import collections
import hashlib
import json
import random
import sqlite3
from pathlib import Path

SEED=42

def write_json(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2))

def balanced_pick(rows,n,rng):
    groups=collections.defaultdict(list)
    for row in rows:groups[row['product']].append(row)
    for group in groups.values():rng.shuffle(group)
    result=[]
    while len(result)<n:
        progress=False
        for product in sorted(groups):
            if groups[product] and len(result)<n:
                result.append(groups[product].pop());progress=True
        if not progress:raise ValueError('Not enough approved images')
    return result

def prepare(root,out,n):
    out.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(f'file:{root}/experiment.sqlite?mode=ro',uri=True);c.row_factory=sqlite3.Row
    with sqlite3.connect(out/'review_snapshot.sqlite') as backup:c.backup(backup)
    rows=[];seen=set()
    for r in c.execute("SELECT j.id,j.condition,j.output,j.output_sha256,s.category,s.product,s.sha256 AS source_sha256,r.updated AS review_updated FROM jobs j JOIN sources s ON s.id=json_extract(j.condition,'$.source_id') JOIN reviews r ON r.job_id=j.id WHERE j.kind='tryon' AND j.status='success' AND r.decision='pass' AND s.category IN ('A','B') ORDER BY j.id"):
        row=dict(r);con=json.loads(row.pop('condition'));row['person_id']=con['person_id'];row['label']=int(row['category']=='A')
        if row['output_sha256'] in seen:continue
        if not Path(row['output']).is_file():raise FileNotFoundError(row['output'])
        if hashlib.sha256(Path(row['output']).read_bytes()).hexdigest()!=row['output_sha256']:raise ValueError('Image digest mismatch')
        seen.add(row['output_sha256']);rows.append(row)
    c.close();rng=random.Random(SEED)
    pool=sum([balanced_pick([r for r in rows if r['category']==category],n,rng) for category in ('A','B')],[])
    people=sorted({r['person_id'] for r in pool});products={category:sorted({r['product'] for r in pool if r['category']==category}) for category in ('A','B')}
    # First feasible random assignment, selected by counts only, before training.
    for attempt in range(2000):
        test_people=set(rng.sample(people,max(1,round(len(people)*.3))))
        test_products=set().union(*(set(rng.sample(p,max(1,round(len(p)*.3)))) for p in products.values()))
        train=[r for r in pool if r['person_id'] not in test_people and r['product'] not in test_products]
        test=[r for r in pool if r['person_id'] in test_people and r['product'] in test_products]
        train_n=min(sum(r['category']==category for r in train) for category in ('A','B'))
        test_n=min(sum(r['category']==category for r in test) for category in ('A','B'))
        if train_n>=150 and test_n>=25:break
    else:raise ValueError('Insufficient independent groups for pilot')
    chosen={}
    for name,eligible,count in [('train',train,train_n),('test',test,test_n)]:
        chosen[name]=sum([balanced_pick([r for r in eligible if r['category']==category],count,rng) for category in ('A','B')],[])
    for key in ['person_id','product','source_sha256','output_sha256']:
        if {r[key] for r in chosen['train']}&{r[key] for r in chosen['test']}:raise ValueError(f'Leakage: {key}')
    used={r['id'] for part in chosen.values() for r in part}
    manifest=dict(seed=SEED,pool_per_class=n,selected_pool=pool,train=chosen['train'],test=chosen['test'],unused=[r for r in pool if r['id'] not in used],test_people=sorted(test_people),test_products=sorted(test_products),assignment_attempt=attempt,selection='human pass only; round robin by product; no selection by test accuracy',real_world_performance='not_evaluated',task='image classification, not bounding-box detection')
    write_json(out/'dataset.json',manifest)
    return manifest

def train(out,epochs,full_fit=False):
    import os,time
    os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8')
    import numpy as np
    import torch
    from PIL import Image
    from torch.utils.data import Dataset,DataLoader
    from torchvision import transforms
    from torchvision.models import resnet18,ResNet18_Weights
    random.seed(SEED);np.random.seed(SEED);torch.manual_seed(SEED);torch.cuda.manual_seed_all(SEED)
    torch.set_num_threads(6);torch.backends.cudnn.benchmark=False
    manifest=json.loads((out/'dataset.json').read_text())
    if full_fit:manifest['train']=manifest['selected_pool']
    progress_file=out/('full_fit_progress.json' if full_fit else 'progress.json')
    class Images(Dataset):
        def __init__(self,rows,training):
            self.rows=rows
            ops=[transforms.Resize((224,224))]
            if training:ops.append(transforms.ColorJitter(brightness=.15,contrast=.15,saturation=.1))
            self.transform=transforms.Compose(ops+[transforms.ToTensor(),transforms.Normalize([.485,.456,.406],[.229,.224,.225])])
        def __len__(self):return len(self.rows)
        def __getitem__(self,i):
            row=self.rows[i]
            with Image.open(row['output']) as image:x=self.transform(image.convert('RGB'))
            return x,row['label']
    loaders={name:DataLoader(Images(manifest[name],name=='train'),batch_size=32,shuffle=name=='train',num_workers=4,pin_memory=True,persistent_workers=True,generator=torch.Generator().manual_seed(SEED)) for name in (['train'] if full_fit else ['train','test'])}
    model=resnet18(weights=ResNet18_Weights.DEFAULT);model.fc=torch.nn.Linear(model.fc.in_features,2);model.cuda()
    optimizer=torch.optim.AdamW(model.parameters(),lr=1e-4,weight_decay=1e-4)
    loss_fn=torch.nn.CrossEntropyLoss();scaler=torch.amp.GradScaler('cuda');history=[];start=time.time()
    # Fixed schedule. The held-out set is used once after the final epoch.
    for epoch in range(epochs):
        model.train();total=0;loss_sum=0;correct=0
        for x,y in loaders['train']:
            x=x.cuda(non_blocking=True);y=y.cuda(non_blocking=True);optimizer.zero_grad(set_to_none=True)
            with torch.autocast('cuda',dtype=torch.float16):logits=model(x);loss=loss_fn(logits,y)
            scaler.scale(loss).backward();scaler.step(optimizer);scaler.update()
            total+=len(y);loss_sum+=loss.item()*len(y);correct+=(logits.argmax(1)==y).sum().item()
        row=dict(epoch=epoch+1,train_loss=loss_sum/total,train_accuracy=correct/total);history.append(row);print(json.dumps(row),flush=True)
        write_json(progress_file,dict(status='training',history=history))
    torch.save(dict(model=model.state_dict(),architecture='resnet18',classes=['B: ordinary glasses','A: camera-equipped glasses'],input_size=224,normalization=dict(mean=[.485,.456,.406],std=[.229,.224,.225]),epochs=epochs,seed=SEED,full_fit=full_fit),out/('full_model.pt' if full_fit else 'model.pt'))
    if full_fit:
        result=dict(status='complete',train_images=len(manifest['train']),epochs=epochs,history=history,training_seconds=time.time()-start,independent_evaluation='not available for this refit; metrics.json describes the separate held-out pilot only',real_world_performance='not_evaluated')
        write_json(out/'full_fit_metrics.json',result);write_json(progress_file,dict(status='complete'));print(json.dumps(result),flush=True);return
    model.eval();predictions=[];matrix=[[0,0],[0,0]];offset=0
    with torch.inference_mode():
        for x,y in loaders['test']:
            probabilities=model(x.cuda()).softmax(1).cpu()
            for label,probability in zip(y.tolist(),probabilities.tolist()):
                pred=int(probability[1]>=.5);matrix[label][pred]+=1;row=manifest['test'][offset];offset+=1
                predictions.append(dict(id=row['id'],true_label=label,prediction=pred,camera_probability=probability[1],product=row['product'],person_id=row['person_id']))
    tn,fp=matrix[0];fn,tp=matrix[1];total=tn+fp+fn+tp
    results=dict(status='complete',task=manifest['task'],train_images=len(manifest['train']),test_images=total,pool_images=len(manifest['selected_pool']),unused_images=len(manifest['unused']),accuracy=(tn+tp)/total,balanced_accuracy=(tp/(tp+fn)+tn/(tn+fp))/2,camera_recall=tp/(tp+fn),ordinary_recall=tn/(tn+fp),camera_precision=tp/max(1,tp+fp),camera_f1=2*tp/max(1,2*tp+fp+fn),confusion_matrix=matrix,confusion_order=['B ordinary','A camera'],majority_baseline=.5,history=history,training_seconds=time.time()-start,real_world_performance='not_evaluated',epochs=epochs,learning_rate=1e-4,seed=SEED,architecture='ImageNet pretrained ResNet18; full fine tuning',threshold=.5,group_overlap=dict(person_id=0,product=0,source_sha256=0,output_sha256=0))
    write_json(out/'predictions.json',predictions);write_json(out/'metrics.json',results);write_json(out/'progress.json',dict(status='complete'))
    print(json.dumps(results),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--per-class',type=int,default=444);parser.add_argument('--epochs',type=int,default=5);parser.add_argument('--full-fit',action='store_true');args=parser.parse_args()
    if args.full_fit:
        if not (args.out/'metrics.json').exists():raise SystemExit('Complete the independent pilot first')
        if (args.out/'full_model.pt').exists():raise SystemExit('Full fit already exists')
        train(args.out,args.epochs,True);raise SystemExit(0)
    if (args.out/'dataset.json').exists():raise SystemExit('Output already exists; use a new directory')
    manifest=prepare(args.root,args.out,args.per_class)
    print(json.dumps(dict(pool=len(manifest['selected_pool']),train=len(manifest['train']),test=len(manifest['test']),unused=len(manifest['unused']))),flush=True)
    train(args.out,args.epochs)
