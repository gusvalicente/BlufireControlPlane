// Workload-profile Container Apps environment on a VNet subnet so apps reach private Postgres.
// Logs go through Azure Monitor diagnostic settings, so no workspace shared key is needed (works cross-subscription).
param name string
param location string
param tags object
param subnetId string
param workspaceId string

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'azure-monitor'
    }
    vnetConfiguration: {
      infrastructureSubnetId: subnetId
      internal: false
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    zoneRedundant: false
  }
}

resource diag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: env
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

output id string = env.id
output name string = env.name
output defaultDomain string = env.properties.defaultDomain
output customDomainVerificationId string = env.properties.customDomainConfiguration.customDomainVerificationId
