"""Explicit live recovery operations. Offline validation never imports cloud credentials."""
import argparse
import contextlib
import json
import os
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .policy import (UnsafeRecovery, authorize_promotion, digest, fresh, require,
                     validate_manifest, verify_adoption, verify_fence, verify_target)

ROOT=Path(__file__).resolve().parents[1]


class Azure:
    def call(self,*args):
        result=subprocess.run(['az',*args,'--only-show-errors','--output','json'],capture_output=True,text=True,timeout=900)
        if result.returncode:
            # Do not forward raw service output containing resource data or credentials.
            raise RuntimeError('Azure CLI operation failed: '+' '.join(args[:3])+f' (exit {result.returncode})')
        return json.loads(result.stdout) if result.stdout.strip() else None


def observe(api,m):
    source=api.call('postgres','flexible-server','show','--ids',m['source']['id'])
    target=api.call('postgres','flexible-server','show','--ids',m['target']['id'])
    nsg=api.call('network','nsg','show','--ids',m['source']['nsg_id'])
    subnet=api.call('network','vnet','subnet','show','--ids',m['source']['subnet_id'])
    return {'source':source,'target':target,'nsg':nsg,'subnet':subnet,
            'observed_at':datetime.now(timezone.utc).isoformat()}


class Control:
    def __init__(self,api,m):
        self.api=api;self.m=m;self.parent=os.environ.get('DR_PARENT_LEASE_ID');self.lease=self.parent or str(uuid.uuid4())
        self.args=['--account-name',m['control']['account'],'--container-name',m['control']['container'],'--auth-mode','login']
    def __enter__(self):
        # A parent Terraform stage keeps the same lease through proof, plan and apply.
        if self.parent:
            self.api.call('storage','blob','lease','renew',*self.args,'--blob-name','campaign.lock','--lease-id',self.lease)
            return self
        # The lock blob is created once by the operator. No silent creation/reset in recovery.
        self.api.call('storage','blob','lease','acquire',*self.args,'--blob-name','campaign.lock',
                      '--lease-duration','-1','--proposed-lease-id',self.lease)
        return self
    def __exit__(self,*exc):
        if self.parent:
            return
        self.api.call('storage','blob','lease','release',*self.args,'--blob-name','campaign.lock','--lease-id',self.lease)
    def load(self):
        exists=self.api.call('storage','blob','exists',*self.args,'--name','incident.json')
        require(exists.get('exists') is True,'No journal. Authorize the incident first.')
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'journal.json'
            self.api.call('storage','blob','download',*self.args,'--name','incident.json','--file',str(p),'--overwrite','true')
            return json.loads(p.read_text())
    def save(self,journal):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'journal.json';p.write_text(json.dumps(journal,indent=2))
            self.api.call('storage','blob','upload',*self.args,'--name','incident.json','--file',str(p),'--overwrite','true')


def writable_probe(api,m,username):
    require(username and '\n' not in username,'Set the Entra PostgreSQL group login name')
    token=api.call('account','get-access-token','--resource','https://ossrdbms-aad.database.windows.net')['accessToken']
    env={**os.environ,'PGHOST':m['target']['fqdn'],'PGPORT':'5432','PGDATABASE':'postgres',
         'PGUSER':username,'PGPASSWORD':token,'PGSSLMODE':'verify-full','PGCONNECT_TIMEOUT':'10'}
    sql=('BEGIN; CREATE TABLE IF NOT EXISTS public.dr_write_probe (id integer PRIMARY KEY); '
         'INSERT INTO public.dr_write_probe VALUES (1) ON CONFLICT (id) DO NOTHING; '
         "SELECT CASE WHEN pg_is_in_recovery() THEN 'READ_ONLY' ELSE 'DR_WRITABLE' END; ROLLBACK;")
    result=subprocess.run(['psql','--no-psqlrc','--set','ON_ERROR_STOP=1','--tuples-only','--no-align','--command',sql],
                          env=env,capture_output=True,text=True,timeout=60)
    require(result.returncode==0 and 'DR_WRITABLE' in result.stdout.splitlines(),'Writable TLS-verified SQL probe failed')


def terraform_state(root,m):
    metadata=ROOT/'stacks'/root/'.terraform/terraform.tfstate'
    require(metadata.is_file(),'Initialize the exact backend before state adoption')
    config=json.loads(metadata.read_text())['backend']['config']
    key='replica' if root=='replica-detach' else 'recovered'
    require(config.get('key')==f'regional-recovery/{key}.tfstate','Wrong state key')
    require(config.get('storage_account_name')==m['control']['account'] and config.get('container_name')=='tfstate','Wrong state account/container')
    result=subprocess.run(['terraform',f'-chdir={ROOT / "stacks" / root}','state','pull'],capture_output=True,text=True,timeout=120)
    require(result.returncode==0,'Cannot read initialized '+root+' backend state')
    return json.loads(result.stdout)


def execute(action,api,m,control,incident=None,ack_loss=False,epoch=2,username=None):
    observation=observe(api,m)
    if action=='authorize':
        # Prevent replacing any existing active incident record accidentally.
        exists=api.call('storage','blob','exists',*control.args,'--name','incident.json')
        require(exists.get('exists') is False,'Incident journal already exists; resume it or archive it after review')
        j=authorize_promotion(m,observation,incident,ack_loss)
        require(type(epoch) is int and epoch>1,'Recovery epoch must exceed the initial epoch')
        j['epoch']=epoch;control.save(j);return j
    j=control.load();require(j['manifest_hash']==digest(m),'Manifest/journal mismatch')
    verify_fence(m,observation)
    if action=='promote':
        require(j['phase'] in ('authorized','promoted'),'Incorrect promotion phase')
        require(j.get('acknowledged_possible_data_loss') is True,'Data-loss acknowledgement missing')
        target=observation['target']
        if target.get('replicationRole')=='Replica':
            fresh(j,m)
            verify_target(m,target,False)
            # The API's forced standalone option is deliberate; there is no zero-data-loss claim.
            api.call('postgres','flexible-server','replica','promote','--ids',m['target']['id'],
                     '--promote-mode','standalone','--promote-option','forced','--yes')
            target=api.call('postgres','flexible-server','show','--ids',m['target']['id'])
        # If a prior attempt committed but the response was lost, verify the actual writer;
        # do not reissue an uncertain promotion blindly.
        verify_target(m,target,True)
        j.update(phase='promoted',verified_at=datetime.now(timezone.utc).isoformat());control.save(j)
    elif action=='probe':
        require(j['phase'] in ('promoted','probed','adopted'),'Promote before SQL probing')
        verify_target(m,observation['target'],True);writable_probe(api,m,username)
        phase='adopted' if j['phase']=='adopted' else 'probed'
        j.update(phase=phase,writable_verified=True,verified_at=datetime.now(timezone.utc).isoformat());control.save(j)
    elif action=='adopted':
        require(j['phase'] in ('probed','adopted'),'Probe before adopting state')
        verify_target(m,observation['target'],True)
        verify_adoption(m,terraform_state('replica-detach',m),terraform_state('recovered',m))
        # A fresh SQL probe avoids accepting a historical observation after state maintenance.
        writable_probe(api,m,username)
        j.update(phase='adopted',writable_verified=True,verified_at=datetime.now(timezone.utc).isoformat());control.save(j)
    elif action=='routing-evidence':
        require(j['phase']=='adopted','State adoption is not complete')
        verify_target(m,observation['target'],True)
        verify_adoption(m,terraform_state('replica-detach',m),terraform_state('recovered',m))
        writable_probe(api,m,username)
        j['verified_at']=datetime.now(timezone.utc).isoformat();control.save(j)
    else:
        raise UnsafeRecovery('Unknown action')
    return j


def main():
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=['observe','stop-primary','authorize','promote','probe','adopted','routing-evidence'])
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--execute',action='store_true')
    p.add_argument('--confirm-target')
    p.add_argument('--incident')
    p.add_argument('--ack-possible-data-loss',action='store_true')
    p.add_argument('--epoch',type=int,default=2)
    args=p.parse_args();m=validate_manifest(json.loads(args.manifest.read_text()));api=Azure()
    if args.action=='observe':
        result=observe(api,m)
    else:
        require(args.execute and args.confirm_target==m['target']['id'],'Explicit execution and exact target confirmation required')
        with Control(api,m) as control:
            if args.action=='stop-primary':
                # The NSG must already deny 5432 BEFORE stopping existing sessions.
                o=observe(api,m)
                hypothetical={**o,'source':{**o['source'],'state':'Stopped'}}
                verify_fence(m,hypothetical)
                if o['source'].get('state')!='Stopped':
                    api.call('postgres','flexible-server','stop','--ids',m['source']['id'])
                result=observe(api,m);verify_fence(m,result)
            else:
                result=execute(args.action,api,m,control,args.incident,args.ack_possible_data_loss,args.epoch,os.environ.get('PG_ADMIN_GROUP'))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print('Recovery operation completed; private evidence written to the requested file.')


if __name__=='__main__':main()
