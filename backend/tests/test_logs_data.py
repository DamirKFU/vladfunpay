import asyncio
import io
import json
import logging
import zipfile

from app.core.log_sink import QueueLogHandler, flush_forever
from app.core.masking import masker
from app.repositories.memory import MemoryLogRepository
from app.usecases.data import LogService


async def test_logs_go_to_repository_masked():
    repo = MemoryLogRepository()
    handler = QueueLogHandler(asyncio.get_running_loop())
    logger = logging.getLogger('test.sink')
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    masker.register('super-secret-golden-key')
    task = asyncio.create_task(flush_forever(handler, repo))
    try:
        logger.info('cookie golden_key=super-secret-golden-key; ok')
        logger.warning('Api-Key AQVNabc123 failed', extra={'chat_id': '7'})
        for _ in range(30):
            await asyncio.sleep(0.05)
            if len(await repo.query(None, None, None, None, 10)) == 2:
                break
    finally:
        task.cancel()
        logger.removeHandler(handler)
    entries = await repo.query(None, None, None, None, 10)
    text = ' '.join(e.message for e in entries)
    assert 'super-secret-golden-key' not in text
    assert 'AQVNabc123' not in text
    warning = (await repo.query('WARNING', None, None, None, 10))[0]
    assert warning.context == {'chat_id': '7'}

    export = await LogService(repo).export(None, 'test.sink', None)
    lines = [json.loads(x) for x in export.decode().splitlines()]
    assert [x['level'] for x in lines] == ['INFO', 'WARNING']


def test_logs_api_and_db_export(auth_client, settings_service):
    asyncio.run(
        settings_service.update({'funpay': {'golden_key': 'gk-secret-777'}}),
    )
    assert auth_client.get('/api/logs').status_code == 200
    resp = auth_client.get('/api/logs/export')
    assert resp.status_code == 200
    assert 'attachment' in resp.headers['content-disposition']

    resp = auth_client.get('/api/data/export')
    assert resp.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    names = set(archive.namelist())
    assert {
        'orders.jsonl',
        'users.jsonl',
        'settings.json',
        'manifest.json',
    } <= names
    assert b'gk-secret-777' not in archive.read('settings.json')
    assert b'password_hash' not in archive.read('users.jsonl')
