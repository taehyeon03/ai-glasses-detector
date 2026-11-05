"""Durable collaborative review and regeneration outbox."""
import contextlib
import fcntl
import json
from ai_glasses.config import PRIORITY_REVIEWER
from pathlib import Path
import shutil
import uuid
import time
from ai_glasses.generation import tryon_lab as lab

class Conflict(ValueError): pass
ARCHIVE='11_검수완료'
REASONS={'folded':'다리가 접힌 채 얼굴에 붙음','camera':'카메라의 개수나 위치','frame':'프레임의 모양이나 색','lens':'렌즈의 색이나 투명도','fit':'착용 위치','face':'얼굴이나 머리 모양','pose':'얼굴의 방향','other':'기타'}
def init(c):
    (lab.ROOT/ARCHIVE).mkdir(exist_ok=True)
    c.executescript('''
    CREATE TABLE IF NOT EXISTS review_drafts(job_id TEXT,session TEXT,data TEXT,updated TEXT,PRIMARY KEY(job_id,session));
    CREATE TABLE IF NOT EXISTS regeneration_requests(id TEXT PRIMARY KEY,parent_job TEXT,child_job TEXT UNIQUE,reason TEXT,notes TEXT,reviewer TEXT,session TEXT,created TEXT);
    CREATE TABLE IF NOT EXISTS review_claims(job_id TEXT PRIMARY KEY,owner TEXT UNIQUE,reviewer TEXT,expires REAL);
    CREATE TABLE IF NOT EXISTS review_methods(event_id INTEGER PRIMARY KEY,method TEXT,owner TEXT);
    CREATE TABLE IF NOT EXISTS review_pool(job_id TEXT PRIMARY KEY,owner TEXT,reviewer TEXT,expires REAL,position INTEGER);
    CREATE INDEX IF NOT EXISTS pool_owner ON review_pool(owner,position);
    CREATE TABLE IF NOT EXISTS review_pool_settings(owner TEXT PRIMARY KEY,filters TEXT);
    CREATE INDEX IF NOT EXISTS regen_parent ON regeneration_requests(parent_job);
    CREATE TABLE IF NOT EXISTS review_item_numbers(number INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL UNIQUE);
    ''');c.commit()

def ensure_numbers(c):
    c.execute("INSERT OR IGNORE INTO review_item_numbers(job_id) SELECT j.id FROM jobs j LEFT JOIN review_item_numbers n ON n.job_id=j.id WHERE j.kind='tryon' AND j.output IS NOT NULL AND n.job_id IS NULL ORDER BY j.rowid")
    c.commit()

def last_reviewed(c):
    ensure_numbers(c);result={}
    rows=c.execute("SELECT e.reviewer,e.job_id,e.updated,n.number FROM review_events e JOIN jobs j ON j.id=e.job_id JOIN review_item_numbers n ON n.job_id=j.id WHERE j.kind='tryon' AND j.status='success' ORDER BY e.id DESC")
    for row in rows:
        if row['reviewer'] not in result:result[row['reviewer']]=dict(id=row['job_id'],number=row['number'],updated=row['updated'])
    return result

def version(c,key):return c.execute('SELECT coalesce(max(id),0) FROM review_events WHERE job_id=?',(key,)).fetchone()[0]

def valid_job(c,key):
    j=c.execute("SELECT * FROM jobs WHERE id=? AND kind='tryon' AND status='success'",(key,)).fetchone()
    if not j:raise ValueError('검수할 수 있는 생성 결과가 아닙니다.')
    return j

def clean(d):
    reviewer=str(d.get('reviewer','')).strip();comment=str(d.get('comment','')).strip();checks=d.get('checks')
    if not reviewer or len(reviewer)>60:raise ValueError('검수자 이름은 1~60자로 입력하세요.')
    if len(comment)>1500:raise ValueError('의견은 1500자 이내로 입력하세요.')
    if not isinstance(checks,list) or len(checks)!=6 or any(x not in ('yes','no','unknown','na') for x in checks):raise ValueError('검수 항목 6개를 확인하세요.')
    return reviewer,comment,checks

def draft(c,key,session,data):
    valid_job(c,key)
    reviewer=str(data.get('reviewer',''))[:60];comment=str(data.get('comment',''))[:1500]
    checks=data.get('checks',['unknown']*6)
    if len(checks)!=6 or any(x not in ('yes','no','unknown','na') for x in checks):raise ValueError('검수 항목을 확인하세요.')
    value=dict(reviewer=reviewer,comment=comment,checks=checks,reason=str(data.get('reason','other'))[:30],notes=str(data.get('notes',''))[:1000],target_person=str(data.get('target_person',''))[:10],mode='quick' if data.get('mode')=='quick' else 'detailed')
    c.execute('INSERT INTO review_drafts VALUES(?,?,?,?) ON CONFLICT(job_id,session) DO UPDATE SET data=excluded.data,updated=excluded.updated',(key,session,json.dumps(value,ensure_ascii=False),lab.now()));c.commit()
    return dict(ok=True,saved_at=lab.now())

def enqueue_regeneration(c,key,con,reason,notes,target_person,reviewer,session):
    request_id=uuid.uuid4().hex
    new=dict(con);new.update(regeneration_of=key,regeneration_request=request_id,regeneration_reason=reason,regeneration_notes=notes,seed=int(uuid.uuid4().hex[:8],16)%(2**31),batch='public_regeneration',protocol='public_review_v1')
    fixes={'folded':'Open both real hinges and place the unfolded temples along the sides of the head and behind the ears. Never place folded temples across the face. Use the open product-side reference for the temple geometry.','camera':'Match the exact number, positions and sizes of the real cameras visible in image 2. Preserve separate indicator lights as lights.','frame':'Preserve the manufactured shape, thickness, dimensions, material and color of the physical frame in image 2.','lens':'Preserve the exact lens tint and opacity in image 2. Opaque dark lenses must remain opaque.','fit':'Fit the frame correctly on the nose and behind both ears. Preserve physical scale.','face':'Preserve the exact adult identity and hairstyle from image 1. Do not change facial anatomy.','pose':'Preserve the precise head direction and camera view of image 1.','other':'Inspect both reference images carefully and correct the mismatch while preserving the real product.'}
    target_person=str(target_person or '')
    if target_person:
        parent=c.execute("SELECT id,condition FROM jobs WHERE kind='portrait' AND json_extract(condition,'$.cohort') IN ('korean_students_v1','user_people_v1') AND json_extract(condition,'$.person_id')=? AND (json_extract(condition,'$.pose')='front' OR json_extract(condition,'$.cohort')='user_people_v1') ORDER BY rowid DESC LIMIT 1",(target_person,)).fetchone()
        if not parent:raise ValueError('변경할 얼굴을 찾을 수 없습니다.')
        pc=json.loads(parent['condition']);new.update(portrait_job=parent['id'],person_id=pc['person_id'],hair=pc['hair'],pose=pc['pose'],light=pc['light'],cohort=pc['cohort'],face_origin=pc.get('face_origin','fictional_generated'),target_person=target_person)
    new['base_prompt']=con.get('base_prompt',con['prompt'].split(' Correction requested after human review: ')[0])
    new['prompt']=new['base_prompt']+' Correction requested after human review: '+fixes[reason]+(' Reviewer feedback: '+notes if notes else '')
    source=c.execute('SELECT * FROM sources WHERE id=?',(new['source_id'],)).fetchone()
    source_meta=json.loads(source['metadata']) if source else {}
    if source_meta.get('selected') is False:
        replacement=c.execute("SELECT * FROM sources WHERE product=? AND json_extract(metadata,'$.selected')=1 ORDER BY rowid DESC LIMIT 1",(new['product'],)).fetchone()
        if replacement:
            replacement_meta=json.loads(replacement['metadata'])
            old_detail=source_meta.get('detail_prompt','')
            if old_detail:
                new['base_prompt']=new['base_prompt'].replace(old_detail,replacement_meta.get('detail_prompt',old_detail))
                new['prompt']=new['prompt'].replace(old_detail,replacement_meta.get('detail_prompt',old_detail))
            new.update(source_id=replacement['id'],source_sha256=replacement['sha256'])
            source_meta=replacement_meta
    if new.get('person_id')=='K04':
        closeup=c.execute("SELECT id FROM jobs WHERE kind='portrait' AND status='success' AND json_extract(condition,'$.person_id')='K04' AND json_extract(condition,'$.protocol')='korean_students_facecrop_v3' ORDER BY rowid DESC LIMIT 1").fetchone()
        if closeup:new['portrait_job']=closeup['id']
    if source_meta.get('extra_references'):
        from ai_glasses.generation.multiview_references import prompt_for_views
        new.update(extra_references=source_meta['extra_references'],reference_resolution=source_meta.get('reference_resolution',768),reference_count=2+len(source_meta['extra_references']))
        new['prompt']=prompt_for_views(new['prompt'],new['extra_references'])
    new['composition']='tight_face_closeup'
    new['prompt']+=' Final composition requirement: create a tight face close-up. Show the whole forehead, hair, face, chin, both ears and complete glasses, with the face filling most of the square. End the frame just below the chin. No shoulders, chest, torso, arms or hands.'
    from ai_glasses.generation.multiview_references import wearing_prompt
    new['prompt']=wearing_prompt(new['prompt']);new['open_temple_required']=True
    from ai_glasses.generation.face_framing import apply_condition
    new.pop('face_framing_version',None)
    new=apply_condition(new)
    child=lab.uid(new)
    c.execute('INSERT INTO jobs(id,kind,condition) VALUES(?,?,?)',(child,'tryon',json.dumps(new,ensure_ascii=False)))
    if reason=='folded' and not new.get('extra_references'):
        c.execute("UPDATE jobs SET status='waiting_reference',error='펴진 다리가 보이는 같은 제품의 참고 사진이 필요합니다.' WHERE id=?",(child,))
    if source_meta.get('generation_excluded'):
        c.execute("UPDATE jobs SET status='excluded_by_scope',error=? WHERE id=?",(source_meta.get('generation_excluded_reason','사용자가 생성 대상에서 제외한 제품입니다.'),child))
    c.execute('INSERT INTO regeneration_requests VALUES(?,?,?,?,?,?,?,?)',(request_id,key,child,reason,notes,reviewer,session,lab.now()))
    return child,request_id

def submit(c,key,session,data,require_claim=False):
    reviewer,comment,checks=clean(data);action=data.get('decision')
    if action not in ('pass','exclude','hold','regenerate'):raise ValueError('판정을 선택하세요.')
    with open(lab.ROOT/'public_review.lock','w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        c.execute('BEGIN IMMEDIATE')
        try:
            j=valid_job(c,key);con=json.loads(j['condition'])
            if require_claim:assert_claim(c,key,session)
            if data.get('version')!=version(c,key):raise Conflict('다른 검수자가 먼저 저장했습니다. 최신 판정을 확인한 뒤 다시 저장하세요.')
            if not Path(j['output']).is_file() or (j['output_sha256'] and lab.digest(j['output'])!=j['output_sha256']):raise ValueError('이미지 파일을 확인해야 합니다.')
            if action=='pass' and data.get('mode')!='quick':
                needed=[0,1,3,4] if con['camera']=='present' else [2,3,4]
                if any(checks[i]!='yes' for i in needed) or checks[5]!='no':raise ValueError('통과하려면 필요한 항목을 예로 확인하고 가림은 아니오로 확인하세요.')
            child=None;request_id=None
            if action in ('regenerate','exclude'):
                reason=data.get('reason','other') if action=='regenerate' else 'other'
                raw_notes=str(data.get('notes','')).strip()
                if reason not in REASONS or len(raw_notes)>1000:raise ValueError('재생성 이유를 확인하세요.')
                notes='\n'.join(dict.fromkeys(part for part in (comment,raw_notes) if part))
                active=c.execute("SELECT r.id,r.child_job FROM regeneration_requests r JOIN jobs j ON j.id=r.child_job WHERE r.parent_job=? AND (j.status IN ('pending','running','interrupted','blocked_dependency','waiting_reference') OR (j.status='failed' AND j.attempts<3))",(key,)).fetchone()
                if active and action=='regenerate':raise Conflict('이 이미지의 재생성이 이미 접수돼 있습니다.')
                if active:
                    child,request_id=active['child_job'],active['id']
                else:
                    n=c.execute("SELECT count(*) FROM regeneration_requests r JOIN jobs j ON j.id=r.child_job WHERE j.status IN ('pending','running','interrupted','blocked_dependency') OR (j.status='failed' AND j.attempts<3)").fetchone()[0]
                    if n>=100 and action=='regenerate':raise ValueError('재생성 대기열이 가득 찼습니다. 잠시 후 다시 시도하세요.')
                    child,request_id=enqueue_regeneration(c,key,con,reason,notes,data.get('target_person',''),reviewer,session)
                comment=(comment+'\n'+('자동 재생성 요청: ' if action=='exclude' else '재생성 요청: ')+REASONS[reason]+(' / '+raw_notes if raw_notes else '')).strip()
            decision='hold' if action=='regenerate' else action
            when=lab.now();values=(key,decision,comment,json.dumps(checks),reviewer,when)
            c.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET decision=excluded.decision,comment=excluded.comment,checks=excluded.checks,reviewer=excluded.reviewer,updated=excluded.updated',values)
            event_id=c.execute('INSERT INTO review_events(job_id,decision,comment,checks,reviewer,updated) VALUES(?,?,?,?,?,?)',values).lastrowid
            c.execute('INSERT INTO review_methods VALUES(?,?,?)',(event_id,'quick' if data.get('mode')=='quick' else 'detailed',session))
            c.execute('DELETE FROM review_claims WHERE job_id=? AND owner=?',(key,session))
            c.execute('DELETE FROM review_pool WHERE job_id=? AND owner=?',(key,session))
            c.execute('DELETE FROM review_drafts WHERE job_id=? AND session=?',(key,session));c.commit()
        except Exception:c.rollback();raise
        reconcile(c)
    return dict(ok=True,version=version(c,key),child_job=child,request_id=request_id,review_stats=review_stats(c),dataset_stats=dataset_stats(c),last_reviewed=last_reviewed(c))

def backfill_excluded(c):
    created=[]
    with open(lab.ROOT/'public_review.lock','w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        c.execute('BEGIN IMMEDIATE')
        try:
            rows=c.execute("SELECT j.id,j.condition,r.comment,r.reviewer FROM reviews r JOIN jobs j ON j.id=r.job_id WHERE r.decision='exclude' AND j.kind='tryon' AND j.status NOT IN ('quarantined_lens_tint','quarantined_category_scope') AND NOT EXISTS(SELECT 1 FROM regeneration_requests q WHERE q.parent_job=j.id)").fetchall()
            for row in rows:
                child,request=enqueue_regeneration(c,row['id'],json.loads(row['condition']),'other',row['comment'] or '',None,row['reviewer'],'backfill_excluded')
                created.append(dict(parent=row['id'],child=child,request=request))
            c.commit()
        except Exception:c.rollback();raise
    return created

def reconcile(c):
    # Originals remain in their original folders. Archive contains copies of reviewed outputs.
    lab.materialize(c)
    for row in c.execute("SELECT j.id,j.output FROM jobs j JOIN reviews r ON r.job_id=j.id WHERE j.status NOT IN ('quarantined_lens_tint','quarantined_category_scope')"):
        src=Path(row['output']);dst=lab.ROOT/ARCHIVE/(row['id']+'.png')
        if src.is_file() and not dst.exists():
            tmp=dst.with_suffix('.'+uuid.uuid4().hex+'.tmp');shutil.copy2(src,tmp);tmp.replace(dst)
    rows=[dict(r) for r in c.execute('SELECT * FROM reviews')]
    target=lab.ROOT/ARCHIVE/'검수기록.json';tmp=target.with_suffix('.'+uuid.uuid4().hex+'.tmp');tmp.write_text(json.dumps(rows,ensure_ascii=False,indent=2));tmp.replace(target)

def dataset_stats(c):
    stats={category:dict(generated=0,passed=0,excluded=0,held=0,waiting=0,products=0,passed_products=0,queued=0,running=0) for category in ('A','B','C')}
    join=" FROM jobs j JOIN sources s ON s.id=json_extract(j.condition,'$.source_id') LEFT JOIN reviews r ON r.job_id=j.id WHERE j.kind='tryon' AND j.status='success'"
    for row in c.execute("SELECT s.category,count(*) AS generated,sum(r.decision='pass') AS passed,sum(r.decision='exclude') AS excluded,sum(r.decision='hold') AS held,sum(r.job_id IS NULL) AS waiting,count(DISTINCT s.product) AS products,count(DISTINCT CASE WHEN r.decision='pass' THEN s.product END) AS passed_products"+join+' GROUP BY s.category'):
        if row['category'] in stats:stats[row['category']].update({k:row[k] or 0 for k in ('generated','passed','excluded','held','waiting','products','passed_products')})
    for row in c.execute("SELECT s.category,j.status,count(*) AS n FROM jobs j JOIN sources s ON s.id=json_extract(j.condition,'$.source_id') WHERE j.kind='tryon' AND (j.status IN ('pending','interrupted','blocked_dependency','waiting_reference','running') OR (j.status='failed' AND j.attempts<3)) GROUP BY s.category,j.status"):
        if row['category'] in stats:stats[row['category']]['running' if row['status']=='running' else 'queued']+=row['n']
    return stats

def review_stats(c):
    stats={category:dict(reviewed=0,passed=0,excluded=0,held=0,products=0) for category in ('A','B','C')}
    join=" FROM reviews r JOIN jobs j ON j.id=r.job_id JOIN sources s ON s.id=json_extract(j.condition,'$.source_id') WHERE j.kind='tryon' AND j.status NOT IN ('quarantined_lens_tint','quarantined_category_scope')"
    names={'pass':'passed','exclude':'excluded','hold':'held'}
    for row in c.execute('SELECT s.category,r.decision,count(*) AS n'+join+' GROUP BY s.category,r.decision'):
        if row['category'] not in stats:continue
        value=stats[row['category']];value['reviewed']+=row['n']
        if row['decision'] in names:value[names[row['decision']]]+=row['n']
    for row in c.execute('SELECT s.category,count(DISTINCT s.product) AS n'+join+' GROUP BY s.category'):
        if row['category'] in stats:stats[row['category']]['products']=row['n']
    return stats

def request_rows(c):
    return [dict(r) for r in c.execute("SELECT r.id,r.parent_job,r.child_job,r.reason,r.notes,r.reviewer,r.created,j.status,j.attempts,j.finished FROM regeneration_requests r JOIN jobs j ON j.id=r.child_job JOIN jobs p ON p.id=r.parent_job WHERE p.status NOT IN ('quarantined_lens_tint','archived_unreviewed_reset','quarantined_category_scope') ORDER BY r.created DESC")]

def catalog(c,ids=None):
    ensure_numbers(c)
    result=[]
    query="SELECT j.id,j.condition,j.finished,j.output_sha256,n.number,r.decision,r.comment,r.checks,r.reviewer,r.updated,(SELECT max(e.id) FROM review_events e WHERE e.job_id=j.id) AS version FROM jobs j LEFT JOIN reviews r ON r.job_id=j.id LEFT JOIN review_item_numbers n ON n.job_id=j.id WHERE j.kind='tryon' AND j.status='success'"
    if ids is not None:
        if not ids:return []
        query+=' AND j.id IN ('+','.join('?' for _ in ids)+')'
    for row in c.execute(query+' ORDER BY j.finished DESC',ids or []):
        d=dict(row);con=json.loads(d.pop('condition'));s=c.execute('SELECT product,category,camera,evidence FROM sources WHERE id=?',(con['source_id'],)).fetchone()
        if not s:continue
        d.update(dict(s));d.update(person_id=con.get('person_id'),hair=con.get('hair',''),pose=con.get('pose'),composition=con.get('composition'),has_side_reference=bool(con.get('extra_references')),reference_count=2+len(con.get('extra_references',[])),cohort=con.get('cohort','original'),portrait_job=con.get('portrait_job'),regeneration_of=con.get('regeneration_of'),seed=con.get('seed'),steps=con.get('steps'),face_origin=con.get('face_origin','fictional_generated'),version=d['version'] or 0)
        d['checks']=json.loads(d['checks']) if d.get('checks') else ['unknown']*6;result.append(d)
    return result

LEASE_SECONDS=300

def review_priority(c,rows,reviewer):
    """Prioritize the underrepresented class for the requested reviewer only."""
    if reviewer!=PRIORITY_REVIEWER:return list(rows)
    counts={};totals={'A':0,'B':0}
    for r in c.execute("SELECT s.category,s.product,count(*) n FROM reviews r JOIN jobs j ON j.id=r.job_id JOIN sources s ON s.id=json_extract(j.condition,'$.source_id') WHERE r.decision='pass' AND j.kind='tryon' AND j.status='success' AND s.category IN ('A','B') GROUP BY s.category,s.product"):
        counts[(r['category'],r['product'])]=r['n'];totals[r['category']]+=r['n']
    if totals['A']==totals['B']:return list(rows)
    deficient=min(totals,key=totals.get);remaining=list(enumerate(rows));ordered=[]
    # Round robin among the models with the fewest accepted images.
    # These virtual counts affect ordering only, never human decisions.
    while remaining:
        k,(original,row)=min(enumerate(remaining),key=lambda item:(item[1][1]['category']!=deficient,counts.get((item[1][1]['category'],item[1][1]['product']),0),item[1][0]))
        ordered.append(row);key=(row['category'],row['product']);counts[key]=counts.get(key,0)+1;remaining.pop(k)
    return ordered

def priority_message(c,reviewer):
    if reviewer!=PRIORITY_REVIEWER:return ''
    stats=dataset_stats(c);a=stats['A']['passed'];b=stats['B']['passed']
    if a==b:return '두 분류의 통과 수가 같습니다.'
    label='일반 안경' if b<a else '카메라 안경'
    return f'{label} 우선 · 통과 수가 {abs(a-b)}장 부족합니다. 모델별 통과 수가 적은 순서로 배정합니다.'

def assert_claim(c,key,owner):
    row=c.execute('SELECT owner,expires FROM review_pool WHERE job_id=? UNION ALL SELECT owner,expires FROM review_claims WHERE job_id=?',(key,key)).fetchone()
    if not row or row['owner']!=owner or row['expires']<=time.time():
        raise Conflict('배정 시간이 끝났거나 다른 검수자에게 배정됐습니다. 다음 이미지 받기를 눌러 주세요.')

def matches_condition(row,filters):
    con=json.loads(row['condition']);category=filters.get('category','all');cohort=filters.get('cohort','all');search=str(filters.get('search','')).strip().casefold()
    return (category=='all' or row['category']==category) and (cohort=='all' or (con.get('composition')=='tight_face_closeup' if cohort=='face_closeup' else (con.get('person_id')=='U01' or con.get('face_origin')=='user_provided_reference') if cohort=='user' else con.get('cohort','original')=='original' and con.get('person_id')!='U01' if cohort=='original' else con.get('cohort')==cohort)) and (not search or search in (row['product']+' '+con.get('person_id','')).casefold())

def claim(c,owner,reviewer,filters=None,preferred=None,skip=None,completed=False):
    reviewer=str(reviewer).strip()
    if not reviewer or len(reviewer)>60:raise ValueError('먼저 검수자 이름이나 별명을 입력하세요.')
    filters=filters or {};stamp=time.time();c.execute('BEGIN IMMEDIATE')
    try:
        c.execute('DELETE FROM review_claims WHERE expires<=?',(stamp,))
        c.execute('DELETE FROM review_pool WHERE expires<=?',(stamp,))
        if completed:
            if not preferred:raise ValueError('결과를 선택하세요.')
            rows=c.execute("SELECT j.id,j.condition,s.product,s.category FROM jobs j JOIN sources s ON s.id=json_extract(j.condition,'$.source_id') WHERE j.id=? AND j.kind='tryon' AND j.status='success'",(preferred,)).fetchall()
        else:
            rows=c.execute("SELECT j.id,j.condition,s.product,s.category FROM jobs j JOIN sources s ON s.id=json_extract(j.condition,'$.source_id') WHERE j.kind='tryon' AND j.status='success' AND NOT EXISTS(SELECT 1 FROM reviews r WHERE r.job_id=j.id) ORDER BY j.finished DESC,j.id").fetchall()
            rows=[r for r in rows if matches_condition(r,filters)]
        reserved={r['job_id']:r['owner'] for r in c.execute('SELECT job_id,owner FROM review_claims UNION ALL SELECT job_id,owner FROM review_pool')}
        available=review_priority(c,[r for r in rows if reserved.get(r['id'],owner)==owner and r['id']!=skip],reviewer)
        if preferred:
            chosen=next((r for r in available if r['id']==preferred),None)
            if completed and not chosen:raise Conflict('이 결과는 다른 검수자가 수정 중입니다.')
        else:chosen=None
        own=c.execute('SELECT job_id FROM review_claims WHERE owner=?',(owner,)).fetchone()
        if not chosen and own:chosen=next((r for r in available if r['id']==own['job_id']),None)
        if not chosen and available:chosen=available[0]
        c.execute('DELETE FROM review_claims WHERE owner=?',(owner,))
        c.execute('DELETE FROM review_pool WHERE owner=?',(owner,))
        if chosen:c.execute('INSERT INTO review_claims VALUES(?,?,?,?)',(chosen['id'],owner,reviewer,stamp+LEASE_SECONDS))
        c.commit()
        return dict(id=chosen['id'] if chosen else None,expires=stamp+LEASE_SECONDS if chosen else None,remaining=len(rows),busy=sum(reserved.get(r['id']) not in (None,owner) for r in rows),available=len(available))
    except Exception:c.rollback();raise

def heartbeat(c,key,owner,activity=None):
    c.execute('BEGIN IMMEDIATE')
    try:
        assert_claim(c,key,owner);stamp=time.time();activity=stamp if activity is None else min(stamp,float(activity))
        expires=min(stamp+LEASE_SECONDS,activity+LEASE_SECONDS)
        if expires<=stamp:raise Conflict('5분 동안 활동이 없어 배정을 해제합니다. 다음 이미지 받기를 눌러 주세요.')
        c.execute('UPDATE review_claims SET expires=? WHERE job_id=? AND owner=?',(expires,key,owner))
        c.execute('UPDATE review_pool SET expires=? WHERE owner=?',(expires,owner));c.commit()
        return dict(ok=True,expires=expires)
    except Exception:c.rollback();raise

def release(c,key,owner,all_reserved=False):
    c.execute('DELETE FROM review_claims WHERE job_id=? AND owner=?',(key,owner))
    if all_reserved:c.execute('DELETE FROM review_pool WHERE owner=?',(owner,))
    else:c.execute('DELETE FROM review_pool WHERE job_id=? AND owner=?',(key,owner))
    c.commit();return dict(ok=True)

def active_claims(c,owner):
    stamp=time.time()
    rows=[dict(r) for r in c.execute('SELECT *,1 AS reserved_count FROM review_claims WHERE expires>?',(stamp,))]
    rows.extend(dict(r) for r in c.execute('SELECT p.*, (SELECT count(*) FROM review_pool x WHERE x.owner=p.owner AND x.expires>?) AS reserved_count FROM review_pool p WHERE p.expires>? AND p.position=(SELECT min(y.position) FROM review_pool y WHERE y.owner=p.owner AND y.expires>?)',(stamp,stamp,stamp)))
    return [dict(job_id=r['job_id'],reviewer=r['reviewer'],expires=r['expires'],mine=r['owner']==owner,reserved_count=r['reserved_count']) for r in rows]

def claim_batch(c,owner,reviewer,filters=None,preferred=None,skip=None):
    reviewer=str(reviewer or '').strip()
    if not reviewer or len(reviewer)>60:raise ValueError('검수자를 선택하세요.')
    filters=filters or {};packed=json.dumps(filters,sort_keys=True);stamp=time.time();c.execute('BEGIN IMMEDIATE')
    try:
        c.execute('DELETE FROM review_claims WHERE expires<=?',(stamp,));c.execute('DELETE FROM review_pool WHERE expires<=?',(stamp,))
        c.execute('DELETE FROM review_pool WHERE job_id IN (SELECT job_id FROM reviews)')
        settings=c.execute('SELECT filters FROM review_pool_settings WHERE owner=?',(owner,)).fetchone()
        if settings and settings['filters']!=packed:c.execute('DELETE FROM review_pool WHERE owner=?',(owner,))
        c.execute('INSERT INTO review_pool_settings VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET filters=excluded.filters',(owner,packed))
        previous=c.execute('SELECT job_id FROM review_claims WHERE owner=?',(owner,)).fetchone()
        if previous and not preferred:preferred=previous['job_id']
        c.execute('DELETE FROM review_claims WHERE owner=?',(owner,))
        if skip:c.execute('DELETE FROM review_pool WHERE job_id=? AND owner=?',(skip,owner))
        rows=c.execute("SELECT j.id,j.condition,s.product,s.category FROM jobs j JOIN sources s ON s.id=json_extract(j.condition,'$.source_id') WHERE j.kind='tryon' AND j.status='success' AND NOT EXISTS(SELECT 1 FROM reviews r WHERE r.job_id=j.id) ORDER BY j.finished DESC,j.id").fetchall()
        rows=[r for r in rows if matches_condition(r,filters)]
        valid={r['id'] for r in rows}
        for r in c.execute('SELECT job_id FROM review_pool WHERE owner=?',(owner,)).fetchall():
            if r['job_id'] not in valid:c.execute('DELETE FROM review_pool WHERE job_id=?',(r['job_id'],))
        own=[r['job_id'] for r in c.execute('SELECT job_id FROM review_pool WHERE owner=? ORDER BY position',(owner,))]
        reserved={r['job_id']:r['owner'] for r in c.execute('SELECT job_id,owner FROM review_claims UNION ALL SELECT job_id,owner FROM review_pool')}
        ranked=review_priority(c,rows,reviewer)
        extra=[r['id'] for r in ranked if r['id']!=skip and r['id'] not in reserved]
        if preferred in extra:extra.remove(preferred);extra.insert(0,preferred)
        additions=extra[:10] if len(own)<=5 else []
        position=c.execute('SELECT coalesce(max(position),0) FROM review_pool WHERE owner=?',(owner,)).fetchone()[0]
        for k,key in enumerate(additions):c.execute('INSERT INTO review_pool VALUES(?,?,?,?,?)',(key,owner,reviewer,stamp+LEASE_SECONDS,position+k+1))
        c.execute('UPDATE review_pool SET reviewer=?,expires=? WHERE owner=?',(reviewer,stamp+LEASE_SECONDS,owner))
        if reviewer==PRIORITY_REVIEWER:
            own_ids={r['job_id'] for r in c.execute('SELECT job_id FROM review_pool WHERE owner=?',(owner,))}
            for position,row in enumerate(r for r in ranked if r['id'] in own_ids):
                c.execute('UPDATE review_pool SET position=? WHERE job_id=? AND owner=?',(position,row['id'],owner))
        ids=[r['job_id'] for r in c.execute('SELECT job_id FROM review_pool WHERE owner=? ORDER BY position',(owner,))]
        if preferred in ids:
            c.execute('UPDATE review_pool SET position=? WHERE job_id=?',(min([r[0] for r in c.execute('SELECT position FROM review_pool WHERE owner=?',(owner,))])-1,preferred))
            ids.remove(preferred);ids.insert(0,preferred)
        c.commit()
    except Exception:c.rollback();raise
    jobs=catalog(c,ids);details={}
    for j in jobs:
        draft=c.execute('SELECT data FROM review_drafts WHERE job_id=? AND session=?',(j['id'],owner)).fetchone()
        details[j['id']]=dict(draft=json.loads(draft[0]) if draft else None,history=[],version=j['version'])
    return dict(ids=ids,jobs=jobs,details=details,added=len(additions),expires=stamp+LEASE_SECONDS,remaining=len(rows),busy=sum(reserved.get(r['id']) not in (None,owner) for r in rows),priority_message=priority_message(c,reviewer))
