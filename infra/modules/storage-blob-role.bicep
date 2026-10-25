// Deployed at the backup resource group (cross-subscription) so each consumer grants its own identity access.
// With containers set, access is scoped to those containers only.
param storageAccountName string
param principalId string

@allowed(['contributor', 'reader'])
param role string

@description('Container names. Empty = the whole account.')
param containers array = []

var roleIds = {
  contributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  reader: '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
}

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource blob 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  parent: sa
  name: 'default'
}

resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' existing = [for c in containers: {
  parent: blob
  name: c
}]

resource accountAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (empty(containers)) {
  scope: sa
  name: guid(sa.id, principalId, roleIds[role])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds[role])
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

resource containerAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (c, i) in containers: {
  scope: container[i]
  name: guid(sa.id, c, principalId, roleIds[role])
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds[role])
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]
