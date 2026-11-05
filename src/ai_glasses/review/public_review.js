'use strict';
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const decisionNames={pass:'통과',exclude:'제외',hold:'판단 보류',regenerate:'재생성 요청'};
const poseNames={front:'정면',left_oblique:'왼쪽 사선',right_oblique:'오른쪽 사선',left_profile:'왼쪽 옆면',right_profile:'오른쪽 옆면',oblique_from_reference:'원본의 사선 방향'};
const reasons={folded:'다리가 접힌 채 얼굴에 붙음',camera:'카메라의 개수나 위치',frame:'프레임의 모양이나 색',lens:'렌즈의 색이나 투명도',fit:'착용 위치',face:'얼굴이나 머리 모양',pose:'얼굴의 방향',other:'기타'};
let nameChanging=false,jumpBusy=false;
let tabToken=sessionStorage.getItem('glassesReviewTab');if(!/^[a-f0-9]{32}$/.test(tabToken||'')){tabToken=crypto.randomUUID().replaceAll('-','');sessionStorage.setItem('glassesReviewTab',tabToken);}
let data={jobs:[],requests:[],portraits:[],claims:[]},tab='waiting',current=null,list=[],index=0,timer=null,dirty=false,loading=false,busy=false,owned=false,saving=Promise.resolve(),selectedVersion=0,leaseExpires=0,lastActivity=Date.now();
const checks=['카메라의 위치가 원본과 같나요?','카메라의 개수가 원본과 같나요?','원본에 없는 카메라가 생기지 않았나요?','프레임과 렌즈가 원본과 같나요?','안경이 자연스럽게 착용됐나요?','머리카락 등이 안경을 가리나요?'];
checks.forEach((label,i)=>{let row=document.createElement('label');row.className='check';let text=document.createElement('span');text.textContent=label;let select=document.createElement('select');select.dataset.check=i;select.setAttribute('aria-label',label);[['unknown','미확인'],['yes','예'],['no','아니오'],['na','해당 없음']].forEach(([v,t])=>select.add(new Option(t,v)));row.append(text,select);$('#checklist').append(row);});
function headers(){return {'Content-Type':'application/json','X-Review-Tab':tabToken};}
async function api(url,body){let response=await fetch(url,body?{method:'POST',headers:headers(),body:JSON.stringify(body)}:{headers:{'X-Review-Tab':tabToken}});let result=await response.json();if(!response.ok){let e=new Error(result.error||'연결하지 못했습니다.');e.status=response.status;throw e;}return result;}
function reviewer(){return $('#teamName').value.trim();}
function filters(){return {category:$('#category').value,cohort:$('#cohort').value,search:$('#search').value};}
function snapshot(){return {id:current?.id,reviewer:reviewer(),comment:$('#comment').value,checks:$$('[data-check]').map(x=>x.value),mode:$('#useDetails').checked?'detailed':'quick',reason:$('#reason').value,notes:$('#notes').value,target_person:$('#targetPerson').value};}
function controls(){for(let id of ['teamName','startReview','category','cohort','search','jumpNumber','jumpGo','lastReviewed'])$('#'+id).disabled=busy||loading||nameChanging||jumpBusy;let can=owned&&!busy&&!loading&&!jumpBusy;$$('[data-decision]').forEach(b=>b.disabled=!can);$('#nextClaim').hidden=tab!=='waiting';$('#nextClaim').disabled=busy||jumpBusy;$('#editReview').hidden=tab!=='completed'||owned;$('#assignment').textContent=owned?'내게 배정됨 · 중복 배정 방지':'완료한 결과 보기';$('#comment').disabled=!owned;$('#useDetails').disabled=!owned;$('#regenOptions').querySelectorAll('select,textarea').forEach(x=>x.disabled=!owned);$$('[data-check]').forEach(x=>x.disabled=!owned);$('#quickbar').hidden=!current;}
function scheduleSave(){if(!current||loading||!owned)return;dirty=true;$('#saveState').textContent='저장 대기';clearTimeout(timer);timer=setTimeout(()=>flush().catch(showError),700);}
async function flush(){clearTimeout(timer);if(!dirty||!current||!owned)return saving;let value=snapshot();dirty=false;$('#saveState').textContent='저장 중…';saving=saving.catch(()=>{}).then(()=>api('/api/draft',value));try{await saving;if(current?.id===value.id)$('#saveState').textContent=dirty?'저장 대기':'자동 저장됨';}catch(e){if(current?.id===value.id){dirty=true;$('#saveState').textContent='저장 실패';}throw e;}}
function updateDatasetCounts(){for(let category of ['A','B','C']){const stats=data.dataset_stats?.[category];$('#generated'+category).textContent=stats?.generated??'—';$('#dataPassed'+category).textContent=stats?`${stats.passed}장`:'—';$('#dataWaiting'+category).textContent=stats?`${stats.waiting}장`:'—';$('#dataQueued'+category).textContent=stats?`${stats.queued}장`:'—';if(stats){const running=document.createElement('small');running.textContent=`진행 ${stats.running}장`;$('#dataQueued'+category).append(running);}$('#dataProducts'+category).textContent=stats?`생성된 안경 ${stats.products}종 · 통과한 안경 ${stats.passed_products}종`:'';}}
function updateCounts(){updateDatasetCounts();for(let category of ['A','B','C']){let stats=data.review_stats?.[category];$('#reviewed'+category).textContent=stats?.reviewed??'—';$('#reviewBreakdown'+category).textContent=stats?`통과 ${stats.passed}장 · 제외 ${stats.excluded}장 · 보류 ${stats.held}장`:'불러오는 중';$('#reviewProducts'+category).textContent=stats?`검수한 안경 ${stats.products}종`:'';}let members=$('#teamMembers');members.replaceChildren();for(let name of window.reviewSettings.reviewers){let chip=document.createElement('span');let done=data.jobs.filter(j=>j.decision&&j.reviewer===name).length;let active=(data.claims||[]).filter(c=>c.reviewer===name&&data.jobs.some(j=>j.id===c.job_id&&!j.decision)).length;chip.textContent=`${name} · 완료 ${done} · 진행 ${active}`;members.append(chip);}let done=data.jobs.filter(j=>j.decision).length,waiting=data.jobs.length-done;let pending=data.requests.filter(r=>(['pending','running','interrupted','blocked_dependency'].includes(r.status)||(r.status==='failed'&&r.attempts<3))).length;$('#totalCount').textContent=data.jobs.length;$('#doneCount').textContent=done;$('#requestCount').textContent=pending;$('#waitingBadge').textContent=waiting;$('#completedBadge').textContent=done;$('#regenBadge').textContent=data.requests.length;$('#updated').textContent='최근 갱신 '+new Date(data.updated).toLocaleString('ko-KR');$('#connection').textContent='연결됨 · 자동 저장';let other=(data.claims||[]).filter(c=>!c.mine&&data.jobs.some(j=>j.id===c.job_id&&!j.decision)).length;$('#teamStatus').textContent=`검수 대기 ${waiting}장 · 다른 사람이 검수 중 ${other}장 · 각자 다른 이미지를 받습니다.`;}
async function refresh(render=true){data=await api('/api/catalog');updateCounts();if(render)await renderTab();}
function matches(j){let f=filters(),search=f.search.trim().toLowerCase();return (f.category==='all'||j.category===f.category)&&(f.cohort==='all'||(f.cohort==='face_closeup'?j.composition==='tight_face_closeup':f.cohort==='user'?(j.person_id==='U01'||j.face_origin==='user_provided_reference'):f.cohort==='original'?j.cohort==='original'&&j.person_id!=='U01':j.cohort===f.cohort))&&(!search||`${j.product} ${j.person_id}`.toLowerCase().includes(search));}
let buffer=[],bufferDetails=new Map(),batchPromise=null,batchEpoch=0,lastBatch=null;
const preloaded=new Map();let prefetchRunning=0,prefetchURLs=[];
function pumpPreloads(){while(prefetchRunning<2){let url=prefetchURLs.find(u=>!preloaded.has(u));if(!url)break;let img=new Image();preloaded.set(url,img);prefetchRunning++;img.onload=img.onerror=()=>{prefetchRunning--;pumpPreloads();};img.src=url;}}
function mergeJobs(jobs){let map=new Map(data.jobs.map(j=>[j.id,j]));jobs.forEach(j=>map.set(j.id,j));data.jobs=[...map.values()];}
function prefetchImages(){prefetchURLs=buffer.flatMap(id=>[`/api/image?id=${id}`,`/api/image?id=${id}&which=source`]);let keep=new Set(prefetchURLs);for(let url of preloaded.keys())if(!keep.has(url))preloaded.delete(url);pumpPreloads();}
async function fetchBatch(preferred=null){
 if(batchPromise)return batchPromise;
 let epoch=batchEpoch;
 batchPromise=api('/api/batch',{reviewer:reviewer(),filters:filters(),preferred}).then(result=>{
  if(epoch!==batchEpoch)return result;
  lastBatch=result;buffer=result.ids;mergeJobs(result.jobs);for(let [id,detail] of Object.entries(result.details))bufferDetails.set(id,detail);leaseExpires=result.expires;prefetchImages();return result;
 }).finally(()=>{batchPromise=null;});
 return batchPromise;
}
async function release(){
 if(batchPromise)await batchPromise.catch(()=>{});
 let id=current?.id||buffer[0];if(id)await api('/api/release',{id,all_reserved:true});
 batchEpoch++;buffer=[];bufferDetails.clear();prefetchURLs=[];preloaded.clear();owned=false;leaseExpires=0;
}
async function claimNext(skip=null,preferred=null){if(busy)return;if(!reviewer()){current=null;owned=false;$('#workspace').hidden=true;$('#quickbar').hidden=true;$('#empty').hidden=false;$('#empty').textContent='각자 자기 이름을 선택하고 검수 시작을 누르세요. 서로 다른 이미지를 자동으로 받습니다.';$('#teamName').focus();return;}
 busy=true;controls();try{
  await flush();if(batchPromise)await batchPromise;
  if(skip){await api('/api/release',{id:skip});buffer=buffer.filter(id=>id!==skip);bufferDetails.delete(skip);}
  if(!buffer.length||leaseExpires*1000<=Date.now()||(preferred&&!buffer.includes(preferred)))await fetchBatch(preferred);
  let id=preferred&&buffer.includes(preferred)?preferred:buffer[0];owned=!!id;lastActivity=Date.now();
  if(!id){current=null;$('#workspace').hidden=true;$('#quickbar').hidden=true;$('#empty').hidden=false;$('#empty').textContent=lastBatch?.busy?'남은 이미지를 다른 검수자들이 보고 있습니다. 잠시 뒤 다음 이미지 받기를 눌러 주세요.':'이 조건에 해당하는 검수 대기 이미지가 없습니다.';return;}
  let j=data.jobs.find(j=>j.id===id);if(!j)throw new Error('배정한 이미지를 불러오지 못했습니다. 다시 시도하세요.');
  data.claims=(data.claims||[]).filter(c=>!c.mine);data.claims.push({job_id:id,reviewer:reviewer(),mine:true,expires:leaseExpires});updateCounts();
  list=[j];index=0;await show(0);$('#resultImage').tabIndex=0;$('#resultImage').focus({preventScroll:true});$('#product').scrollIntoView({block:'start'});$('#status').textContent=lastBatch?.priority_message||'이 이미지는 나에게 배정됐습니다. 판정하면 저장하고 다음으로 넘어갑니다.';
  if(buffer.length<=5)fetchBatch().catch(e=>{$('#connection').textContent='다음 묶음 재시도 대기';});
 }finally{busy=false;controls();}}
async function setTab(next){if(busy)return;await flush();await release();tab=next;current=null;$('#status').textContent='';$('#submitError').textContent='';$$('[data-tab]').forEach(b=>b.classList.toggle('selected',b.dataset.tab===tab));await refresh(false);await renderTab();}
async function renderTab(preferred){$('#workspace').hidden=true;$('#quickbar').hidden=true;$('#requestList').hidden=true;$('#faceGrid').hidden=true;$('#empty').hidden=true;$('#position').textContent='';if(tab==='regeneration'){renderRequests();return;}if(tab==='faces'){renderFaces();return;}if(tab==='waiting'){await claimNext(null,preferred);return;}
 list=data.jobs.filter(j=>matches(j)&&j.decision);if(!list.length){current=null;$('#empty').hidden=false;$('#empty').textContent='아직 완료된 검수가 없습니다. 저장한 판정은 이 공간에 모입니다.';return;}index=Math.max(0,list.findIndex(j=>j.id===(preferred||current?.id)));await show(index);}
async function show(i){current=list[Math.max(0,Math.min(i,list.length-1))];index=i;let j=current;loading=true;controls();$('#workspace').hidden=false;$('#empty').hidden=true;$('#product').textContent=j.product;$('#categoryBadge').textContent=j.category==='A'?'카메라가 있는 안경':j.category==='C'?'스마트 안경 · 카메라 없음':'일반 안경';$('#modelType').textContent=j.category==='A'?'AI 안경 · 카메라 있음':j.category==='B'?'일반 안경 · 카메라 없음':j.category==='C'?'스마트 안경 · 카메라 없음':'종류 확인 필요';$('#modelType').classList.toggle('camera-model',j.category==='A');$('#metadata').textContent=`사진 번호 ${j.number} · ${j.person_id} · ${poseNames[j.pose]||j.pose} · ${j.cohort==='korean_students_v1'?'새로 추가한 대학생':j.face_origin==='user_provided_reference'?'제공한 실제 얼굴을 참고한 인물':'기존 가상 인물'} · ${j.id.slice(0,8)}`;$('#position').textContent=tab==='waiting'?'나에게 배정한 1장':`완료 목록 ${index+1} / ${list.length}`;$('#resultLabel').textContent=j.decision==='hold'&&data.requests.some(r=>r.parent_job===j.id)?'재생성 요청 · 보류':j.decision?decisionNames[j.decision]:'검수 전';$('#prev').hidden=tab==='waiting';$('#next').hidden=tab==='waiting';$('#prev').disabled=i===0;$('#next').disabled=i===list.length-1;
 $('#resultImage').src=`/api/image?id=${j.id}`;initSourceViews(j);$('#portraitImage').src=`/api/image?id=${j.id}&which=portrait`;$('#evidence').href=/^https:\/\//.test(j.evidence)?j.evidence:'#';$('#origin').textContent=j.face_origin==='user_provided_reference'?'사용자가 제공한 실제 얼굴을 참고한 생성 이미지입니다.':'실제 인물을 지정하지 않고 생성한 성인 인물입니다.';$('#generationInfo').textContent=`인물 ID: ${j.person_id} · 시드: ${j.seed} · 생성 단계: ${j.steps}`;
 $('#reviewer').value=reviewer();$('#comment').value='';$('#notes').value='';$('#targetPerson').value='';$('#reason').value='camera';$('#useDetails').checked=false;$('#checklist').hidden=true;$('#regenOptions').open=false;$$('[data-check]').forEach(x=>x.value='unknown');$('#submitError').textContent='';$('#history').replaceChildren();selectedVersion=j.version;$('#saveState').textContent='불러오는 중';let key=j.id;location.hash=key;
 try{let detail=tab==='waiting'&&bufferDetails.has(key)?bufferDetails.get(key):await api(`/api/detail?id=${key}`);if(current?.id!==key)return;selectedVersion=detail.version;let v=detail.draft||(j.decision?j:null);if(v){$('#comment').value=v.comment||'';$$('[data-check]').forEach((x,k)=>x.value=v.checks?.[k]||'unknown');$('#reason').value=v.reason||'camera';$('#notes').value=v.notes||'';$('#targetPerson').value=v.target_person||'';$('#useDetails').checked=v.mode==='detailed';$('#checklist').hidden=!$('#useDetails').checked;}$('#saveState').textContent=owned?(detail.draft?'저장된 초안':'간편 검수'):'저장된 판정';for(let h of detail.history){let a=document.createElement('article'),b=document.createElement('b'),p=document.createElement('p'),small=document.createElement('small');b.textContent=`${decisionNames[h.decision]} · ${h.reviewer} · ${h.method==='quick'?'종합 판정':'상세 판정'}`;p.textContent=h.comment||'별도 의견 없음';small.textContent=new Date(h.updated).toLocaleString('ko-KR');a.append(b,p,small);$('#history').append(a);}if(!detail.history.length)$('#history').textContent='아직 저장된 판정이 없습니다.';
 }finally{loading=false;dirty=false;controls();}}
async function openNumberedJob(job){
 if(busy||loading||nameChanging)return;
 await flush();await release();current=null;
 $('#category').value='all';$('#cohort').value='all';$('#search').value='';
 tab=job.decision?'completed':'waiting';$$('[data-tab]').forEach(b=>b.classList.toggle('selected',b.dataset.tab===tab));
 $('#submitError').textContent='';$('#status').textContent='';
 await renderTab(job.id);
 if(current?.id===job.id){$('#jumpNumber').value=job.number;$('#jumpMessage').textContent=job.decision?`사진 번호 ${job.number} · 판정 수정하기를 누르면 바꿀 수 있습니다.`:`사진 번호 ${job.number}`;$('#product').scrollIntoView({block:'start'});}
}
async function jumpToNumber(number){
 if(busy||loading||nameChanging||jumpBusy)return;
 if(!Number.isSafeInteger(number)||number<1){$('#jumpMessage').textContent='사진 번호를 1 이상의 정수로 입력해 주세요.';return;}
 jumpBusy=true;controls();try{
 await refresh(false);const job=data.jobs.find(j=>j.number===number);
 if(!job){$('#jumpMessage').textContent=`사진 번호 ${number}는 현재 검수 목록에 없습니다. 보관되거나 제외된 사진일 수 있습니다.`;return;}
 if(!job.decision){$('#jumpMessage').textContent='이 사진은 아직 검수되지 않았습니다. 검수 대기에서 배정받아 주세요.';return;}
 await openNumberedJob(job);
 }finally{jumpBusy=false;controls();}
}
async function returnToLastReview(){
 if(busy||loading||nameChanging||jumpBusy)return;
 if(!reviewer()){$('#jumpMessage').textContent='먼저 검수자 이름을 선택해 주세요.';$('#teamName').focus();return;}
 jumpBusy=true;controls();try{
 await refresh(false);const last=data.last_reviewed?.[reviewer()];
 if(!last){$('#jumpMessage').textContent=`${reviewer()} 님이 검수한 사진을 찾지 못했습니다.`;return;}
 const job=data.jobs.find(j=>j.id===last.id);
 if(job)await openNumberedJob(job);else $('#jumpMessage').textContent='마지막 검수 사진은 현재 목록에서 제외되었습니다.';
 }finally{jumpBusy=false;controls();}
}
$('#jumpForm').onsubmit=e=>{e.preventDefault();jumpToNumber(Number($('#jumpNumber').value)).catch(showError);};
$('#lastReviewed').onclick=()=>returnToLastReview().catch(showError);
async function editCompleted(){if(!current||busy||jumpBusy)return;if(!reviewer()){showError(new Error('먼저 이름이나 별명을 입력하세요.'));$('#teamName').focus();return;}busy=true;controls();try{let result=await api('/api/claim',{reviewer:reviewer(),preferred:current.id,completed:true});owned=!!result.id;leaseExpires=result.expires;lastActivity=Date.now();await show(index);}finally{busy=false;controls();}}
async function submit(decision){if(!current||busy||loading||!owned)return;if(!$('#sourceImage').complete||!$('#sourceImage').naturalWidth||!$('#resultImage').complete||!$('#resultImage').naturalWidth){showError(new Error('이미지가 아직 로딩 중입니다.'));return;}if(decision==='regenerate'&&!$('#regenOptions').open){$('#regenOptions').open=true;$('#reason').focus();$('#regenOptions').scrollIntoView({block:'center',behavior:'smooth'});$('#status').textContent='다시 만들 부분을 고른 뒤 요청하세요. Ctrl+Enter로도 접수할 수 있습니다.';return;}
 busy=true;controls();let value=snapshot();value.decision=decision;value.version=selectedVersion;try{await flush();if(batchPromise)await batchPromise;let result=await api('/api/submit',value);if(result.review_stats)data.review_stats=result.review_stats;if(result.dataset_stats)data.dataset_stats=result.dataset_stats;if(result.last_reviewed)data.last_reviewed=result.last_reviewed;let old=current.id;$('#jumpMessage').textContent=`방금 검수한 사진 번호 ${current.number}`;Object.assign(current,{decision:decision==='regenerate'?'hold':decision,reviewer:value.reviewer,comment:value.comment,checks:value.checks,version:result.version,updated:new Date().toISOString()});data.jobs=data.jobs.map(j=>j.id===old?{...j,...current}:j);buffer=buffer.filter(id=>id!==old);bufferDetails.delete(old);dirty=false;owned=false;current=null;data.claims=(data.claims||[]).filter(c=>!c.mine);updateCounts();tab='waiting';$$('[data-tab]').forEach(b=>b.classList.toggle('selected',b.dataset.tab===tab));$('#status').textContent=decision==='exclude'?'제외 판정을 저장하고 재생성을 요청했습니다. 다음 이미지를 받습니다.':'저장했습니다. 다음 이미지를 받습니다.';busy=false;await renderTab();}catch(e){if(e.status===409){buffer=[];bufferDetails.clear();leaseExpires=0;owned=false;dirty=false;saving=Promise.resolve();}showError(e);}finally{busy=false;controls();}}
async function skip(){if(busy)return;let key=current?.id;await claimNext(key);}
function zoom(img,canvas,x=.5,y=.5){if(!img.naturalWidth)return;let ctx=canvas.getContext('2d'),w=img.naturalWidth,h=img.naturalHeight,cw=w*.27,ch=Math.min(h*.27,cw*canvas.height/canvas.width),sx=Math.max(0,Math.min(w-cw,w*x-cw/2)),sy=Math.max(0,Math.min(h-ch,h*y-ch/2));ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(img,sx,sy,cw,ch,0,0,canvas.width,canvas.height);}
[['sourceImage','sourceZoom'],['resultImage','resultZoom']].forEach(([a,b])=>{let img=$('#'+a),canvas=$('#'+b);img.onload=()=>zoom(img,canvas,.5,a==='sourceImage'?.5:.42);img.addEventListener('click',e=>{let rect=img.getBoundingClientRect(),scale=Math.min(rect.width/img.naturalWidth,rect.height/img.naturalHeight),w=img.naturalWidth*scale,h=img.naturalHeight*scale,x=(e.clientX-rect.left-(rect.width-w)/2)/w,y=(e.clientY-rect.top-(rect.height-h)/2)/h;if(x>=0&&x<=1&&y>=0&&y<=1)zoom(img,canvas,x,y);});});
function renderRequests(){let root=$('#requestList');root.replaceChildren();root.hidden=false;let rows=data.requests.filter(r=>{let j=data.jobs.find(x=>x.id===r.parent_job);return j&&matches(j);});if(!rows.length){$('#empty').hidden=false;$('#empty').textContent='아직 재생성 요청이 없습니다. 검수 중에 다시 만들 부분을 지정해 주세요.';return;}let names={pending:'대기 중',running:'생성 중',success:'생성 완료 · 새 검수 필요',failed:'생성 실패',interrupted:'다시 시도 대기',blocked_dependency:'기준 이미지 확인 필요',waiting_reference:'펴진 안경 참고 사진 대기',excluded_by_scope:'사용자가 생성 대상에서 제외한 제품'};for(let r of rows){let parent=data.jobs.find(x=>x.id===r.parent_job),card=document.createElement('article');card.className='request-card';let img=new Image();img.src=`/api/image?id=${r.status==='success'?r.child_job:r.parent_job}`;img.alt='재생성 결과 또는 요청한 원래 이미지';let info=document.createElement('div');info.className='request-info';let h=document.createElement('h3');h.textContent=parent?.product||r.parent_job;let p=document.createElement('p');p.textContent=`${r.status==='failed'&&r.attempts<3?'재시도 대기':names[r.status]||r.status} · ${reasons[r.reason]} · ${r.reviewer}`;let notes=document.createElement('p');notes.textContent=r.notes||'추가 요청 없음';info.append(h,p,notes);let button=document.createElement('button');button.textContent=r.status==='success'?'새 결과 검수':'원래 결과 보기';button.onclick=async()=>{let key=r.status==='success'?r.child_job:r.parent_job;let j=data.jobs.find(x=>x.id===key);await setTab(j?.decision?'completed':'waiting');await renderTab(key);};card.append(img,info,button);root.append(card);}}
function renderFaces(){let root=$('#faceGrid');root.hidden=false;root.replaceChildren();let note=document.createElement('p');note.className='face-note';note.textContent=`대학생 분위기의 가상 인물과 사용자가 제공한 실제 인물을 구분해 관리합니다. 현재 기준 얼굴은 ${data.portraits.length}개입니다. 착용 이미지는 순서대로 검수 대기에 추가됩니다.`;root.append(note);for(let p of data.portraits){let card=document.createElement('article');card.className='face-card';let img=new Image();img.src=`/api/image?id=${p.id}`;img.alt=p.person_id+'의 새로운 얼굴';let div=document.createElement('div'),h=document.createElement('h3'),t=document.createElement('p');h.textContent=p.person_id+' · '+(p.face_origin==='user_provided_reference'?'사용자가 제공한 실제 인물':(Number(p.person_id.slice(1))<=8?Number(p.person_id.slice(1))<=4:Number(p.person_id.slice(1))%2===1)?'남성':'여성');let hairs={K01:'짧은 투블록과 자연스러운 앞머리',K02:'6:4 가르마와 쉼표 모양의 앞머리',K03:'짧은 머리와 가벼운 앞머리',K04:'자연스러운 가운데 가르마',K05:'긴 레이어드 머리와 C컬',K06:'어깨 길이의 머리와 가벼운 앞머리',K07:'턱 길이의 단발과 옆 가르마',K08:'낮게 묶은 머리와 옆 가르마'};t.textContent=p.face_origin==='user_provided_reference'?'추가한 사진의 얼굴과 구도를 기준으로 사용합니다.':hairs[p.person_id]||'피부 톤과 머리 모양과 옷깃을 다양하게 구성한 가상 인물입니다.';div.append(h,t);card.append(img,div);root.append(card);}}
function showError(e){$('#status').textContent=e.message;$('#submitError').textContent=e.message;}
$$('[data-tab]').forEach(b=>b.onclick=()=>setTab(b.dataset.tab).catch(showError));
$('#startReview').onclick=async()=>{try{localStorage.setItem('glassesReviewer',reviewer());if(tab!=='waiting')await setTab('waiting');else await claimNext();}catch(e){showError(e);}};
$('#nextClaim').onclick=()=>skip().catch(showError);$('#editReview').onclick=()=>editCompleted().catch(showError);
$('#prev').onclick=async()=>{try{await flush();await release();await show(Math.max(0,index-1));}catch(e){showError(e);}};
$('#next').onclick=async()=>{try{await flush();await release();await show(Math.min(list.length-1,index+1));}catch(e){showError(e);}};
$('#refresh').onclick=async()=>{try{await flush();await refresh();}catch(e){showError(e);}};
$$('[data-decision]').forEach(b=>b.onclick=()=>submit(b.dataset.decision));
let searchTimer;['category','cohort'].forEach(id=>$('#'+id).onchange=async()=>{try{await flush();await release();current=null;await renderTab();}catch(e){showError(e);}});
$('#search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(async()=>{try{await flush();await release();current=null;await renderTab();}catch(e){showError(e);}},400);};
['comment','reason','notes','targetPerson'].forEach(id=>$('#'+id).addEventListener('input',scheduleSave));$$('[data-check]').forEach(x=>x.onchange=scheduleSave);
$('#useDetails').onchange=()=>{$('#checklist').hidden=!$('#useDetails').checked;scheduleSave();};
for(const name of window.reviewSettings.reviewers) $('#teamName').add(new Option(name,name));
$('#teamName').value=window.reviewSettings.reviewers.includes(localStorage.getItem('glassesReviewer'))?localStorage.getItem('glassesReviewer'):'';$('#teamName').addEventListener('keydown',e=>{if(e.key==='Enter')$('#startReview').click();});
['pointerdown','keydown','wheel','touchstart'].forEach(type=>document.addEventListener(type,()=>{lastActivity=Date.now();},{passive:true}));
$('#teamName').addEventListener('change',async()=>{nameChanging=true;controls();try{await flush();await release();current=null;localStorage.setItem('glassesReviewer',reviewer());await refresh(false);if(tab==='waiting')await renderTab();}catch(e){showError(e);}finally{nameChanging=false;controls();}});
document.addEventListener('keydown',e=>{if(e.repeat||e.isComposing||busy||loading||jumpBusy)return;let editable=e.target.closest('input,textarea,select,[contenteditable="true"]');if((e.ctrlKey||e.metaKey)&&e.key==='Enter'&&owned&&$('#regenOptions').open){e.preventDefault();submit('regenerate');return;}if(editable||e.ctrlKey||e.metaKey||e.altKey)return;if(e.key==='Escape'){$('#regenOptions').open=false;return;}if(!current||!owned)return;let action={'1':'pass','2':'exclude','3':'hold','4':'regenerate'}[e.key];if(action){e.preventDefault();submit(action);}else if(e.key.toLowerCase()==='n'&&tab==='waiting'){e.preventDefault();skip().catch(showError);}});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
window.addEventListener('pagehide',()=>{if(owned&&current)fetch('/api/release',{method:'POST',headers:headers(),body:JSON.stringify({id:current.id,all_reserved:true}),keepalive:true}).catch(()=>{});});
document.addEventListener('visibilitychange',()=>{if(document.hidden&&dirty)flush().catch(showError);if(!document.hidden&&owned&&current)api('/api/heartbeat',{id:current.id,activity:lastActivity/1000}).then(r=>leaseExpires=r.expires).catch(e=>{owned=false;controls();showError(e);});});
(async()=>{let hash=location.hash.slice(1);await refresh(false);let j=data.jobs.find(x=>x.id===hash);if(j?.decision){tab='completed';$$('[data-tab]').forEach(b=>b.classList.toggle('selected',b.dataset.tab===tab));}await renderTab(hash);setInterval(async()=>{if(busy||loading||document.hidden)return;try{if(owned&&current){let r=await api('/api/heartbeat',{id:current.id,activity:lastActivity/1000});leaseExpires=r.expires;}await refresh(false);if(tab==='faces')renderFaces();if(tab==='regeneration')renderRequests();if(tab==='waiting'&&current){let latest=data.jobs.find(j=>j.id===current.id);if(!latest||latest.decision){dirty=false;owned=false;current=null;buffer=[];bufferDetails.clear();saving=Promise.resolve();await renderTab();}}}catch(e){if(e.status===409){owned=false;controls();}showError(e);}},30000);})().catch(showError);

function initSourceViews(j){
 $('#viewSide').hidden=!j.has_side_reference;
 $('#referenceSummary').textContent=j.has_side_reference?'생성 참고: 얼굴 1장 + 안경 2장. 정면과 옆면을 버튼으로 바꿔 볼 수 있습니다.':'생성 참고: 얼굴 1장 + 안경 1장. 이 결과는 정면 사진만 사용했습니다.';
 selectSourceView('front');
}
function selectSourceView(view){
 if(!current)return;
 if(view==='side'&&!current.has_side_reference)return;
 $('#viewFront').setAttribute('aria-pressed',String(view==='front'));
 $('#viewSide').setAttribute('aria-pressed',String(view==='side'));
 $('#sourceImage').alt=view==='front'?'생성에 사용한 실제 안경의 정면 사진':'생성에 사용한 실제 안경의 옆면 사진';
 $('#sourceImage').src=`/api/image?id=${current.id}&which=${view==='front'?'source':'side'}`;
}
$('#viewFront').onclick=()=>selectSourceView('front');
$('#viewSide').onclick=()=>selectSourceView('side');
