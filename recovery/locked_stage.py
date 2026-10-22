"""Serialize proof, Terraform plan and exact-plan apply across compliant controllers."""
import json
import os
import subprocess
import sys
from pathlib import Path
from .live import Azure, Control, ROOT
from .policy import require, validate_manifest


def main():
    require(len(sys.argv)==3,'Choose stack and plan/apply operation')
    m=validate_manifest(json.loads(os.environ['RECOVERY_MANIFEST_JSON']))
    require(m['control']['account']==os.environ['BACKEND_ACCOUNT'],'Backend/control account mismatch')
    api=Azure()
    with Control(api,m) as control:
        run=ROOT/'.run';run.mkdir(exist_ok=True)
        journal=run/'journal.json'
        exists=api.call('storage','blob','exists',*control.args,'--name','incident.json')
        if exists.get('exists') is True:
            journal.write_text(json.dumps(control.load()))
        else:
            journal.unlink(missing_ok=True)
        env={**os.environ,'DR_PARENT_LEASE_ID':control.lease}
        result=subprocess.run(['bash','scripts/terraform-stage.sh',*sys.argv[1:]],cwd=ROOT,env=env)
        require(result.returncode==0,'Terraform stage failed; inspect private runner logs')


if __name__=='__main__':main()
