"""Run budgeted YOLO trials on the RTX host, then open one frozen test once."""
import collections,datetime,fcntl,hashlib,itertools,json,os,shutil,subprocess,sys,time,traceback
from pathlib import Path
from ai_glasses.training.yolo_experiment import BASE,PROJECT,dump

CUTOFF=datetime.datetime.fromisoformat('2026-11-05T07:50:00+09:00').timestamp()
TRAIN_END=datetime.datetime.fromisoformat('2026-11-05T08:00:00+09:00').timestamp()
INITIAL=[('full','none'),('face','none'),('band','none'),('band','color'),('band','light'),('band','affine'),('band','quality'),('face','photo_quality'),('band','combo'),('mixed','combo')]

def results():
 return [json.loads(p.read_text()) for p in sorted((BASE/'experiments').glob('exp_*/result.json'))]

def signature(config):return json.dumps({k:v for k,v in config.items() if k not in ['name','seed','deadline']},sort_keys=True)

def choose(rows):
 groups=collections.defaultdict(list)
 for row in rows:groups[signature(row['config'])].append(row)
 repeated={key:value for key,value in groups.items() if len(value)>=2};groups=repeated or groups
 winning=max(groups.values(),key=lambda group:(sum(r['validation']['balanced_accuracy'] for r in group)/len(group),-sum(r['validation']['false_positive_rate'] for r in group)/len(group)))
 mean=sum(r['validation']['balanced_accuracy'] for r in winning)/len(winning)
 return min(winning,key=lambda r:abs(r['validation']['balanced_accuracy']-mean)),dict(group_mean_validation_balanced_accuracy=mean,seeds=len(winning),rule='Choose configuration by mean validation balanced accuracy across seeds; FPR breaks ties. Use its seed closest to the mean. Test scores are unavailable during selection.')

def trial_config(index,rows):
 if index<10:crop,aug=INITIAL[index];model='n';size=320;seed=42;lr=.0001;epochs=80
 else:
  scores=collections.defaultdict(list)
  for row in rows:scores[(row['config']['crop'],row['config']['augmentation'])].append(row['validation']['balanced_accuracy'])
  top=sorted(scores,key=lambda k:sum(scores[k])/len(scores[k]),reverse=True)[:4] or INITIAL[:4]
  # Match seeds across architecture, resolution and learning-rate comparisons.
  choices=list(itertools.product(top,['n','s','m'],[320,448,640],[.0001,.00003]))
  offset=index-10;choice=choices[(offset//3)%len(choices)];(crop,aug),model,size,lr=choice;seed=42+(offset%3)+3*(offset//(len(choices)*3));epochs=100
 return dict(name=f'exp_{index+1:04d}_{model}_{size}_{crop}_{aug}_s{seed}',model=f'yolo26{model}-cls.pt',crop=crop,augmentation=aug,imgsz=size,batch=16 if model=='m' and size==640 else 32,lr=lr,seed=seed,epochs=epochs,patience=25,deadline=CUTOFF)

def final_test(rows):
 if (BASE/'final_test.json').exists():return
 if not rows:raise RuntimeError('No completed experiments; test remains sealed')
 chosen,selection=choose(rows);lock=BASE/'selection_before_test.json'
 if lock.exists():frozen=json.loads(lock.read_text());chosen=frozen['chosen'];selection=frozen['selection']
 else:
  frozen=dict(chosen=chosen,selection=selection,selected_at=time.time(),checkpoint_sha256=hashlib.sha256(Path(chosen['checkpoint']).read_bytes()).hexdigest());dump(lock,frozen)
 assert hashlib.sha256(Path(chosen['checkpoint']).read_bytes()).hexdigest()==frozen['checkpoint_sha256']
 import torch,wandb
 from torch.utils.data import DataLoader
 from ai_glasses.training.yolo_experiment import Images,make_model,evaluate
 torch.set_num_threads(6);manifest=json.loads((BASE/'dataset.json').read_text());config=chosen['config'];model=make_model(config).cuda()
 saved=torch.load(chosen['checkpoint'],map_location='cpu',weights_only=False);model.load_state_dict(saved['weights'])
 loader=DataLoader(Images(manifest['parts']['test'],config),batch_size=16,num_workers=2,pin_memory=True)
 metrics=evaluate(model,loader)
 report=dict(selected_run=chosen['name'],selection=selection,test_images=len(manifest['parts']['test']),metrics=metrics,test_used_for_selection=False,groups=manifest['group_overlap'],prior_resnet_warning=manifest['prior_resnet_warning'],real_world_performance='not measured',completed_experiments=len(rows))
 dump(BASE/'final_test.json',report);shutil.copy2(chosen['checkpoint'],BASE/'selected_model.pt');dump(BASE/'selected_model_config.json',config)
 run=wandb.init(project=PROJECT,id='sealed-test-20261105',resume='allow',name='final-sealed-test-200',job_type='final-test',mode='online',dir=str(BASE),config=dict(selected_run=chosen['name'],test_images=200,test_used_for_selection=False),settings=wandb.Settings(init_timeout=45))
 run.log({'test/'+k:v for k,v in metrics.items() if k!='confusion_matrix'});run.summary['confusion_matrix_ordinary_camera']=metrics['confusion_matrix']
 artifact=wandb.Artifact('selected-yolo-camera-glasses',type='model',metadata=config);artifact.add_file(str(BASE/'selected_model.pt'));artifact.add_file(str(BASE/'selected_model_config.json'));run.log_artifact(artifact);run.finish()
 text=f"# YOLO 실험 결과\n\n완료한 실험은 {len(rows)}개입니다.\n\n선택한 실험: {chosen['name']}\n\n검증 점수로 모델을 선택했습니다. 선택이 끝난 뒤 고정한 테스트 200장을 평가했습니다.\n\n테스트 정확도: {metrics['accuracy']:.1%}\n\n카메라 안경을 찾은 비율: {metrics['camera_recall']:.1%}\n\n일반 안경을 잘못 의심한 비율: {metrics['false_positive_rate']:.1%}\n\n모든 테스트 사진은 합성 이미지입니다. 일부는 앞선 ResNet 시험에 쓰였습니다. 이번 YOLO의 학습과 검증에는 쓰이지 않았습니다. 실제 착용 사진의 성능은 측정하지 않았습니다.\n\n검증 자료는 30장입니다. 많은 실험을 비교한 만큼 검증 점수의 변동에 주의해야 합니다. 학습과 검증은 얼굴을 분리했습니다. 그 사이에 안경 모델은 겹칠 수 있습니다. 테스트는 얼굴과 안경 모델을 모두 분리했습니다.\n"
 (BASE/'결과_요약.md').write_text(text)

def main():
 lock=open(BASE/'controller.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 (BASE/'configs').mkdir(exist_ok=True);(BASE/'experiments').mkdir(exist_ok=True)
 if (BASE/'final_test.json').exists():dump(BASE/'status.json',dict(phase='experiments_complete',updated=time.time(),completed=len(results())));return
 # Cache official pretrained assets before starting long runs.
 from ultralytics import YOLO
 for size in ['n','s','m']:
  target=BASE/'weights'/f'yolo26{size}-cls.pt'
  if not target.exists():YOLO(str(target))
 failures=collections.Counter();index=0
 while time.time()<CUTOFF and not (BASE/'selection_before_test.json').exists():
  rows=results();cfg=trial_config(index,rows);folder=BASE/'experiments'/cfg['name']
  # Keep an already written configuration stable across service restarts.
  existing=list((BASE/'configs').glob(f'{index+1:04d}_*.json'))
  if existing:path=existing[0];cfg=json.loads(path.read_text());folder=BASE/'experiments'/cfg['name']
  else:path=BASE/'configs'/f'{index+1:04d}_{cfg["name"]}.json';dump(path,cfg)
  if (folder/'result.json').exists():index+=1;continue
  dump(BASE/'status.json',dict(phase='training',current=cfg['name'],completed=len(rows),cutoff_kst='2026-11-05 07:50',transition_kst='2026-11-05 08:00',updated=time.time(),test_opened=False))
  with open(BASE/'training.log','a') as log:
   child=subprocess.Popen([sys.executable,'-u','-m','ai_glasses.training.yolo_experiment','--config',str(path)],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
   try:code=child.wait(timeout=max(30,CUTOFF-time.time()+30))
   except subprocess.TimeoutExpired:
    os.killpg(child.pid,15)
    try:child.wait(timeout=20)
    except subprocess.TimeoutExpired:os.killpg(child.pid,9);child.wait()
    code=124
  if code and time.time()<CUTOFF:
   failures[cfg['name']]+=1;dump(BASE/'last_failure.json',dict(run=cfg['name'],returncode=code,retries=failures[cfg['name']],updated=time.time()))
   if failures[cfg['name']]<3:time.sleep(10);continue
  index+=1
  dump(BASE/'leaderboard.json',results())
 final_test(results());dump(BASE/'leaderboard.json',results());dump(BASE/'status.json',dict(phase='experiments_complete',completed=len(results()),test_opened=True,updated=time.time()))

if __name__=='__main__':main()
