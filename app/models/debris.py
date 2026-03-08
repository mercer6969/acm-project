import numpy as np


class Debris:

    def __init__(self, obj_id: str, position, velocity):
        self.id = obj_id
        self.r = np.array(position, dtype=float)   # km, ECI
        self.v = np.array(velocity, dtype=float)   # km/s, ECI

    def state_vector(self) -> np.ndarray:
        return np.concatenate([self.r, self.v])