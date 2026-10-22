"""Resolve a TXT contract, preserving the server's canonical TLS hostname."""
import argparse
import json
import re
import shlex
import subprocess
from pathlib import Path
from .policy import require


def parse_txt(answer,allowed_hosts,minimum_epoch):
    records=[line for line in answer.splitlines() if line.strip()]
    require(len(records)==1,'Expected exactly one writer TXT record')
    value=json.loads(''.join(shlex.split(records[0])))
    require(set(value)=={'host','epoch'} and value['host'] in allowed_hosts,'Unknown writer')
    require(type(value['epoch']) is int and value['epoch']>=minimum_epoch,'Stale or invalid routing epoch')
    require(re.fullmatch(r'[a-z0-9-]+\.postgres\.database\.azure\.com',value['host']) is not None,'Use canonical TLS hostname')
    return value


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--minimum-epoch',type=int,required=True)
    args=p.parse_args();m=json.loads(args.manifest.read_text())
    name='writer.'+m['routing']['zone_name']
    answer=subprocess.check_output(['dig','+short','TXT',name],text=True,timeout=10)
    print(json.dumps(parse_txt(answer,{m['source']['fqdn'],m['target']['fqdn']},args.minimum_epoch)))


if __name__=='__main__':main()
