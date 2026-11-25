import argparse
import json
import time
from pathlib import Path
from dotenv import load_dotenv
from audit_client import get_job

def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description='Poll an audit and save the report')
    parser.add_argument('--job-id')
    parser.add_argument('--job-file', type=Path, default=Path('audit_job.json'))
    parser.add_argument('--output', type=Path, default=Path('audit_result.json'))
    parser.add_argument('--interval', type=float, default=10)
    parser.add_argument('--timeout', type=float, default=3600)
    args = parser.parse_args()
    if args.interval <= 0 or args.timeout <= 0:
        parser.error('interval and timeout must be positive')
    job_id = args.job_id or json.loads(args.job_file.read_text(encoding='utf-8'))['job_id']
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        data = get_job(job_id)
        print(f"{job_id}: {data['status']} | {data.get('current_stage') or 'pending'}", flush=True)
        if data['status'] in ('COMPLETED', 'FAILED'):
            args.output.write_text(json.dumps(data, indent=2), encoding='utf-8')
            print(json.dumps(data.get('result') or data.get('error'), indent=2))
            return 0 if data['status'] == 'COMPLETED' else 1
        time.sleep(min(args.interval, max(0, deadline - time.monotonic())))
    print('Polling timed out; the server job may still be running.')
    return 2

if __name__ == '__main__':
    raise SystemExit(main())
