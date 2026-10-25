// One isolation tier inside a shared resource group: Container Apps environment, Postgres server, Key Vault and
// its db-ops job. Graduated clients get two tiers (prod, nonprod); the sandbox gets one.
param location string
param tags object
param tenantId string
param workspaceId string

param caeName string
param caeSubnetId string

param pgName string
param pgSku string
param pgStorageGB int
param pgRetentionDays int
param pgHighAvailability bool = false
param pgGeoRedundantBackup bool = false
param pgSubnetId string
param dnsZoneId string
param pgAdminGroupObjectId string
param pgAdminGroupName string = 'pg-admins'

param kvName string

param dbopsJobName string
param dbopsIdentityId string
param dbopsIdentityName string
param dbopsPrincipalId string
param dbopsClientId string
param dbopsImage string
param registryServer string
param backupStorageAccount string

@description('Platform identity: starts db-ops executions and rotates secrets in this tier\'s vault.')
param platformPrincipalId string

@description('Extra env for the db-ops job, e.g. DBOPS_ALLOW_DROP on the sandbox only.')
param dbopsExtraEnv array = []

module cae 'cae.bicep' = {
  name: '${caeName}-env'
  params: {
    name: caeName
    location: location
    tags: tags
    subnetId: caeSubnetId
    workspaceId: workspaceId
  }
}

module pg 'postgres.bicep' = {
  name: '${pgName}-server'
  params: {
    name: pgName
    location: location
    tags: tags
    skuName: pgSku
    storageSizeGB: pgStorageGB
    backupRetentionDays: pgRetentionDays
    highAvailability: pgHighAvailability
    geoRedundantBackup: pgGeoRedundantBackup
    delegatedSubnetId: pgSubnetId
    privateDnsZoneId: dnsZoneId
    tenantId: tenantId
    workspaceId: workspaceId
    admins: [
      {
        objectId: pgAdminGroupObjectId
        principalName: pgAdminGroupName
        principalType: 'Group'
      }
      {
        objectId: dbopsPrincipalId
        principalName: dbopsIdentityName
        principalType: 'ServicePrincipal'
      }
    ]
  }
}

module kv 'keyvault.bicep' = {
  name: '${kvName}-vault'
  params: {
    name: kvName
    location: location
    tags: tags
    tenantId: tenantId
    workspaceId: workspaceId
    secretsOfficerPrincipalIds: [platformPrincipalId]
  }
}

module dbops 'job.bicep' = {
  name: '${dbopsJobName}-job'
  params: {
    name: dbopsJobName
    location: location
    tags: tags
    environmentId: cae.outputs.id
    identityId: dbopsIdentityId
    registryServer: registryServer
    image: dbopsImage
    command: ['blufire-dbops']
    containerName: 'dbops'
    triggerType: 'Manual'
    replicaTimeout: 7200
    cpu: '1.0'
    memory: '2Gi'
    env: concat([
      { name: 'PGHOST', value: pg.outputs.fqdn }
      { name: 'AZURE_CLIENT_ID', value: dbopsClientId }
      { name: 'PGUSER', value: dbopsIdentityName }
      { name: 'BACKUP_STORAGE_ACCOUNT', value: backupStorageAccount }
      { name: 'BACKUP_CONTAINER', value: 'pg-dumps' }
      { name: 'BACKUP_CONTAINER_PRE_PROMOTION', value: 'pg-dumps-prepromotion' }
      { name: 'RESULT_CONTAINER', value: 'dbops-results' }
    ], dbopsExtraEnv)
  }
}

resource dbopsJob 'Microsoft.App/jobs@2024-03-01' existing = {
  name: dbopsJobName
}

// Contributor on this one job is the narrowest built-in role that allows starting executions with argument overrides.
resource dbopsStarter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: dbopsJob
  name: guid(resourceGroup().id, dbopsJobName, platformPrincipalId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b24988ac-6180-42a0-ab88-20f7382dd24c')
    principalId: platformPrincipalId
    principalType: 'ServicePrincipal'
  }
  dependsOn: [dbops]
}

output caeId string = cae.outputs.id
output caeDefaultDomain string = cae.outputs.defaultDomain
output pgFqdn string = pg.outputs.fqdn
output kvUri string = kv.outputs.uri
