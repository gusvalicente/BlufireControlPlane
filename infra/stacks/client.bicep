// sub-<client>: shared infrastructure for a graduated client. Two isolation tiers in rg-<c>-shared:
// prod (dedicated Postgres + Container Apps environment) and nonprod (one Postgres + environment shared by dev and
// cert). The environment split mirrors the Postgres split so prod network, data and secrets never mix with nonprod.
targetScope = 'subscription'

param location string
param tenantId string
param clientId string
param names object
param prodSku string
param nonprodSku string
param prodHighAvailability bool
param prodRetentionDays int
param pgStorageGB int
param geoRedundantBackup bool = false
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
  client: clientId
  app: 'shared'
  env: 'shared'
  'managed-by': 'blufire-platform'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: names.resourceGroup
  location: location
  tags: tags
}

module network '../modules/network.bicep' = {
  scope: rg
  name: '${clientId}-network'
  params: {
    location: location
    tags: tags
    vnetName: names.vnet
    addressPrefix: '10.20.0.0/16'
    postgresDnsZoneName: '${clientId}.private.postgres.database.azure.com'
    subnets: [
      {
        name: 'snet-cae-prod'
        prefix: '10.20.0.0/23'
        delegation: 'Microsoft.App/environments'
        serviceEndpoints: ['Microsoft.Storage']
      }
      {
        name: 'snet-cae-nonprod'
        prefix: '10.20.2.0/23'
        delegation: 'Microsoft.App/environments'
        serviceEndpoints: ['Microsoft.Storage']
      }
      {
        name: 'snet-pg-prod'
        prefix: '10.20.4.0/28'
        delegation: 'Microsoft.DBforPostgreSQL/flexibleServers'
        serviceEndpoints: []
      }
      {
        name: 'snet-pg-nonprod'
        prefix: '10.20.4.16/28'
        delegation: 'Microsoft.DBforPostgreSQL/flexibleServers'
        serviceEndpoints: []
      }
    ]
  }
}

module dbopsIdentity '../modules/identity.bicep' = {
  scope: rg
  name: '${clientId}-dbops-identity'
  params: {
    name: names.dbopsIdentity
    location: location
    tags: tags
  }
}

module acrPull '../modules/acr-pull.bicep' = {
  scope: resourceGroup(platformSubscriptionId, platformResourceGroupName)
  name: '${clientId}-dbops-acr-pull'
  params: {
    acrName: acrName
    principalId: dbopsIdentity.outputs.principalId
  }
}

module backupAccess '../modules/storage-blob-role.bicep' = {
  scope: resourceGroup(backupSubscriptionId, backupResourceGroupName)
  name: '${clientId}-dbops-backup-access'
  params: {
    storageAccountName: backupStorageAccountName
    principalId: dbopsIdentity.outputs.principalId
    role: 'contributor'
    containers: ['pg-dumps', 'pg-dumps-prepromotion', 'dbops-results', 'migrations']
  }
}

var tiers = [
  {
    key: 'prod'
    sku: prodSku
    ha: prodHighAvailability
    retention: prodRetentionDays
  }
  {
    key: 'nonprod'
    sku: nonprodSku
    ha: false
    retention: 7
  }
]

module tier '../modules/tier.bicep' = [for t in tiers: {
  scope: rg
  name: '${clientId}-tier-${t.key}'
  params: {
    location: location
    tags: union(tags, { env: t.key })
    tenantId: tenantId
    workspaceId: workspaceId
    caeName: names.cae[t.key]
    caeSubnetId: network.outputs.subnetIds['snet-cae-${t.key}']
    pgName: names.postgres[t.key]
    pgSku: t.sku
    pgStorageGB: pgStorageGB
    pgRetentionDays: t.retention
    pgHighAvailability: t.ha
    pgGeoRedundantBackup: geoRedundantBackup
    pgSubnetId: network.outputs.subnetIds['snet-pg-${t.key}']
    dnsZoneId: network.outputs.dnsZoneId
    pgAdminGroupObjectId: pgAdminGroupObjectId
    kvName: names.keyVault[t.key]
    dbopsJobName: names.dbopsJob[t.key]
    dbopsIdentityId: dbopsIdentity.outputs.id
    dbopsIdentityName: dbopsIdentity.outputs.name
    dbopsPrincipalId: dbopsIdentity.outputs.principalId
    dbopsClientId: dbopsIdentity.outputs.clientId
    dbopsImage: dbopsImage
    registryServer: acrLoginServer
    backupStorageAccount: backupStorageAccountName
    platformPrincipalId: platformPrincipalId
  }
  dependsOn: [acrPull]
}]

module activityLog '../modules/activity-log.bicep' = {
  name: '${clientId}-activity-log'
  params: {
    workspaceId: workspaceId
  }
}

output caeSubnetIds array = [network.outputs.subnetIds['snet-cae-prod'], network.outputs.subnetIds['snet-cae-nonprod']]
