"""Aggregate independent inspections. Missing positives never become zero recall."""
from collections import defaultdict
import math

from pipeline.records import metrics


def aggregate(records,threshold=.5):
    groups=defaultdict(list)
    for row in records:
        if row["label"] not in ["ordinary_glasses","camera_glasses","no_glasses"]:
            raise ValueError("Unknown inspection label")
        probability=row.get("camera_probability")
        if probability is not None and (not math.isfinite(probability) or not 0<=probability<=1):
            raise ValueError("Invalid camera probability")
        if not row.get("consent_confirmed"):
            raise ValueError("Capture consent was not confirmed")
        if row["domain"] not in ["real_worn","screen_recapture","product_only"]:
            raise ValueError("Unrecognized evaluation domain")
        groups[(row["domain"],row["session_id"],row["inspection_id"])].append(row)
    domains=defaultdict(list)
    for (domain,session,inspection),frames in groups.items():
        if len({r["label"] for r in frames})!=1:
            raise ValueError("Labels changed within one inspection")
        if len({r["person_group_id"] for r in frames})!=1:
            raise ValueError("Person groups changed within one inspection")
        valid=[r for r in frames if r.get("camera_probability") is not None]
        if len(frames)!=5:
            outcome="incomplete_capture"
        elif len(valid)!=5:
            outcome="retry_required"
        else:
            outcome="scored"
        score=sum(r["camera_probability"] for r in valid)/len(valid) if valid else None
        domains[domain].append(dict(session_id=session,inspection_id=inspection,
            label=frames[0]["label"],outcome=outcome,score=score,
            prediction=int(score>=threshold) if score is not None and outcome=="scored" else None,
            frame_count=len(frames),valid_frames=len(valid)))
    result={}
    for domain,inspections in domains.items():
        scored=[r for r in inspections if r["outcome"]=="scored"]
        negative=[r for r in scored if r["label"]=="ordinary_glasses"]
        positive=[r for r in scored if r["label"]=="camera_glasses"]
        bare=[r for r in scored if r["label"]=="no_glasses"]
        fp=sum(r["prediction"]==1 for r in negative)
        tp=sum(r["prediction"]==1 for r in positive)
        cm=[[len(negative)-fp,fp],[len(positive)-tp,tp]]
        binary=negative+positive
        complete_metrics=None
        if negative and positive:
            labels=[int(r["label"]=="camera_glasses") for r in binary]
            loss=sum(-math.log(max(min(r["score"] if label else 1-r["score"],1-1e-12),1e-12))
                     for r,label in zip(binary,labels))/len(binary)
            complete_metrics=metrics(labels,[r["prediction"] for r in binary],loss)
        result[domain]=dict(n_inspections=len(inspections),n_scored=len(scored),n_negative=len(negative),
            n_positive=len(positive),confusion_matrix=cm,class_order=["ordinary_glasses","camera_glasses"],
            false_positive_rate=fp/len(negative) if negative else None,
            camera_recall=tp/len(positive) if positive else None,
            no_glasses_alarm_rate=sum(r["prediction"]==1 for r in bare)/len(bare) if bare else None,
            retry_rate=sum(r["outcome"]=="retry_required" for r in inspections)/len(inspections),
            incomplete_inspections=sum(r["outcome"]=="incomplete_capture" for r in inspections),
            coverage=len(scored)/len(inspections),
            loss=complete_metrics["loss"] if complete_metrics else None,
            accuracy=complete_metrics["accuracy"] if complete_metrics else None,
            macro_f1=complete_metrics["macro_f1"] if complete_metrics else None,
            threshold=threshold,aggregation="mean of five frame probabilities; missing geometry requires retry",
            camera_recall_status="measured" if positive else "pending: no positive inspections",
            inspections=inspections)
    return result
