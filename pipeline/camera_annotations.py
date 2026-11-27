"""Validate user-created camera annotations without promoting automatic regions to truth."""
import json
from datetime import datetime,timezone
from pathlib import Path

KINDS={"camera_aperture","optical_lens","decorative_rivet","indicator_light"}


def validate_annotation(value,row,width,height):
    reviewer=str(value.get("reviewer","")).strip()
    if not reviewer:
        raise ValueError("Enter an annotator identifier")
    visibility=value.get("visibility")
    if visibility not in ["visible","occluded","uncertain","not_applicable"]:
        raise ValueError("Choose camera visibility")
    objects=[]
    for obj in value.get("objects",[]):
        if obj.get("kind") not in KINDS:
            raise ValueError("Unknown object kind")
        box=obj.get("box",[])
        if len(box)!=4:
            raise ValueError("Expected x0,y0,x1,y1")
        x0,y0,x1,y1=map(float,box)
        if not (0<=x0<x1<=width and 0<=y0<y1<=height):
            raise ValueError("Box is outside the original image")
        objects.append(dict(kind=obj["kind"],box=[x0,y0,x1,y1]))
    cameras=[o for o in objects if o["kind"]=="camera_aperture"]
    if visibility=="visible" and not cameras:
        raise ValueError("Visible camera requires at least one aperture box")
    if visibility in ["occluded","not_applicable"] and cameras:
        raise ValueError("Do not invent a box for an invisible camera")
    conflict=bool((cameras and row["label"]==0) or (visibility=="not_applicable" and row["label"]==1))
    reference_checked=bool(value.get("reference_checked"))
    status="confirmed" if visibility!="uncertain" and reference_checked and not conflict else "needs_review"
    return dict(sample_id=row["sample_id"],product_id=row["product_id"],split=row["split"],
        original_label=row["label"],width=width,height=height,objects=objects,visibility=visibility,
        reviewer=reviewer,reference_checked=reference_checked,reference=str(value.get("reference","")),
        label_conflict=conflict,status=status,source="user annotation interface",
        created_at=datetime.now(timezone.utc).isoformat())


def latest(path):
    records={}
    if Path(path).exists():
        for line in Path(path).read_text().splitlines():
            row=json.loads(line);records[row["sample_id"]]=row
    return records
