// RBAC-only Key Vault. Secret values are set by bootstrap scripts or rotation, never by Bicep.
param name string
param location string
param tags object
param tenantId string
param workspaceId string
param secretsUserPrincipalIds array = []

@description('Principals that rotate secrets and list their metadata (the platform identity).')
param secretsOfficerPrincipalIds array = []

var secretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
var secretsOfficerRoleId = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    tenantId: tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enablePurgeProtection: true
    publicNetworkAccess: 'Enabled'
  }
}

resource secretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for p in secretsUserPrincipalIds: {
  scope: kv
  name: guid(kv.id, p, secretsUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsUserRoleId)
    principalId: p
    principalType: 'ServicePrincipal'
  }
}]

resource secretsOfficer 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for p in secretsOfficerPrincipalIds: {
  scope: kv
  name: guid(kv.id, p, secretsOfficerRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsOfficerRoleId)
    principalId: p
    principalType: 'ServicePrincipal'
  }
}]

resource diag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: kv
  name: 'to-platform-workspace'
  properties: {
    workspaceId: workspaceId
    logs: [
      {
        categoryGroup: 'audit'
        enabled: true
      }
    ]
  }
}

output id string = kv.id
output name string = kv.name
output uri string = kv.properties.vaultUri
