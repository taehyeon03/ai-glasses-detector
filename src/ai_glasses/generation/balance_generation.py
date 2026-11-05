"""Plan balanced human-approved training candidates; never judge or edit reviews."""
import collections,fcntl,json,math,sqlite3
from pathlib import Path
from ai_glasses.generation import tryon_lab as lab
from ai_glasses.generation.multiview_references import prompt_for_views,wearing_prompt
from ai_glasses.generation.face_framing import apply_condition

BATCH='balanced_classes_20261104'
SETTINGS='generation_balance_settings.json'
ACTIVE=('pending','interrupted','blocked_dependency','running')
POSES=('front','left_oblique','right_oblique','left_profile','right_profile')

def settings():
    path=lab.ROOT/SETTINGS
    return json.loads(path.read_text()) if path.exists() else None

def portraits(c):
    result={}
    for row in c.execute("SELECT * FROM jobs WHERE kind='portrait' AND status='success' ORDER BY rowid"):
        con=json.loads(row['condition']);person=con.get('person_id','');pose=con.get('pose')
        if not (person.startswith('K') or person in ('U01','U02','U03')) or pose not in POSES:continue
        if row['output'] and Path(row['output']).is_file():result[(person,pose)]=(dict(row),con)
    return result

def ready(c,row,valid_parents):
    con=json.loads(row['condition']);parent=con.get('portrait_job')
    if parent not in valid_parents:return False
    return row['status'] in ACTIVE or (row['status']=='failed' and row['attempts']<3)

def create_condition(source,parent,pc,ordinal):
    meta=json.loads(source['metadata'])
    con={key:pc[key] for key in ('model','revision','person_id','hair','skin_tone','clothing','pose','light','width','height','steps','kv_cache','cohort','face_origin','occlusion') if key in pc}
    con.update(model=lab.MODEL,revision=lab.REVISION,kind='tryon',width=1024,height=1024,steps=40,kv_cache=True,synthetic=True,portrait_job=parent['id'],source_id=source['id'],source_sha256=source['sha256'],product=source['product'],camera=source['camera'],batch=BATCH,protocol=BATCH,balance_category=source['category'],balance_ordinal=ordinal,seed=int(lab.uid([BATCH,source['id'],ordinal])[:8],16)%(2**31),open_temple_required=True,unseen_geometry='contralateral_structure_assumed_symmetric_when_not_shown',pose_verified=False)
    if meta.get('camera_count') is not None:con['camera_count']=meta['camera_count']
    camera=('This is camera-equipped eyewear. Preserve every visible real camera and distinguish indicator lights from camera apertures.' if source['category']=='A' else 'This product has ZERO cameras. Do not turn rivets, logos, microphones, display optics or status lights into cameras.')
    prompt=('Edit image 1. Preserve this exact adult identity, hairstyle, skin texture and requested head direction. Put only the physical glasses from image 2 onto the person. Preserve the exact frame and lens outline, dimensions, material, color, lens tint and opacity, bridge, nose support, hinge and temple design. '+camera+' Fit the unfolded frame naturally on the nose and behind the visible ears. Keep visible camera apertures and hinges unobscured. Do not add HUD overlays, extra glasses, text or comparison panels. '+meta.get('detail_prompt',''))
    if meta.get('extra_references'):
        con.update(extra_references=meta['extra_references'],reference_resolution=768,reference_count=2+len(meta['extra_references']))
        prompt=prompt_for_views(prompt,con['extra_references'])
    con['prompt']=wearing_prompt(prompt)
    return apply_condition(con)

def reconcile(c,config=None):
    config=config or settings()
    if not config or not config.get('enabled'):return None
    target=int(config['target_per_category']);reserve=float(config['reserve_multiplier'])
    with open(lab.ROOT/'public_review.lock','w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX);c.commit();c.execute('BEGIN IMMEDIATE')
        try:
            sources={}
            for row in c.execute("SELECT * FROM sources WHERE category IN ('A','B','C') ORDER BY rowid"):
                meta=json.loads(row['metadata'])
                if meta.get('selected') is False or meta.get('generation_excluded'):continue
                key=(row['category'],row['product']);old=sources.get(key)
                if old is None or bool(meta.get('extra_references'))>=bool(json.loads(old['metadata']).get('extra_references')):sources[key]=dict(row)
            groups={category:sorted([s for (cat,_),s in sources.items() if cat==category],key=lambda x:x['product']) for category in ('A','B','C')}
            pool=portraits(c);by_pose={pose:[v for (person,p),v in sorted(pool.items()) if p==pose] for pose in POSES}
            assert all(by_pose.values()),'Every requested pose needs a successful portrait'
            valid_parents={row['id'] for row,pc in pool.values()}
            counts={}
            for row in c.execute("SELECT s.category,s.product,r.decision,count(*) AS n FROM jobs j JOIN sources s ON s.id=json_extract(j.condition,'$.source_id') LEFT JOIN reviews r ON r.job_id=j.id WHERE j.kind='tryon' AND j.status='success' GROUP BY s.category,s.product,r.decision"):
                counts.setdefault((row['category'],row['product']),collections.Counter())[row['decision'] or 'unreviewed']+=row['n']
            queued=collections.defaultdict(list)
            for row in c.execute("SELECT j.*,s.category,s.product FROM jobs j JOIN sources s ON s.id=json_extract(j.condition,'$.source_id') WHERE j.kind='tryon' AND (j.status IN ('pending','interrupted','blocked_dependency','running') OR (j.status='failed' AND j.attempts<3)) ORDER BY j.rowid DESC"):
                if ready(c,row,valid_parents):queued[(row['category'],row['product'])].append(dict(row))
            categories={};products=[];created=[];assigned=[]
            for category,members in groups.items():
                assert members,'Missing category '+category
                base,remainder=divmod(target,len(members));summary=dict(target=target,models=len(members),covered_passed=0,passed=0,new_jobs=0,scheduled=0)
                for index,source in enumerate(members):
                    quota=base+(index<remainder);key=(category,source['product']);n=counts.get(key,collections.Counter());passed=n['pass'];reviewed=passed+n['exclude']+n['hold'];deficit=max(0,quota-passed)
                    # A 60% prior with 20 observations prevents trusting a 2/2 pass rate.
                    rate=max(.25,min(.85,(passed+12)/(reviewed+20)))
                    needed=math.ceil(deficit/rate*reserve) if deficit else 0
                    required=max(0,needed-n['unreviewed'])
                    active=queued.get(key,[]);reused=active[:required]
                    for ordinal,row in enumerate(reused):
                        c.execute('INSERT OR IGNORE INTO batch_jobs VALUES(?,?,?)',(BATCH,row['id'],ordinal*len(members)+index));assigned.append(row['id'])
                    missing=max(0,required-len(reused))
                    existing=c.execute("SELECT count(*) AS n,max(json_extract(condition,'$.balance_ordinal')) AS last FROM jobs WHERE json_extract(condition,'$.protocol')=? AND json_extract(condition,'$.source_id')=?",(BATCH,source['id'])).fetchone()
                    # A finite cap prevents an endless loop on an unfaithful product.
                    allowance=max(0,quota*6-existing['n']);missing=min(missing,allowance)
                    start=(existing['last'] or 0)+1
                    for ordinal in range(start,start+missing):
                        pose=POSES[(ordinal+index)%len(POSES)];options=by_pose[pose];parent,pc=options[(ordinal//len(POSES)+index)%len(options)]
                        con=create_condition(source,parent,pc,ordinal);job_id=lab.uid(con)
                        c.execute('INSERT OR IGNORE INTO jobs(id,kind,condition) VALUES(?,?,?)',(job_id,'tryon',json.dumps(con,ensure_ascii=False)))
                        c.execute('INSERT OR IGNORE INTO batch_jobs VALUES(?,?,?)',(BATCH,job_id,(len(reused)+ordinal)*len(members)+index));created.append(job_id);assigned.append(job_id)
                    summary['covered_passed']+=min(passed,quota);summary['passed']+=passed;summary['new_jobs']+=missing;summary['scheduled']+=len(reused)+missing
                    products.append(dict(category=category,product=source['product'],source_id=source['id'],quota=quota,passed=passed,unreviewed=n['unreviewed'],reviewed=reviewed,estimated_yield=round(rate,4),reserve_multiplier=reserve,reused_pending=len(reused),new_jobs=missing,planned_unreviewed_total=needed,needs_manual_attention=required>len(reused)+missing))
                categories[category]=summary
            # Prioritize categories with the least balanced, approved coverage.
            order=sorted(categories,key=lambda cat:(categories[cat]['covered_passed']/target,cat))
            for rank,category in enumerate(order):
                for row in c.execute("SELECT b.job_id,b.priority FROM batch_jobs b JOIN jobs j ON j.id=b.job_id JOIN sources s ON s.id=json_extract(j.condition,'$.source_id') WHERE b.batch=? AND s.category=?",(BATCH,category)).fetchall():
                    c.execute('UPDATE batch_jobs SET priority=? WHERE batch=? AND job_id=?',(rank*10000000+row['priority']%10000000,BATCH,row['job_id']))
            # Retain obsolete background work for rollback without reporting it as active.
            c.execute('CREATE TABLE IF NOT EXISTS balance_deferred_jobs(job_id TEXT PRIMARY KEY,previous_status TEXT,created TEXT)')
            deferred=c.execute("SELECT j.id,j.status FROM jobs j WHERE j.kind='tryon' AND j.status IN ('pending','interrupted','blocked_dependency','failed') AND NOT EXISTS(SELECT 1 FROM batch_jobs b WHERE b.batch=? AND b.job_id=j.id) AND NOT EXISTS(SELECT 1 FROM regeneration_requests r WHERE r.child_job=j.id)",(BATCH,)).fetchall()
            for row in deferred:
                c.execute('INSERT OR IGNORE INTO balance_deferred_jobs VALUES(?,?,?)',(row['id'],row['status'],lab.now()))
                c.execute("UPDATE jobs SET status='deferred_balance',error='Deferred by the user-requested balanced generation plan; original state retained in balance_deferred_jobs' WHERE id=?",(row['id'],))
            c.execute('INSERT OR IGNORE INTO batches VALUES(?,?,?,?,?)',(BATCH,lab.now(),None,'prepared',json.dumps(config,ensure_ascii=False)))
            report=dict(updated=lab.now(),batch=BATCH,config=config,categories=categories,products=products,category_priority=order,created_this_pass=len(created),assigned_this_pass=len(assigned),deferred_this_pass=len(deferred),human_review_required=True)
            c.commit()
        except Exception:c.rollback();raise
    (lab.ROOT/lab.FOLDERS[9]/'balanced_generation_plan.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    selection={category:[] for category in ('A','B','C')}
    for product in products:
        rows=c.execute("SELECT j.id,j.condition FROM jobs j JOIN reviews r ON r.job_id=j.id JOIN sources s ON s.id=json_extract(j.condition,'$.source_id') WHERE j.kind='tryon' AND j.status='success' AND r.decision='pass' AND s.category=? AND s.product=? ORDER BY j.rowid DESC",(product['category'],product['product'])).fetchall()
        candidates=[(dict(r),json.loads(r['condition'])) for r in rows];people=collections.Counter();poses=collections.Counter()
        for index in range(min(product['quota'],len(candidates))):
            best=min(range(len(candidates)),key=lambda i:(people[candidates[i][1].get('person_id')],poses[candidates[i][1].get('pose')],i))
            row,con=candidates.pop(best);people[con.get('person_id')]+=1;poses[con.get('pose')]+=1
            selection[product['category']].append(dict(id=row['id'],product=product['product'],person_id=con.get('person_id'),pose=con.get('pose')))
    (lab.ROOT/lab.FOLDERS[9]/'balanced_approved_candidates.json').write_text(json.dumps(dict(updated=lab.now(),target_per_category=target,selection_type='Human-approved candidates, not a train/test split or training run',counts={key:len(value) for key,value in selection.items()},categories=selection),ensure_ascii=False,indent=2))
    return report

def next_batch(c):
    # Batch membership is the source of truth for scheduling, not a stale protocol.
    config=settings() or {}
    if config.get('mode')=='pilot':names=[config['active_batch']]
    elif config.get('enabled'):names=[BATCH,'unreviewed_reset_20261103','public_regeneration']
    else:names=['unreviewed_reset_20261103','k04_vanguard_rebuild_20261102','pose_preview_20261103','public_regeneration','camera_free_smart_20261103','diversity_20261102_v1','user_people_v1','korean_students_v1','overnight_10h']
    for batch in names:
        rows=c.execute("SELECT j.* FROM jobs j JOIN batch_jobs b ON b.job_id=j.id WHERE b.batch=? AND j.attempts<3 AND j.status IN ('pending','interrupted','blocked_dependency','failed') ORDER BY b.priority",(batch,)).fetchall()
        for row in rows:
            con=json.loads(row['condition']);parent_id=con.get('portrait_job') or con.get('portrait_parent')
            if not parent_id:return batch
            parent=c.execute('SELECT status,output FROM jobs WHERE id=?',(parent_id,)).fetchone()
            if parent and parent['status']=='success' and parent['output'] and Path(parent['output']).is_file():return batch
    return None

def prepare():
    from ai_glasses.review import public_review_store as store
    c=lab.connect();store.init(c)
    backup=lab.ROOT/'work'/('before_balancing_'+lab.now().replace(':','-')+'.sqlite')
    with sqlite3.connect(backup) as dst:c.backup(dst)
    config=dict(enabled=True,target_per_category=500,reserve_multiplier=1.25,created=lab.now(),basis='Human-approved training selection quotas; preserve surplus and all reviews; no AI judging; 60% prior shrunk toward observed per-product yield',max_new_per_product_multiplier=6)
    path=lab.ROOT/SETTINGS
    if path.exists():config=json.loads(path.read_text())
    else:path.write_text(json.dumps(config,ensure_ascii=False,indent=2))
    report=reconcile(c,config);lab.export(c)
    print(json.dumps({key:report[key] for key in ('categories','category_priority','created_this_pass','assigned_this_pass')},ensure_ascii=False))

if __name__=='__main__':prepare()
