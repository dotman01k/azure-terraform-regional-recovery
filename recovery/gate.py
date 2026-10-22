import argparse
import json
from pathlib import Path
from .policy import inspect_plan, validate_manifest


def main():
    p=argparse.ArgumentParser(description='Reject unsafe Terraform JSON plans')
    p.add_argument('--plan',type=Path,required=True)
    p.add_argument('--stack',required=True)
    p.add_argument('--manifest',type=Path)
    p.add_argument('--journal',type=Path)
    args=p.parse_args()
    m=validate_manifest(json.loads(args.manifest.read_text())) if args.manifest else None
    j=json.loads(args.journal.read_text()) if args.journal else None
    print(json.dumps(inspect_plan(json.loads(args.plan.read_text()),args.stack,m,j),sort_keys=True))


if __name__=='__main__':main()
