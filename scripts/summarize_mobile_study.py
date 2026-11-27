"""Export numerical records and figures that contain no source photographs."""
import argparse
import json
import shutil
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pipeline.records import write_json
from scripts.validate_run import validate


def summarize(root, evidence, output):
    output.mkdir(parents=True,exist_ok=False)
    records=[]
    for run in sorted(root.glob("mobilenet-*-s*")):
        validation=validate(run)
        summary=json.loads((run/"summary.json").read_text())
        provenance=json.loads((run/"provenance.json").read_text())
        architecture=json.loads((run/"model.json").read_text())
        config=provenance["config"]
        target=output/run.name
        target.mkdir()
        for name in ["summary.json","metrics.jsonl","record-validation.json"]:
            shutil.copy2(run/name,target/name)
        records.append(dict(run_id=run.name,view=config["view"],seed=config["seed"],
            git_commit=provenance["git_commit"],git_branch=provenance["git_branch"],
            git_dirty=provenance["git_dirty"],best_epoch=summary["best_epoch"],
            parameters=architecture["parameters"],pretrained_sha256=architecture["pretrained_sha256"],
            final=summary["final"],checkpoint_sha256=summary["checkpoint_sha256"],
            record_validation=validation))
    if len(records)!=9:
        raise ValueError("Expected all nine predeclared runs")
    aggregate=[]
    for view in ["full","roi_mask","roi_crop"]:
        runs=[r for r in records if r["view"]==view]
        result=dict(view=view,seeds=[r["seed"] for r in runs])
        for split in ["validation","test"]:
            result[split]={}
            for field in ["loss","accuracy","macro_f1","false_positive_rate","camera_recall"]:
                values=[r["final"][split][field] for r in runs]
                result[split][field]=dict(mean=float(np.mean(values)),std_across_seeds=float(np.std(values,ddof=1)),values=values)
        aggregate.append(result)
    best_view=max(aggregate,key=lambda r:r["validation"]["macro_f1"]["mean"])["view"]
    best=max([r for r in records if r["view"]==best_view],key=lambda r:(
        r["final"]["validation"]["macro_f1"],-r["final"]["validation"]["false_positive_rate"],
        -r["final"]["validation"]["loss"]))
    cache=json.loads((Path(provenance["config"]["view_cache"])/"metadata.json").read_text())
    geometry={split:dict(n=sum(r["split"]==split for r in cache["rows"]),
        failed=sum(r["split"]==split and r["geometry"] is None for r in cache["rows"]),
        low_confidence=sum(r["split"]==split and r["low_confidence_detection"] for r in cache["rows"]))
        for split in ["train","validation","test"]}
    result=dict(runs=records,aggregate=aggregate,selected_run=best["run_id"],
        selection="highest mean validation macro-F1 selects view; highest validation macro-F1 selects seed; FPR/loss break seed ties",
        geometry=geometry,source_manifest_sha256=cache["source_manifest_sha256"],
        dataset_revision=provenance["config"]["dataset_revision"],jetson_validation="pending",
        notes=["Standard deviations describe three optimizer seeds on the same fixed split, not population confidence intervals",
               "Every split contains known products; this is not an unseen-product benchmark",
               "Automatic regions are estimates; exact camera annotations and manual geometry review remain pending"])
    write_json(output/"comparison.json",result)
    for name in ["summary.json","occlusion-summary.json","model-selection.json","occlusion-selection.json"]:
        content=json.loads((evidence/name).read_text())
        if name=="occlusion-selection.json":
            content.pop("indices",None)
        write_json(output/f"evidence-{name}",content)
    regions=json.loads((evidence/"region-summary.json").read_text())
    write_json(output/"evidence-region-overall.json",[r for r in regions if r["group_type"]=="overall"])
    fig,axes=plt.subplots(1,2,figsize=(10,4),layout="constrained")
    labels=["Full image","Outside ROI masked","ROI enlarged"]
    for ax,split in zip(axes,["validation","test"]):
        for i,row in enumerate(aggregate):
            values=np.asarray(row[split]["macro_f1"]["values"])*100
            ax.scatter([i-.07,i,i+.07],values,s=30)
            ax.errorbar(i,float(values.mean()),yerr=float(values.std(ddof=1)),color="black",capsize=4)
        ax.set(xticks=range(3),xticklabels=labels,ylabel="Macro-F1 (%)",title=split.capitalize())
        ax.tick_params(axis="x",labelsize=8)
        ax.grid(axis="y",alpha=.2)
    fig.suptitle("MobileNetV3-Small; three seeds; synthetic known-product evaluation")
    fig.savefig(output/"comparison.png",dpi=170)
    fig.savefig(output/"comparison.svg")
    plt.close(fig)
    occlusion=json.loads((evidence/"occlusion-summary.json").read_text())
    subset=[r for r in occlusion if r["truth"]==1 and r["prediction"]==1 and r["baseline"]=="blur"]
    fig,ax=plt.subplots(figsize=(11,4),layout="constrained")
    x=np.arange(len(subset))
    ax.bar(x-.18,[r["true_margin_drop_mean"] for r in subset],width=.36,label="Target region")
    ax.bar(x+.18,[r["random_true_margin_drop_mean"] for r in subset],width=.36,label="Same-size random region")
    ax.set(xticks=x,xticklabels=[r["region"] for r in subset],ylabel="Mean drop in camera margin",
           title=f"Blur occlusion; {subset[0]['n']} correctly classified camera examples")
    ax.tick_params(axis="x",rotation=25,labelsize=8)
    ax.legend()
    fig.savefig(output/"occlusion.png",dpi=170)
    fig.savefig(output/"occlusion.svg")
    plt.close(fig)
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--runs",required=True)
    parser.add_argument("--evidence",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    result=summarize(Path(args.runs),Path(args.evidence),Path(args.output))
    print(json.dumps(dict(selected_run=result["selected_run"],aggregate=result["aggregate"]),indent=2))
