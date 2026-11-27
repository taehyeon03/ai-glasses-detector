"""Export one selected checkpoint and verify FP32 CPU ONNX parity on validation inputs."""
import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch

from pipeline.part_model import create
from pipeline.records import sha256,write_json


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--run",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    run=Path(args.run);output=Path(args.output);output.mkdir(parents=True,exist_ok=False)
    saved=torch.load(run/"checkpoint.pt",map_location="cpu",weights_only=True)
    config=saved["config"]
    network=create(config).eval()
    network.load_state_dict(saved["model"])
    if config["mode"].startswith("mobileclip"):
        import mobileclip
        network.encoder=mobileclip.reparameterize_model(network.encoder.eval())
    network=network.eval().cuda()
    torch.backends.cudnn.allow_tf32=False;torch.backends.cuda.matmul.allow_tf32=False
    metadata=json.loads((Path(config["view_cache"])/"metadata.json").read_text())
    indices=[i for i,row in enumerate(metadata["rows"]) if row["split"]=="validation"][:5]
    arrays=dict(global_image=np.load(Path(config["view_cache"])/"roi_crop.npy",mmap_mode="r"),
        parts=np.load(Path(config["part_cache"])/"parts.npy",mmap_mode="r"),
        quality=np.load(Path(config["part_cache"])/"quality.npy"),
        valid=np.load(Path(config["part_cache"])/"valid.npy"))
    names=list(arrays)
    sample=tuple(torch.from_numpy(np.array(arrays[name][indices[0]:indices[0]+1],copy=True)).cuda() for name in names)
    torch.onnx.export(network,sample,str(output/"model.onnx"),input_names=names,output_names=["logits"],
        dynamic_axes={name:{0:"batch"} for name in names}|{"logits":{0:"batch"}},opset_version=13,dynamo=False)
    onnx.checker.check_model(onnx.load(str(output/"model.onnx")))
    session=ort.InferenceSession(str(output/"model.onnx"),providers=["CPUExecutionProvider"])
    used=[item.name for item in session.get_inputs()]
    checks=[]
    for index in indices:
        values={name:np.array(array[index:index+1],copy=True) for name,array in arrays.items()}
        with torch.no_grad():
            expected=network(*(torch.from_numpy(values[name]).cuda() for name in names)).float().cpu().numpy()
        actual=session.run(None,{name:values[name] for name in used})[0]
        checks.append(dict(validation_index=index,max_abs_logit_error=float(np.max(np.abs(expected-actual))),
                           same_decision=bool(expected.argmax(1)[0]==actual.argmax(1)[0])))
    if max(c["max_abs_logit_error"] for c in checks)>.002 or not all(c["same_decision"] for c in checks):
        write_json(output/"parity.json",dict(passed=False,cases=checks))
        raise ValueError("ONNX parity check failed")
    detector=Path(config["view_cache"])/"face_detection_yunet_2023mar.onnx"
    shutil.copy2(detector,output/detector.name)
    write_json(output/"manifest.json",dict(format_version=1,mode=config["mode"],
        image_size=config["image_size"],local_size=config["local_size"],threshold=.5,
        class_order=["ordinary_glasses","camera_glasses"],source_checkpoint_sha256=sha256(run/"checkpoint.pt"),
        model_sha256=sha256(output/"model.onnx"),input_names=used,normalization="inside ONNX graph",
        geometry_policy="fixed YuNet estimates; missing geometry requires retry",opset=13,
        jetson_validation="pending"))
    write_json(output/"parity.json",dict(passed=True,cases=checks,scope="PC FP32; five validation cases; batch 1",
        jetson_validation="pending"))
    print(json.dumps(dict(output=str(output),parity=checks),indent=2))


if __name__=="__main__":main()
