// One app in one environment: resource group, identity, App Insights, database, Key Vault access, and the
// frontend/backend Container Apps. Runs in the client subscription (graduated) or the sandbox (incubating).
targetScope = 'subscription'

param location string
param clientId string
param appId string
param env string
param resourceGroupName string
param sharedResourceGroupName string
param caeName string
param postgresServerName string
param databaseName string
param keyVaultName string
param identityName string
param appInsightsName string
param frontendName string
param backendName string
param frontendImage string
param backendImage string
param minReplicas int
param maxReplicas int
param allowedCidrs array
param envVars object
param secretNames array
param entraClientId string
param allowedTenants array
param workspaceId string
param actionGroupId string
param availabilityTest bool
param availabilityFrequencySeconds int
param availabilityLocations int
param platformSubscriptionId string
param platformResourceGroupName string
param acrName string
param acrLoginServer string
param platformPrincipalId string

var tags = {
  client: clientId
  app: appId
  env: env
  'managed-by': 'blufire-platform'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

resource sharedRg 'Microsoft.Resources/resourceGroups@2024-03-01' existing = {
  name: sharedResourceGroupName
}

resource cae 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  scope: sharedRg
  name: caeName
}

module identity '../modules/app-identity.bicep' = {
  scope: rg
  name: '${identityName}-base'
  params: {
    location: location
    tags: tags
    identityName: identityName
    appInsightsName: appInsightsName
    workspaceId: workspaceId
  }
}

module acrPull '../modules/acr-pull.bicep' = {
  scope: resourceGroup(platformSubscriptionId, platformResourceGroupName)
  name: '${identityName}-acr-pull'
  params: {
    acrName: acrName
    principalId: identity.outputs.principalId
  }
}

module vault '../modules/kv-secrets-user.bicep' = {
  scope: sharedRg
  name: '${identityName}-kv'
  params: {
    keyVaultName: keyVaultName
    principalId: identity.outputs.principalId
    secretNames: concat(secretNames, ['${appId}-auth-secret', '${appId}-entra-client-secret'])
  }
}

module database '../modules/pg-database.bicep' = {
  scope: sharedRg
  name: '${identityName}-db'
  params: {
    serverName: postgresServerName
    databaseName: databaseName
  }
}

// Contract: docs/runtime-config.md "Client app containers".
var kvSecretBase = 'https://${keyVaultName}${environment().suffixes.keyvaultDns}/secrets'

var plainEnv = [for item in items(envVars): {
  name: item.key
  value: item.value
}]

var registrySecretEnv = [for s in secretNames: {
  name: toUpper(replace(s, '-', '_'))
  secretRef: s
}]

var registrySecrets = [for s in secretNames: {
  name: s
  keyVaultUrl: '${kvSecretBase}/${s}'
}]

var authSecrets = [
  { name: '${appId}-auth-secret', keyVaultUrl: '${kvSecretBase}/${appId}-auth-secret' }
  { name: '${appId}-entra-client-secret', keyVaultUrl: '${kvSecretBase}/${appId}-entra-client-secret' }
]

var baseEnv = [
  { name: 'APP_ID', value: appId }
  { name: 'APP_ENV', value: env }
  { name: 'AZURE_CLIENT_ID', value: identity.outputs.clientId }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: identity.outputs.appInsightsConnectionString }
  { name: 'ENTRA_CLIENT_ID', value: entraClientId }
  { name: 'ALLOWED_TENANTS', value: join(allowedTenants, ',') }
]

module runtime '../modules/app-runtime.bicep' = {
  scope: rg
  name: '${identityName}-runtime'
  params: {
    location: location
    tags: tags
    environmentId: cae.id
    identityId: identity.outputs.identityId
    registryServer: acrLoginServer
    frontendName: frontendName
    backendName: backendName
    frontendImage: frontendImage
    backendImage: backendImage
    minReplicas: minReplicas
    maxReplicas: maxReplicas
    allowedCidrs: allowedCidrs
    backendEnv: concat(baseEnv, plainEnv, registrySecretEnv, [
      { name: 'PGHOST', value: database.outputs.fqdn }
      { name: 'PGDATABASE', value: databaseName }
      { name: 'PGUSER', value: identityName }
    ])
    frontendEnv: concat(baseEnv, plainEnv, registrySecretEnv, [
      { name: 'BACKEND_URL', value: 'http://${backendName}' }
      { name: 'AUTH_SECRET', secretRef: '${appId}-auth-secret' }
      { name: 'ENTRA_CLIENT_SECRET', secretRef: '${appId}-entra-client-secret' }
    ])
    backendSecrets: registrySecrets
    frontendSecrets: concat(registrySecrets, authSecrets)
    appInsightsId: identity.outputs.appInsightsId
    availabilityTest: availabilityTest
    availabilityFrequencySeconds: availabilityFrequencySeconds
    availabilityLocations: availabilityLocations
    actionGroupId: actionGroupId
    testName: 'avail-${frontendName}'
    platformPrincipalId: platformPrincipalId
  }
  dependsOn: [acrPull, vault]
}

output frontendFqdn string = runtime.outputs.frontendFqdn
