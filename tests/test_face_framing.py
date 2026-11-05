import json,tempfile,unittest
from pathlib import Path
from ai_glasses.generation import tryon_lab as lab
from ai_glasses.review import public_review_store as store
from ai_glasses.generation import face_framing as framing
class FramingTests(unittest.TestCase):
 def test_guidance_is_idempotent_and_records_a_target(self):
  con=dict(kind='tryon',prompt='Preserve both ears and the glasses.')
  first=framing.apply_condition(con);self.assertEqual(first,framing.apply_condition(first))
  first.pop('face_framing_version');second=framing.apply_condition(first)
  self.assertEqual(second['prompt'].count('Framing target'),1);self.assertEqual(second['background_fraction_target'],.1);self.assertFalse(second['framing_verified'])
 def test_scene_selection_does_not_use_product_or_camera_class_and_upgrades_old_jobs(self):
  original=dict(kind='tryon',prompt='Preserve background and glasses.'+framing.GUIDANCE,face_framing_version=framing.VERSION,person_id='U02',pose='left_profile',seed=123)
  a=framing.apply_condition(dict(original,product='camera glasses',camera='yes'))
  b=framing.apply_condition(dict(original,product='ordinary glasses',camera='no'))
  self.assertEqual(a['background_style'],b['background_style']);self.assertEqual(a['lighting_variant'],b['lighting_variant'])
  self.assertEqual(a['scene_policy_version'],framing.SCENE_VERSION);self.assertFalse(a['scene_verified'])
  self.assertIn('Do not pull the camera back',a['prompt']);self.assertIn('must not invent, remove, move',a['prompt'])
  a.pop('scene_policy_version');again=framing.apply_condition(a)
  self.assertEqual(again['prompt'].count('[SCENE_POLICY_BEGIN]'),1);self.assertEqual(again['prompt'].count('Framing target'),1)
 def test_migration_relinks_dependencies_and_preserves_reviews_and_waiting_states(self):
  with tempfile.TemporaryDirectory() as directory:
   original=lab.ROOT;lab.ROOT=Path(directory);c=lab.connect();store.init(c)
   try:
    for key,kind,con,status in [('P','portrait',dict(prompt='face portrait'),'pending'),('T','tryon',dict(kind='tryon',prompt='wear glasses',portrait_job='P'),'waiting_reference'),('S','tryon',dict(kind='tryon',prompt='already generated'),'success'),('R','tryon',dict(kind='tryon',prompt='in flight'),'running')]:
     c.execute('INSERT INTO jobs(id,kind,condition,status) VALUES(?,?,?,?)',(key,kind,json.dumps(con),status))
    c.execute('INSERT INTO batch_jobs VALUES(?,?,?)',('batch','T',7));c.execute('INSERT INTO regeneration_requests VALUES(?,?,?,?,?,?,?,?)',('request','S','T','folded','feedback','reviewer','owner',lab.now()));c.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?)',('S','hold','human text','[]','reviewer',lab.now()));c.commit()
    before=[tuple(r) for r in c.execute('SELECT * FROM reviews')];changes=framing.migrate_pending(c);self.assertEqual(len(changes),2)
    mapping={r['old']:r['new'] for r in changes};child=c.execute('SELECT * FROM jobs WHERE id=?',(mapping['T'],)).fetchone();self.assertEqual(child['status'],'waiting_reference');self.assertEqual(json.loads(child['condition'])['portrait_job'],mapping['P'])
    self.assertEqual(c.execute('SELECT child_job FROM regeneration_requests').fetchone()[0],mapping['T']);self.assertEqual(c.execute('SELECT job_id FROM batch_jobs').fetchone()[0],mapping['T'])
    self.assertEqual(before,[tuple(r) for r in c.execute('SELECT * FROM reviews')]);self.assertEqual(c.execute('SELECT status FROM jobs WHERE id="R"').fetchone()[0],'running');self.assertEqual(framing.migrate_pending(c),[])
   finally:c.close();lab.ROOT=original
if __name__=='__main__':unittest.main()
