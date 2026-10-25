// sub-blufire-backup: immutable backup storage, isolated from every client and platform identity's own subscription.
targetScope = 'subscription'

param location string
param resourceGroupName string
param storageAccountName string
param workspaceId string
param adminIp string
param allowedSubnetIds array
param macMiniPrincipalId string = ''

var tags = {
  client: 'blufire'
  app: 'backup'
  env: 'prod'
  'managed-by': 'blufire-platform'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module core '../modules/backup-core.bicep' = {
  scope: rg
  name: 'backup-core'
  params: {
    location: location
    tags: tags
    storageAccountName: storageAccountName
    workspaceId: workspaceId
    adminIp: adminIp
    allowedSubnetIds: allowedSubnetIds
    macMiniPrincipalId: macMiniPrincipalId
  }
}

module activityLog '../modules/activity-log.bicep' = {
  name: 'backup-activity-log'
  params: {
    workspaceId: workspaceId
  }
}

output storageAccountName string = core.outputs.name
