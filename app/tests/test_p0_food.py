import json
from pathlib import Path


def test_source_coverage_and_missing_purine():
    foods = json.loads((Path(__file__).parents[1]/'resources/foods.json').read_text(encoding='utf-8'))
    assert len(foods) >= 80
    assert len({f['id'] for f in foods}) == len(foods)
    assert {'fruit','vegetable','grain','meat','fish','soy','dairy'}.issubset({f['category'] for f in foods})
    for f in foods:
        assert f['source']['fdc_id'] and f['source']['description'] and f['per_grams']==100
        assert f['nutrients']['purine'] is None
        assert f['nutrients']['energy'] is not None
        assert all(v is None or v >= 0 for v in f['nutrients'].values())

def test_composite_ingredient_uncertainty_and_aliases():
    import json
    from pathlib import Path
    foods = json.loads((Path(__file__).resolve().parents[1] / 'resources/foods.json').read_text(encoding='utf-8'))
    breads = [f for f in foods if '面包' in f['name']]
    assert breads and all(not f['ingredients_complete'] for f in breads)
    peanut = next(f for f in foods if '花生' in f['name'])
    assert '花生' in peanut['allergens']
    assert any('牛排' in f['aliases'] for f in foods)
