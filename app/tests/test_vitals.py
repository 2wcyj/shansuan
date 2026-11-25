"""Optional blood pressure and resting heart rate: grouping, multiple readings, no silent overwrite."""
import pytest

from app.backend.domain.records import delete_vital, list_vitals, save_vital
from app.backend.domain.reports import report
from app.backend.errors import AppError
from app.backend.storage.database import Store


def vital(**values):
    return {'date': '2026-10-16', 'time': '08:30', **values}


def test_blood_pressure_and_heart_rate_round_trip(tmp_path):
    store = Store(tmp_path)
    saved = save_vital(store, vital(systolic=120, diastolic=80, heart_rate=68))
    assert (saved['systolic'], saved['diastolic'], saved['heart_rate']) == (120, 80, 68)
    assert saved['note'] == '' and saved['source'] == 'manual'
    assert saved['warnings'] == []
    assert [item['id'] for item in list_vitals(store, '2026-10-16')] == [saved['id']]
    store.close()


def test_several_readings_on_the_same_day_are_not_overwritten(tmp_path):
    store = Store(tmp_path)
    morning = save_vital(store, vital(time='08:00', systolic=118, diastolic=78))
    evening = save_vital(store, vital(time='20:00', systolic=125, diastolic=82))
    assert morning['id'] != evening['id']
    assert len(list_vitals(store, '2026-10-16')) == 2
    store.close()


def test_heart_rate_alone_is_allowed(tmp_path):
    store = Store(tmp_path)
    saved = save_vital(store, vital(heart_rate=64))
    assert saved['systolic'] is None and saved['diastolic'] is None
    assert saved['heart_rate'] == 64
    store.close()


@pytest.mark.parametrize('payload', [
    {'systolic': 120},
    {'diastolic': 80},
    {'systolic': 80, 'diastolic': 120},
    {},
])
def test_incomplete_or_reversed_blood_pressure_is_rejected(tmp_path, payload):
    store = Store(tmp_path)
    with pytest.raises(AppError):
        save_vital(store, vital(**payload))
    store.close()


def test_invalid_time_and_out_of_range_values_are_rejected(tmp_path):
    store = Store(tmp_path)
    with pytest.raises(AppError):
        save_vital(store, vital(time='25:00', heart_rate=60))
    with pytest.raises(AppError):
        save_vital(store, vital(systolic=400, diastolic=80))
    with pytest.raises(AppError):
        save_vital(store, vital(heart_rate=500))
    store.close()


def test_extreme_but_plausible_readings_are_kept_with_warnings(tmp_path):
    store = Store(tmp_path)
    saved = save_vital(store, vital(systolic=190, diastolic=125, heart_rate=130))
    assert (saved['systolic'], saved['diastolic'], saved['heart_rate']) == (190, 125, 130)
    assert len(saved['warnings']) == 2
    assert list_vitals(store, '2026-10-16')[0]['systolic'] == 190
    store.close()


def test_update_requires_the_current_version_and_delete_removes_it(tmp_path):
    store = Store(tmp_path)
    saved = save_vital(store, vital(heart_rate=60))
    edited = save_vital(store, {**vital(heart_rate=62), 'version': saved['version']}, saved['id'])
    assert edited['heart_rate'] == 62
    with pytest.raises(AppError):
        save_vital(store, {**vital(heart_rate=70), 'version': 0}, saved['id'])
    delete_vital(store, saved['id'], edited['version'])
    assert list_vitals(store, '2026-10-16') == []
    store.close()


def test_report_includes_vitals_and_never_fills_blank_days(tmp_path):
    store = Store(tmp_path)
    save_vital(store, vital(systolic=120, diastolic=80, heart_rate=66))
    result = report(store, '2026-10-16')
    assert len(result['vitals']) == 1
    assert result['vitals'][0]['systolic'] == 120
    blank = [day for day in result['days'] if day['date'] != '2026-10-16']
    assert all(day['vitals'] == [] for day in blank)
    store.close()