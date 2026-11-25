import pytest

from liner_parts.instance import InstanceLock


def test_second_instance_is_rejected_and_lock_released(tmp_path):
    first = InstanceLock(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="另一窗口"):
            InstanceLock(tmp_path)
    finally:
        first.close()
    second = InstanceLock(tmp_path)
    second.close()
