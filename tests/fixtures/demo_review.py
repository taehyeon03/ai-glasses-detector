"""Create a small synthetic fixture for the review UI in an empty directory."""
import json

from PIL import Image, ImageDraw

from ai_glasses.generation import tryon_lab as lab
from ai_glasses.review import public_review_store as store


def main():
    if lab.ROOT.exists() and any(lab.ROOT.iterdir()):
        raise SystemExit('Set TRYON_ROOT to an empty demo directory.')
    with lab.connect() as connection:
        store.init(connection)
        for index, (category, camera) in enumerate((('A', 'present'), ('B', 'absent'))):
            source = lab.ROOT / f'demo-source-{index}.png'
            result = lab.ROOT / lab.FOLDERS[5] / f'demo-result-{index}.png'
            for path, color in ((source, '#b9d7e2'), (result, '#e5ceaa')):
                image = Image.new('RGB', (360, 250), color)
                draw = ImageDraw.Draw(image)
                draw.rectangle((60, 94, 165, 148), outline='black', width=5)
                draw.rectangle((195, 94, 300, 148), outline='black', width=5)
                draw.line((165, 108, 195, 108), fill='black', width=5)
                draw.text((12, 12), f'Demo {category}', fill='black')
                image.save(path)
            source_id = f'demo-source-{index}'
            product = f'Demo {category}'
            connection.execute(
                'INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)',
                (source_id, str(source), lab.digest(source), product, category, camera, '', '{}'),
            )
            condition = dict(source_id=source_id, product=product, camera=camera, pose='front', person_id='demo')
            connection.execute(
                "INSERT INTO jobs(id,kind,condition,status,output,output_sha256,finished) VALUES(?,'tryon',?,'success',?,?,?)",
                (f'demo-{index}', json.dumps(condition), str(result), lab.digest(result), lab.now()),
            )


if __name__ == '__main__':
    main()
