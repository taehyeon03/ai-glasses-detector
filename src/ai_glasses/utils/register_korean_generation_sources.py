"""Register verified Korean-brand reference pairs for the generation queue."""
import json

from ai_glasses.generation import tryon_lab as lab
from ai_glasses.generation.product_fidelity import DETAILS

root = lab.ROOT / 'source_snapshot' / '한국브랜드_일반안경_20261103'
manifest = json.loads((root / 'manifest.json').read_text())
with lab.connect() as connection:
    for item in manifest:
        product = item['brand'] + ' ' + item['model_color']
        views = {view['role']: view for view in item['images']}
        front, side = views['front'], views['side']
        for view in (front, side):
            assert lab.digest(root / view['file']) == view['sha256'], product
        assert item['camera'] == 'absent' and item['category'] == 'B'
        role = 'side' if item['pair_type'] == '정면_측면' else 'oblique'
        metadata = dict(
            item, selected=True, pose='front', detail_prompt=DETAILS[product],
            reference_resolution=768,
            extra_references=[dict(
                role=role, product=product, path=str(root / side['file']),
                sha256=side['sha256'], temple_state=item['temple_state'],
                source_image_url=side['source_url'], source_page=item['product_url'],
            )],
        )
        front_path = str(root / front['file'])
        key = lab.uid([product, front['sha256']])
        connection.execute(
            'INSERT OR IGNORE INTO sources VALUES(?,?,?,?,?,?,?,?)',
            (key, front_path, front['sha256'], product, 'B', 'absent',
             item['product_url'], json.dumps(metadata, ensure_ascii=False)),
        )
        registered = connection.execute('SELECT product, sha256 FROM sources WHERE id=?', (key,)).fetchone()
        assert registered and tuple(registered) == (product, front['sha256'])
print(f'Registered {len(manifest)} product reference pairs.')
