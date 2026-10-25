// sub-blufire-sandbox: one shared environment and one shared Postgres server for incubating apps.
// No real client data belongs here; backups are PITR only (7 days).
targetScope = 'subscription'

param location string
param tenantId string
param names object
param pgSku string
param pgStorageGB int
param pgAdminGroupObjectId string
param workspaceId string
param platformSubscriptionId string
param platformResourceGroupName string
param acrName string
param acrLoginServer string
param dbopsImage string
param backupSubscriptionId string
param backupResourceGroupName string
param backupStorageAccountName string
param platformPrincipalId string

var tags = {
  client: 'sandbox'
  app: 'shared'
  env: 'sandbox'
  'managed-by': 'blufire-platform'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: names.resourceGroup
  location: location
  tags: tags
}

module network '../modules/network.bicep' = {
  scope: rg
  name: 'sandbox-network'
  params: {
    location: location
    tags: tags
    vnetName: names.vnet
    addressPrefix: '10.30.0.0/16'
    postgresDnsZoneName: 'sandbox.private.postgres.database.azure.com'
    subnets: [
      {
        name: 'snet-cae'
        prefix: '10.30.0.0/23'
        delegation: 'Microsoft.App/environments'
        serviceEndpoints: ['Microsoft.Storage']
      }
      {
        name: 'snet-pg'
        prefix: '10.30.2.0/28'
        delegation: 'Microsoft.DBforPostgreSQL/flexibleServers'
        serviceEndpoints: []
      }
    ]
  }
}

module dbopsIdentity '../modules/identity.bicep' = {
  scope: rg
  name: 'sandbox-dbops-identity'
  params: {
    name: names.dbopsIdentity
    location: location
    tags: tags
  }
}

module tier '../modules/tier.bicep' = {
  scope: rg
  name: 'sandbox-tier'
  params: {
    location: location
    tags: tags
    tenantId: tenantId
    workspaceId: workspaceId
    caeName: names.cae
    caeSubnetId: network.outputs.subnetIds['snet-cae']
    pgName: names.postgres
    pgSku: pgSku
    pgStorageGB: pgStorageGB
    pgRetentionDays: 7
    pgSubnetId: network.outputs.subnetIds['snet-pg']
    dnsZoneId: network.outputs.dnsZoneId
    pgAdminGroupObjectId: pgAdminGroupObjectId
    kvName: names.keyVault
    dbopsJobName: names.dbopsJob
    dbopsIdentityId: dbopsIdentity.outputs.id
    dbopsIdentityName: dbopsIdentity.outputs.name
    dbopsPrincipalId: dbopsIdentity.outputs.principalId
    dbopsClientId: dbopsIdentity.outputs.clientId
    dbopsImage: dbopsImage
    registryServer: acrLoginServer
    backupStorageAccount: backupStorageAccountName
    platformPrincipalId: platformPrincipalId
    dbopsExtraEnv: [
      { name: 'DBOPS_ALLOW_DROP', value: '1' }
    ]
  }
  dependsOn: [acrPull]
}

module acrPull '../modules/acr-pull.bicep' = {
  scope: resourceGroup(platformSubscriptionId, platformResourceGroupName)
  name: 'sandbox-dbops-acr-pull'
  params: {
    acrName: acrName
    principalId: dbopsIdentity.outputs.principalId
  }
}

module backupAccess '../modules/storage-blob-role.bicep' = {
  scope: resourceGroup(backupSubscriptionId, backupResourceGroupName)
  name: 'sandbox-dbops-backup-access'
  params: {
    storageAccountName: backupStorageAccountName
    principalId: dbopsIdentity.outputs.principalId
    role: 'contributor'
    containers: ['pg-dumps', 'pg-dumps-prepromotion', 'dbops-results', 'migrations']
  }
}

module activityLog '../modules/activity-log.bicep' = {
  name: 'sandbox-activity-log'
  params: {
    workspaceId: workspaceId
  }
}

output caeSubnetId string = network.outputs.subnetIds['snet-cae']
output pgFqdn string = tier.outputs.pgFqdn
