from math import dist
from random import Random
from statistics import fmean, pstdev

RANDOM_SEED = 20261121
FEATURES = ('median', 'p90', 'late_rate')
ALERT_RATE = 25


def initialize(points, k, rng):
    centers = [rng.choice(points)]
    while len(centers) < k:
        weights = [min(dist(point, center) ** 2 for center in centers) for point in points]
        centers.append(rng.choices(points, weights=weights, k=1)[0])
    return centers


def fit(points, k):
    rng = Random(RANDOM_SEED)
    best = None
    for _ in range(16):
        centers = initialize(points, k, rng)
        groups = []
        for _ in range(200):
            previous = groups
            groups = [min(range(k), key=lambda index: dist(point, centers[index])) for point in points]
            if len(set(groups)) < k:
                break
            if previous == groups:
                inertia = sum(dist(point, centers[group]) ** 2 for point, group in zip(points, groups))
                if best is None or inertia < best[0]:
                    best = (inertia, groups, centers)
                break
            centers = [tuple(map(fmean, zip(*(point for point, label in zip(points, groups) if label == group))))
                       for group in range(k)]
    if best is None:
        raise ValueError('没有找到稳定的非空分群，请减少群数或拓宽日期窗口')
    return best


def silhouette(points, labels):
    scores = []
    groups = {label: [i for i, item in enumerate(labels) if item == label] for label in set(labels)}
    for i, (point, label) in enumerate(zip(points, labels)):
        peers = [j for j in groups[label] if j != i]
        if not peers:
            scores.append(0)
            continue
        a = fmean(dist(point, points[j]) for j in peers)
        b = min(fmean(dist(point, points[j]) for j in members) for group, members in groups.items() if group != label)
        scores.append((b - a) / (max(a, b) or 1))
    return fmean(scores)


def analyze(snapshot, k, minimum):
    eligible = [station for station in snapshot if station['count'] >= minimum]
    omitted = [station | {'segment': None} for station in snapshot if station['count'] < minimum]
    if len(eligible) <= k:
        raise ValueError(f'有效网点 {len(eligible)} 家，至少需要 {k + 1} 家才能分群并计算轮廓系数')
    vectors = [tuple(station[feature] for feature in FEATURES) for station in eligible]
    if len(set(vectors)) < k:
        raise ValueError('不同的特征组合少于目标群数，请调整日期或减少群数')
    columns = list(zip(*vectors))
    means = list(map(fmean, columns))
    scales = [pstdev(column) or 1 for column in columns]
    points = [tuple((value - mean) / scale for value, mean, scale in zip(vector, means, scales)) for vector in vectors]
    inertia, labels, centers = fit(points, k)
    order = sorted(range(k), key=lambda i: (centers[i][2], centers[i][1], centers[i][0], i))
    mapping = {label: i + 1 for i, label in enumerate(order)}
    segments = []
    members = [station | {'segment': mapping[label]} for station, label in zip(eligible, labels)]
    for label in order:
        index = mapping[label]
        assigned = [station for station in members if station['segment'] == index]
        centroid = {feature: fmean(station[feature] for station in assigned) for feature in FEATURES}
        alert = centroid['late_rate'] >= ALERT_RATE
        shift_action = '复盘班次交接，核查超时面单并记录调度调整'
        segments.append({
            'id': index, 'count': len(assigned), 'centroid': {key: round(value, 2) for key, value in centroid.items()},
            'alert': alert, 'name': '超时整改' if alert else '常态观察',
            'action': shift_action if alert else '补采下一班次面单并核对扫描时效',
        })
    return {
        'segments': segments, 'members': members, 'excluded': omitted,
        'silhouette': round(silhouette(points, labels), 4), 'inertia': round(inertia, 6),
        'normalization': {name: {'mean': mean, 'scale': scale} for name, mean, scale in zip(FEATURES, means, scales)},
        'seed': RANDOM_SEED, 'alert_rate': ALERT_RATE,
    }
