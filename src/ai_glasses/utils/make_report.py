"""Write an honest, current report from completed work rather than planned counts."""
import collections
import json
import os
import statistics
from pathlib import Path
from ai_glasses.generation import tryon_lab as lab

def main():
    c=lab.connect();lab.export(c);rec=lab.ROOT/lab.FOLDERS[9]
    jobs=[dict(x) for x in c.execute('SELECT * FROM jobs')]
    complete=[j for j in jobs if j['status']=='success'];tryons=[j for j in complete if j['kind']=='tryon'];portraits=[j for j in complete if j['kind']=='portrait']
    reviews={r['job_id']:dict(r) for r in c.execute('SELECT * FROM reviews')};counts=collections.Counter(reviews.get(j['id'],{}).get('decision','unreviewed') for j in tryons)
    intake=json.loads((rec/'intake_summary.json').read_text());audit=json.loads((rec/'duplicate_audit_summary.json').read_text()) if (rec/'duplicate_audit_summary.json').exists() else {}
    batch=[j for j in jobs if json.loads(j['condition']).get('batch')=='first_56' and j['status']!='superseded'];bcounts=collections.Counter(j['status'] for j in batch)
    summary=dict(updated=lab.now(),drive_url=json.loads((lab.ROOT/'drive_folders.json').read_text())['url'],source_categories=intake['groups'],source_inventory_total=intake['inventory_images'],generated_total=len(complete),generated_portraits=len(portraits),generated_tryons=len(tryons),human_reviews=dict(counts),first_batch=dict(planned=len(batch),statuses=dict(bcounts)),statuses=dict(collections.Counter(j['status'] for j in jobs)),duplicate_audit=audit)
    overnight=c.execute("SELECT * FROM batches WHERE name='overnight_10h'").fetchone()
    if overnight:
        summary['overnight']=dict(overnight);summary['overnight']['metadata']=json.loads(overnight['metadata'])
        summary['overnight']['tryon_statuses']=dict(c.execute("SELECT j.status,count(*) FROM jobs j JOIN batch_jobs b ON b.job_id=j.id WHERE b.batch='overnight_10h' AND j.kind='tryon' GROUP BY j.status").fetchall())
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='regeneration_requests'").fetchone():
        summary['public_review']=dict(url=os.environ.get('REVIEW_PUBLIC_ORIGIN','http://127.0.0.1:8790').rstrip('/')+'/',reviewed=len(reviews),new_student_portraits=len({json.loads(j['condition']).get('person_id') for j in portraits if json.loads(j['condition']).get('cohort')=='korean_students_v1'}),new_student_tryons=sum(json.loads(j['condition']).get('composition')=='tight_face_closeup' for j in tryons),regeneration_statuses=dict(c.execute('SELECT j.status,count(*) FROM regeneration_requests r JOIN jobs j ON j.id=r.child_job GROUP BY j.status').fetchall()))
    (rec/'current_status.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    def stats(field):
        a=[j[field] for j in tryons if j[field] is not None]
        return f'{min(a):.1f}〜{max(a):.1f} (중앙값 {statistics.median(a):.1f})' if a else '아직 측정하지 못함'
    lines=[
    '# 가상 착용 실험의 실행 보고',
    f'갱신 시각: {lab.dt.datetime.fromisoformat(summary["updated"]).astimezone(lab.dt.timezone(lab.dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S KST")}',
    f'\nDrive: {summary["drive_url"]}',
    '\n이 보고서는 SQLite에 저장된 실제 상태로 갱신됩니다. 계획한 작업 수를 생성 완료 수로 세지 않습니다.',
    '\n## 원본 자료',
    f'- 기존 Drive에서 이미지 {intake["inventory_images"]:,}개를 확인했습니다.',
    f'- A: 카메라가 있는 안경 {intake["groups"].get("A",0)}장입니다.',
    f'- B: 일반 안경 또는 선글라스 {intake["groups"].get("B",0)}장입니다.',
    f'- C: 카메라가 없는 스마트 안경 {intake["groups"].get("C",0)}장입니다.',
    f'- D: 확인이 필요한 사진 {intake["groups"].get("D",0):,}장입니다.',
    f'- A와 B에서는 제품을 각각 {intake["groups"].get("A",0)}종과 {intake["groups"].get("B",0)}종 확인했습니다.',
    '- 카메라가 있는 제품에는 Ray-Ban Meta와 Oakley Meta와 RayNeo와 Rokid와 Solos와 Mentra가 포함됩니다.',
    '- 일반 제품에는 Ray-Ban과 Oakley의 표준 광학 모델이 포함됩니다. 투명 렌즈와 선글라스 렌즈를 모두 포함합니다.',
    '- C는 Even G2입니다. 제조사의 privacy-center에서 카메라가 없음을 확인했습니다.',
    '- 확정한 원본은 새 분류 폴더의 사본으로 관리합니다. 기존 Drive 파일은 이동하지 않았습니다.',
    f'- D 폴더에는 원본의 ID와 경로를 가진 목록을 저장했습니다. {intake["groups"].get("D",0):,}개 전체를 개별 검수하거나 복사한 것은 아닙니다.',
    '- 기존 README와 수집 기록을 읽었습니다. 기존 문서에 적힌 연구 목적의 사용 안내를 권리자의 허락으로 간주하지 않았습니다.',
    '\n## 중복 검사',
    f'- 기존 이미지 {intake["md5_checked"]:,}개의 Drive MD5를 비교했습니다.',
    f'- 완전히 같은 파일은 {intake["exact_duplicate_groups"]}묶음이었습니다. 묶음마다 한 파일만 남긴다고 가정하면 추가 파일은 {intake["duplicate_extra_files"]}개입니다. 실제 파일은 삭제하지 않았습니다.',
    f'- 로컬 SHA-256과 지각 해시를 확인한 사진은 {audit.get("downloaded_sha256_and_perceptual_checked",0):,}장입니다.',
    f'- 크기 또는 여백이 다른 사진으로 의심한 조합은 {audit.get("suspected_pairs",0):,}개입니다. 중복으로 확정한 수가 아닙니다.',
    f'- 지각 해시를 확인하지 못한 파일은 {audit.get("not_checked",intake["inventory_images"]):,}개입니다. 확장자가 avif인 두 파일은 실제 H.264 동영상임을 확인했습니다. 정지사진으로 사용하지 않습니다.',
    f'- 생성 이미지 {audit.get("generated_checked",0)}장도 원본과 비교했습니다. 생성 결과 사이의 같은 파일은 {audit.get("generated_exact_duplicate_groups",0)}묶음입니다.',
    '- 같은 인물에게 다른 제품을 씌운 결과는 의도적으로 비슷합니다. 유사하다는 이유만으로 제거하지 않습니다.',
    '- 심한 잘림과 회전은 이 검사에서 빠질 수 있습니다. 형태가 비슷한 다른 제품도 후보로 잡힐 수 있습니다.',
    '\n## 생성 결과',
    f'- 착용 전의 인물 사진을 {len(portraits)}장 생성했습니다. 가상 인물의 사진과 사용자 제공 사진의 파생본을 구분합니다.',
    f'- 착용 결과를 {len(tryons)}장 생성했습니다.',
    f'- 첫 묶음은 {len(batch)}장으로 설정했습니다. 완료한 수는 {bcounts.get("success",0)}장입니다.',
    f'- 첫 묶음의 대기 수는 {bcounts.get("pending",0)}장입니다. 실행 중인 수는 {bcounts.get("running",0)}장입니다.',
    f'- 첫 묶음의 실패 수는 {bcounts.get("failed",0)}장입니다. 선행 작업을 기다리는 수는 {bcounts.get("blocked_dependency",0)}장입니다.',
    f'- 검수 전 {counts.get("unreviewed",0)}장입니다. 통과 {counts.get("pass",0)}장입니다. 제외 {counts.get("exclude",0)}장입니다. 보류 {counts.get("hold",0)}장입니다.',
    '- 자동 기능 시험에서 저장한 판정은 별도 시험 폴더에 있습니다. 실제 검수 수에 포함하지 않았습니다.',
    '\n## 모델과 조건',
    f'- 모델은 {lab.MODEL}입니다.',
    f'- 모델의 리비전은 {lab.REVISION}입니다.',
    '- 기존 qwen_image 환경과 모델 파일을 재사용했습니다.',
    '- GPU는 RTX 5070 Ti입니다. GPU 메모리는 16,303 MiB입니다.',
    '- 가중치는 FP8로 저장합니다. 연산에는 BF16을 사용합니다. CPU로 모델을 옮기는 기능을 사용합니다.',
    '- 해상도는 1024×1024입니다. KV 캐시를 사용합니다.',
    '- 최초 시험에는 30단계를 사용했습니다. 보강한 조건에는 40단계를 사용합니다.',
    '- 인물마다 ID를 부여했습니다. 동일한 인물과 방향과 조명에 A와 B를 모두 적용합니다.',
    '- 10시간 대기열에는 가상 인물 4명과 사용자 제공 사진을 참조한 인물 1명이 포함됩니다. 정면과 양쪽 사선과 양쪽 측면을 요청합니다.',
    '- 단발과 긴 머리와 짧은 머리와 묶은 머리가 포함됩니다. 조명은 세 종류입니다.',
    '- 기존 제품의 착용 사진에서 다른 실제 얼굴을 수집하지 않았습니다. 사용자가 직접 제공한 얼굴만 별도 실사 참조로 추가했습니다.',
    '- U01의 원본 제공 사진은 RTX 컴퓨터의 user_provided_references에 보관합니다. 생성한 파생본은 U01이라는 같은 인물 ID로 기록합니다.',
    '- 제품의 정면 사진만 확인한 조건에서는 측면의 보이지 않는 형상을 모델이 추정합니다. 해당 부분의 제품 일치는 확인하지 못했습니다.',
    f'- 착용 결과 한 장의 생성 시간은 {stats("seconds")}초입니다. 모델을 처음 불러오는 시간은 포함하지 않습니다.',
    f'- PyTorch가 할당한 GPU 메모리의 최대값은 {stats("peak_gb")}GB입니다. GPU 전체 사용량을 측정한 값은 아닙니다.',
    '- 프롬프트와 시드와 작업별 실행 환경은 jobs.jsonl과 jobs.csv에 기록합니다.',
    '\n## 비교에서 관찰한 문제',
    '- 초기 HSTN 결과에서는 원본보다 눈이 잘 비쳤습니다. 렌즈의 불투명도가 바뀐 사례입니다.',
    '- 프롬프트를 보강한 뒤에는 같은 조건의 렌즈가 더 어둡게 보입니다. 눈이 비치는 문제는 여전히 확인해야 합니다.',
    '- Wayfarer 원본에 있는 렌즈의 로고가 일부 생성 결과에서 사라졌습니다.',
    '- 측면을 요청한 인물 사진이 사선으로 나온 사례가 있습니다. 코가 향하는 방향을 이미지 기준으로 지정한 새 조건을 준비했습니다.',
    '- 화면의 얼굴 방향은 요청한 조건입니다. 실제 방향은 별도 검증이 필요합니다.',
    '- 일부 인물 사진에는 분홍색의 국소 흔적이 보입니다. 피부 표현도 검수해야 합니다.',
    '- 카메라와 촬영 표시등의 작은 내부 형태는 아직 사람이 판정하지 않았습니다. 표시등을 두 번째 카메라로 세면 안 됩니다.',
    '- 작은 프레임의 곡률과 굵기는 검수 대상입니다. 자연스러운 착용만으로 제품의 일치를 확정하지 않습니다.',
    '- 비교 예시는 원본과_생성결과_비교.png에 저장합니다. 자동 작업자의 관찰은 diagnostics에 따로 저장합니다.',
    '\n## 기능의 검증',
    '- 5개 시험이 통과했습니다. 작업 ID가 중복 조건을 합치는지 확인했습니다.',
    '- 검수 기록이 다시 연결한 데이터베이스에도 남는지 확인했습니다.',
    '- 미확인 항목이 있는 결과를 통과시킬 수 없는지 확인했습니다.',
    '- 실패한 작업을 검수 대상으로 저장할 수 없는지 확인했습니다.',
    '- 생성 파일을 옮긴 직후 중단된 상태를 복구하는지 확인했습니다.',
    '- 별도 시험 화면에서 통과와 제외와 보류를 눌렀습니다. 새로고침 뒤에도 기록이 남았습니다.',
    '- 실제 생성 작업을 한 장 뒤에 멈췄습니다. 재개 뒤 기존 파일 5개의 SHA-256이 그대로임을 확인했습니다.',
    '\n## 이용 조건',
    f'- 선별한 제품 사진 {sum(intake["groups"].get(k,0) for k in ("A","B","C"))}장 모두 권리 확인이 필요합니다. 제조사 또는 판매자의 사진이라는 이유로 학습이나 재배포가 허용된다고 판단하지 않았습니다.',
    '- 나머지 기존 사진도 권리자의 이용 허락을 확인한 상태가 아닙니다.',
    '- 모델에는 Qwen Research License가 적용됩니다. 모델 자료의 사용은 비상업적인 연구 또는 평가 목적에 한정됩니다.',
    '- 모델의 상업적인 사용에는 별도 허락이 필요합니다.',
    '- Qwen의 출력으로 개선한 AI 모델을 배포하거나 제공하는 경우에는 관련 문서에 요구된 표시를 해야 합니다.',
    '- 모델 라이선스는 제품 사진의 이용 권한을 제공하지 않습니다.',
    '- 확인한 라이선스의 원문과 주소는 QWEN_LICENSE와 rights_and_sources.md에 저장합니다.',
    '\n## 아직 검증하지 못한 부분',
    f'- 현재 판정이 저장된 결과는 {len(reviews)}장입니다. 검수 이후에만 통과 수가 늘어납니다.',
    '- D에 기록한 대부분의 사진은 개별 제품과 사진의 적합성을 아직 확인하지 못했습니다.',
    '- 원본 정면에서 보이지 않는 다리와 측면은 검증하지 못했습니다.',
    '- 실제 착용 사진으로 최종 평가하지 않았습니다. 탐지 모델도 학습하지 않았습니다.',
    '- 같은 인물과 같은 원본을 함께 묶으면 데이터가 하나의 연결 묶음이 될 수 있습니다. 이 경우 독립된 시험 세트를 만들지 않습니다.',
    '- CLIP 점수는 계산하지 않았습니다. 향후 점수를 추가해도 자동 통과 기준으로 사용하면 안 됩니다.',
    '- 생성 사진끼리 얻은 결과를 실제 환경의 성능으로 해석하면 안 됩니다.',
    ]
    if overnight:
        item=summary['overnight'];details=item['metadata'];progress=item['tryon_statuses']
        def local_time(value):return lab.dt.datetime.fromisoformat(value).astimezone(lab.dt.timezone(lab.dt.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S KST') if value else '아직 시작하지 않음'
        lines[6:6]=['\n## 10시간 자동 실행',f'- 상태는 {item["status"]}입니다.',f'- 시작한 시각은 {local_time(item["started"])}입니다.',f'- 종료 기준 시각은 {local_time(item["deadline"])}입니다. 진행 중인 이미지를 마친 뒤 멈춥니다.',f'- 카메라 제품 {details["camera_products"]}종과 일반 제품 {details["ordinary_products"]}종을 교대로 사용합니다.',f'- 착용 결과 {details["planned_tryons"]}개의 대기열을 준비했습니다. 이 수는 생성 완료 수가 아닙니다.',f'- 대기열에서 실제 완료한 결과는 {progress.get("success",0)}장입니다. 실패한 작업은 {progress.get("failed",0)}개입니다.', '- RTX 컴퓨터의 사용자 서비스가 실행합니다. 접속한 컴퓨터의 SSH 연결과 별개입니다.', '- RTX 컴퓨터의 AC 자동 절전 설정은 nothing임을 확인했습니다. 사용자 서비스의 Linger 설정도 켜져 있습니다.', '- Drive 전송기는 별도 서비스에서 재시도합니다. 동기화의 최근 결과는 drive_sync_status.json에 기록합니다.', '\n### 대상 제품',*['- '+p['category']+': '+p['name'] for p in details['products']]]
    if 'public_review' in summary:
        public=summary['public_review']
        lines[5:5]=['\n## 공개 검수 서비스',f'- 접속 주소: {public["url"]}', '- 로그인 없이 검수할 수 있습니다. 입력한 답변은 초안으로 자동 저장합니다.', '- 판정을 저장하면 웹의 검수 완료 공간에 모입니다. 이전 판정도 이력에 보존합니다.', '- 재생성 요청은 자동 대기열에 들어갑니다. 새 결과는 다시 검수해야 합니다.',f'- 새 대학생 얼굴은 8명 중 {public["new_student_portraits"]}명이 생성됐습니다.',f'- 새 인물의 착용 이미지는 160개 조건 중 {public["new_student_tryons"]}장이 생성됐습니다.',f'- 재생성 요청의 상태는 {public["regeneration_statuses"]}입니다.', '- 파일의 사본은 11_검수완료 폴더에도 저장합니다. Drive 전송은 요청 제한에 따라 지연될 수 있습니다.']
    (rec/'실행보고.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k!='duplicate_audit'},ensure_ascii=False))
if __name__=='__main__':main()
