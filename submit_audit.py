import argparse
import json
from pathlib import Path
from dotenv import load_dotenv
from audit_client import request_json, RELATIONSHIPS, PLACEMENTS, FORMATS

def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description='Submit a video compliance screening job')
    parser.add_argument('video_url')
    parser.add_argument('--relationship', choices=RELATIONSHIPS, default='UNKNOWN')
    parser.add_argument('--placement', choices=PLACEMENTS, default='UNKNOWN')
    parser.add_argument('--ad-format', choices=FORMATS, default='UNKNOWN')
    parser.add_argument('--jurisdiction', default='UNKNOWN')
    parser.add_argument('--job-file', type=Path, default=Path('audit_job.json'))
    args = parser.parse_args()
    result = request_json('/audit/jobs', {'video_url': args.video_url, 'commercial_relationship': args.relationship,
                          'youtube_placement': args.placement, 'ad_format': args.ad_format, 'jurisdiction': args.jurisdiction})
    args.job_file.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
