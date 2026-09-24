"""The register -> output index map, pinned against the GPU that produced it."""
import pytest

from matchedfilter import _vulkan

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import gpu_output_order as output_order


@pytest.mark.parametrize("n", sorted(output_order.RADICES))
def test_permutation_is_a_permutation(n):
    p = output_order.permutation(n)
    assert sorted(p) == list(range(n))


@pytest.mark.parametrize("n,radices", sorted(output_order.RADICES.items()))
def test_radices_multiply_to_the_transform_length(n, radices):
    prod = 1
    for r in radices:
        prod *= r
    assert prod == n


def test_high_bits_of_the_index_come_from_the_register():
    """index = q*WG + reverse(tid) -- the property the fast path rests on."""
    n = 4096
    wg = n // 16
    for q in range(16):
        for tid in (0, 1, 7, 255):
            assert output_order.slot_to_index(tid * 16 + q,
                                              output_order.RADICES[n]) // wg == q


def test_register_bins_degrade_gracefully_with_an_unaligned_start():
    """An arbitrary start does not disable the fast path, it shrinks it."""
    n = 4096
    assert len(output_order.bin_is_fixed_by_register(n, 0, 4096)) == 16
    assert len(output_order.bin_is_fixed_by_register(n, 0, 256)) == 16
    partial = output_order.bin_is_fixed_by_register(n, 37, 1000)
    assert 0 < len(partial) < 16
