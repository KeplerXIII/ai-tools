"""Преобразование расстояний pgvector в similarity score (cosine)."""


def cosine_distance_to_similarity(distance: float) -> float:
    """pgvector cosine distance (<=>): 0 = идентичны, 2 = противоположны (норм. векторы)."""
    return max(0.0, min(1.0, 1.0 - float(distance)))
