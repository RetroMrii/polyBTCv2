"""Read-only integration checks. Output and inventories stay inside dashboard/."""
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parents[1]
ROOT = DASHBOARD.parent
sys.path.insert(0, str(DASHBOARD / 'backend'))

import httpx  # noqa: E402
from app.config import Settings  # noqa: E402
from app.data import read_db  # noqa: E402
from app.services import Monitor  # noqa: E402


def main():
    settings = Settings.load()
    statements = []
    original_connect = sqlite3.connect

    def trace_connect(*args, **kwargs):
        assert kwargs.get('uri') is True and str(args[0]).endswith('?mode=ro')
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    sqlite3.connect = trace_connect
    monitor = Monitor(settings)
    monitor.overview()
    monitor.performance()
    assert statements and all(s.lstrip().upper().startswith(('SELECT ', 'PRAGMA QUERY_ONLY=ON')) for s in statements)

    endpoints = {}
    with httpx.Client(base_url='http://127.0.0.1:8001', timeout=15) as client:
        for name in ('overview', 'market', 'telemetry', 'predictions', 'decisions', 'performance', 'resolutions', 'health', 'settings'):
            response = client.get('/api/' + name)
            assert response.status_code == 200, (name, response.text)
            endpoints[name] = {'status': response.status_code, 'bytes': len(response.content)}
        decisions = client.get('/api/decisions?page_size=100').json()['rows']
        with read_db(settings.decisions) as db:
            for row in decisions:
                stored = dict(db.execute('SELECT * FROM decisions WHERE id=?', (row['id'],)).fetchone())
                for key in ('condition_id', 'horizon_seconds', 'target_at_utc', 'reason', 'model_probability_yes', 'prediction_market_probability_yes', 'market_probability_yes', 'execution_price'):
                    assert row[key] == stored.get(key), (row['id'], key)
        report = client.get('/api/performance').json()['report']
        if report:
            original = json.loads(settings.report.read_text())
            for key in ('coverage', 'paired_model', 'paired_market', 'model_all_resolved', 'market_all_resolved', 'by_horizon', 'calibration_model'):
                assert report[key] == original[key], key
        resolutions = client.get('/api/resolutions').json()['rows']
        with read_db(settings.resolutions) as db:
            for row in resolutions:
                stored = dict(db.execute('SELECT * FROM resolutions WHERE condition_id=?', (row['condition_id'],)).fetchone())
                for key in row:
                    assert row[key] == stored.get(key)
        overview = client.get('/api/overview').json()

    initial = json.loads((DASHBOARD / 'audit/initial_inventory.json').read_text())['files']
    changed_static, missing, new_outside, live_changes = [], [], [], []
    for relative, before in initial.items():
        path = ROOT / relative
        if not path.exists():
            (live_changes if relative.startswith('data/') else missing).append(relative)
        elif 'sha256' in before:
            if hashlib.sha256(path.read_bytes()).hexdigest() != before['sha256']:
                changed_static.append(relative)
        elif path.stat().st_mtime_ns != before['mtime_ns']:
            live_changes.append(relative)
    for path in ROOT.rglob('*'):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if relative.parts[0] in ('dashboard', '.venv'):
            continue
        if relative.as_posix() not in initial:
            (live_changes if relative.parts[0] == 'data' else new_outside).append(relative.as_posix())
    result = {
        'checked_at_utc': datetime.now(timezone.utc).isoformat(),
        'api_endpoints': endpoints,
        'decision_rows_compared_to_database': len(decisions),
        'resolution_rows_compared_to_registry': len(resolutions),
        'report_matches_existing_json': bool(report),
        'actual_market': overview['telemetry']['current']['market_id'] if overview['telemetry']['current'] else None,
        'collector': overview['telemetry']['source'],
        'journal_activity': overview['health']['sources']['journal_activity'],
        'sql_trace': sorted(set(statements)),
        'all_dashboard_sql_read_only': True,
        'static_files_changed_outside_dashboard': changed_static,
        'static_files_missing_outside_dashboard': missing,
        'new_static_files_outside_dashboard': new_outside,
        'live_data_files_changed_by_concurrent_pipeline': sorted(set(live_changes)),
        'caveat': 'Live source files are concurrently written by the existing bot. Read-only URI, query_only, SQLite authorizer, isolated non-mutation tests and read-only SQL traces establish dashboard non-mutation; live hashes are not expected to stay constant.',
    }
    (DASHBOARD / 'audit/validation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    assert not changed_static and not missing and not new_outside, result
    print(json.dumps({key: value for key, value in result.items() if key not in ('sql_trace', 'live_data_files_changed_by_concurrent_pipeline')}, indent=2))


if __name__ == '__main__':
    main()
