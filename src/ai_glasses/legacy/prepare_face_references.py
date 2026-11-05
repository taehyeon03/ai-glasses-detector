import json,time,os
from pathlib import Path
import cv2
from PIL import Image
from ai_glasses.generation import tryon_lab as lab
c=lab.connect();detector=cv2.CascadeClassifier(cv2.data.haarcascades+'haarcascade_frontalface_default.xml');result=[]
for n in range(1,9):
 pid=f'K{n:02d}';row=c.execute("SELECT * FROM jobs WHERE kind='portrait' AND status='success' AND json_extract(condition,'$.person_id')=? AND json_extract(condition,'$.protocol')='korean_students_v1' ORDER BY rowid LIMIT 1",(pid,)).fetchone()
 if not row:raise ValueError('Original clean identity missing: '+pid)
 image=Image.open(row['output']).convert('RGB');frame=cv2.imread(row['output']);gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY);faces=detector.detectMultiScale(gray,scaleFactor=1.1,minNeighbors=5,minSize=(70,70))
 if not len(faces):raise ValueError('No reliable frontal face: '+pid)
 x,y,w,h=map(int,max(faces,key=lambda b:int(b[2])*int(b[3])));side=int(max(w,h)*1.55);cx=x+w/2;bottom=y+h*1.03;left=max(0,min(image.width-side,int(cx-side/2)));top=max(0,min(image.height-side,int(bottom-side)));box=[left,top,left+side,top+side]
 con=json.loads(row['condition']);con.update(protocol='korean_students_facecrop_v3',composition='tight_face_closeup',derivation='deterministic_crop_of_existing_glasses_free_portrait',reference_parent=row['id'],reference_sha256=row['output_sha256'],crop_box=box,face_detector='OpenCV frontalface Haar cascade',face_bbox=[x,y,w,h])
 key=lab.add_job(c,con,'portrait');out=lab.ROOT/lab.FOLDERS[4]/(key+'.png');image.crop(box).resize((1024,1024),Image.Resampling.LANCZOS).save(out)
 c.execute("UPDATE jobs SET status='success',output=?,output_sha256=?,finished=?,environment=? WHERE id=?",(str(out),lab.digest(out),lab.now(),json.dumps({'derivation':'crop','opencv':cv2.__version__}),key));c.commit();result.append({'person':pid,'job':key,'box':box})
# Supersede only replacement attempts. Preserve their files and all original portrait identities.
c.execute("UPDATE jobs SET status='superseded',error='Replaced with a crop of the verified glasses-free source identity' WHERE kind='portrait' AND json_extract(condition,'$.protocol')='korean_students_facecrop_v2' AND status!='running'")
c.execute("UPDATE jobs SET status='superseded',error='Replaced with a crop of the glasses-free identity' WHERE kind='tryon' AND json_extract(condition,'$.protocol')='korean_students_facecrop_v2' AND status IN ('pending','failed','interrupted','blocked_dependency')")
c.commit();(lab.ROOT/lab.FOLDERS[9]/'face_crop_references.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result))
