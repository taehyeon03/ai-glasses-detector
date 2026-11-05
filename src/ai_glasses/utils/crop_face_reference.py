"""Create an auditable closer reference without modifying the supplied portrait."""
import json,sys
from pathlib import Path
import cv2
from PIL import Image,ImageOps

def crop_box(face,size):
    x,y,w,h=map(int,face);width,height=size
    side=min(max(width,height),round(max(w,h)*1.65))
    # Leave lateral space for the ears and complete glasses while removing torso.
    side=min(side,width,height)
    left=max(0,min(width-side,round(x+w/2-side/2)))
    top=max(0,min(height-side,round(y+h*.48-side/2)))
    return (left,top,left+side,top+side)

def main():
    source=Path(sys.argv[1]);destination=Path(sys.argv[2])
    image=ImageOps.exif_transpose(Image.open(source)).convert('RGB')
    import numpy as np
    gray=cv2.cvtColor(np.array(image),cv2.COLOR_RGB2GRAY)
    faces=[]
    for cascade,flipped in [('haarcascade_frontalface_default.xml',False),('haarcascade_profileface.xml',False),('haarcascade_profileface.xml',True)]:
        frame=cv2.flip(gray,1) if flipped else gray
        found=cv2.CascadeClassifier(cv2.data.haarcascades+cascade).detectMultiScale(frame,1.1,5,minSize=(90,90))
        for x,y,w,h in found:faces.append((image.width-int(x)-int(w) if flipped else int(x),int(y),int(w),int(h)))
        if faces:break
    if not faces:
        print(json.dumps(dict(cropped=False,reason='No reliable face detection; original reference retained')));return
    face=max(faces,key=lambda b:b[2]*b[3]);box=crop_box(face,image.size)
    destination.parent.mkdir(parents=True,exist_ok=True)
    # Never upscale this reference. The model generates the output at native resolution.
    image.crop(box).save(destination)
    print(json.dumps(dict(cropped=True,box=box,face_box=face,original_size=image.size,derived_path=str(destination))))

if __name__=='__main__':main()
