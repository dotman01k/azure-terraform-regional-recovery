import json,os,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import Mock,patch
from recovery.policy import UnsafeRecovery,authorize_promotion,digest,fresh,inspect_plan,topology,validate_manifest,verify_adoption,verify_fence,verify_target
from recovery.discovery import parse_txt
from recovery.live import Control,execute
ROOT=Path(__file__).resolve().parents[1]
def manifest():return json.loads((ROOT/'examples/manifest.json').read_text())
def observation(promoted=False):
 m=manifest()
 return {'source':{'id':m['source']['id'],'state':'Stopped'},'target':{'id':m['target']['id'],'state':'Ready','fullyQualifiedDomainName':m['target']['fqdn'],'replicationRole':'None' if promoted else 'Replica','sourceServerResourceId':None if promoted else m['source']['id'],'authConfig':{'activeDirectoryAuth':'Enabled','passwordAuth':'Disabled'}},'subnet':{'id':m['source']['subnet_id'],'networkSecurityGroup':{'id':m['source']['nsg_id']}},'nsg':{'id':m['source']['nsg_id'],'securityRules':[{'name':'database-client-fence','priority':100,'direction':'Inbound','access':'Deny','protocol':'Tcp','sourcePortRange':'*','destinationPortRange':'5432','sourceAddressPrefix':'*','destinationAddressPrefix':'*'}]}}
def journal(phase='adopted'):return {'phase':phase,'manifest_hash':digest(manifest()),'verified_at':datetime.now(timezone.utc).isoformat(),'epoch':2,'writable_verified':True,'acknowledged_possible_data_loss':True,'incident':'INC-001'}
def change(address,kind,actions=None,after=None,before=None,**other):return {'address':address,'type':kind,'mode':'managed','change':{'actions':actions or ['no-op'],'after':after or {},'before':before,**other}}
def plan(*c):return {'complete':True,'resource_changes':list(c)}
def route(host,epoch=2,actions=None):return change('azurerm_private_dns_txt_record.writer','azurerm_private_dns_txt_record',actions,{'record':[{'value':json.dumps({'host':host,'epoch':epoch})}]})
class SafetyTests(unittest.TestCase):
 def test_manifest(self):validate_manifest(manifest())
 def test_same_server_rejected(self):
  m=manifest();m['target']=dict(m['source'])
  with self.assertRaises(UnsafeRecovery):validate_manifest(m)
 def test_wrong_hostname(self):
  m=manifest();m['target']['fqdn']='evil.example'
  with self.assertRaises(UnsafeRecovery):validate_manifest(m)
 def test_good_fence(self):verify_fence(manifest(),observation())
 def test_running_source(self):
  o=observation();o['source']['state']='Ready'
  with self.assertRaises(UnsafeRecovery):verify_fence(manifest(),o)
 def test_unattached_fence(self):
  o=observation();o['subnet']['networkSecurityGroup']={}
  with self.assertRaises(UnsafeRecovery):verify_fence(manifest(),o)
 def test_allow_is_not_fence(self):
  o=observation();o['nsg']['securityRules'][0]['access']='Allow'
  with self.assertRaises(UnsafeRecovery):verify_fence(manifest(),o)
 def test_partial_source_fence(self):
  o=observation();o['nsg']['securityRules'][0]['sourceAddressPrefix']='10.60.1.0/24'
  with self.assertRaises(UnsafeRecovery):verify_fence(manifest(),o)
 def test_precedence_bypass(self):
  o=observation();o['nsg']['securityRules'].append({'name':'bypass','priority':99})
  with self.assertRaises(UnsafeRecovery):verify_fence(manifest(),o)
 def test_loss_ack_required(self):
  with self.assertRaises(UnsafeRecovery):authorize_promotion(manifest(),observation(),'INC-1',False)
 def test_bound_authorization(self):
  j=authorize_promotion(manifest(),observation(),'INC-1',True);self.assertEqual(j['manifest_hash'],digest(manifest()));self.assertEqual(j['phase'],'authorized')
 def test_wrong_source(self):
  o=observation();o['target']['sourceServerResourceId']='other'
  with self.assertRaises(UnsafeRecovery):verify_target(manifest(),o['target'],False)
 def test_password_auth(self):
  o=observation();o['target']['authConfig']['passwordAuth']='Enabled'
  with self.assertRaises(UnsafeRecovery):verify_target(manifest(),o['target'],False)
 def test_promoted_cannot_keep_source(self):
  o=observation(True);o['target']['sourceServerResourceId']=manifest()['source']['id']
  with self.assertRaises(UnsafeRecovery):verify_target(manifest(),o['target'],True)
 def test_stale_and_future(self):
  for seconds in (-901,60):
   j=journal();j['verified_at']=(datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat()
   with self.assertRaises(UnsafeRecovery):fresh(j,manifest())
 def test_manifest_mutation(self):
  m=manifest();m['control']['account']='differentaccount'
  with self.assertRaises(UnsafeRecovery):fresh(journal(),m)
class PlanTests(unittest.TestCase):
 def test_replace_rejected(self):
  c=change('module.replica.azurerm_postgresql_flexible_server.this','azurerm_postgresql_flexible_server',['delete','create'])
  with self.assertRaises(UnsafeRecovery):inspect_plan(plan(c),'replica')
 def test_incomplete(self):
  p=plan();p['complete']=False
  with self.assertRaises(UnsafeRecovery):inspect_plan(p,'network')
 def test_unrelated_resource(self):
  with self.assertRaises(UnsafeRecovery):inspect_plan(plan(change('vm.other','azurerm_virtual_machine',['create'])),'network')
 def test_forget_restricted(self):
  c=change('module.replica.azurerm_postgresql_flexible_server.this','azurerm_postgresql_flexible_server',['forget'])
  self.assertTrue(inspect_plan(plan(c),'replica-detach')['passed'])
  with self.assertRaises(UnsafeRecovery):inspect_plan(plan(c),'replica')
 def test_adoption_no_mutation(self):
  for a in (['create'],['update']):
   with self.assertRaises(UnsafeRecovery):inspect_plan(plan(change('module.recovered.azurerm_postgresql_flexible_server.this','azurerm_postgresql_flexible_server',a)),'recovered',manifest())
 def test_wrong_import(self):
  c=change('module.recovered.azurerm_postgresql_flexible_server.this','azurerm_postgresql_flexible_server',importing={'id':'wrong'})
  with self.assertRaises(UnsafeRecovery):inspect_plan(plan(c),'recovered',manifest())
 def test_noop_import(self):
  c=change('module.recovered.azurerm_postgresql_flexible_server.this','azurerm_postgresql_flexible_server',importing={'id':manifest()['target']['id']})
  self.assertTrue(inspect_plan(plan(c),'recovered',manifest())['passed'])
 def test_route_requires_proof(self):
  for j in (None,journal('promoted'),{**journal(),'writable_verified':False}):
   with self.assertRaises(UnsafeRecovery):inspect_plan(plan(route(manifest()['target']['fqdn'])),'routing',manifest(),j)
 def test_route_verified(self):self.assertTrue(inspect_plan(plan(route(manifest()['target']['fqdn'])),'routing',manifest(),journal())['passed'])
 def test_unknown_writer(self):
  with self.assertRaises(UnsafeRecovery):inspect_plan(plan(route('evil.example')),'routing',manifest(),journal())
 def test_no_automatic_failback(self):
  with self.assertRaises(UnsafeRecovery):inspect_plan(plan(route(manifest()['source']['fqdn'],1,['update'])),'routing',manifest(),journal())
 def test_epoch_rollback(self):
  c=route(manifest()['target']['fqdn']);c['change']['before']={'record':[{'value':json.dumps({'host':manifest()['target']['fqdn'],'epoch':3})}]}
  with self.assertRaises(UnsafeRecovery):inspect_plan(plan(c),'routing',manifest(),journal())
 def test_original_stacks_frozen(self):
  c=change('module.primary.azurerm_postgresql_flexible_server.this','azurerm_postgresql_flexible_server',['update'])
  with self.assertRaises(UnsafeRecovery):inspect_plan(plan(c),'primary',manifest(),journal())
class AdoptionTests(unittest.TestCase):
 def states(self):
  m=manifest();return {'lineage':'old','resources':[]},{'lineage':'new','resources':[{'module':'module.recovered','mode':'managed','type':'azurerm_postgresql_flexible_server','instances':[{'attributes':{'id':m['target']['id'],'source_server_id':None}}]},{'module':'module.recovered','mode':'managed','type':'azurerm_postgresql_flexible_server_active_directory_administrator','instances':[{'attributes':{'id':m['target']['id']+'/administrators/admin'}}]}]}
 def test_valid(self):verify_adoption(manifest(),*self.states())
 def test_two_owners(self):
  old,new=self.states();old['resources']=[new['resources'][0]]
  with self.assertRaises(UnsafeRecovery):verify_adoption(manifest(),old,new)
 def test_same_lineage(self):
  old,new=self.states();new['lineage']='old'
  with self.assertRaises(UnsafeRecovery):verify_adoption(manifest(),old,new)
 def test_wrong_import(self):
  old,new=self.states();new['resources'][0]['instances'][0]['attributes']['id']='wrong'
  with self.assertRaises(UnsafeRecovery):verify_adoption(manifest(),old,new)
class LockTests(unittest.TestCase):
 def test_release(self):
  api=Mock()
  with patch.dict(os.environ,{},clear=True):
   with Control(api,manifest()):pass
  self.assertEqual(api.call.call_args_list[0].args[:4],('storage','blob','lease','acquire'));self.assertEqual(api.call.call_args_list[-1].args[:4],('storage','blob','lease','release'))
 def test_nested_renews_only(self):
  api=Mock()
  with patch.dict(os.environ,{'DR_PARENT_LEASE_ID':'parent'},clear=True):
   with Control(api,manifest()):pass
  api.call.assert_called_once();self.assertEqual(api.call.call_args.args[:4],('storage','blob','lease','renew'))
 def test_uncertain_promotion_observed(self):
  api=Mock();control=Mock();control.load.return_value=journal('authorized')
  with patch('recovery.live.observe',return_value=observation(True)):j=execute('promote',api,manifest(),control)
  api.call.assert_not_called();self.assertEqual(j['phase'],'promoted')
 def test_saved_ack_required(self):
  control=Mock();control.load.return_value={**journal('authorized'),'acknowledged_possible_data_loss':False}
  with patch('recovery.live.observe',return_value=observation()):
   with self.assertRaises(UnsafeRecovery):execute('promote',Mock(),manifest(),control)
class DiscoveryTests(unittest.TestCase):
 def test_canonical_tls_name(self):
  host=manifest()['target']['fqdn'];s=json.dumps(json.dumps({'host':host,'epoch':2}));self.assertEqual(parse_txt(s,{host},2)['host'],host)
 def test_stale_epoch(self):
  host=manifest()['target']['fqdn'];s=json.dumps(json.dumps({'host':host,'epoch':1}))
  with self.assertRaises(UnsafeRecovery):parse_txt(s,{host},2)
 def test_multiple_records(self):
  with self.assertRaises(UnsafeRecovery):parse_txt('"one"\n"two"',set(),1)
 def test_overlap(self):
  r={'primary':{'location':'eastus','cidr':'10.60.0.0/16','database_cidr':'10.60.0.0/24','client_cidr':'10.60.1.0/24'},'recovery':{'location':'westus3','cidr':'10.60.0.0/16','database_cidr':'10.60.2.0/24','client_cidr':'10.60.3.0/24'}}
  with self.assertRaises(UnsafeRecovery):topology(r)
if __name__=='__main__':unittest.main()

class AdditionalGateTests(unittest.TestCase):
 def test_unknown_empty_stack(self):
  with self.assertRaises(UnsafeRecovery):inspect_plan(plan(),'invalid')
 def test_unknown_action(self):
  with self.assertRaises(UnsafeRecovery):inspect_plan(plan(change('azurerm_virtual_network.region','azurerm_virtual_network',['invalid'])),'network')
 def test_weakened_incident_fence(self):
  rule={'name':'database-client-fence','priority':100,'direction':'Inbound','access':'Deny','protocol':'Tcp','source_port_range':'*','destination_port_range':'5432','source_address_prefix':'10.60.1.0/24','destination_address_prefix':'*'}
  c=change('azurerm_network_security_group.database["primary"]','azurerm_network_security_group',['update'],{'security_rule':[rule]})
  with self.assertRaises(UnsafeRecovery):inspect_plan(plan(c),'network',manifest(),journal())
