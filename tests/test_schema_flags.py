from collections.abc import Iterator
from inspect import isclass

import pytest
from pydantic import BaseModel

from vitess_ai.schema import (
    GuideParameters,
    Monitor1DParameters,
    Monitor2DParameters,
    ReadInParameters,
    WriteoutParameters,
)


EXPECTED_LEAF_COUNTS = {
    ReadInParameters: 13,
    GuideParameters: 15,
    WriteoutParameters: 31,
    Monitor1DParameters: 20,
    Monitor2DParameters: 25,
}


def _is_model(annotation: object) -> bool:
    return isclass(annotation) and issubclass(annotation, BaseModel)


def _leaf_fields(
    model: type[BaseModel], prefix: str = ""
) -> Iterator[tuple[str, object]]:
    for field_name, field_info in model.model_fields.items():
        qualified_name = f"{prefix}.{field_name}" if prefix else field_name
        if _is_model(field_info.annotation):
            yield from _leaf_fields(field_info.annotation, qualified_name)
        else:
            yield qualified_name, field_info


@pytest.mark.parametrize(
    ("model", "expected_leaf_count"), EXPECTED_LEAF_COUNTS.items()
)
def test_parameter_leaf_fields_have_cli_flags(
    model: type[BaseModel], expected_leaf_count: int
) -> None:
    leaves = list(_leaf_fields(model))
    missing_flags = [
        field_name
        for field_name, field_info in leaves
        if not isinstance(field_info.json_schema_extra, dict)
        or not field_info.json_schema_extra.get("flag")
    ]

    assert not missing_flags, (
        f"{model.__name__} fields missing a non-empty CLI flag: "
        f"{', '.join(missing_flags)}"
    )
    assert len(leaves) == expected_leaf_count, (
        f"{model.__name__} leaf-field baseline changed: "
        f"expected {expected_leaf_count}, found {len(leaves)}"
    )


def test_total_parameter_leaf_count() -> None:
    assert sum(len(list(_leaf_fields(model))) for model in EXPECTED_LEAF_COUNTS) == 104
