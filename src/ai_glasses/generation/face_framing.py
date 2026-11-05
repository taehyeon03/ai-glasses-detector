"""Apply the user's approximate 80% head / 20% background composition target."""
import json,fcntl,hashlib,re
VERSION='face90_glasses_closeup_v2'
SCENE_VERSION='realistic_indoor_backgrounds_v2'
BACKGROUNDS=(
    ('computer_desk','a university computer laboratory with a pale wall, small glimpses of wooden desks, black monitors and office chairs, and a white tiled ceiling'),
    ('whiteboard_wood','a university practical classroom with a pale wall, a whiteboard, light wood panels and a white tiled ceiling'),
    ('computer_rows','a university computer classroom with rows of black desktop monitors, light desks, windows and rectangular ceiling lights'),
    ('research_office','a modest university research office with a monitor on a slightly used wooden desk, a pale wall and an ordinary swivel chair'),
    ('seminar_room','a small university seminar room with everyday tables, dark chairs, a whiteboard and ceiling panels'),
    ('window_classroom','an ordinary classroom beside a window with roller blinds, pale walls and light wooden desks'),
    ('shared_office','a shared campus office with low desk partitions, black monitors and ordinary overhead lights'),
    ('study_room','a small campus study room with a wooden study table, a bookcase and matte off-white walls'),
    ('library_desk','a quiet university library study area with wooden desk dividers and softly visible bookshelves'),
    ('meeting_table','a modest meeting room with a light conference table, practical office chairs and a pale wall'),
    ('lab_storage','a university computer laboratory with light wooden storage cabinets, a desk corner and ordinary ceiling panels'),
    ('wall_desk_corner','an everyday campus workspace with a slightly textured pale wall, a desk corner, a monitor edge and an office chair'),
)
LIGHTING=(
    ('ceiling_neutral','ordinary neutral-white overhead classroom lighting with soft natural shadows'),
    ('window_side','soft daylight from a side window mixed with ordinary ceiling lighting'),
    ('ceiling_dim','slightly dimmer overhead classroom lighting, with the face and small eyeglass details still clearly exposed'),
    ('window_fill','gentle window backlighting balanced by indoor fill light; no silhouette or blown highlights'),
)
def scene_guidance(con):
    # Product and class are deliberately absent from the selection inputs.
    key=json.dumps([con.get('person_id'),con.get('pose'),con.get('seed',0)],ensure_ascii=False)
    value=int(hashlib.sha256(key.encode()).hexdigest(),16)
    bg=BACKGROUNDS[value%len(BACKGROUNDS)];light=LIGHTING[(value//len(BACKGROUNDS))%len(LIGHTING)]
    con.update(scene_policy_version=SCENE_VERSION,background_style=bg[0],lighting_variant=light[0],scene_reference_people=['U01','U02','U03'],scene_reference_mode='visually_inspected_style_description',scene_verified=False)
    return (' [SCENE_POLICY_BEGIN] The following scene instructions replace earlier background and lighting instructions only. '
        'Use varied believable everyday university interiors inspired by the atmosphere of the three user-provided photographs. The background is '+bg[1]+'. '
        'Show only the small background margins permitted by the face-close-up framing. Do not pull the camera back to display the room. '
        'Use '+light[1]+'. Keep realistic phone-camera color, skin texture and moderate background detail. '
        'Include subtle ordinary surface wear and plausible room perspective. Avoid showroom staging, luxury interiors, cinematic grading and artificial studio backdrops. '
        'Do not add other recognizable people or readable screen text. Preserve the exact identity and requested head direction. '
        'Preserve all product geometry, frame colors, lens tint, cameras, sensors and indicator lights from the glasses references. '
        'Background or lighting changes must not invent, remove, move, recolor or reshape any eyeglass component. '
        'Allow physically plausible illumination and reflections without changing lens material or concealing a camera aperture. [SCENE_POLICY_END]')
LEGACY_GUIDANCE=' Framing target (approximate, not a measured mask): use a very tight FACE CLOSE-UP. Aim for the head, face, hair and worn glasses to occupy about 80 percent of the image area, leaving about 20 percent as background. Keep only small margins around the head and glasses. End the lower edge just below the chin, with at most a very narrow clothing neckline. No shoulders, chest, torso, arms or hands. Keep all physically visible eyeglass rims, camera locations, hinges and temple sections inside the image; do not enlarge or distort the glasses to fill the frame. Preserve the requested head direction. In profile show only the near eye and near ear, with far-side features naturally hidden. Do not add text or numeric proportions to the image.'
GUIDANCE=' Framing target (approximate, not a measured mask): this final framing instruction overrides any earlier camera-distance or head-and-shoulders instruction. Create a FACE-ONLY CLOSE-UP focused on the worn glasses. Aim for the face, hair and glasses to occupy about 90 percent of the image, with only about 10 percent background. Crop immediately below the chin. No shoulders, chest or clothing neckline. The topmost hair tips may leave the image if needed, but keep the forehead, chin and all physically visible glasses parts inside the image. In front and oblique views, let the glasses span roughly 60 to 80 percent of image width without changing their physical scale relative to the face. In side views, retain the complete visible temple and hinge near the ear. Keep the requested head direction. Focus precisely on the glasses, with crisp frame edges, hinges, camera apertures and lens boundaries. Keep the visible glasses in focus across their depth. Use natural optical detail, without artificial sharpening halos or invented texture. Never alter product geometry or camera positions for sharpness. In profile show only the near eye and near ear. Do not add text or numeric proportions.'

def _apply_scene_condition(condition):
    con=dict(condition)
    from ai_glasses.generation.multiview_references import HINGE_VERSION,apply_hinge_condition
    needs_hinge=con.get('kind')=='tryon' and con.get('hinge_fidelity_version')!=HINGE_VERSION
    if con.get('face_framing_version')==VERSION and con.get('scene_policy_version')==SCENE_VERSION and not needs_hinge:return con
    if con.get('kind') not in ('portrait','tryon') or not con.get('prompt'):return con
    prompt=re.sub(r'\s*\[SCENE_POLICY_BEGIN\].*?\[SCENE_POLICY_END\]','',con['prompt'],flags=re.S)
    con['prompt']=prompt.replace(LEGACY_GUIDANCE,'').replace(GUIDANCE,'').replace('both ears','the ear or ears physically visible at this angle')+GUIDANCE+scene_guidance(con)
    con.update(composition='tight_face_closeup',face_framing_version=VERSION,foreground_fraction_target=.9,background_fraction_target=.1,framing_verified=False)
    return apply_hinge_condition(con)

def apply_condition(condition):
    con=_apply_scene_condition(condition)
    from ai_glasses.generation import tryon_lab as lab
    if (lab.ROOT/'product_fidelity_enabled.json').exists() and con.get('kind')=='tryon':
        from ai_glasses.generation.product_fidelity import apply_fidelity
        con=apply_fidelity(con)
    return con

def prepare_closeup_reference(path,con):
    import os,subprocess,sys
    from pathlib import Path
    from ai_glasses.generation import tryon_lab as lab
    if con.get('face_framing_version')!=VERSION:return str(path),None
    folder=lab.ROOT/'work'/'closeup_references'
    key=lab.uid([lab.digest(path),VERSION]);out=folder/(key+'.png');record=folder/(key+'.json')
    if record.exists():
        info=json.loads(record.read_text())
        if not info.get('cropped') or (out.exists() and lab.digest(out)==info.get('derived_sha256')):
            return str(out if info.get('cropped') else path),info
    python=os.environ.get('TRYON_FACE_CROP_PYTHON',sys.executable)
    result=subprocess.run([python,'-m','ai_glasses.utils.crop_face_reference',str(path),str(out)],capture_output=True,text=True,check=True)
    info=json.loads(result.stdout);info.update(source_path=str(path),source_sha256=lab.digest(path),version=VERSION)
    if info.get('cropped'):info['derived_sha256']=lab.digest(out)
    folder.mkdir(parents=True,exist_ok=True);record.write_text(json.dumps(info,ensure_ascii=False,indent=2))
    return str(out if info.get('cropped') else path),info

def migrate_pending(c):
    from ai_glasses.generation import tryon_lab as lab
    statuses=('pending','interrupted','blocked_dependency','waiting_reference')
    placeholders=','.join('?' for _ in statuses)
    with open(lab.ROOT/'public_review.lock','w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX);c.execute('BEGIN IMMEDIATE')
        try:
            rows={r['id']:r for r in c.execute("SELECT * FROM jobs WHERE kind IN ('portrait','tryon') AND (status IN ("+placeholders+") OR (status='failed' AND attempts<3))",statuses)}
            planned={};visiting=set()
            def plan(key):
                if key in planned:return planned[key][0]
                if key in visiting:raise ValueError('Portrait dependency cycle')
                visiting.add(key);old=rows[key];raw=json.loads(old['condition']);raw.setdefault('kind',old['kind']);con=apply_condition(raw)
                for field in ('portrait_job','portrait_parent'):
                    parent=con.get(field)
                    if parent in rows:con[field]=plan(parent)
                newkey=lab.uid(con);planned[key]=(newkey,con);visiting.remove(key);return newkey
            for key in rows:plan(key)
            changes=[]
            for oldkey,(newkey,con) in planned.items():
                if oldkey==newkey:continue
                row=rows[oldkey]
                # Keep request/reference waiting state; successful outputs and reviews are untouched.
                status='pending' if row['status'] in ('interrupted','failed') else row['status']
                c.execute('INSERT OR IGNORE INTO jobs(id,kind,condition,status) VALUES(?,?,?,?)',(newkey,row['kind'],json.dumps(con,ensure_ascii=False),status))
                for batch in c.execute('SELECT * FROM batch_jobs WHERE job_id=?',(oldkey,)).fetchall():
                    c.execute('DELETE FROM batch_jobs WHERE batch=? AND job_id=?',(batch['batch'],oldkey));c.execute('INSERT OR IGNORE INTO batch_jobs VALUES(?,?,?)',(batch['batch'],newkey,batch['priority']))
                c.execute('UPDATE regeneration_requests SET child_job=? WHERE child_job=?',(newkey,oldkey))
                c.execute("UPDATE jobs SET status='superseded',error='Replaced before generation: face close-up with closer face-only framing, sharp glasses and realistic indoor backgrounds' WHERE id=?",(oldkey,))
                changes.append(dict(old=oldkey,new=newkey,kind=row['kind']))
            c.commit()
        except Exception:c.rollback();raise
    return changes
if __name__=='__main__':
    from ai_glasses.generation import tryon_lab as lab
    c=lab.connect();changes=migrate_pending(c)
    (lab.ROOT/lab.FOLDERS[9]/'face_framing_80_20.json').write_text(json.dumps(dict(created=lab.now(),version=VERSION,changes=changes),ensure_ascii=False,indent=2));lab.export(c)
    print(json.dumps(dict(replaced=len(changes),portraits=sum(r['kind']=='portrait' for r in changes),tryons=sum(r['kind']=='tryon' for r in changes))))
