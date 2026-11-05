"""One resumable YOLO classification run; never loads the sealed test split."""
import argparse,hashlib,io,json,os,random,time
from pathlib import Path
os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8')
import numpy as np
import torch
from PIL import Image,ImageEnhance,ImageFilter,ImageOps
from torch.utils.data import DataLoader,Dataset
from torchvision import transforms as T
from ultralytics import YOLO
import wandb

from ai_glasses.config import YOLO_RUN_ROOT as BASE

PROJECT=os.environ.get('TRYON_WANDB_PROJECT','camera-glasses-yolo')

def dump(path,value):
 tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2));tmp.replace(path)

class Quality:
 def __call__(self,im):
  if random.random()<.4:im=im.filter(ImageFilter.GaussianBlur(random.uniform(.1,.7)))
  if random.random()<.5:
   buf=io.BytesIO();im.save(buf,format='JPEG',quality=random.randint(65,95));buf.seek(0)
   with Image.open(buf) as opened:im=opened.convert('RGB').copy()
  if random.random()<.3:
   a=np.array(im,dtype=np.float32);a+=np.random.normal(0,random.uniform(1,4),a.shape);im=Image.fromarray(np.clip(a,0,255).astype('uint8'))
  return im

class Gamma:
 def __call__(self,im):
  value=random.uniform(.8,1.2);lut=[round(255*(i/255)**value) for i in range(256)];return im.point(lut*3)

class Images(Dataset):
 def __init__(self,rows,config,training=False):self.rows=rows;self.config=config;self.training=training
 def __len__(self):return len(self.rows)
 def __getitem__(self,i):
  row=self.rows[i];cfg=self.config;view=cfg['crop']
  if view=='mixed':view=random.choice(['full','face','band']) if self.training else 'band'
  with Image.open(row['views'][view]) as opened:im=opened.convert('RGB')
  im=ImageOps.pad(im,(cfg['imgsz'],cfg['imgsz']),method=Image.Resampling.BILINEAR,color=(127,127,127))
  if self.training:
   aug=cfg['augmentation']
   if aug in ['color','light','combo','photo_quality']:
    im=T.ColorJitter(brightness=.2,contrast=.2,saturation=.12 if aug!='light' else 0,hue=0)(im)
   if aug in ['light','combo','photo_quality']:im=Gamma()(im)
   if aug in ['affine','combo']:im=T.RandomAffine(degrees=3,translate=(.02,.02),scale=(.97,1.03),fill=127)(im)
   if aug in ['quality','combo','photo_quality']:im=Quality()(im)
  # YOLO's pretrained classification transform uses [0,1] normalization.
  return T.ToTensor()(im),row['label']

def make_model(config):
 model=YOLO(str(BASE/'weights'/config['model'])).model
 head=model.model[-1];head.linear=torch.nn.Linear(head.linear.in_features,2)
 for parameter in model.parameters():parameter.requires_grad_(True)
 model.names={0:'ordinary',1:'camera'};model.nc=2
 return model

def evaluate(model,loader):
 model.eval();matrix=np.zeros((2,2),dtype=np.int64);loss_sum=0;total=0
 with torch.inference_mode():
  for x,y in loader:
   output=model(x.cuda(non_blocking=True));logits=output[1] if isinstance(output,tuple) else output
   loss_sum+=torch.nn.functional.cross_entropy(logits,y.cuda(),reduction='sum').item();pred=logits.argmax(1).cpu().numpy()
   for actual,guess in zip(y.numpy(),pred):matrix[actual,guess]+=1
   total+=len(y)
 tn,fp=map(int,matrix[0]);fn,tp=map(int,matrix[1])
 return dict(accuracy=(tn+tp)/total,balanced_accuracy=(tn/max(1,tn+fp)+tp/max(1,tp+fn))/2,camera_recall=tp/max(1,tp+fn),false_positive_rate=fp/max(1,tn+fp),camera_f1=2*tp/max(1,2*tp+fp+fn),loss=loss_sum/total,confusion_matrix=matrix.tolist())

def main(config_path):
 cfg=json.loads(config_path.read_text());folder=BASE/'experiments'/cfg['name'];folder.mkdir(parents=True,exist_ok=True)
 if (folder/'result.json').exists():return
 manifest=json.loads((BASE/'dataset.json').read_text());manifest_hash=hashlib.sha256((BASE/'dataset.json').read_bytes()).hexdigest()
 seed=cfg['seed'];random.seed(seed);np.random.seed(seed);torch.manual_seed(seed);torch.cuda.manual_seed_all(seed);torch.set_num_threads(6)
 torch.backends.cudnn.benchmark=False
 train_loader=DataLoader(Images(manifest['parts']['train'],cfg,True),batch_size=cfg['batch'],shuffle=True,num_workers=4,pin_memory=True,persistent_workers=True,generator=torch.Generator().manual_seed(seed))
 val_loader=DataLoader(Images(manifest['parts']['val'],cfg),batch_size=cfg['batch'],num_workers=2,pin_memory=True,persistent_workers=True)
 model=make_model(cfg).cuda();optimizer=torch.optim.AdamW(model.parameters(),lr=cfg['lr'],weight_decay=.0005);scaler=torch.amp.GradScaler('cuda')
 scheduler=torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,T_max=cfg['epochs'],eta_min=cfg['lr']*.05)
 start_epoch=0;history=[];best=-1;best_fpr=2;stale=0;checkpoint=folder/'last.pt'
 if checkpoint.exists():
  saved=torch.load(checkpoint,map_location='cpu',weights_only=False);assert saved['manifest_hash']==manifest_hash
  model.load_state_dict(saved['weights']);optimizer.load_state_dict(saved['optimizer']);scaler.load_state_dict(saved['scaler']);scheduler.load_state_dict(saved['scheduler'])
  start_epoch=saved['epoch']+1;history=saved['history'];best=saved['best'];best_fpr=saved['best_fpr'];stale=saved['stale']
  random.setstate(saved['random_state']);np.random.set_state(saved['numpy_state']);torch.set_rng_state(saved['torch_state']);torch.cuda.set_rng_state_all(saved['cuda_state'])
  train_loader.generator.set_state(saved['loader_state'])
 deadline=cfg['deadline'];run_id=hashlib.sha256(cfg['name'].encode()).hexdigest()[:12]
 run=wandb.init(project=PROJECT,id=run_id,resume='allow',name=cfg['name'],group='crop-augmentation-yolo',job_type='train',mode='online',dir=str(BASE),config=dict(cfg,dataset_sha256=manifest_hash,train_images=len(manifest['parts']['train']),validation_images=len(manifest['parts']['val']),test_used=False),settings=wandb.Settings(init_timeout=45))
 started=time.time();failure=None
 try:
  for epoch in range(start_epoch,cfg['epochs']):
   if time.time()>=deadline:break
   model.train();total=0;loss_sum=0;correct=0
   for x,y in train_loader:
    x=x.cuda(non_blocking=True);y=y.cuda(non_blocking=True);optimizer.zero_grad(set_to_none=True)
    with torch.autocast('cuda',dtype=torch.float16):logits=model(x);loss=torch.nn.functional.cross_entropy(logits,y)
    scaler.scale(loss).backward();scaler.unscale_(optimizer);torch.nn.utils.clip_grad_norm_(model.parameters(),10);scaler.step(optimizer);scaler.update()
    total+=len(y);loss_sum+=loss.item()*len(y);correct+=(logits.argmax(1)==y).sum().item()
   scheduler.step();metrics=evaluate(model,val_loader);entry=dict(epoch=epoch+1,train_loss=loss_sum/total,train_accuracy=correct/total,validation=metrics);history.append(entry)
   score=metrics['balanced_accuracy'];improved=score>best+1e-7 or (abs(score-best)<1e-7 and metrics['false_positive_rate']<best_fpr)
   if improved:
    best=score;best_fpr=metrics['false_positive_rate'];stale=0
    torch.save(dict(weights=model.state_dict(),config=cfg,manifest_hash=manifest_hash,epoch=epoch+1,validation=metrics,classes=['ordinary','camera']),folder/'best.tmp');(folder/'best.tmp').replace(folder/'best.pt')
   else:stale+=1
   state=dict(weights=model.state_dict(),optimizer=optimizer.state_dict(),scaler=scaler.state_dict(),scheduler=scheduler.state_dict(),epoch=epoch,history=history,best=best,best_fpr=best_fpr,stale=stale,manifest_hash=manifest_hash,random_state=random.getstate(),numpy_state=np.random.get_state(),torch_state=torch.get_rng_state(),cuda_state=torch.cuda.get_rng_state_all(),loader_state=train_loader.generator.get_state())
   torch.save(state,folder/'last.tmp');(folder/'last.tmp').replace(checkpoint)
   run.log({'epoch':epoch+1,'train/loss':entry['train_loss'],'train/accuracy':entry['train_accuracy'],**{'val/'+k:v for k,v in metrics.items() if k!='confusion_matrix'},'train/lr':optimizer.param_groups[0]['lr']})
   dump(folder/'progress.json',dict(status='training',epoch=epoch+1,best_validation_balanced_accuracy=best,wandb_url=run.url))
   print(json.dumps(dict(run=cfg['name'],epoch=epoch+1,val=score,best=best)),flush=True)
   if epoch+1>=20 and stale>=cfg['patience']:break
  if not (folder/'best.pt').exists():raise RuntimeError('No completed epoch before deadline')
  saved=torch.load(folder/'best.pt',map_location='cpu',weights_only=False)
  result=dict(name=cfg['name'],config=cfg,validation=saved['validation'],best_epoch=saved['epoch'],epochs_completed=len(history),history=history,seconds=time.time()-started,wandb_url=run.url,checkpoint=str(folder/'best.pt'),test_used=False)
  dump(folder/'result.json',result);run.summary.update(dict(best_validation_balanced_accuracy=best,best_false_positive_rate=best_fpr,epochs_completed=len(history),test_used=False));dump(folder/'progress.json',dict(status='complete',wandb_url=run.url))
 except BaseException as exc:
  failure=repr(exc);dump(folder/'failure.json',dict(error=failure,time=time.time()));raise
 finally:run.finish(exit_code=1 if failure else 0)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);args=parser.parse_args();main(args.config)
