"""Report windows stay explicit: 7/30 only, missing days never filled with zero."""
import pytest

from app.backend.domain.records import save_record
from app.backend.domain.reports import report
from app.backend.errors import AppError
from app.backend.storage.database import Store


def body(date='2026-10-16'):
    return dict(date=date, meal='午餐', time='12:30',
                items=[{'food_id': 'usda-168878', 'grams': 200}])


def test_seven_day_window_is_the_default_and_keeps_the_existing_contract(tmp_path):
    store = Store(tmp_path)
    save_record(store, body())
    result = report(store, '2026-10-16')
    assert result['window'] == 7
    assert len(result['days']) == 7
    assert result['start'] == '2026-10-10'
    assert result['end'] == '2026-10-16'
    assert result['recorded_days'] == 1
    for key in ['means', 'life', 'execution', 'weight', 'tips', 'calculation_version']:
        assert key in result
    store.close()


def test_thirty_day_window_keeps_blank_days_blank(tmp_path):
    store = Store(tmp_path)
    save_record(store, body())
    result = report(store, '2026-10-16', 30)
    assert result['window'] == 30
    assert len(result['days']) == 30
    assert result['start'] == '2026-09-17'
    blank = [day for day in result['days'] if day['record_count'] == 0]
    assert blank
    assert all(day['nutrition']['energy']['total'] is None for day in blank)
    assert result['recorded_days'] == 1
    store.close()


@pytest.mark.parametrize('window', [0, 1, 14, 31, 365, -7])
def test_unsupported_windows_are_rejected(tmp_path, window):
    store = Store(tmp_path)
    with pytest.raises(AppError):
        report(store, '2026-10-16', window)
    store.close()