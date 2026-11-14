import numpy as np

from smartscan.rotation import apply_state, rotate_90, state_after


def test_four_clockwise_rotations_are_pixel_identical():
    arr = np.arange(24, dtype=np.uint8).reshape(4, 6)
    out = arr
    for _ in range(4):
        out = rotate_90(out, clockwise=True)
    assert np.array_equal(out, arr)


def test_counter_clockwise_is_inverse_of_clockwise():
    arr = np.arange(24, dtype=np.uint8).reshape(4, 6)
    assert np.array_equal(rotate_90(rotate_90(arr, True), False), arr)


def test_state_wraps_and_apply_from_base():
    assert state_after(270, 1) == 0
    assert state_after(0, -1) == 270
    base = np.arange(24, dtype=np.uint8).reshape(4, 6)
    assert np.array_equal(apply_state(base, 0), base)
    assert apply_state(base, 90).shape == (6, 4)


def test_apply_state_is_a_single_transform_from_base():
    base = np.arange(24, dtype=np.uint8).reshape(4, 6)
    twice = rotate_90(rotate_90(base, True), True)
    assert np.array_equal(apply_state(base, 180), twice)
