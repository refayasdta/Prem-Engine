import pytest
from prem_engine_modeling import validate_result_probabilities


def test_valid_result_probabilities_are_accepted() -> None:
    validate_result_probabilities((0.54, 0.26, 0.20))


@pytest.mark.parametrize(
    "probabilities",
    [
        (0.5, 0.5),
        (0.7, 0.4, -0.1),
        (0.4, 0.3, 0.2),
    ],
)
def test_invalid_result_probabilities_are_rejected(
    probabilities: tuple[float, ...],
) -> None:
    with pytest.raises(ValueError):
        validate_result_probabilities(probabilities)
