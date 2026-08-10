from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType


def load_probe_module(name: str = "probe_kickoffapi") -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / f"{name}.py"
    spec = spec_from_file_location(name, path)
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


def test_player_probe_records_only_shapes_and_templates() -> None:
    module = load_probe_module("probe_player_coverage")
    payload = {
        "data": [{"player": {"id": "pl_secret", "name": "Private Value"}}],
        "meta": {"team": "tm_secret"},
    }

    shape = module.describe_shape(payload)

    assert shape["data"]["item"]["player"] == {"id": "str", "name": "str"}
    assert "pl_secret" not in str(shape)
    assert "Private Value" not in str(shape)
    assert module.coverage_state(payload) == "available"
    assert module.coverage_state({"data": []}) == "empty"
