from collections import Counter
from copy import deepcopy

import pytest

from archcoach.models import Critique, Lesson
from archcoach.review import validate_critique_quality
from tests.test_history import fixture_quiz


def test_blocked_review_is_not_presented_as_strength():
    critique = Critique(
        strengths=["Review blocked: cannot access the source."],
        lessons=[Lesson(id="x", title="Boundary", explanation="x", code_example="x", self_check="x", answer="x", exercise="x")],
    )
    with pytest.raises(ValueError, match="source access"):
        validate_critique_quality(critique)


@pytest.mark.parametrize('correct_index', range(4))
def test_new_quiz_balances_positions_without_changing_answer_meaning(correct_index):
    raw = fixture_quiz()
    for question in raw:
        for key in ('options', 'explanations'):
            question[key][0], question[key][correct_index] = question[key][correct_index], question[key][0]
        question['correct_index'] = correct_index
    original = deepcopy(raw)
    result = validate_critique_quality(Critique(quiz=raw))
    assert sorted(Counter(q.correct_index for q in result.quiz).values()) == [2, 2, 3, 3]
    assert [q.id for q in result.quiz] == [q['id'] for q in original]
    for question, before in zip(result.quiz, original):
        assert question.options[question.correct_index] == before['options'][before['correct_index']]
        assert dict(zip(question.options, question.explanations)) == dict(zip(before['options'], before['explanations']))
        assert question.question == before['question'] and [ref.model_dump() for ref in question.evidence] == before['evidence']
    assert raw == original
    saved = result.model_dump()
    assert validate_critique_quality(result).model_dump() == saved
    assert validate_critique_quality(Critique(quiz=list(reversed(raw)))).model_dump()['quiz'] == list(reversed(saved['quiz']))


@pytest.mark.parametrize(('field', 'text'), [
    ('question', 'Option B owns validation.'), ('options', 'All of the above'),
    ('explanations', 'Both A and C'), ('explanations', 'option b owns validation.'),
    ('options', 'none of the above'), ('question', 'either a or d'),
])
def test_position_dependent_quiz_text_is_rejected_before_reordering(field, text):
    raw = fixture_quiz()
    if field == 'question':
        raw[0][field] = text
    else:
        raw[0][field][0] = text
    critique = Critique(quiz=raw); before = critique.model_dump()
    with pytest.raises(ValueError, match='position'):
        validate_critique_quality(critique)
    assert critique.model_dump() == before
