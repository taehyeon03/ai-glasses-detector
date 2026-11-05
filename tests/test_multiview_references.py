import tempfile,unittest
from pathlib import Path
from PIL import Image
from ai_glasses.generation import tryon_lab as lab
from ai_glasses.generation.multiview_references import append_references,prompt_for_views,apply_hinge_condition,HINGE_VERSION
class ReferenceTests(unittest.TestCase):
 def test_extra_reference_is_third_and_bytes_are_verified(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'side.png';Image.new('RGB',(32,32),'blue').save(p)
   references=[{'path':str(p),'sha256':lab.digest(p),'role':'left_side','product':'Frame'}]
   face=Image.new('RGB',(32,32),'red');front=Image.new('RGB',(32,32),'green');images=append_references([face,front],{'extra_references':references,'product':'Frame'})
   self.assertIs(images[0],face);self.assertIs(images[1],front);self.assertEqual(images[2].getpixel((0,0)),(0,0,255))
   p.write_bytes(b'changed')
   with self.assertRaises(ValueError):append_references([face,front],{'extra_references':references,'product':'Frame'})
 def test_product_mismatch_is_rejected(self):
  with self.assertRaises(ValueError):append_references([],{"product":"A","extra_references":[{'product':'B','role':'left_side'}]})
 def test_legacy_two_reference_jobs_are_unchanged(self):
  images=[object(),object()];self.assertIs(append_references(images,{}),images);self.assertEqual(prompt_for_views('base',[]),'base')
 def test_hinge_symmetry_is_explicit_and_does_not_mirror_electronics(self):
  for side,pose in [('left_side','right_profile'),('right_side','left_profile')]:
   con=dict(kind='tryon',prompt='Keep the original product.',pose=pose,extra_references=[dict(role=side)])
   updated=apply_hinge_condition(con)
   self.assertEqual(updated,apply_hinge_condition(updated));self.assertEqual(updated['hinge_fidelity_version'],HINGE_VERSION)
   self.assertEqual(updated['hinge_reference_sides'],[side]);self.assertFalse(updated['hinge_assumption_verified'])
   self.assertIn('left-right symmetric',updated['prompt']);self.assertIn('Do not duplicate or relocate cameras',updated['prompt'])
   self.assertIn('visible screw positions',updated['prompt']);self.assertEqual(updated['prompt'].count('[HINGE_POLICY_BEGIN]'),1)
if __name__=='__main__':unittest.main()
