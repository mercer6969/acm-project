import numpy as np
from sklearn.neighbors import KDTree


def build_tree(positions: list) -> KDTree | None:
    """
    Build a KDTree from a list of 3D positions.
    Returns None if no positions provided.
    """
    if not positions:
        return None

    arr = np.array(positions, dtype=float)

    if arr.ndim == 1:
        arr = arr.reshape(1, -1)

    return KDTree(arr)


def query_collisions(tree: KDTree | None, satellite_positions: list, radius: float) -> list:
    """
    For each satellite position, return indices of debris within radius km.
    Returns list of arrays (one per satellite).
    """
    if tree is None or not satellite_positions:
        return [np.array([], dtype=int) for _ in satellite_positions]

    sats = np.array(satellite_positions, dtype=float)

    if sats.ndim == 1:
        sats = sats.reshape(1, -1)

    return tree.query_radius(sats, r=radius)