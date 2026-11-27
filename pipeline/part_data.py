"""Prepare high-resolution local views without treating them as camera annotations."""
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from pipeline.mobile_evidence import add_bridge_region
from pipeline.records import sha256, write_json

PARTS = ["outer_left", "bridge", "outer_right"]


def local_views(original, geometry, full_size=224, local_size=112):
    images = np.zeros((3,3,local_size,local_size),dtype=np.uint8)
    quality = np.zeros((3,4),dtype=np.float32)
    valid = np.zeros(3,dtype=np.float32)
    boxes=[]
    if geometry is None:
        return images,quality,valid,boxes
    geometry=add_bridge_region(geometry,full_size)
    sx,sy=original.width/full_size,original.height/full_size
    for index,name in enumerate(PARTS):
        x0,y0,x1,y1=geometry["regions"][name]
        view=np.asarray(original.crop((x0*sx,y0*sy,x1*sx,y1*sy)).resize(
            (local_size,local_size),Image.Resampling.BILINEAR))
        gray=cv2.cvtColor(view,cv2.COLOR_RGB2GRAY)
        images[index]=view.transpose(2,0,1)
        quality[index]=[min(np.log1p(cv2.Laplacian(gray,cv2.CV_64F).var())/10,1),
                        gray.mean()/255,gray.std()/128,geometry["confidence"]]
        valid[index]=1
        boxes.append([x0,y0,x1,y1])
    return images,quality,valid,boxes


def prepare_parts(config):
    root=Path(config["part_cache"])
    root.mkdir(parents=True,exist_ok=True)
    source=Path(config["view_cache"])/"metadata.json"
    digest=sha256(source)
    if (root/"metadata.json").exists():
        cached=json.loads((root/"metadata.json").read_text())
        if cached["source_metadata_sha256"]!=digest:
            raise ValueError("Part cache belongs to a different source")
        return cached
    metadata=json.loads(source.read_text())
    n=len(metadata["rows"])
    size=config["local_size"]
    images=np.lib.format.open_memmap(root/"parts.npy",mode="w+",dtype=np.uint8,shape=(n,3,3,size,size))
    quality=np.zeros((n,3,4),dtype=np.float32)
    valid=np.zeros((n,3),dtype=np.float32)
    for index,row in enumerate(metadata["rows"]):
        with Image.open(row["path"]) as image:
            views,q,v,_=local_views(image.convert("RGB"),row["geometry"],config["image_size"],size)
        images[index]=views
        quality[index],valid[index]=q,v
        if index%1000==0:
            print(f"part cache {index}/{n}",flush=True)
    images.flush()
    np.save(root/"quality.npy",quality)
    np.save(root/"valid.npy",valid)
    result=dict(version=1,n=n,local_size=size,parts=PARTS,source_metadata_sha256=digest,
        source_manifest_sha256=metadata["source_manifest_sha256"],
        failed_geometry=int((valid.sum(1)==0).sum()),exact_camera_annotations="pending",
        sha256={name:sha256(root/name) for name in ["parts.npy","quality.npy","valid.npy"]})
    write_json(root/"metadata.json",result)
    return result
