// App identity and App Insights, created before the role assignments the app's containers depend on.
param location string
param tags object
param identityName string
param appInsightsName string
param workspaceId string

module identity 'identity.bicep' = {
  name: '${identityName}-identity'
  params: {
    name: identityName
    location: location
    tags: tags
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspaceId
  }
}

output identityId string = identity.outputs.id
output principalId string = identity.outputs.principalId
output clientId string = identity.outputs.clientId
output appInsightsId string = appInsights.id
output appInsightsConnectionString string = appInsights.properties.ConnectionString
