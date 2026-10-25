// Frontend (external) and backend (internal only) Container Apps, plus the prod availability test and its alert.
param location string
param tags object
param environmentId string
param identityId string
param registryServer string
param frontendName string
param backendName string
param frontendImage string
param backendImage string
param minReplicas int
param maxReplicas int
param allowedCidrs array
param frontendEnv array
param backendEnv array
param frontendSecrets array
param backendSecrets array
param appInsightsId string
param availabilityTest bool
param availabilityFrequencySeconds int
param availabilityLocations int
param actionGroupId string
param testName string

@description('Platform identity: restarts revisions after secret rotation.')
param platformPrincipalId string

var probesBackend = [
  {
    type: 'Liveness'
    httpGet: { path: '/healthz', port: 8000 }
    periodSeconds: 15
  }
  {
    type: 'Readiness'
    httpGet: { path: '/readyz', port: 8000 }
    periodSeconds: 15
  }
]

var probesFrontend = [
  {
    type: 'Readiness'
    httpGet: { path: '/api/health', port: 3000 }
    periodSeconds: 15
  }
]

module backend 'container-app.bicep' = {
  name: '${backendName}-app'
  params: {
    name: backendName
    location: location
    tags: tags
    environmentId: environmentId
    identityId: identityId
    registryServer: registryServer
    image: backendImage
    external: false
    targetPort: 8000
    minReplicas: minReplicas
    maxReplicas: maxReplicas
    env: backendEnv
    secrets: backendSecrets
    probes: probesBackend
  }
}

module frontend 'container-app.bicep' = {
  name: '${frontendName}-app'
  params: {
    name: frontendName
    location: location
    tags: tags
    environmentId: environmentId
    identityId: identityId
    registryServer: registryServer
    image: frontendImage
    external: true
    targetPort: 3000
    minReplicas: minReplicas
    maxReplicas: maxReplicas
    allowedCidrs: allowedCidrs
    env: frontendEnv
    secrets: frontendSecrets
    probes: probesFrontend
  }
  dependsOn: [backend]
}

// Standard test locations in the US. With origin restriction on, these probes are blocked unless their published
// IP ranges are in availabilityTestCidrs (see infra/platform-settings.json).
var allLocations = ['us-va-ash-azr', 'us-tx-sn1-azr', 'us-il-ch1-azr', 'us-ca-sjc-azr', 'us-fl-mia-edge']

resource webtest 'Microsoft.Insights/webtests@2022-06-15' = if (availabilityTest) {
  name: testName
  location: location
  tags: union(tags, {
    'hidden-link:${appInsightsId}': 'Resource'
  })
  kind: 'standard'
  properties: {
    SyntheticMonitorId: testName
    Name: testName
    Enabled: true
    Frequency: availabilityFrequencySeconds
    Timeout: 30
    Kind: 'standard'
    RetryEnabled: true
    Locations: map(take(allLocations, availabilityLocations), l => { Id: l })
    Request: {
      RequestUrl: 'https://${frontend.outputs.fqdn}/api/health'
      HttpVerb: 'GET'
      ParseDependentRequests: false
    }
    ValidationRules: {
      ExpectedHttpStatusCode: 200
      SSLCheck: true
      SSLCertRemainingLifetimeCheck: 14
    }
  }
}

resource availabilityAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = if (availabilityTest) {
  name: 'alert-${testName}'
  location: 'global'
  tags: tags
  properties: {
    description: 'Prod frontend failing from 2 or more locations'
    severity: 1
    enabled: true
    scopes: [webtest.id, appInsightsId]
    evaluationFrequency: 'PT1M'
    windowSize: 'PT5M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.WebtestLocationAvailabilityCriteria'
      webTestId: webtest.id
      componentId: appInsightsId
      failedLocationCount: 2
    }
    actions: [
      {
        actionGroupId: actionGroupId
      }
    ]
  }
}

resource frontendRef 'Microsoft.App/containerApps@2024-03-01' existing = {
  name: frontendName
}

resource backendRef 'Microsoft.App/containerApps@2024-03-01' existing = {
  name: backendName
}

var contributorRoleId = 'b24988ac-6180-42a0-ab88-20f7382dd24c'

resource restartFrontend 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: frontendRef
  name: guid(resourceGroup().id, frontendName, platformPrincipalId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: platformPrincipalId
    principalType: 'ServicePrincipal'
  }
  dependsOn: [frontend]
}

resource restartBackend 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: backendRef
  name: guid(resourceGroup().id, backendName, platformPrincipalId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: platformPrincipalId
    principalType: 'ServicePrincipal'
  }
  dependsOn: [backend]
}

output frontendFqdn string = frontend.outputs.fqdn
