// Sends the subscription Activity Log to the central workspace (Sentinel reads AzureActivity).
targetScope = 'subscription'

param workspaceId string

resource diag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'to-platform-workspace'
  properties: {
    workspaceId: workspaceId
    logs: [for c in ['Administrative', 'Security', 'ServiceHealth', 'Alert', 'Recommendation', 'Policy', 'Autoscale', 'ResourceHealth']: {
      category: c
      enabled: true
    }]
  }
}
