"""User-operated laptop preview. Camera stays off until Start is pressed."""
import argparse
import json
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageTk

from pipeline.live_inspection import Recorder
from pipeline.onnx_runtime import Runtime


def camera_worker(device, runtime, stopped, updates):
    capture = cv2.VideoCapture(device)
    try:
        if not capture.isOpened():
            raise RuntimeError(f"카메라 {device}를 열 수 없습니다. 다른 앱의 카메라 사용을 확인하세요.")
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        while not stopped.is_set():
            start = time.perf_counter()
            ok, bgr = capture.read()
            read_ms = (time.perf_counter()-start)*1000
            if not ok:
                raise RuntimeError("카메라에서 프레임을 받지 못했습니다.")
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            prediction = runtime.predict(rgb)
            prediction.update(camera_read_ms=read_ms, width=rgb.shape[1], height=rgb.shape[0])
            if updates.full():
                try:
                    updates.get_nowait()
                except queue.Empty:
                    pass
            updates.put((rgb, prediction, None))
    except Exception as error:
        if updates.full():
            updates.get_nowait()
        updates.put((None, None, str(error)))
    finally:
        capture.release()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--check-camera", action="store_true", help="Read one frame and infer; save no image")
    parser.add_argument("--image", help="Check a saved image without opening a camera")
    args = parser.parse_args()
    runtime = Runtime(args.bundle)
    if args.image or args.check_camera:
        if args.image:
            rgb = np.asarray(Image.open(args.image).convert("RGB"))
        else:
            capture = cv2.VideoCapture(args.camera)
            try:
                if not capture.isOpened():
                    raise RuntimeError("Cannot open camera")
                capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                ok, bgr = capture.read()
                if not ok:
                    raise RuntimeError("Cannot read camera")
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            finally:
                capture.release()
        print(json.dumps(dict(**runtime.predict(rgb), images_saved=False, width=rgb.shape[1], height=rgb.shape[0])))
        return

    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("카메라 안경 · 노트북 테스트")
    root.geometry("1060x840")
    root.minsize(900, 760)
    ttk.Style().configure("TButton", padding=7)
    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="카메라 안경 의심 여부를 확인합니다", font=("Noto Sans CJK KR", 19, "bold")).pack(anchor="w")
    ttk.Label(frame, text=runtime.metadata.get("display_name", runtime.metadata["mode"])).pack(anchor="w")
    ttk.Label(frame, text="한 사람의 정면 얼굴을 비추세요. 카메라는 시작 버튼을 눌러야 켜집니다. 사진은 저장하지 않습니다.").pack(anchor="w", pady=(4, 10))
    controls = ttk.Frame(frame)
    controls.pack(fill="x")
    device = tk.StringVar(value=str(args.camera))
    ttk.Label(controls, text="카메라 번호").pack(side="left")
    ttk.Combobox(controls, textvariable=device, values=["0", "1", "2", "3"], width=4, state="readonly").pack(side="left", padx=8)
    preview = tk.Label(frame, text="카메라 꺼짐", bg="#17232e", fg="white", font=("Noto Sans CJK KR", 15))
    preview.pack(fill="both", expand=True, pady=12)
    verdict = tk.Label(frame, text="시작을 기다리는 중", font=("Noto Sans CJK KR", 19, "bold"), anchor="w")
    verdict.pack(fill="x")
    details = tk.StringVar(value="점수는 모델의 출력이며 보정된 확률이 아닙니다.")
    ttk.Label(frame, textvariable=details).pack(anchor="w", pady=4)
    evaluation = ttk.Frame(frame)
    evaluation.pack(fill="x", pady=8)
    labels = {"일반 안경 · 실제 착용": ("ordinary_glasses", "real_worn"),
              "안경 없음 · 별도 확인": ("no_glasses", "real_worn"),
              "카메라 안경 사진 · 화면 재촬영": ("camera_glasses", "screen_recapture")}
    truth = tk.StringVar(value=next(iter(labels)))
    ttk.Label(evaluation, text="검사할 대상").pack(side="left")
    ttk.Combobox(evaluation, textvariable=truth, values=list(labels), width=36, state="readonly").pack(side="left", padx=8)
    person = tk.StringVar(value="participant-01")
    ttk.Entry(evaluation, textvariable=person, width=18).pack(side="left")
    progress = tk.StringVar(value="검사 버튼을 누르면 1초 간격으로 5개 프레임의 판정을 기록합니다.")
    ttk.Label(frame, textvariable=progress).pack(anchor="w")
    ttk.Label(frame, text="실물 카메라 안경의 재현율과 Nano 구동 성능은 아직 검증하지 않았습니다.").pack(anchor="w", pady=4)
    output = Path(args.output) / datetime.now().strftime("live-%Y%m%d-%H%M%S-%f")
    ttk.Label(frame, text=f"판정 기록: {output}", wraplength=1000).pack(anchor="w")
    recorder = Recorder(output, runtime.metadata)
    updates = queue.Queue(maxsize=1)
    state = dict(worker=None, stopped=threading.Event(), photo=None, latest=None, closing=False)

    def stop():
        state["stopped"].set()
        if state["worker"] is not None:
            state["worker"].join(timeout=2)
        state["latest"] = None
        recorder.flush()
        progress.set("카메라를 중지했습니다. 완료되지 않은 검사는 미완료로 기록합니다.")
        preview.configure(image="", text="카메라 꺼짐")
        state["photo"] = None
        verdict.configure(text="카메라를 중지했습니다", fg="#555555")
        start_button.configure(state="normal")
        inspect_button.configure(state="disabled")

    def start():
        if state["worker"] is not None and state["worker"].is_alive():
            return
        while not updates.empty():
            updates.get_nowait()
        state["stopped"] = threading.Event()
        state["worker"] = threading.Thread(target=camera_worker,
            args=(int(device.get()), runtime, state["stopped"], updates), daemon=True)
        state["worker"].start()
        start_button.configure(state="disabled")
        verdict.configure(text="카메라를 연결하는 중", fg="#555555")

    def inspect():
        if state["latest"] is None or recorder.active is not None:
            return
        label, domain = labels[truth.get()]
        recorder.start(label, domain, person.get().strip() or "participant-01", time.monotonic())
        inspect_button.configure(state="disabled")

    start_button = ttk.Button(controls, text="카메라 시작", command=start)
    start_button.pack(side="left")
    ttk.Button(controls, text="카메라 중지", command=stop).pack(side="left", padx=8)
    inspect_button = ttk.Button(evaluation, text="5프레임 검사 저장", command=inspect, state="disabled")
    inspect_button.pack(side="right")

    def tick():
        try:
            rgb, prediction, error = updates.get_nowait()
        except queue.Empty:
            pass
        else:
            if error:
                stop()
                verdict.configure(text=error, fg="#b42318")
            elif not state["stopped"].is_set():
                state["latest"] = prediction
                if prediction["reason"] == "scored":
                    x1,y1,x2,y2 = prediction["estimated_glasses_box"]
                    cv2.rectangle(rgb, (x1,y1), (x2,y2), (80,220,150), 2)
                    probability = prediction["camera_probability"]
                    alarm = probability >= runtime.metadata["threshold"]
                    verdict.configure(text="카메라 안경 의심" if alarm else "일반 안경 쪽으로 분류", fg="#b42318" if alarm else "#16704a")
                    details.set(f"카메라 안경 점수 {probability:.3f} / 기준 0.500  ·  처리 {prediction['pipeline_ms']:.1f} ms  ·  입력 {prediction['width']}×{prediction['height']}")
                else:
                    verdict.configure(text="한 사람만 화면에 들어오세요" if prediction["reason"] == "multiple_faces" else "얼굴 위치를 찾지 못했습니다. 거리와 조명을 조절하세요.", fg="#9b6500")
                    details.set("안경 착용 여부를 따로 검출하는 모델은 아닙니다. 안경이 없는 얼굴도 점수가 나올 수 있습니다.")
                image = Image.fromarray(rgb)
                image.thumbnail((max(preview.winfo_width(), 640), max(preview.winfo_height(), 300)))
                state["photo"] = ImageTk.PhotoImage(image)
                preview.configure(image=state["photo"], text="")
                if recorder.active is not None:
                    done = recorder.observe(prediction, time.monotonic())
                    if done:
                        groups = recorder.flush()
                        field = groups.get("real_worn", {})
                        rate = field.get("false_positive_rate")
                        message = f"일반 안경 검사 {field.get('n_negative',0)}회 / 오탐률 {rate:.1%}" if rate is not None else "기록했습니다. 일반 안경의 완료된 검사가 아직 없습니다."
                        progress.set(message + " · 실제 카메라 안경 재현율: 미측정")
                    else:
                        progress.set(f"검사 중: {recorder.active['count']}/5 · 같은 자세를 유지하세요.")
                if recorder.active is None:
                    inspect_button.configure(state="normal")
        if not state["closing"]:
            root.after(50, tick)

    def close():
        state["closing"] = True
        stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.after(50, tick)
    root.mainloop()


if __name__ == "__main__":
    main()
