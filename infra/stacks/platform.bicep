// sub-blufire-platform: control plane, monitoring, Sentinel, registry and email. Parameters come from
// tools/render_params.py (build/params/platform.json).
targetScope = 'subscription'

param location string
param tenantId string
param resourceGroupName string
param names object
param adminStaticIp string
param mcpClientCidrs array
param uiDomain string
param mcpDomain string
param bindCustomDomains bool = true
param alertEmail string
param smsCountryCode string
param smsNumber string
param pushEmail string
param pgAdminGroupObjectId string
param backupSubscriptionId string
param backupResourceGroupName string
param backupStorageAccountName string
param githubOwner string
param githubRepo string
param settings object
param controlPlaneImage string
param uiImage string
param dbopsImage string
param deployApps bool
param digestCronUtc string

var tags = {
  client: 'blufire'
  app: 'platform'
  env: 'prod'
  'managed-by': 'blufire-platform'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module core '../modules/platform-core.bicep' = {
  scope: rg
  name: 'platform-core'
  params: {
    location: location
    tags: tags
    tenantId: tenantId
    names: names
    adminStaticIp: adminStaticIp
    mcpClientCidrs: mcpClientCidrs
    uiDomain: uiDomain
    mcpDomain: mcpDomain
    bindCustomDomains: bindCustomDomains
    alertEmail: alertEmail
    smsCountryCode: smsCountryCode
    smsNumber: smsNumber
    pushEmail: pushEmail
    pgAdminGroupObjectId: pgAdminGroupObjectId
    backupStorageAccountName: backupStorageAccountName
    githubOwner: githubOwner
    githubRepo: githubRepo
    settings: settings
    controlPlaneImage: controlPlaneImage
    uiImage: uiImage
    dbopsImage: dbopsImage
    deployApps: deployApps
    digestCronUtc: digestCronUtc
  }
}

module activityLog '../modules/activity-log.bicep' = {
  name: 'platform-activity-log'
  params: {
    workspaceId: core.outputs.workspaceId
  }
}

module backupRead '../modules/storage-blob-role.bicep' = {
  scope: resourceGroup(backupSubscriptionId, backupResourceGroupName)
  name: 'platform-backup-read'
  params: {
    storageAccountName: backupStorageAccountName
    principalId: core.outputs.identityPrincipalId
    role: 'reader'
    containers: ['pg-dumps', 'pg-dumps-prepromotion', 'scan-results', 'dbops-results']
  }
}

module dbopsBackupWrite '../modules/storage-blob-role.bicep' = {
  scope: resourceGroup(backupSubscriptionId, backupResourceGroupName)
  name: 'platform-dbops-backup-write'
  params: {
    storageAccountName: backupStorageAccountName
    principalId: core.outputs.dbopsPrincipalId
    role: 'contributor'
    containers: ['pg-dumps', 'pg-dumps-prepromotion', 'dbops-results']
  }
}

output identityPrincipalId string = core.outputs.identityPrincipalId
output identityClientId string = core.outputs.identityClientId
output mcpPrincipalId string = core.outputs.mcpPrincipalId
output workspaceId string = core.outputs.workspaceId
output acrLoginServer string = core.outputs.acrLoginServer
output keyVaultName string = core.outputs.keyVaultName
output customDomainVerificationId string = core.outputs.customDomainVerificationId
output uiFqdn string = core.outputs.uiFqdn
output mcpFqdn string = core.outputs.mcpFqdn
output digestSender string = core.outputs.digestSender
