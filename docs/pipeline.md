# 생성에서 학습까지

1. `TRYON_ROOT`에 원본을 준비합니다. 원본 등록 도구는 제품과 앞면·측면 사진의 해시를 데이터베이스에 기록합니다. 운영에 쓰는 원본 목록은 해당 데이터 폴더에서 관리합니다.
2. `./ops/run generation.plan_product_floor --floor 12`로 상품당 최소 수량에 맞춰 대기열을 준비합니다. 운영 설정의 `active_batch`를 이 도구가 출력한 배치로 지정합니다.
3. `./ops/run generation.review_generation_worker`가 대기열을 실행합니다. 생성은 별도로 설치한 Qwen Image 2.1 로더와 가중치가 필요합니다. `TRYON_QWEN_LOADER`와 `TRYON_QWEN_SNAPSHOTS`로 설치 위치를 설정합니다. 얼굴 크롭에 OpenCV가 설치된 별도 Python을 쓸 경우 `TRYON_FACE_CROP_PYTHON`을 지정합니다.
4. 검수 화면에서 통과·제외·보류를 기록합니다. 학습용 데이터 분리에는 통과한 이미지가 들어갑니다.
5. `./ops/run training.prepare_yolo_overnight`로 YOLO용 분리 자료를 준비합니다. 이 명령은 이전 ResNet 실험 목록을 읽어 사용 이력을 표시합니다. `TRYON_YOLO_RUN_ROOT`에 실험 설정, 체크포인트, 평가 결과를 저장합니다. 단일 실험은 `./ops/run training.yolo_experiment --config /path/to/trial.json`으로 실행합니다. W&B 연결과 YOLO 초기 가중치가 필요합니다. 시험 자료는 모델을 선택한 뒤 별도로 평가합니다.

운영 코드와 데이터는 서로 다른 위치에 둘 수 있습니다. `TRYON_ROOT`는 SQLite, 원본, 생성 결과, 판정과 로그가 있는 루트입니다. DB에는 이미지의 절대 경로가 들어 있으므로 서버에서 데이터를 다른 디스크로 옮길 때는 DB 경로도 함께 이전합니다. 코드만 배포할 때는 기존 데이터 루트를 그대로 지정합니다.

`ops/runtime.env.example`을 복사해 환경별 경로와 검수자 목록을 설정합니다. 서비스 예시의 위치와 Python을 설치 환경에 맞춰 조정합니다. Drive 동기화는 별도 rclone 설정과 데이터 루트의 `drive_folders.json`을 읽습니다.

기존 실험과 복구 스크립트는 `legacy/`에 있습니다. 특정 배치나 날짜를 전제로 하므로 사용 전에 스크립트가 읽는 데이터와 범위를 확인합니다. `training/yolo_overnight.py`와 `generation/quality_regeneration.py`에도 11월 5일 실험의 종료 시간이 기록돼 있습니다.
