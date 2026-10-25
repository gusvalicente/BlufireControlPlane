// Private, Entra-only Postgres Flexible Server. Password auth is disabled; there is no admin password anywhere.
param name string
param location string
param tags object
param skuName string
param storageSizeGB int = 32
param backupRetentionDays int

@description('Can only be chosen at creation; changing it later requires a new server.')
param geoRedundantBackup bool = false

@description('Zone-redundant HA. Ignored on Burstable SKUs, which do not support it.')
param highAvailability bool = false

param delegatedSubnetId string
param privateDnsZoneId string
param tenantId string

@description('Entra admins: [{objectId, principalName, principalType: Group | ServicePrincipal | User}]')
param admins array

param workspaceId string
param databases array = []

var tier = startsWith(skuName, 'Standard_B') ? 'Burstable' : (startsWith(skuName, 'Standard_E') ? 'MemoryOptimized' : 'GeneralPurpose')

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: skuName
    tier: tier
  }
  properties: {
    version: '16'
    storage: {
      storageSizeGB: storageSizeGB
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: backupRetentionDays
      geoRedundantBackup: geoRedundantBackup ? 'Enabled' : 'Disabled'
    }
    highAvailability: {
      mode: highAvailability && tier != 'Burstable' ? 'ZoneRedundant' : 'Disabled'
    }
    network: {
      delegatedSubnetResourceId: delegatedSubnetId
      privateDnsZoneArmResourceId: privateDnsZoneId
      publicNetworkAccess: 'Disabled'
    }
    authConfig: {
      activeDirectoryAuth: 'Enabled'
      passwordAuth: 'Disabled'
      tenantId: tenantId
    }
  }
}

// Admins must be added one at a time.
@batchSize(1)
resource admin 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2024-08-01' = [for a in admins: {
  parent: server
  name: a.objectId
  properties: {
    principalName: a.principalName
    principalType: a.principalType
    tenantId: tenantId
  }
}]

@batchSize(1)
resource db 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = [for d in databases: {
  parent: server
  name: d
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
  dependsOn: [admin]
}]

resource diag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: server
  name: 'to-platform-workspace'
  properties: {
    workspaceId: workspaceId
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

output id string = server.id
output name string = server.name
output fqdn string = server.properties.fullyQualifiedDomainName
