"""Tests for ``parse_order`` in ``order_parser.py``."""

from order_parser import parse_order


def test_milk_and_eggs():
    assert parse_order("milk and eggs") == {"milk": 1, "eggs": 1}


def test_two_milk_aur_eggs():
    assert parse_order("2 milk aur eggs") == {"milk": 2, "eggs": 1}


def test_three_bread_one_milk():
    assert parse_order("3 bread 1 milk") == {"bread": 3, "milk": 1}


def test_two_milk_two_eggs_and_bread():
    assert parse_order("2 milk and 2 eggs and bread") == {
        "milk": 2,
        "eggs": 2,
        "bread": 1,
    }


def test_milk_milk_eggs_combines_repeats():
    assert parse_order("milk milk eggs") == {"milk": 2, "eggs": 1}


def test_milk_aur_milk_combines_repeats():
    assert parse_order("milk aur milk") == {"milk": 2}


def test_two_eggs_and_eggs():
    assert parse_order("2 eggs and eggs") == {"eggs": 3}
