"""Source independence: near-duplicate claims (syndicated copies, one press release quoted ten times) fold into one
cluster via MinHash + LSH over word 3-gram shingles. Repetition must not look like agreement."""
import hashlib, re

N_HASH, BANDS = 32, 8           # 8 bands x 4 rows -> pairs with Jaccard >~0.5 collide
_SALTS = [hashlib.blake2b(str(i).encode(), digest_size=8).digest() for i in range(N_HASH)]


def _shingles(text):
    w = re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split()
    return {" ".join(w[i:i + 3]) for i in range(max(1, len(w) - 2))}


def _minhash(sh):
    return [min(int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8, key=salt).digest(), "big") for s in sh) for salt in _SALTS]


def _jaccard(a, b):
    return len(a & b) / (len(a | b) or 1)


def cluster(items: list[tuple[str, str]], threshold=0.5) -> dict[str, str]:
    """items: [(claim_id, text)] -> {claim_id: cluster_id}; cluster_id = first claim id of the cluster."""
    sh = {cid: _shingles(t) for cid, t in items}
    parent = {cid: cid for cid, _ in items}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    rows = N_HASH // BANDS
    buckets = {}
    for cid, _ in items:
        mh = _minhash(sh[cid])
        for b in range(BANDS):
            buckets.setdefault((b, tuple(mh[b * rows:(b + 1) * rows])), []).append(cid)
    for group in buckets.values():
        for other in group[1:]:
            if find(other) != find(group[0]) and _jaccard(sh[group[0]], sh[other]) >= threshold:
                a, b = sorted((find(group[0]), find(other)), key=lambda c: [i for i, _ in items].index(c))
                parent[b] = a
    return {cid: find(cid) for cid, _ in items}
