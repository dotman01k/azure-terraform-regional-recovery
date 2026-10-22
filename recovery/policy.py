import hashlib
import ipaddress
import json
import re
from datetime import datetime, timezone


class UnsafeRecovery(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise UnsafeRecovery(message)


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_manifest(m):
    require(m.get('schema_version') == 1, 'Unsupported manifest')
    server = r'/subscriptions/([0-9a-fA-F-]{36})/resourceGroups/([^/]+)/providers/Microsoft.DBforPostgreSQL/flexibleServers/([a-z0-9-]+)'
    ids=[]
    for key in ('source','target'):
        match=re.fullmatch(server,m[key]['id'],re.I)
        require(match is not None,'Invalid PostgreSQL ARM ID')
        require(m[key]['fqdn'] == match.group(3)+'.postgres.database.azure.com','Canonical hostname mismatch')
        ids.append(match)
    require(m['source']['id'].lower()!=m['target']['id'].lower(),'Source and target must differ')
    require(ids[0].group(1).lower()==ids[1].group(1).lower(),'Cross-subscription recovery is outside scope')
    require(m['source']['nsg_id'].lower().startswith('/subscriptions/'+ids[0].group(1).lower()+'/'),'NSG subscription mismatch')
    require(m['source']['subnet_id'].lower().startswith('/subscriptions/'+ids[0].group(1).lower()+'/'),'Subnet subscription mismatch')
    require(re.fullmatch(r'[a-z0-9]{3,24}',m['control']['account']) is not None,'Invalid control storage account')
    require(re.fullmatch(r'[a-z0-9-]{3,63}',m['control']['container']) is not None,'Invalid control container')
    return m


def verify_fence(m, observation):
    require(observation['source']['id'].lower()==m['source']['id'].lower(),'Wrong source evidence')
    require(observation['source'].get('state')=='Stopped','Source must be observed Stopped')
    require(observation['nsg']['id'].lower()==m['source']['nsg_id'].lower(),'Wrong NSG')
    subnet=observation['subnet']
    require(subnet['id'].lower()==m['source']['subnet_id'].lower(),'Wrong subnet')
    require(subnet.get('networkSecurityGroup',{}).get('id','').lower()==m['source']['nsg_id'].lower(),'Fence NSG is not attached')
    rules=[r for r in observation['nsg'].get('securityRules',[]) if r['name']=='database-client-fence']
    require(len(rules)==1,'Missing unique fence rule')
    r=rules[0]
    require(all(r.get(k)==v for k,v in {'priority':100,'direction':'Inbound','access':'Deny','protocol':'Tcp',
      'sourcePortRange':'*','destinationPortRange':'5432','sourceAddressPrefix':'*','destinationAddressPrefix':'*'}.items()),'Fence rule does not block all supported client paths')
    # A lower-priority-number allow can bypass the fence. Reject all custom rules ahead of it.
    require(not any(r.get('priority',4096)<100 for r in observation['nsg'].get('securityRules',[])),'Higher precedence rule bypasses fence')


def verify_target(m, target, promoted):
    require(target['id'].lower()==m['target']['id'].lower(),'Wrong target')
    require(target.get('state')=='Ready','Target is not Ready')
    require(target.get('fullyQualifiedDomainName')==m['target']['fqdn'],'Target hostname mismatch')
    auth=target.get('authConfig',{})
    require(auth.get('activeDirectoryAuth')=='Enabled' and auth.get('passwordAuth')=='Disabled','Target must retain Entra-only authentication')
    if promoted:
        require(target.get('replicationRole') in ('None','Primary') and not target.get('sourceServerResourceId'),'Target is not an independent writer')
    else:
        require(target.get('replicationRole')=='Replica','Target is not a read replica')
        require(target.get('sourceServerResourceId','').lower()==m['source']['id'].lower(),'Replica source mismatch')


def fresh(journal,m,now=None):
    now=now or datetime.now(timezone.utc)
    require(journal.get('manifest_hash')==digest(m),'Manifest changed during incident')
    timestamp=datetime.fromisoformat(journal['verified_at'])
    require(timestamp.tzinfo is not None,'Evidence timestamp must include a timezone')
    age=(now-timestamp).total_seconds()
    require(0<=age<=900,'Evidence is stale or from the future; re-verify')


def authorize_promotion(m, observation, incident, ack_loss):
    validate_manifest(m)
    require(re.fullmatch(r'[A-Za-z0-9_-]{3,64}',incident) is not None,'Invalid incident reference')
    require(ack_loss is True,'Forced promotion requires explicit potential data-loss acknowledgement')
    verify_fence(m,observation)
    verify_target(m,observation['target'],False)
    return {'schema_version':1,'incident':incident,'manifest_hash':digest(m),'phase':'authorized',
      'acknowledged_possible_data_loss':True,'verified_at':datetime.now(timezone.utc).isoformat()}


def verify_adoption(m,old_state,new_state):
    require(old_state.get('lineage') and new_state.get('lineage'),'Missing Terraform state lineage')
    require(old_state['lineage']!=new_state['lineage'],'The two roots point to the same state')
    require(not old_state.get('resources'),'Replica state still owns resources')
    resources=[r for r in new_state.get('resources',[]) if r.get('mode')=='managed']
    servers=[r for r in resources if r.get('type')=='azurerm_postgresql_flexible_server']
    require(len(servers)==1 and servers[0].get('module')=='module.recovered','Wrong recovered ownership address')
    instances=servers[0].get('instances',[])
    require(len(instances)==1 and instances[0]['attributes']['id'].lower()==m['target']['id'].lower(),'Recovered state points elsewhere')
    require(instances[0]['attributes'].get('source_server_id') in (None,''),'Recovered state still references a replication source')
    admins=[r for r in resources if r.get('type')=='azurerm_postgresql_flexible_server_active_directory_administrator']
    require(len(admins)==1 and len(resources)==2,'Recovered state must own exactly the server and Entra admin')
    require(admins[0].get('module')=='module.recovered','Wrong admin ownership address')
    require(len(admins[0].get('instances',[]))==1 and admins[0]['instances'][0]['attributes']['id'].lower().startswith(m['target']['id'].lower()+'/administrators/'),'Wrong adopted admin')


def topology(regions):
    require(set(regions)=={'primary','recovery'},'Exactly two named regions required')
    require(regions['primary']['location']!=regions['recovery']['location'],'Regions must differ')
    networks=[]
    for region in regions.values():
        parent=ipaddress.ip_network(region['cidr'],strict=True)
        db=ipaddress.ip_network(region['database_cidr'],strict=True)
        client=ipaddress.ip_network(region['client_cidr'],strict=True)
        require(parent.version==4 and db.subnet_of(parent) and client.subnet_of(parent),'Subnets must lie within the IPv4 VNet')
        require(not db.overlaps(client) and db.num_addresses>=16,'DB/client subnets overlap or DB subnet is too small')
        networks.append(parent)
    require(not networks[0].overlaps(networks[1]),'Peered VNet address ranges overlap')


DATABASE_TYPES={'azurerm_postgresql_flexible_server','azurerm_postgresql_flexible_server_active_directory_administrator'}
NETWORK_TYPES={'azurerm_resource_group','azurerm_virtual_network','azurerm_subnet','azurerm_network_security_group',
 'azurerm_subnet_network_security_group_association','azurerm_virtual_network_peering','azurerm_private_dns_zone','azurerm_private_dns_zone_virtual_network_link'}


def inspect_plan(plan,stack,m=None,journal=None,now=None):
    require(plan.get('errored') is not True,'Terraform plan errored')
    require(plan.get('complete') is True and not plan.get('deferred_changes'),'Incomplete/deferred plans are prohibited')
    changes=plan.get('resource_changes',[])
    require(isinstance(changes,list),'Malformed plan')
    for entry in changes:
        if entry.get('mode')=='data':
            continue
        action=entry['change']['actions']
        address=entry['address'];kind=entry['type']
        require('delete' not in action,'Deletes and replacements are prohibited: '+address)
        if stack=='replica-detach':
            require(address.startswith('module.replica.') and kind in DATABASE_TYPES,'Unexpected state detachment target')
            require(action in (['forget'],['no-op']),'Detach must only forget Terraform ownership')
            continue
        require('forget' not in action,'Forget is restricted to replica-detach')
        if stack=='network':
            if journal and kind=='azurerm_network_security_group' and address.endswith('["primary"]'):
                rules=(entry['change'].get('after') or {}).get('security_rule',[])
                require(any(r.get('name')=='database-client-fence' and r.get('access')=='Deny' for r in rules),'Cannot remove the incident fence')
            require(kind in NETWORK_TYPES and not address.startswith('module.'),'Unexpected network resource')
        elif stack in ('primary','replica','recovered'):
            if journal and stack in ('primary','replica'):
                require(action==['no-op'],'Original database stacks are frozen during recovery')
            require(kind in DATABASE_TYPES and address==f'module.{stack}.{kind}.this','Unexpected database resource')
            if stack=='recovered':
                require(action==['no-op'],'Adoption must import without changing cloud resources')
                if entry['change'].get('importing'):
                    imported=entry['change']['importing'].get('id','')
                    require(m is not None and (imported.lower()==m['target']['id'].lower() if kind.endswith('flexible_server') else imported.lower().startswith(m['target']['id'].lower()+'/administrators/')),'Import ID mismatch')
        elif stack=='routing':
            require(address=='azurerm_private_dns_txt_record.writer','Unexpected routing resource')
            after=entry['change'].get('after') or {}
            records=after.get('record',[])
            require(len(records)==1 and isinstance(records[0].get('value'),str),'Unknown/multiple routing values')
            try: writer=json.loads(records[0]['value'])
            except (ValueError,TypeError) as exc: raise UnsafeRecovery('Invalid TXT routing payload') from exc
            require(set(writer)=={'host','epoch'} and type(writer['epoch']) is int and writer['epoch']>=1,'Invalid routing contract')
            require(m is not None,'Routing requires an explicit recovery manifest')
            if writer['host']==m['source']['fqdn']:
                require(writer['epoch']==1 and action in (['create'],['no-op']),'Automatic failback is prohibited')
            else:
                require(writer['host']==m['target']['fqdn'] and journal is not None,'Unknown writer')
                fresh(journal,m,now)
                require(journal['phase']=='adopted' and journal.get('writable_verified') is True,'Verify writable DB and state adoption before routing')
                require(writer['epoch']==journal['epoch'] and writer['epoch']>1,'Routing epoch mismatch')
                before=entry['change'].get('before') or {}
                if before.get('record'):
                    previous=json.loads(before['record'][0]['value'])
                    require(writer['epoch']>previous['epoch'] or (writer==previous and action==['no-op']),'Routing epoch cannot go backward')
        else:
            raise UnsafeRecovery('Unknown stack')
    return {'stack':stack,'managed_changes':sum(e.get('mode')!='data' and e['change']['actions']!=['no-op'] for e in changes),'passed':True}
