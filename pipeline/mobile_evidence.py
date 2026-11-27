"""Analyse every validation image and run controlled region occlusion."""
import argparse
import itertools
import json
import random
import time
import traceback
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw
from torchvision.transforms.functional import gaussian_blur

from pipeline.mobile_train import model, normalize
from pipeline.mobile_data import clip_box
from pipeline.records import append_jsonl, metrics, provenance, sha256, write_json


def gradcam(network, images, layers=(8, 12)):
    captured = {}
    handles = []
    for layer in layers:
        def capture(module, inputs, output, index=layer):
            captured[index] = output
        handles.append(network.features[layer].register_forward_hook(capture))
    try:
        inputs = images.detach().requires_grad_(True)
        logits = network(inputs)
        gradients = torch.autograd.grad((logits[:, 1] - logits[:, 0]).sum(),
                                       [captured[layer] for layer in layers])
        maps = {layer: (gradient.mean((2, 3), keepdim=True) * captured[layer]).sum(1).detach()
                for layer, gradient in zip(layers, gradients)}
        return logits.detach(), maps
    finally:
        for handle in handles:
            handle.remove()


def load(run, device):
    checkpoint = torch.load(run / "checkpoint.pt", map_location="cpu", weights_only=True)
    network = model(pretrained=False).to(device)
    network.load_state_dict(checkpoint["model"])
    return network.eval().requires_grad_(False), checkpoint["config"]


def region_values(cam, geometry, size):
    positive = np.maximum(cam, 0)
    total = float(positive.sum())
    if geometry is None:
        return dict(positive_mass=total, regions=None)
    result = {}
    for name, (x0, y0, x1, y1) in geometry["regions"].items():
        fraction = max((x1-x0)*(y1-y0) / size**2, 1 / size**2)
        mass = float(positive[y0:y1, x0:x1].sum()) / max(total, 1e-20)
        result[name] = dict(positive_mass_fraction=mass, area_fraction=fraction,
                            enrichment=mass/fraction)
    return dict(positive_mass=total, regions=result)


def add_bridge_region(geometry, size=224):
    if geometry is None:
        return None
    updated = json.loads(json.dumps(geometry))
    eyes = np.asarray(geometry["landmarks"][:2])
    distance = float(np.linalg.norm(eyes[1]-eyes[0]))
    center = eyes.mean(0) + np.array([0., -.18*distance])
    updated["regions"]["bridge"] = clip_box([center[0]-.22*distance,center[1]-.28*distance,
                                               center[0]+.22*distance,center[1]+.28*distance],size)
    return updated


def select_cases(rows, predictions, count, seed=20261127):
    rng = random.Random(seed)
    selected = []
    for label in (0, 1):
        groups = defaultdict(list)
        for index, (row, result) in enumerate(zip(rows, predictions)):
            if row["label"] == label and row["geometry"] is not None:
                groups[(row["product_id"], result["prediction"])].append(index)
        for items in groups.values():
            rng.shuffle(items)
        keys = sorted(groups)
        quota = count // 2
        taken = 0
        while taken < quota:
            progress = False
            for key in keys:
                if groups[key] and taken < quota:
                    selected.append(groups[key].pop())
                    taken += 1
                    progress = True
            if not progress:
                raise ValueError("Not enough images with geometry for balanced occlusion")
    return sorted(selected)


def seed_stability(all_maps, rows, output):
    summaries = []
    for a, b in itertools.combinations(sorted(all_maps), 2):
        first, second = all_maps[a], all_maps[b]
        values = []
        for index, (x, y) in enumerate(zip(first, second)):
            x, y = np.maximum(x, 0).ravel(), np.maximum(y, 0).ravel()
            valid = bool(x.sum() > 1e-12 and y.sum() > 1e-12 and x.std() > 1e-12 and y.std() > 1e-12)
            row = dict(sample_id=rows[index]["sample_id"], product_id=rows[index]["product_id"],
                       identity_group_id=rows[index]["identity_group_id"], seeds=[a, b], valid=valid)
            if valid:
                k = max(1, round(len(x)*.1))
                overlap = len(set(np.argpartition(x, -k)[-k:]) & set(np.argpartition(y, -k)[-k:])) / k
                row.update(top10_overlap=overlap, pearson=float(np.corrcoef(x, y)[0, 1]))
                values.append(row)
            append_jsonl(output / "seed-stability.jsonl", row)
        summaries.append(dict(seeds=[a,b], n_valid=len(values), n_excluded=len(rows)-len(values),
            top10_overlap_mean=float(np.mean([v["top10_overlap"] for v in values])) if values else None,
            pearson_mean=float(np.mean([v["pearson"] for v in values])) if values else None))
    return summaries


def show_case(rgb, signed, row, prediction, output):
    fig, axes = plt.subplots(1, 3, figsize=(11, 4), layout="constrained")
    for ax in axes:
        ax.imshow(rgb)
        ax.axis("off")
    axes[0].set_title(f"Truth={row['label']}; prediction={prediction}")
    if row["geometry"]:
        for name in ["glasses", "outer_left", "outer_right"]:
            x0,y0,x1,y1 = row["geometry"]["regions"][name]
            axes[1].add_patch(plt.Rectangle((x0,y0),x1-x0,y1-y0,fill=False,
                                           edgecolor="lime" if name=="glasses" else "orange", linewidth=1.5))
    axes[1].set_title("Estimated regions; review pending")
    bound = max(float(np.abs(signed).max()), 1e-12)
    axes[2].imshow(signed, cmap="bwr", vmin=-bound, vmax=bound, alpha=.55)
    axes[2].set_title("Signed CAM: camera minus ordinary")
    fig.savefig(output, dpi=140)
    plt.close(fig)


@torch.no_grad()
def occlusion(network, images, rows, predictions, selected, config, output):
    rng = np.random.default_rng(20261127)
    all_records = []
    size = config["image_size"]
    for step, index in enumerate(selected):
        original = normalize(images[index:index+1])
        geometry = rows[index]["geometry"]
        region_names, rectangles, layout = [], [], []
        for name, box in geometry["regions"].items():
            x0,y0,x1,y1 = box
            width, height = x1-x0, y1-y0
            start = len(rectangles)
            rectangles.append(box)
            for _ in range(config["occlusion_random_repeats"]):
                x = int(rng.integers(0, size-width+1))
                y = int(rng.integers(0, size-height+1))
                rectangles.append([x,y,x+width,y+height])
            layout.append((name,start,len(rectangles)))
        masks = torch.zeros(len(rectangles),1,size,size,dtype=torch.bool,device=images.device)
        for i,(x0,y0,x1,y1) in enumerate(rectangles):
            masks[i,:,y0:y1,x0:x1] = True
        reference_margins = []
        for begin in range(0,len(rectangles),config["eval_batch_size"]):
            count = min(config["eval_batch_size"],len(rectangles)-begin)
            reference = network(original.expand(count,-1,-1,-1).contiguous())
            reference_margins.append(reference[:,1]-reference[:,0])
        reference_margins = torch.cat(reference_margins).cpu().numpy()
        original_margin = float(reference_margins[0])
        for baseline_name, baseline in [("mean", torch.zeros_like(original)),
                                         ("blur", gaussian_blur(original,[31,31],[10,10]))]:
            perturbed = torch.where(masks, baseline, original)
            margins = []
            for batch in perturbed.split(config["eval_batch_size"]):
                scores = network(batch)
                margins.append(scores[:,1]-scores[:,0])
            drops = reference_margins-torch.cat(margins).cpu().numpy()
            true_sign = 2*rows[index]["label"]-1
            for name,start,end in layout:
                random_drops = drops[start+1:end]
                record = dict(sample_id=rows[index]["sample_id"], product_id=rows[index]["product_id"],
                    identity_group_id=rows[index]["identity_group_id"], truth=rows[index]["label"],
                    prediction=predictions[index]["prediction"], region=name, baseline=baseline_name,
                    geometry_confidence=geometry["confidence"], geometry_review="pending",
                    original_camera_margin=original_margin, camera_margin_drop=float(drops[start]),
                    true_margin_drop=float(true_sign*drops[start]),
                    random_camera_margin_drop_mean=float(random_drops.mean()),
                    random_true_margin_drop_mean=float(true_sign*random_drops.mean()),
                    random_camera_margin_drop_std=float(random_drops.std()),
                    random_camera_margin_drops=random_drops.tolist(),
                    matched_reference_batch_size=len(rectangles),
                    area_pixels=int(masks[start].sum().item()))
                append_jsonl(output / "occlusion.jsonl", record)
                all_records.append(record)
        if step % 25 == 0:
            print(f"occlusion {step}/{len(selected)}", flush=True)
    groups = defaultdict(list)
    for record in all_records:
        groups[(record["region"], record["baseline"], record["truth"], record["prediction"])].append(record)
    return [dict(region=key[0], baseline=key[1], truth=key[2], prediction=key[3], n=len(records),
        true_margin_drop_mean=float(np.mean([r["true_margin_drop"] for r in records])),
        random_true_margin_drop_mean=float(np.mean([r["random_true_margin_drop_mean"] for r in records])),
        targeted_exceeds_random_count=sum(r["true_margin_drop"]>r["random_true_margin_drop_mean"] for r in records))
        for key, records in sorted(groups.items())]


def analyse(config, runs, output):
    metadata = json.loads((Path(config["view_cache"])/"metadata.json").read_text())
    rows = [dict(r,geometry=add_bridge_region(r["geometry"],config["image_size"]))
            for r in metadata["rows"] if r["split"]=="validation"]
    all_rows = metadata["rows"]
    indices = [i for i,r in enumerate(all_rows) if r["split"]=="validation"]
    full = np.load(Path(config["view_cache"])/"full.npy", mmap_mode="r")
    images = torch.from_numpy(np.asarray(full[indices]).copy()).cuda()
    write_json(output / "validation-index.json", [dict(index=i,sample_id=r["sample_id"],
        product_id=r["product_id"],identity_group_id=r["identity_group_id"],label=r["label"],
        geometry_review=r["geometry_review"]) for i,r in enumerate(rows)])
    candidates, maps_by_seed, records_for_groups = [], {}, []
    for seed in config["seeds"]:
        run = runs/f"mobilenet-full-s{seed}"
        network, _ = load(run, "cuda")
        predictions = [json.loads(v) for v in (run/"validation-predictions.jsonl").read_text().splitlines()]
        saved = json.loads((run/"summary.json").read_text())
        result = saved["final"]["validation"]
        candidates.append((result["macro_f1"],-result["false_positive_rate"],-result["loss"],seed))
        arrays = {layer: [] for layer in config["gradcam_layers"]}
        probabilities = []
        for begin in range(0,len(rows),config["eval_batch_size"]):
            batch = images[begin:begin+config["eval_batch_size"]]
            logits, cams = gradcam(network,normalize(batch),config["gradcam_layers"])
            probabilities.extend(logits.softmax(1)[:,1].tolist())
            for layer, cam in cams.items():
                arrays[layer].append(cam.cpu().numpy())
        arrays = {layer:np.concatenate(values) for layer,values in arrays.items()}
        np.savez_compressed(output/f"gradcam-s{seed}.npz",**{f"layer{layer}_signed":v for layer,v in arrays.items()})
        maps_by_seed[seed] = arrays[8]
        discrepancy = max(abs(a-b["camera_probability"]) for a,b in zip(probabilities,predictions))
        if discrepancy > 1e-4:
            raise ValueError(f"Explanation model differs from recorded predictions: {discrepancy}")
        for layer, values in arrays.items():
            upsampled = F.interpolate(torch.from_numpy(values)[:,None],size=(224,224),mode="bilinear",align_corners=False)[:,0].numpy()
            for index,(row,cam) in enumerate(zip(rows,upsampled)):
                item = dict(seed=seed,layer=layer,sample_id=row["sample_id"],product_id=row["product_id"],
                    identity_group_id=row["identity_group_id"],truth=row["label"],prediction=predictions[index]["prediction"],
                    **region_values(cam,row["geometry"],224))
                append_jsonl(output/"region-cam.jsonl",item)
                records_for_groups.append(item)
        print(f"Grad-CAM completed: seed={seed}, n={len(rows)}, two layers",flush=True)
        del network
        torch.cuda.empty_cache()
    stability = seed_stability(maps_by_seed, rows, output)
    best_seed = max(candidates)[-1]
    write_json(output/"model-selection.json",dict(seed=best_seed,source="validation only",candidates=candidates))
    run = runs/f"mobilenet-full-s{best_seed}"
    network,_ = load(run,"cuda")
    predictions = [json.loads(v) for v in (run/"validation-predictions.jsonl").read_text().splitlines()]
    selected = select_cases(rows,predictions,config["occlusion_samples"])
    write_json(output/"occlusion-selection.json",dict(indices=selected,n=len(selected),
        seed=20261127,policy="balanced classes; round-robin across product and prediction strata; no CAM selection",
        products=len({rows[i]["product_id"] for i in selected}),annotation_status="automatic geometry; review pending"))
    preview = output/"review"
    preview.mkdir()
    signed = F.interpolate(torch.from_numpy(maps_by_seed[best_seed])[:,None],size=(224,224),mode="bilinear",align_corners=False)[:,0].numpy()
    # Save all 300 cases for review. The first 12 are also rendered with a CAM overlay.
    links = []
    for position,index in enumerate(selected):
        rgb = images[index].permute(1,2,0).cpu().numpy()
        picture = Image.fromarray(rgb)
        draw = ImageDraw.Draw(picture)
        for name,box in rows[index]["geometry"]["regions"].items():
            draw.rectangle(box,outline="lime" if name=="glasses" else "orange",width=1)
        picture.save(preview/f"regions-{index}.png")
        links.append(f'<figure><img src="regions-{index}.png"><figcaption>index={index}; truth={rows[index]["label"]}; prediction={predictions[index]["prediction"]}; review pending</figcaption></figure>')
        if position < 12:
            show_case(rgb,signed[index],rows[index],predictions[index]["prediction"],preview/f"cam-{index}.png")
    (preview/"index.html").write_text('<!doctype html><meta charset="utf-8"><title>Automatic ROI review</title><style>body{font-family:sans-serif}main{display:flex;flex-wrap:wrap}figure{width:240px}img{width:224px}</style><h1>Automatic regions; manual review pending</h1><main>'+''.join(links)+'</main>')
    occlusion_summary = occlusion(network,images,rows,predictions,selected,config,output)
    write_json(output/"occlusion-summary.json",occlusion_summary)
    # Aggregate geometry-adjusted positive CAM values without publishing source images.
    grouped = defaultdict(list)
    for row in records_for_groups:
        if row["regions"] is None or row["positive_mass"] <= 1e-12:
            continue
        for category,value in [("overall","all"),("product",row["product_id"]),
                               ("identity_group",row["identity_group_id"]),
                               ("outcome",f"{row['truth']}->{row['prediction']}")]:
            for region,values in row["regions"].items():
                grouped[(row["seed"],row["layer"],category,value,region)].append(values)
    aggregates = [dict(seed=k[0],layer=k[1],group_type=k[2],group=k[3],region=k[4],n=len(v),
        positive_mass_fraction_mean=float(np.mean([x["positive_mass_fraction"] for x in v])),
        enrichment_mean=float(np.mean([x["enrichment"] for x in v]))) for k,v in grouped.items()]
    write_json(output/"region-summary.json",aggregates)
    write_json(output/"summary.json",dict(validation_images_per_seed=len(rows),seeds=config["seeds"],
        layers=config["gradcam_layers"],explained_image_model_pairs=len(rows)*len(config["seeds"]),
        selected_seed=best_seed,seed_stability=stability,occlusion_images=len(selected),
        geometry_missing_validation=sum(r["geometry"] is None for r in rows),
        exact_camera_annotations="pending",manual_geometry_review="pending",jetson_validation="pending"))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--config",required=True)
    parser.add_argument("--runs",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    config=json.loads(Path(args.config).read_text())
    output=Path(args.output)
    output.mkdir(parents=True,exist_ok=False)
    started=time.time()
    write_json(output/"status.json",dict(state="running",kind="validation_evidence"))
    meta=provenance(dict(config,seed=20261127))
    meta.update(kind="validation_evidence",training_runs=args.runs)
    write_json(output/"provenance.json",meta)
    try:
        analyse(config,Path(args.runs),output)
    except BaseException:
        write_json(output/"status.json",dict(state="failed",traceback=traceback.format_exc()))
        raise
    write_json(output/"status.json",dict(state="completed",elapsed_seconds=time.time()-started,
        kind="validation_evidence",jetson_validation="pending"))


if __name__=="__main__":
    main()
