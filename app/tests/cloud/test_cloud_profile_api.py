"""Cloud profile API preserves the local DTO while enforcing consent and tenant ownership."""
import asyncio
import uuid

import asyncpg
from fastapi.testclient import TestClient

from app.backend.cloud.auth import AuthService, hash_password
from app.backend.cloud.config import CloudSettings
from app.tests.cloud.test_cloud_crypto import FakeKeyService


def test_cloud_profile_crud_isolated_by_account_and_requires_consent(postgres_database, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://runtime:unused@localhost/shansuan")
    monkeypatch.setenv("SESSION_SIGNING_KEY", "cloud-profile-test-signing-key-0001")
    monkeypatch.setenv("FRONTEND_ORIGINS", "https://app.example.cn")
    monkeypatch.setenv("APP_ENV", "test")
    from app.backend.cloud.crypto import CloudCrypto
    from app.backend.cloud.repository import TenantRepository
    from app.backend.cloud_main import create_cloud_app

    signing_key = b"cloud-profile-test-signing-key-0001"
    service = AuthService(postgres_database["runtime_url"], signing_key=signing_key)
    accounts = [uuid.uuid4(), uuid.uuid4()]
    emails = [f"{account}@example.test" for account in accounts]

    async def seed_accounts():
        connection = await asyncpg.connect(
            host=postgres_database["host"], port=postgres_database["port"],
            user="postgres", password=postgres_database["admin_password"],
            database=postgres_database["database"],
        )
        try:
            await connection.executemany(
                "INSERT INTO accounts(id,email,password_hash,status,is_admin,created_at) "
                "VALUES($1,$2,$3,'active',false,now())",
                [(account, email, hash_password("cloud-profile-password-" + str(i)))
                 for i, (account, email) in enumerate(zip(accounts, emails))],
            )
        finally:
            await connection.close()
        return [await service.login(email, "cloud-profile-password-" + str(i),
                                    remote_key="profile-api-test-" + str(i))
                for i, email in enumerate(emails)]

    sessions = asyncio.run(seed_accounts())
    repository = TenantRepository(postgres_database["runtime_url"], CloudCrypto(FakeKeyService()))
    settings = CloudSettings(
        "postgresql+asyncpg://runtime:unused@localhost/shansuan", signing_key,
        ("https://app.example.cn",), "test",
    )
    app = create_cloud_app(settings, auth_service=service, tenant_repository=repository)
    clients = [TestClient(app), TestClient(app)]
    headers = []
    for client, issued in zip(clients, sessions):
        client.cookies.set("shansuan_session", issued.cookie_token)
        client.cookies.set("shansuan_csrf", issued.csrf_token)
        headers.append({"Origin": "https://app.example.cn", "X-CSRF-Token": issued.csrf_token})

    try:
        assert clients[0].get("/api/profile").status_code == 428
        assert clients[0].get("/api/auth/me").status_code == 200
        for client, header in zip(clients, headers):
            response = client.post(
                "/api/privacy/consent",
                json={"notice_version": "2026-10-21-v1", "confirmed": True},
                headers=header,
            )
            assert response.status_code == 200

        profile = {
            "sex": "女", "age": 31, "height": 162, "weight": 59,
            "sleep_hours": 7, "exercise_weekly": 2, "activity": "轻度",
            "lifestyle": "上班族", "goals": ["日常营养均衡"],
            "primary_goal": "日常营养均衡", "health_status": "明确无",
            "allergy_status": "明确无",
        }
        created = clients[0].put("/api/profile", json=profile, headers=headers[0])
        assert created.status_code == 200, created.text
        assert 'no-store' in created.headers.get('cache-control', '')
        assert created.json()["profile"]["weight"] == 59
        assert created.json()["profile"]["version"] == 1
        from datetime import date
        today = date.today().isoformat()
        planned = clients[0].get('/api/plans/' + today)
        assert planned.status_code == 200, planned.text
        assert {meal['meal'] for meal in planned.json()['plan']['meals']} == {'早餐', '午餐', '晚餐', '加餐'}
        assert clients[1].get('/api/plans/' + today).json()['plan'] is None
        assert clients[0].get('/api/records', params={'date': today}).json()['record_count'] == 0
        from app.backend.domain.food import BASE
        food = next(food for food in BASE if food['nutrients']['protein'] is not None)
        record_body = {'date': today, 'meal': '午餐', 'time': '12:30',
            'items': [{'food_id': food['id'], 'grams': 100}],
            'request_key': 'cloud-record-test-first'}
        actual = clients[0].post('/api/records', json=record_body, headers=headers[0])
        assert actual.status_code == 200, actual.text
        recorded = actual.json()
        assert recorded['nutrition']['protein']['known'] == round(food['nutrients']['protein'], 2)
        assert clients[0].post('/api/records', json=record_body, headers=headers[0]).json()['id'] == recorded['id']
        assert clients[0].get('/api/records', params={'date': today}).json()['record_count'] == 1
        overview = clients[0].get('/api/home/' + today)
        assert overview.status_code == 200, overview.text
        assert overview.json()['record_count'] == 1
        assert clients[0].get('/api/foods').status_code == 200
        calculated = clients[0].post('/api/nutrition/calculate', json={
            'items': record_body['items']}, headers=headers[0])
        assert calculated.status_code == 200
        assert calculated.json()['nutrition'] == recorded['nutrition']
        assert clients[1].get('/api/records', params={'date': today}).json()['record_count'] == 0
        water = clients[0].post('/api/life/water', json={'date': today, 'amount': 200,
            'request_key': 'cloud-water-first'}, headers=headers[0])
        assert water.status_code == 200, water.text
        assert water.json()['water_ml'] == 200
        life_result = clients[0].put('/api/life', json={'date': today, 'water_ml': 200,
            'sleep_hours': 7.5, 'version': water.json()['version'],
            'request_key': 'cloud-life-sleep-update'}, headers=headers[0])
        assert life_result.status_code == 200, life_result.text
        assert life_result.json()['sleep_hours'] == 7.5
        feedback = clients[0].put('/api/feedback/' + today, json={
            'hunger': '经常饿', 'request_key': 'cloud-feedback-first'}, headers=headers[0])
        assert feedback.status_code == 200, feedback.text
        assert feedback.json()['feedback']['hunger'] == '经常饿'
        assert clients[1].get('/api/feedback/' + today).json()['feedback'] is None
        report = clients[0].get('/api/reports', params={'end': today})
        assert report.status_code == 200, report.text
        assert len(report.json()['days']) == 7
        catalog = clients[0].get('/api/products')
        assert catalog.status_code == 200, catalog.text
        assert len(catalog.json()['items']) == 6
        assert catalog.json()['recommendations'] == []
        product = clients[0].post('/api/products', json={'name': '账户A私有测试产品',
            'request_key': 'cloud-product-create'}, headers=headers[0])
        assert product.status_code == 200, product.text
        product_id = product.json()['id']
        assert clients[1].get('/api/products/' + product_id).status_code == 404
        assert clients[0].get('/api/products/' + product_id).json()['match']['eligible'] is False
        edited_product = clients[0].put('/api/products/' + product_id, json={
            'name': '已隐藏测试产品', 'hidden': True, 'version': 1,
            'request_key': 'cloud-product-edit'}, headers=headers[0])
        assert edited_product.status_code == 200, edited_product.text
        assert edited_product.json()['hidden'] is True
        assert clients[0].post('/api/products/settings', json={'enabled': True,
            'request_key': 'cloud-product-settings'}, headers=headers[0]).status_code == 200
        assert clients[1].get('/api/products').json()['settings']['enabled'] is False
        assert clients[0].get('/api/product-plans', params={'date': today}).json()['items'] == []
        assert '推广内容' in clients[0].get('/api/products/' + product_id).json()['match']['commercial']
        rejected = clients[0].post('/api/products/' + product_id + '/consume', json={
            'version': 2, 'date': today, 'meal': '午餐', 'amount': 30,
            'confirmed': True, 'time': '12:00', 'request_key': 'unverified-product-consume'}, headers=headers[0])
        assert rejected.status_code == 400
        assert clients[0].get('/api/records', params={'date': today}).json()['record_count'] == 1
        # Product plans preserve the local explicit-plan / explicit-consumption boundary.
        verified_body = {'name': '合成正式标签样品', 'ingredients': '燕麦、水',
            'allergens': [], 'cross_contact': '无已知交叉接触', 'allergens_confirmed': True,
            'verification': '已核实', 'source': '自动化测试合成标签', 'verifier': '测试',
            'verified_date': today, 'unit': 'g',
            'nutrients': {'energy': 200, 'protein': 20, 'fat': 5, 'carbs': 20, 'sodium': 100},
            'request_key': 'verified-cloud-product'}
        verified = clients[0].post('/api/products', json=verified_body, headers=headers[0])
        assert verified.status_code == 200, verified.text
        verified_id = verified.json()['id']
        plan_body = {'date': today, 'meal': '加餐', 'amount': 35, 'version': 1,
                     'request_key': 'verified-product-plan'}
        product_plan = clients[0].post('/api/products/' + verified_id + '/plan',
            json=plan_body, headers=headers[0])
        assert product_plan.status_code == 200, product_plan.text
        pending_product = product_plan.json()
        assert clients[0].post('/api/products/' + verified_id + '/plan',
            json=plan_body, headers=headers[0]).json()['id'] == pending_product['id']
        assert len(clients[0].get('/api/product-plans', params={'date': today}).json()['items']) == 1
        assert clients[1].get('/api/product-plans', params={'date': today}).json()['items'] == []
        assert clients[0].get('/api/records', params={'date': today}).json()['record_count'] == 1
        cancel_path = '/api/product-plans/' + pending_product['id'] + '/cancel'
        cancel_body = {'version': 1, 'request_key': 'cancel-product-plan'}
        assert clients[1].post(cancel_path, json=cancel_body, headers=headers[1]).status_code == 404
        cancelled = clients[0].post(cancel_path, json=cancel_body, headers=headers[0])
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()['status'] == 'cancelled'
        assert clients[0].post(cancel_path, json=cancel_body, headers=headers[0]).json() == cancelled.json()
        assert clients[0].post(cancel_path, json={**cancel_body, 'version': 2,
            'request_key': 'cancel-again-new-request'}, headers=headers[0]).status_code == 400
        consume_body = {**plan_body, 'time': '15:00', 'plan_id': pending_product['id'],
            'plan_version': 2, 'confirmed': True, 'request_key': 'consume-cancelled-plan'}
        assert clients[0].post('/api/products/' + verified_id + '/consume',
            json=consume_body, headers=headers[0]).status_code == 409
        assert clients[0].get('/api/records', params={'date': today}).json()['record_count'] == 1
        next_plan = clients[0].post('/api/products/' + verified_id + '/plan',
            json={**plan_body, 'request_key': 'second-product-plan'}, headers=headers[0]).json()
        consume_body.update(plan_id=next_plan['id'], plan_version=1,
                            request_key='consume-pending-product', confirmed=False)
        assert clients[0].post('/api/products/' + verified_id + '/consume',
            json=consume_body, headers=headers[0]).status_code == 422
        assert clients[0].get('/api/records', params={'date': today}).json()['record_count'] == 1
        consume_body['confirmed'] = True
        eaten = clients[0].post('/api/products/' + verified_id + '/consume',
            json=consume_body, headers=headers[0])
        assert eaten.status_code == 200, eaten.text
        assert eaten.json()['nutrition']['protein']['known'] == 7
        assert clients[0].post('/api/products/' + verified_id + '/consume',
            json=consume_body, headers=headers[0]).json()['id'] == eaten.json()['id']
        assert clients[0].get('/api/records', params={'date': today}).json()['record_count'] == 2
        assert clients[1].get('/api/records', params={'date': today}).json()['record_count'] == 0
        assert clients[0].post('/api/products/' + verified_id + '/consume',
            json={**consume_body, 'request_key': 'consume-recorded-plan-again'},
            headers=headers[0]).status_code == 409
        assert clients[0].post('/api/records/' + eaten.json()['id'] + '/delete', json={
            'version': 1, 'request_key': 'remove-product-test-record'}, headers=headers[0]).status_code == 200
        assert clients[1].put('/api/records/' + recorded['id'], json={**record_body,
            'version': recorded['version']}, headers=headers[1]).status_code == 404
        assert clients[1].post('/api/records/' + recorded['id'] + '/delete', json={
            'version': recorded['version'], 'request_key': 'other-tenant-delete'}, headers=headers[1]).status_code == 404
        meal = next(meal for meal in planned.json()['plan']['meals'] if meal['recommendation'])
        confirmation = {'version': planned.json()['plan']['version'], 'action': 'confirm',
            'items': [{'food_id': item['food_id'], 'grams': item['grams']}
                      for item in meal['recommendation']['items']],
            'time': '13:00', 'request_key': 'confirm-plan-meal-cloud'}
        confirmed = clients[0].post('/api/plans/' + today + '/meals/' + meal['id'],
            json=confirmation, headers=headers[0])
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()['record']['source'] == 'plan'
        assert clients[0].get('/api/records', params={'date': today}).json()['record_count'] == 2
        assert clients[1].get('/api/records', params={'date': today}).json()['record_count'] == 0
        assert clients[1].get("/api/profile").json()["profile"] is None

        draft = clients[0].put('/api/profile/draft', json={
            'values': {'weight': 59}, 'step': 2, 'version': 0,
        }, headers=headers[0])
        assert draft.status_code == 200
        assert draft.json()['version'] == 1
        assert clients[0].get('/api/profile').json()['draft']['values'] == {'weight': 59}
        assert clients[0].get('/api/profile').json()['draft']['version'] == 1
        assert clients[1].get('/api/profile').json()['draft'] is None

        original_put = repository.put
        async def failed_measurement(kind, *args, **kwargs):
            if kind == "measurement":
                raise RuntimeError("simulated measurement persistence failure")
            return await original_put(kind, *args, **kwargs)
        monkeypatch.setattr(repository, "put", failed_measurement)
        with TestClient(app, raise_server_exceptions=False) as failing_client:
            failing_client.cookies.set("shansuan_session", sessions[1].cookie_token)
            response = failing_client.put("/api/profile", json=profile, headers=headers[1])
            assert response.status_code >= 500
        monkeypatch.setattr(repository, "put", original_put)
        assert clients[1].get("/api/profile").json()["profile"] is None, "profile and measurements must commit atomically"

        updated = clients[0].put(
            "/api/profile", json={**profile, "weight": 58, "version": 1}, headers=headers[0]
        )
        assert updated.status_code == 200, updated.text
        revised_plan = clients[0].get('/api/plans/' + today).json()['plan']
        assert revised_plan['needs_review'] is True
        pending = next(meal for meal in revised_plan['meals'] if meal['status'] == 'pending' and meal['recommendation'])
        blocked_confirmation = {**confirmation, 'version': revised_plan['version'],
                                'request_key': 'stale-profile-confirmation'}
        assert clients[0].post('/api/plans/' + today + '/meals/' + pending['id'],
            json=blocked_confirmation, headers=headers[0]).status_code == 409
        stale = clients[0].put(
            "/api/profile", json={**profile, "version": 1}, headers=headers[0]
        )
        assert stale.status_code == 409
        invalid = clients[0].put(
            "/api/profile", json={**profile, "primary_goal": "增肌", "version": 2}, headers=headers[0]
        )
        assert invalid.status_code == 422
        assert clients[0].get("/api/profile").json()["profile"]["weight"] == 58
        assert clients[1].get("/api/profile").json()["profile"] is None

        export = clients[0].post('/api/privacy/export', json={
            'password': 'cloud-profile-password-0'}, headers=headers[0])
        assert export.status_code == 200, export.text
        exported = export.json()
        assert exported['format'] == 'shansuan-account-export-v1'
        assert exported['account']['email'] == emails[0]
        assert any(entity['kind'] == 'profile' and entity['data']['weight'] == 58
                   for entity in exported['data']['entities'])
        assert not any(entity['kind'] == 'profile' and entity['data'].get('weight') == 59
                       for entity in exported['data']['entities'])
        assert exported['data']['attachments']['count'] == 0
        assert len(exported['data']['history']) > 0
        assert 'password_hash' not in export.text and 'wrapped_key' not in export.text
        assert 'Content-Disposition'.lower() in export.headers.get('access-control-expose-headers', '').lower()
        assert clients[0].post('/api/privacy/export', json={
            'password': 'cloud-profile-password-0'}, headers={'Origin': headers[0]['Origin']}).status_code == 403
        denied_export = clients[0].post('/api/privacy/export', json={
            'password': 'incorrect password'}, headers=headers[0])
        assert denied_export.status_code == 403

        async def inspect_history():
            connection = await asyncpg.connect(
                host=postgres_database['host'], port=postgres_database['port'],
                user='postgres', password=postgres_database['admin_password'],
                database=postgres_database['database'])
            try:
                rows = await connection.fetch(
                    'SELECT body_ciphertext FROM history WHERE account_id=$1', accounts[0])
                assert len(rows) >= 1, 'profile changes must preserve encrypted history before deletion'
                assert all(b'weight' not in bytes(row['body_ciphertext']) for row in rows)
            finally:
                await connection.close()
        asyncio.run(inspect_history())

        withdrawn = clients[0].post('/api/privacy/consent/withdraw', headers=headers[0])
        assert withdrawn.status_code == 200
        # Every currently enabled health route must stop processing after withdrawal.
        for method, path in [
            ('GET', '/api/profile'), ('PUT', '/api/profile'), ('PUT', '/api/profile/draft'),
            ('GET', '/api/home/' + today), ('GET', '/api/foods'),
            ('POST', '/api/nutrition/calculate'), ('PUT', '/api/life'),
            ('POST', '/api/life/water'), ('GET', '/api/feedback/' + today),
            ('PUT', '/api/feedback/' + today), ('GET', '/api/reports?end=' + today),
            ('GET', '/api/plans/' + today), ('POST', '/api/plans/' + today + '/meals/test'),
            ('GET', '/api/records?date=' + today), ('POST', '/api/records'),
            ('PUT', '/api/records/' + recorded['id']),
            ('POST', '/api/records/' + recorded['id'] + '/delete'),
            ('GET', '/api/products'), ('POST', '/api/products'),
            ('POST', '/api/products/settings'), ('GET', '/api/products/' + verified_id),
            ('PUT', '/api/products/' + verified_id),
            ('POST', '/api/products/' + verified_id + '/plan'),
            ('POST', '/api/products/' + verified_id + '/consume'),
            ('GET', '/api/product-plans?date=' + today), ('POST', cancel_path),
        ]:
            kwargs = {'headers': headers[0]}
            if method != 'GET':
                kwargs['json'] = {}
            response = clients[0].request(method, path, **kwargs)
            assert response.status_code == 428, (method, path, response.text)
        assert clients[0].get('/api/auth/me').status_code == 200
        assert clients[0].get('/api/privacy/consent').json()['accepted'] is False
        assert clients[1].get('/api/privacy/consent').json()['accepted'] is True
        post_withdrawal_export = clients[0].post('/api/privacy/export', json={
            'password': 'cloud-profile-password-0'}, headers=headers[0])
        assert post_withdrawal_export.status_code == 200, post_withdrawal_export.text
        assert post_withdrawal_export.json()['account']['email'] == emails[0]
        other_export = clients[1].post('/api/privacy/export', json={
            'password': 'cloud-profile-password-1'}, headers=headers[1])
        assert other_export.status_code == 200, other_export.text
        assert other_export.json()['account']['email'] == emails[1]
        assert not any(entity['kind'] == 'profile' for entity in other_export.json()['data']['entities'])
        assert other_export.json()['data']['history'] == []
        assert clients[0].request('DELETE', '/api/privacy/account', json={
            'password': 'wrong password', 'confirmation': '删除我的云端账户及全部数据'},
            headers=headers[0]).status_code == 403
        assert clients[0].request('DELETE', '/api/privacy/account', json={
            'password': 'cloud-profile-password-0', 'confirmation': '删除'},
            headers=headers[0]).status_code == 400
        assert clients[1].request('DELETE', '/api/privacy/account', json={
            'password': 'cloud-profile-password-0', 'confirmation': '删除我的云端账户及全部数据'},
            headers=headers[1]).status_code == 403
        deletion = clients[0].request('DELETE', '/api/privacy/account', json={
            'password': 'cloud-profile-password-0', 'confirmation': '删除我的云端账户及全部数据'},
            headers=headers[0])
        assert deletion.status_code == 200, deletion.text
        assert deletion.json() == {'deleted': True,
            'retention_note': '主数据库账户数据已删除；云端备份尚未配置。正式上线前需明确备份保留期限。'}
        assert clients[0].get('/api/auth/me').status_code == 401
        assert clients[1].get('/api/auth/me').status_code == 200
        assert clients[1].get('/api/privacy/consent').json()['accepted'] is True
        async def inspect_deleted_account():
            connection = await asyncpg.connect(
                host=postgres_database['host'], port=postgres_database['port'],
                user='postgres', password=postgres_database['admin_password'],
                database=postgres_database['database'])
            try:
                assert await connection.fetchval('SELECT count(*) FROM accounts WHERE id=$1', accounts[0]) == 0
                for table in ['sessions', 'privacy_consents', 'entities', 'history', 'requests',
                              'attachments', 'entity_photos', 'links', 'tasks', 'invites',
                              'audit_events', 'password_resets', 'account_keys']:
                    assert await connection.fetchval(
                        f'SELECT count(*) FROM {table} WHERE account_id=$1', accounts[0]) == 0, table
                assert await connection.fetchval('SELECT count(*) FROM accounts WHERE id=$1', accounts[1]) == 1
            finally:
                await connection.close()
        asyncio.run(inspect_deleted_account())
    finally:
        for client in clients:
            client.close()
