"""Raise the generated-image floor for products with reviewed reference descriptions."""
import argparse
import collections
import fcntl
import json
from pathlib import Path

from ai_glasses.generation import tryon_lab as lab
from ai_glasses.generation.balance_generation import create_condition, portraits
from ai_glasses.generation.product_fidelity import DETAILS, apply_fidelity

BATCH = 'product_floor_20261105'


def plan(connection, floor):
    pool = portraits(connection)
    sources = {}
    for row in connection.execute("SELECT * FROM sources WHERE category IN ('A','B') ORDER BY rowid"):
        metadata = json.loads(row['metadata'])
        if metadata.get('selected') is False or metadata.get('generation_excluded'):
            continue
        if row['product'] not in DETAILS:
            continue
        old = sources.get(row['product'])
        if old is None or metadata.get('extra_references'):
            sources[row['product']] = dict(row)

    counts = collections.Counter()
    used = collections.defaultdict(set)
    existing = collections.Counter()
    for row in connection.execute("SELECT condition,status FROM jobs WHERE kind='tryon'"):
        condition = json.loads(row['condition'])
        product = condition.get('product')
        if row['status'] == 'success':
            counts[product] += 1
            used[product].add((condition.get('person_id'), condition.get('pose')))
        if condition.get('batch') == BATCH:
            existing[product] += 1
            used[product].add((condition.get('person_id'), condition.get('pose')))
            if row['status'] in ('pending', 'running', 'interrupted', 'blocked_dependency'):
                counts[product] += 1

    created = collections.Counter()
    for level in range(floor):
        for product, source in sorted(sources.items()):
            if counts[product] > level:
                continue
            metadata = json.loads(source['metadata'])
            candidates = [
                (key, value) for key, value in pool.items()
                if metadata.get('extra_references') or key[1] == 'front'
            ]
            if not candidates:
                raise RuntimeError(f'No matching portrait for {product}')
            ordinal = existing[product] + created[product]
            candidates.sort(key=lambda item: (
                item[0] in used[product],
                lab.uid([BATCH, product, ordinal, item[0]]),
            ))
            key, (parent, portrait) = candidates[0]
            condition = create_condition(source, parent, portrait, ordinal)
            condition.update(
                batch=BATCH, protocol=BATCH, reference_resolution=768,
                seed=int(lab.uid([BATCH, product, ordinal])[:8], 16) % (2**31),
            )
            condition = apply_fidelity(condition)
            job_id = lab.uid(condition)
            connection.execute(
                'INSERT INTO jobs(id,kind,condition) VALUES(?,?,?)',
                (job_id, 'tryon', json.dumps(condition, ensure_ascii=False)),
            )
            connection.execute('INSERT INTO batch_jobs VALUES(?,?,?)', (BATCH, job_id, level))
            created[product] += 1
            counts[product] += 1
            used[product].add(key)
    return created


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--floor', type=int, default=12)
    args = parser.parse_args()
    with open(lab.ROOT / 'public_review.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with lab.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            created = plan(connection, args.floor)
    print(json.dumps(dict(batch=BATCH, created=sum(created.values()), products=created), ensure_ascii=False))
