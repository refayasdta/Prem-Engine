from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType


def load_probe_module() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "probe_kickoffapi.py"
    spec = spec_from_file_location("probe_kickoffapi", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probe_records_shapes_without_values() -> None:
    module = load_probe_module()
    payload = {"data": [{"id": "fx_secret", "score": 2}], "meta": {"nextCursor": None}}

    shape = module.describe_shape(payload)

    assert shape == {
        "data": {
            "type": "list",
            "length": 1,
            "item": {"id": "str", "score": "int"},
        },
        "meta": {"nextCursor": "null"},
    }
    assert "fx_secret" not in str(shape)
