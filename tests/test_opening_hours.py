"""Tests for ``geoevals.opening_hours``, with expectations worked out by hand from the rule
text. 2026-10-09 is a Friday."""

import socket
from datetime import date, datetime

import pytest

from geoevals.opening_hours import (
    OpeningHoursError,
    holiday_dates,
    local_instant,
    open_state,
    parse,
)

FRI, SAT, SUN, MON = date(2026, 10, 9), date(2026, 10, 10), date(2026, 10, 11), date(2026, 10, 12)


def at(day: date, clock: str) -> datetime:
    hours, minutes = clock.split(":")
    return datetime(day.year, day.month, day.day, int(hours), int(minutes))


def test_24_7_is_always_open() -> None:
    hours = parse("24/7")
    for day in (FRI, SAT, SUN, MON):
        for clock in ("00:00", "03:00", "12:00", "23:59"):
            assert hours.is_open(at(day, clock), frozenset({day}))


def test_weekday_rules_and_span_boundaries() -> None:
    hours = parse("Mo-Sa 08:00-21:00; Su 09:00-18:00")
    assert hours.is_open(at(SAT, "08:00"))  # start inclusive
    assert not hours.is_open(at(SAT, "07:59"))
    assert not hours.is_open(at(SAT, "21:00"))  # end exclusive
    assert hours.is_open(at(SUN, "09:00"))
    assert hours.is_open(at(SUN, "17:59"))
    assert not hours.is_open(at(SUN, "18:00"))
    assert not hours.is_open(at(SUN, "20:00"))  # Su overrides nothing else; Mo-Sa skips Sunday


def test_several_spans_and_a_later_rule_overrides_its_days() -> None:
    split = parse("Mo-Fr 08:00-12:00,13:00-17:00")
    assert split.is_open(at(FRI, "11:59"))
    assert not split.is_open(at(FRI, "12:30"))
    assert split.is_open(at(FRI, "13:00"))
    assert not split.is_open(at(SAT, "10:00"))
    clinic = parse("Mo-Th 08:00-20:00; Fr 08:00-16:00")
    assert not clinic.is_open(at(FRI, "17:00"))
    assert clinic.is_open(at(date(2026, 10, 8), "19:00"))
    assert not parse("Mo-Su 08:00-18:00; We off").is_open(at(date(2026, 10, 14), "10:00"))


def test_hours_that_cross_midnight_belong_to_the_day_they_start() -> None:
    hours = parse("Mo-Fr 05:00-01:00; Sa,Su 06:00-00:30")
    assert hours.is_open(at(SAT, "00:45"))  # Friday's span until 01:00
    assert not hours.is_open(at(SAT, "01:00"))
    assert not hours.is_open(at(SAT, "05:30"))  # Saturday starts at 06:00
    assert hours.is_open(at(SUN, "00:15"))  # Saturday's span until 00:30
    assert not hours.is_open(at(MON, "00:45"))  # Sunday's span ended at 00:30
    assert not hours.is_open(at(MON, "04:59"))
    assert hours.is_open(at(MON, "05:00"))
    # The part after midnight stays open even when a later rule closes the next day.
    assert parse("Fr 22:00-02:00; Sa off").is_open(at(SAT, "01:00"))
    assert parse("Mo-Su 18:00-24:00").is_open(at(SAT, "23:59"))
    assert not parse("Mo-Su 18:00-24:00").is_open(at(SUN, "00:00"))


def test_public_holiday_rules_apply_only_to_listed_holidays() -> None:
    hours = parse("Mo-Su 08:00-22:00; PH off")
    assert hours.is_open(at(SUN, "21:30"))
    assert not hours.is_open(at(SUN, "21:30"), frozenset({SUN}))
    assert hours.is_open(at(SUN, "21:30"), frozenset({MON}))
    # Weekday rules match holidays too when no PH rule follows.
    assert parse("Mo-Fr 08:30-19:00").is_open(at(MON, "10:00"), frozenset({MON}))
    holiday_only = parse("PH 10:00-14:00")
    assert holiday_only.is_open(at(MON, "11:00"), frozenset({MON}))
    assert not holiday_only.is_open(at(MON, "11:00"))


def test_selectors() -> None:
    assert parse("Fr-Mo 10:00-11:00").rules[0].weekdays == frozenset({4, 5, 6, 0})
    assert parse("Mo,We,Fr 10:00-11:00").rules[0].weekdays == frozenset({0, 2, 4})
    everyday = parse("10:00-11:00")
    assert everyday.rules[0].weekdays == frozenset(range(7))
    assert not everyday.rules[0].public_holiday
    assert parse("Mo-Fr closed").rules[0].spans == ()


@pytest.mark.parametrize(
    "value",
    [
        "sunrise-sunset",
        "Mo-Fr 9-17",
        "Jan-Mar Mo-Fr 08:00-12:00",
        "Mo-Fr 08:00-08:00",
        "Mo-Fr 24:00-02:00",
        "Mo-Fr 08:00-25:00",
        "Xx 08:00-12:00",
        "Mo-Fr 08:00-12:00;",
        "open",
    ],
)
def test_values_outside_the_subset_raise_and_count_as_unknown(value: str) -> None:
    with pytest.raises(OpeningHoursError):
        parse(value)
    assert open_state(value, at(FRI, "10:00")) is None


def test_open_state() -> None:
    assert open_state("24/7", at(FRI, "03:00")) is True
    assert open_state("Mo-Fr 08:00-12:00", at(FRI, "13:00")) is False
    for missing in (None, "", "  ", float("nan")):
        assert open_state(missing, at(FRI, "10:00")) is None  # type: ignore[arg-type]


def test_local_instant() -> None:
    when = local_instant("2026-10-11", "21:30", "Africa/Abidjan")
    assert (when.isoformat(), when.weekday()) == ("2026-10-11T21:30:00+00:00", 6)
    for day, clock, zone in [
        ("2026-02-30", "21:30", "Africa/Abidjan"),
        ("20261011", "21:30", "Africa/Abidjan"),
        ("2026-10-11", "24:00", "Africa/Abidjan"),
        ("2026-10-11", "9:30", "Africa/Abidjan"),
        ("2026-10-11", "21:30", "Mars/Olympus_Mons"),
        ("2026-10-11", "21:30", "../etc/passwd"),
        ("2026-10-11", "21:30", 5),
    ]:
        with pytest.raises(ValueError):
            local_instant(day, clock, zone)


def test_holiday_dates() -> None:
    assert holiday_dates([]) == frozenset()
    assert holiday_dates(["2026-12-25", "2026-12-25"]) == frozenset({date(2026, 12, 25)})
    for bad in ("2026-12-25", ["2026-13-01"], [20261225]):
        with pytest.raises(ValueError):
            holiday_dates(bad)


def test_parsing_makes_no_network_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    assert parse("Mo-Su 08:00-22:00; PH off").is_open(at(SUN, "21:30"))
    assert local_instant("2026-10-11", "21:30", "Africa/Abidjan").hour == 21
