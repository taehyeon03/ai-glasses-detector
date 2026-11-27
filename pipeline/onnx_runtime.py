"""CPU inference without a PyTorch dependency. No photographs are saved here."""
import json
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image

from pipeline.image_views import geometry,local_views,matched_views
from pipeline.records import sha256


class Runtime:
    def __init__(self,bundle):
        self.root=Path(bundle)
        self.metadata=json.loads((self.root/"manifest.json").read_text())
        options=ort.SessionOptions();options.intra_op_num_threads=4
        if sha256(self.root/"model.onnx") != self.metadata["model_sha256"]:
            raise ValueError("Model checksum does not match the bundle manifest")
        self.session=ort.InferenceSession(str(self.root/"model.onnx"),sess_options=options,
                                         providers=["CPUExecutionProvider"])
        size=self.metadata["image_size"]
        self.detector=cv2.FaceDetectorYN.create(str(self.root/"face_detection_yunet_2023mar.onnx"),"",(size,size),.6,.3,5000)

    def predict(self,rgb):
        start=perf_counter()
        original=Image.fromarray(rgb)
        size=self.metadata["image_size"]
        small=np.asarray(original.resize((size,size),Image.Resampling.BILINEAR))
        self.detector.setScoreThreshold(.6)
        _,faces=self.detector.detect(cv2.cvtColor(small,cv2.COLOR_RGB2BGR))
        if faces is None:
            self.detector.setScoreThreshold(.3)
            _,faces=self.detector.detect(cv2.cvtColor(small,cv2.COLOR_RGB2BGR))
        if faces is not None and len(faces)>1:
            return dict(camera_probability=None,reason="multiple_faces",pipeline_ms=(perf_counter()-start)*1000)
        info=geometry(max(faces,key=lambda v:v[2]*v[3]),size) if faces is not None else None
        if info is None:
            return dict(camera_probability=None,reason="geometry_missing",pipeline_ms=(perf_counter()-start)*1000)
        view=matched_views(original,info,size)["roi_crop"]
        values=dict(global_image=view.transpose(2,0,1)[None].copy())
        if any(item.name!="global_image" for item in self.session.get_inputs()):
            parts,quality,valid,_=local_views(original,info,size,self.metadata["local_size"])
            values.update(parts=parts[None],quality=quality[None],valid=valid[None])
        feed={item.name:values[item.name] for item in self.session.get_inputs()}
        ready=perf_counter()
        logits=self.session.run(None,feed)[0][0].astype(np.float64)
        scores=np.exp(logits-logits.max());scores/=scores.sum()
        return dict(camera_probability=float(scores[1]),reason="scored",
            preprocessing_ms=(ready-start)*1000,inference_ms=(perf_counter()-ready)*1000,
            pipeline_ms=(perf_counter()-start)*1000,geometry_confidence=info["confidence"],
            estimated_glasses_box=[int(v*(rgb.shape[1] if i%2==0 else rgb.shape[0])/size)
                                   for i,v in enumerate(info["roi"])])
