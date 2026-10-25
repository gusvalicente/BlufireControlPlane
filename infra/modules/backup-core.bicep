// Backup storage: no shared keys, deny by default, immutable containers for dumps and repo mirrors.
// Immutability policies are left unlocked here; lock them once by hand (bootstrap/README.md).
param location string
param tags object
param storageAccountName string
param workspaceId string

@description('Plain IPv4 address (no /32). Storage firewall rules do not accept /31 or /32 prefixes.')
param adminIp string

@description('Subnet resource IDs allowed through the firewall. Each subnet needs the Microsoft.Storage service endpoint.')
param allowedSubnetIds array

@description('Service principal the Mac Mini signs in as: reads both dump containers and repo-mirrors, writes receipts to dbops-results. Empty = not set up yet.')
param macMiniPrincipalId string = ''

var readerRoleId = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
var contributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_GRS'
  }
  properties: {
    accessTier: 'Cool'
    allowSharedKeyAccess: false
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    defaultToOAuthAuthentication: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
      ipRules: empty(adminIp) ? [] : [
        {
          value: adminIp
          action: 'Allow'
        }
      ]
      virtualNetworkRules: [for id in allowedSubnetIds: {
        id: id
        action: 'Allow'
      }]
    }
  }
}

resource blob 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: sa
  name: 'default'
  properties: {
    isVersioningEnabled: false
    deleteRetentionPolicy: {
      enabled: true
      days: 14
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 14
    }
  }
}

// Nightly and manual dumps: 90 days. Pre-promotion dumps: 365 days, in their own container so each
// retention period is a plain container-level policy.
resource pgDumps 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blob
  name: 'pg-dumps'
  properties: {
    publicAccess: 'None'
  }
}

resource prePromotion 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blob
  name: 'pg-dumps-prepromotion'
  properties: {
    publicAccess: 'None'
  }
}

resource prePromotionPolicy 'Microsoft.Storage/storageAccounts/blobServices/containers/immutabilityPolicies@2023-05-01' = {
  parent: prePromotion
  name: 'default'
  properties: {
    immutabilityPeriodSinceCreationInDays: 365
    allowProtectedAppendWrites: false
  }
}

resource pgDumpsPolicy 'Microsoft.Storage/storageAccounts/blobServices/containers/immutabilityPolicies@2023-05-01' = {
  parent: pgDumps
  name: 'default'
  properties: {
    immutabilityPeriodSinceCreationInDays: 90
    allowProtectedAppendWrites: false
  }
}

resource repoMirrors 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blob
  name: 'repo-mirrors'
  properties: {
    publicAccess: 'None'
  }
}

resource repoMirrorsPolicy 'Microsoft.Storage/storageAccounts/blobServices/containers/immutabilityPolicies@2023-05-01' = {
  parent: repoMirrors
  name: 'default'
  properties: {
    immutabilityPeriodSinceCreationInDays: 90
    allowProtectedAppendWrites: false
  }
}

resource plainContainers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [for c in ['dbops-results', 'migrations', 'scan-results']: {
  parent: blob
  name: c
  properties: {
    publicAccess: 'None'
  }
}]

resource lifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2023-05-01' = {
  parent: sa
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'expire-migrations'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: {
              blobTypes: ['blockBlob']
              prefixMatch: ['migrations/']
            }
            actions: {
              baseBlob: {
                delete: {
                  daysAfterModificationGreaterThan: 30
                }
              }
            }
          }
        }
        {
          name: 'expire-scan-results'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: {
              blobTypes: ['blockBlob']
              prefixMatch: ['scan-results/', 'dbops-results/']
            }
            actions: {
              baseBlob: {
                delete: {
                  daysAfterModificationGreaterThan: 365
                }
              }
            }
          }
        }
      ]
    }
  }
  dependsOn: [plainContainers]
}

resource macMiniDumps 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(macMiniPrincipalId)) {
  scope: pgDumps
  name: guid(pgDumps.id, macMiniPrincipalId, readerRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', readerRoleId)
    principalId: macMiniPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource macMiniPrePromotion 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(macMiniPrincipalId)) {
  scope: prePromotion
  name: guid(prePromotion.id, macMiniPrincipalId, readerRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', readerRoleId)
    principalId: macMiniPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource macMiniMirrors 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(macMiniPrincipalId)) {
  scope: repoMirrors
  name: guid(repoMirrors.id, macMiniPrincipalId, readerRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', readerRoleId)
    principalId: macMiniPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// dbops-results is plainContainers[0].
resource macMiniReceipts 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(macMiniPrincipalId)) {
  scope: plainContainers[0]
  name: guid(plainContainers[0].id, macMiniPrincipalId, contributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: macMiniPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource diag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: blob
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

output name string = sa.name
output id string = sa.id
