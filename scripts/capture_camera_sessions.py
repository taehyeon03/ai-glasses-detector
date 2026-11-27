"""Record explicitly started inspections. Opening this script does not start recording."""
import argparse
import json
import time
import uuid
from datetime import datetime,timezone
from pathlib import Path

import cv2


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--camera",type=int,default=0)
    parser.add_argument("--output",required=True)
    parser.add_argument("--person-group",required=True)
    parser.add_argument("--product",required=True)
    parser.add_argument("--label",choices=["ordinary_glasses","camera_glasses","no_glasses"],required=True)
    parser.add_argument("--domain",choices=["real_worn","screen_recapture","product_only"],default="real_worn")
    parser.add_argument("--physical-camera-glasses-available",action="store_true")
    parser.add_argument("--consent-confirmed",action="store_true")
    parser.add_argument("--view",choices=["frontal","left","right","unknown"],default="unknown")
    parser.add_argument("--lighting",default="unreported")
    parser.add_argument("--distance-m",type=float)
    args=parser.parse_args()
    if not args.consent_confirmed:
        parser.error("Recording requires --consent-confirmed")
    if args.domain=="real_worn" and args.label=="camera_glasses" and not args.physical_camera_glasses_available:
        parser.error("Real-worn positives require a physical camera-glasses product")
    session=Path(args.output)/f"session-{uuid.uuid4().hex[:12]}"
    session.mkdir(parents=True,exist_ok=False)
    metadata=dict(session_id=session.name,person_group_id=args.person_group,product_id=args.product,
        label=args.label,truth={"ordinary_glasses":0,"camera_glasses":1,"no_glasses":None}[args.label],
        domain=args.domain,view_reported=args.view,lighting_reported=args.lighting,
        distance_m_reported=args.distance_m,consent_confirmed=True,source="user-operated camera capture",
        created_at=datetime.now(timezone.utc).isoformat(),camera_device=args.camera)
    capture=cv2.VideoCapture(args.camera)
    if not capture.isOpened():
        raise RuntimeError("Cannot open camera")
    capture.set(cv2.CAP_PROP_FRAME_WIDTH,1280)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT,720)
    metadata.update(actual_width=capture.get(cv2.CAP_PROP_FRAME_WIDTH),
                    actual_height=capture.get(cv2.CAP_PROP_FRAME_HEIGHT),camera_fps=capture.get(cv2.CAP_PROP_FPS))
    (session/"session.json").write_text(json.dumps(metadata,indent=2,ensure_ascii=False))
    inspection=None; frames=0; next_frame=0
    try:
        while True:
            ok,image=capture.read()
            if not ok:
                raise RuntimeError("Camera stopped returning frames")
            shown=image.copy()
            message="SPACE: start one inspection (5 frames); Q: quit" if inspection is None else f"Recording inspection: {frames}/5"
            cv2.putText(shown,message,(20,35),cv2.FONT_HERSHEY_SIMPLEX,.65,(0,255,0),2)
            cv2.imshow("Eyewear evaluation capture",shown)
            key=cv2.waitKey(1)&255
            if key==ord("q"):
                break
            if key==32 and inspection is None:
                inspection=uuid.uuid4().hex[:12];frames=0;next_frame=time.monotonic()
            if inspection is not None and time.monotonic()>=next_frame:
                name=f"{inspection}-{frames}.png"
                if not cv2.imwrite(str(session/name),image):
                    raise RuntimeError("Cannot save frame")
                row=dict(**metadata,inspection_id=inspection,frame_index=frames,image=name,
                         captured_at=datetime.now(timezone.utc).isoformat())
                with (session/"frames.jsonl").open("a") as stream:
                    stream.write(json.dumps(row,ensure_ascii=False)+"\n")
                frames+=1;next_frame=time.monotonic()+1
                if frames==5:
                    inspection=None
    finally:
        capture.release();cv2.destroyAllWindows()
    print(session)


if __name__=="__main__":
    main()
