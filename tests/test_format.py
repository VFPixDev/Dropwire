from src.utils.text_format import format_number, create_progress_bar, format_poll
from src.twitter.models import Poll, PollOption


def test_format_number():
    """Тест форматирования чисел"""
    assert format_number(500) == "500"
    assert format_number(1500) == "1.5K"
    assert format_number(1000000) == "1M"
    assert format_number(1234567) == "1.2M"


def test_create_progress_bar():
    """Тест создания прогресс-бара"""
    bar = create_progress_bar(50, 10)
    assert len(bar) == 10
    assert bar.count("█") == 5
    assert bar.count("░") == 5

    bar_full = create_progress_bar(100, 20)
    assert bar_full == "█" * 20

    bar_empty = create_progress_bar(0, 20)
    assert bar_empty == "░" * 20


def test_format_poll():
    """Тест форматирования опроса"""
    poll = Poll(
        question="Какой язык лучше?",
        options=[
            PollOption(text="Python", votes=150, percent=60.0),
            PollOption(text="JavaScript", votes=100, percent=40.0),
        ],
        total_votes=250,
        is_ended=True,
    )

    result = format_poll(poll)

    assert "Какой язык лучше?" in result
    assert "Python" in result
    assert "60%" in result
    assert "250 голосов" in result
    assert "завершён" in result
