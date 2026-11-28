"""Run every case of a shared YouTube test set with one model bundle.

python -m scripts.youtube_testset --set youtube_test/v1.json --check
python -m scripts.youtube_testset --set youtube_test/v1.json --model mobilenet-crop-s44
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline.records import write_json
from pipeline.youtube_timeline import (DEFAULT_MODELS, DEFAULT_ROOT, LABELS, git_state, parse_time,
                                       parse_timeline, run_test)

VIEWS = {"frontal", "three_quarter", "profile", "mixed"}
REVIEW = {"pending_human_review", "confirmed"}
OVERLAP = {"in_training", "same_family", "ood", "not_applicable"}
PERSON = {"korean", "non_korean", "unknown"}
PRODUCTS = Path(__file__).resolve().parent.parent / "youtube_test" / "training-products-20261127.json"


def load_set(path):
    """Validate the set file. Raise ValueError with every problem found."""
    data = json.loads(Path(path).read_text())
    problems, seen = [], set()
    if not data.get("name"):
        problems.append("세트에 name이 없습니다")
    for i, case in enumerate(data.get("cases") or []):
        where = f"cases[{i}] {case.get('id', '?')}"
        if not case.get("id") or case["id"] in seen:
            problems.append(f"{where}: id가 없거나 중복입니다")
        seen.add(case.get("id"))
        if not str(case.get("url", "")).startswith(("https://www.youtube.com/", "https://youtu.be/")):
            problems.append(f"{where}: YouTube 주소가 아닙니다")
        if (case.get("review") or {}).get("status") not in REVIEW:
            problems.append(f"{where}: review.status는 {sorted(REVIEW)} 중 하나여야 합니다")
        if case.get("training_overlap") not in OVERLAP:
            problems.append(f"{where}: training_overlap는 {sorted(OVERLAP)} 중 하나여야 합니다")
        if case.get("person_group", "unknown") not in PERSON:
            problems.append(f"{where}: person_group은 {sorted(PERSON)} 중 하나여야 합니다")
        if case.get("person_group", "unknown") != "unknown" and not case.get("person_group_basis"):
            problems.append(f"{where}: person_group을 적으려면 person_group_basis(근거)가 필요합니다")
        known = training_product_ids()
        for pid in case.get("training_product_ids") or []:
            if known and pid not in known:
                problems.append(f"{where}: 학습 제품 목록에 없는 product_id {pid}")
        if case.get("training_overlap") in ("in_training", "same_family") and not case.get("training_product_ids"):
            problems.append(f"{where}: in_training/same_family에는 training_product_ids가 필요합니다")
        if not case.get("segments"):
            problems.append(f"{where}: segments가 비어 있습니다")
        for j, seg in enumerate(case.get("segments") or []):
            try:
                if seg.get("label") not in LABELS.values():
                    raise ValueError(f"label {seg.get('label')!r}")
                if seg.get("view", "mixed") not in VIEWS:
                    raise ValueError(f"view {seg.get('view')!r}")
                parse_timeline(timeline(case)[j])
            except (ValueError, KeyError) as error:
                problems.append(f"{where} segments[{j}]: {error}")
    if not data.get("cases"):
        problems.append("cases가 비어 있습니다")
    if problems:
        raise ValueError("\n".join(problems))
    return data


def training_product_ids():
    if not PRODUCTS.exists():
        return set()
    return {p["product_id"] for p in json.loads(PRODUCTS.read_text())["products"]}


def overlap_of(case, label):
    """Glasses-free segments never overlap with a training product."""
    return "not_applicable" if label == "no_glasses" else case["training_overlap"]


def timeline(case):
    return [f"{s['start']}-{s['end']}={s['label']}" for s in case["segments"]]


def rate(segments, label):
    items = [s for s in segments if s["label"] == label and s["prediction"] is not None]
    if not items:
        return None, 0
    return sum(s["prediction"] == "camera_glasses" for s in items) / len(items), len(items)


def report(data, model, runs):
    segments = []
    for case, record in runs:
        for meta, result in zip(case["segments"], record.get("segments") or []):
            segments.append(dict(case_id=case["id"], product=case.get("product"),
                                 training_overlap=overlap_of(case, meta["label"]),
                                 person_group=meta.get("person_group", case.get("person_group", "unknown")),
                                 review=case["review"]["status"], view=meta.get("view", "mixed"),
                                 start=meta["start"], end=meta["end"], label=result["label"],
                                 verdict=result["verdict"], prediction=result["prediction"],
                                 mean_score=result["mean_score"], n_scored=result["n_scored"],
                                 n_frames=result["n_frames"], run_id=record["run_id"]))
    def block(items):
        fpr, n_neg = rate(items, "ordinary_glasses")
        recall, n_pos = rate(items, "camera_glasses")
        decided = [s for s in items if s["prediction"] is not None]
        return dict(n_segments=len(items), n_held=len(items) - len(decided),
                    alarm_rate=sum(s["prediction"] == "camera_glasses" for s in decided) / len(decided) if decided else None,
                    n_ordinary_decided=n_neg, false_positive_rate=fpr,
                    n_camera_decided=n_pos, camera_recall=recall)
    return dict(schema_version=1, testset=data["name"], domain="youtube_video", unit="segment",
                created_at=datetime.now(timezone.utc).isoformat(), model=model, **git_state(),
                failed_cases=[c["id"] for c, r in runs if r["status"] != "completed"],
                overall=block(segments),
                confirmed_only=block([s for s in segments if s["review"] == "confirmed"]),
                by_training_overlap={o: block([s for s in segments if s["training_overlap"] == o])
                                     for o in sorted({s["training_overlap"] for s in segments})},
                by_person_group={g: block([s for s in segments if s["person_group"] == g])
                                 for g in sorted({s["person_group"] for s in segments})},
                by_view={v: block([s for s in segments if s["view"] == v])
                         for v in sorted({s["view"] for s in segments})},
                segments=segments, jetson_validation="pending",
                interpretation="Online video domain. Not merged with real_worn. Products may overlap training data.")


def markdown(result):
    def pct(v):
        return "null" if v is None else f"{v:.1%}"
    o = result["overall"]
    lines = [f"# {result['testset']} · {result['model']['display_name']}", "",
             f"- 생성: {result['created_at']}", f"- Git: {result['git_commit']} ({result['git_branch']})",
             f"- 구간 {o['n_segments']}개 중 판정 보류 {o['n_held']}개",
             f"- 일반 안경 오탐률: {pct(o['false_positive_rate'])} (판정 구간 {o['n_ordinary_decided']})",
             f"- 카메라 안경 재현율: {pct(o['camera_recall'])} (판정 구간 {o['n_camera_decided']})",
             f"- 사람이 확인한 구간만: 오탐률 {pct(result['confirmed_only']['false_positive_rate'])},"
             f" 재현율 {pct(result['confirmed_only']['camera_recall'])}",
             f"- 실패한 영상: {', '.join(result['failed_cases']) or '없음'}", "",
             "| 학습 제품과의 관계 | 구간 | 보류 | 경보율 | 일반 안경 오탐률 | 카메라 안경 재현율 |", "|---|---|---|---|---|---|"]
    for name, b in result["by_training_overlap"].items():
        lines.append(f"| {name} | {b['n_segments']} | {b['n_held']} | {pct(b['alarm_rate'])} | {pct(b['false_positive_rate'])} (n={b['n_ordinary_decided']})"
                     f" | {pct(b['camera_recall'])} (n={b['n_camera_decided']}) |")
    lines += ["", "| 인물 그룹 | 구간 | 보류 | 경보율 | 일반 안경 오탐률 | 카메라 안경 재현율 |", "|---|---|---|---|---|---|"]
    for name, b in result["by_person_group"].items():
        lines.append(f"| {name} | {b['n_segments']} | {b['n_held']} | {pct(b['alarm_rate'])} | {pct(b['false_positive_rate'])}"
                     f" (n={b['n_ordinary_decided']}) | {pct(b['camera_recall'])} (n={b['n_camera_decided']}) |")
    lines += ["",
             "| 영상 | 학습 관계 | 구간 | 시점 | 정답 | 판정 | 평균 점수 | 판정 프레임 | 확인 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for s in result["segments"]:
        score = "–" if s["mean_score"] is None else f"{s['mean_score']:.3f}"
        lines.append(f"| {s['case_id']} | {s['training_overlap']} | {s['start']}–{s['end']} | {s['view']} | {s['label']} | {s['verdict']}"
                     f" | {score} | {s['n_scored']}/{s['n_frames']} | {s['review']} |")
    lines += ["", "온라인 영상 결과는 실제 착용 평가와 합치지 않는다.",
              "in_training과 same_family 결과는 처음 보는 제품의 성능이 아니다.",
              "ood 결과만 학습에 없던 제품에 대한 결과로 본다. 영상과 학습 사진의 촬영 조건도 다르다."]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", required=True)
    parser.add_argument("--check", action="store_true", help="Validate the set file only")
    parser.add_argument("--model")
    parser.add_argument("--models-root", default=str(DEFAULT_MODELS))
    parser.add_argument("--only-confirmed", action="store_true")
    parser.add_argument("--person-group", choices=sorted(PERSON), action="append",
                        help="Run only cases with this person_group (repeatable)")
    parser.add_argument("--overlap", choices=sorted(OVERLAP), action="append",
                        help="Run only cases with this training_overlap (repeatable)")
    parser.add_argument("--fps", type=float)
    parser.add_argument("--save-frames", action="store_true")
    parser.add_argument("--rebuild", help="Recompute report.json/report.md in this report folder from its run records")
    parser.add_argument("--output", default=str(DEFAULT_ROOT))
    args = parser.parse_args()
    data = load_set(args.set)
    if args.rebuild:
        out = Path(args.rebuild)
        old = json.loads((out / "report.json").read_text())
        run_of = {s["case_id"]: s["run_id"] for s in old["segments"]}
        runs = [(c, json.loads((Path(args.output) / run_of[c["id"]] / "run.json").read_text()))
                for c in data["cases"] if c["id"] in run_of]
        result = report(data, old["model"], runs)
        result["created_at"] = old["created_at"]
        write_json(out / "report.json", result)
        (out / "report.md").write_text(markdown(result))
        print(markdown(result))
        return
    cases = [c for c in data["cases"] if (not args.only_confirmed or c["review"]["status"] == "confirmed")
             and (not args.overlap or c["training_overlap"] in args.overlap)
             and (not args.person_group or c.get("person_group", "unknown") in args.person_group)]
    n_seg = sum(len(c["segments"]) for c in cases)
    print(f"{data['name']}: 영상 {len(cases)}개, 구간 {n_seg}개 · 형식 검사 통과")
    if args.check:
        return
    if not args.model:
        parser.error("--model is required unless --check")
    from pipeline.onnx_runtime import Runtime
    bundle = Path(args.model) if Path(args.model).is_dir() else Path(args.models_root) / args.model
    runtime = Runtime(bundle)
    fps = args.fps or data.get("defaults", {}).get("fps", 2.0)
    runs = []
    for case in cases:
        print(f"\n=== {case['id']} ===", flush=True)
        record = run_test(bundle, case["url"], ", ".join(timeline(case)), fps=fps,
                          save_frames=args.save_frames, output_root=args.output, runtime=runtime,
                          note=f"testset={data['name']} case={case['id']}")
        runs.append((case, record))
    meta = runtime.metadata
    model = dict(id=bundle.name, display_name=meta.get("display_name", meta.get("mode")),
                 threshold=meta["threshold"], model_sha256=meta.get("model_sha256"))
    result = report(data, model, runs)
    out = Path(args.output) / "sets" / f"{data['name']}-{bundle.name}-{datetime.now():%Y%m%d-%H%M%S}"
    write_json(out / "report.json", result)
    (out / "report.md").write_text(markdown(result))
    print("\n" + markdown(result))
    print(f"기록: {out}")


if __name__ == "__main__":
    main()
