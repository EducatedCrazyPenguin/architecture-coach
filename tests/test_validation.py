import pytest

from archcoach.models import Critique, Lesson
from archcoach.review import validate_critique_quality


def test_blocked_review_is_not_presented_as_strength():
    critique = Critique(
        strengths=["Review blocked: cannot access the source."],
        lessons=[Lesson(id="x", title="Boundary", explanation="x", code_example="x", self_check="x", answer="x", exercise="x")],
    )
    with pytest.raises(ValueError, match="source access"):
        validate_critique_quality(critique)
