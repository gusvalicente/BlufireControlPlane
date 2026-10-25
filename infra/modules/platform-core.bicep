// Everything in rg-platform-prod: monitoring, Sentinel, registry, secrets, state database, email,
// and the control plane apps and worker jobs.
param location string
param tags object
param tenantId string
param names object
param adminStaticIp string
param mcpClientCidrs array
param uiDomain string
param mcpDomain string

@description('false on first deploy: DNS records for custom domains must exist before binding.')
param bindCustomDomains bool

param alertEmail string
param smsCountryCode string
param smsNumber string
param pushEmail string
param pgAdminGroupObjectId string
param backupStorageAccountName string
param githubOwner string
param githubRepo string
param settings object
param controlPlaneImage string
param uiImage string
param dbopsImage string
param deployApps bool
param digestCronUtc string

var roles = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538f'
  logAnalyticsReader: '73c42c96-874c-492b-b04d-ab87d138a893'
  contributor: 'b24988ac-6180-42a0-ab88-20f7382dd24c'
}

module identity 'identity.bicep' = {
  name: 'platform-identity'
  params: {
    name: names.identity
    location: location
    tags: tags
  }
}

// The internet-facing UI and MCP server get their own identities with almost no rights, so a compromise of either
// cannot read client secrets, the GitHub App key or the state database. Only platform-api and the worker use the
// platform identity. The MCP identity holds just the Agent app role on platform-api (granted by bootstrap 60).
module uiIdentity 'identity.bicep' = {
  name: 'platform-ui-identity'
  params: {
    name: 'id-platform-ui'
    location: location
    tags: tags
  }
}

module mcpIdentity 'identity.bicep' = {
  name: 'platform-mcp-identity'
  params: {
    name: 'id-platform-mcp'
    location: location
    tags: tags
  }
}

resource uiAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, 'id-platform-ui', roles.acrPull)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
    principalId: uiIdentity.outputs.principalId
    principalType: 'ServicePrincipal'
  }
}

resource mcpAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, 'id-platform-mcp', roles.acrPull)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
    principalId: mcpIdentity.outputs.principalId
    principalType: 'ServicePrincipal'
  }
}

resource kvRef 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: names.keyVault
}

// UI may read exactly its two secrets (they are created by bootstrap 60 before the apps pass).
resource uiSecretRead 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for s in [
  'ui-auth-secret'
  'ui-entra-client-secret'
]: if (deployApps) {
  scope: secretRef[indexOf(['ui-auth-secret', 'ui-entra-client-secret'], s)]
  name: guid(kvRef.id, s, 'id-platform-ui')
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
    principalId: uiIdentity.outputs.principalId
    principalType: 'ServicePrincipal'
  }
  dependsOn: [kv]
}]

resource secretRef 'Microsoft.KeyVault/vaults/secrets@2023-07-01' existing = [for s in [
  'ui-auth-secret'
  'ui-entra-client-secret'
]: {
  parent: kvRef
  name: s
}]

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: names.logAnalytics
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 90
  }
}

resource sentinel 'Microsoft.SecurityInsights/onboardingStates@2024-03-01' = {
  scope: law
  name: 'default'
  properties: {}
}

var outOfBandQuery = '''
let ci = dynamic(__CI__);
AzureActivity
| where CategoryValue == "Administrative" and ActivityStatusValue =~ "Success"
| where OperationNameValue in~ (
    "MICROSOFT.APP/CONTAINERAPPS/WRITE",
    "MICROSOFT.APP/MANAGEDENVIRONMENTS/WRITE",
    "MICROSOFT.AUTHORIZATION/ROLEASSIGNMENTS/WRITE",
    "MICROSOFT.NETWORK/VIRTUALNETWORKS/WRITE",
    "MICROSOFT.NETWORK/VIRTUALNETWORKS/SUBNETS/WRITE",
    "MICROSOFT.DBFORPOSTGRESQL/FLEXIBLESERVERS/WRITE",
    "MICROSOFT.KEYVAULT/VAULTS/WRITE",
    "MICROSOFT.STORAGE/STORAGEACCOUNTS/WRITE")
| where Caller !in (ci)
| project TimeGenerated, Caller, CallerIpAddress, OperationNameValue, _ResourceId
'''

// Container Apps, role assignments and network changes made by anyone except the CI identities.
// Activity Log alerts cannot express "caller is not X", so this lives in Sentinel.
resource outOfBandChanges 'Microsoft.SecurityInsights/alertRules@2024-03-01' = {
  scope: law
  name: guid(law.id, 'out-of-band-changes')
  kind: 'Scheduled'
  properties: {
    displayName: 'Infrastructure changed outside CI'
    description: 'A write to ingress, networking, Postgres or role assignments by an identity other than the platform CI identities.'
    enabled: true
    severity: 'High'
    query: replace(outOfBandQuery, '__CI__', string(settings.ciPrincipalIds))
    queryFrequency: 'PT15M'
    queryPeriod: 'PT15M'
    triggerOperator: 'GreaterThan'
    triggerThreshold: 0
    suppressionEnabled: false
    suppressionDuration: 'PT1H'
    tactics: ['Persistence', 'DefenseEvasion']
    incidentConfiguration: {
      createIncident: true
      groupingConfiguration: {
        enabled: false
        reopenClosedIncident: false
        lookbackDuration: 'PT5H'
        matchingMethod: 'AllEntities'
        groupByEntities: []
        groupByAlertDetails: []
        groupByCustomDetails: []
      }
    }
  }
  dependsOn: [sentinel]
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: names.appInsights
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
  }
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: names.acr
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
  }
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, names.identity, roles.acrPull)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
    principalId: identity.outputs.principalId
    principalType: 'ServicePrincipal'
  }
}

resource lawReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: law
  name: guid(law.id, names.identity, roles.logAnalyticsReader)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.logAnalyticsReader)
    principalId: identity.outputs.principalId
    principalType: 'ServicePrincipal'
  }
}

module kv 'keyvault.bicep' = {
  name: 'platform-vault'
  params: {
    name: names.keyVault
    location: location
    tags: tags
    tenantId: tenantId
    workspaceId: law.id
    secretsUserPrincipalIds: [identity.outputs.principalId]
  }
}

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: names.actionGroup
  location: 'global'
  tags: tags
  properties: {
    groupShortName: 'BluFireP1'
    enabled: true
    emailReceivers: empty(alertEmail) ? [] : [
      {
        name: 'email'
        emailAddress: alertEmail
        useCommonAlertSchema: true
      }
    ]
    smsReceivers: empty(smsNumber) ? [] : [
      {
        name: 'sms'
        countryCode: smsCountryCode
        phoneNumber: smsNumber
      }
    ]
    azureAppPushReceivers: empty(pushEmail) ? [] : [
      {
        name: 'push'
        emailAddress: pushEmail
      }
    ]
  }
}

// Worker telemetry lands in AppTraces with Message = event name (see docs/runtime-config.md).
var workerAlerts = [
  {
    name: 'backup-failed'
    severity: 1
    page: true
    query: 'AppTraces | where Message == "backup_failed"'
    operator: 'GreaterThan'
    threshold: 0
    window: 'PT15M'
  }
  {
    name: 'restore-test-failed'
    severity: 1
    page: true
    query: 'AppTraces | where Message == "restore_test_failed"'
    operator: 'GreaterThan'
    threshold: 0
    window: 'PT15M'
  }
  {
    name: 'worker-heartbeat-missing'
    severity: 1
    page: true
    query: 'AppTraces | where Message == "worker_heartbeat"'
    operator: 'LessThan'
    threshold: 1
    window: 'PT1H'
  }
  {
    // P2: visible in Azure Monitor and the digest, not paged.
    name: 'drift-detected-prod'
    severity: 2
    page: false
    query: 'AppTraces | where Message == "drift_detected_prod"'
    operator: 'GreaterThan'
    threshold: 0
    window: 'PT1H'
  }
  {
    name: 'sentinel-high-incident'
    severity: 1
    page: true
    query: 'SecurityIncident | where Severity == "High" and Status == "New"'
    operator: 'GreaterThan'
    threshold: 0
    window: 'PT15M'
  }
]

resource logAlerts 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = [for a in workerAlerts: {
  name: 'alert-${a.name}'
  location: location
  tags: tags
  kind: 'LogAlert'
  properties: {
    displayName: a.name
    severity: a.severity
    enabled: true
    evaluationFrequency: 'PT15M'
    windowSize: a.window
    scopes: [law.id]
    criteria: {
      allOf: [
        {
          query: a.query
          timeAggregation: 'Count'
          operator: a.operator
          threshold: a.threshold
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    actions: {
      actionGroups: a.page ? [actionGroup.id] : []
    }
  }
}]

module network 'network.bicep' = {
  name: 'platform-network'
  params: {
    location: location
    tags: tags
    vnetName: names.vnet
    addressPrefix: '10.10.0.0/16'
    postgresDnsZoneName: 'platform.private.postgres.database.azure.com'
    subnets: [
      {
        name: 'snet-cae'
        prefix: '10.10.0.0/24'
        delegation: 'Microsoft.App/environments'
        serviceEndpoints: ['Microsoft.Storage']
      }
      {
        name: 'snet-pg'
        prefix: '10.10.1.0/28'
        delegation: 'Microsoft.DBforPostgreSQL/flexibleServers'
        serviceEndpoints: []
      }
    ]
  }
}

module cae 'cae.bicep' = {
  name: 'platform-cae'
  params: {
    name: names.cae
    location: location
    tags: tags
    subnetId: network.outputs.subnetIds['snet-cae']
    workspaceId: law.id
  }
}

module stateDb 'postgres.bicep' = {
  name: 'platform-state-db'
  params: {
    name: names.stateDb
    location: location
    tags: tags
    skuName: 'Standard_B1ms'
    backupRetentionDays: 35
    delegatedSubnetId: network.outputs.subnetIds['snet-pg']
    privateDnsZoneId: network.outputs.dnsZoneId
    tenantId: tenantId
    workspaceId: law.id
    databases: ['blufire']
    admins: [
      {
        objectId: pgAdminGroupObjectId
        principalName: 'pg-admins'
        principalType: 'Group'
      }
      {
        objectId: identity.outputs.principalId
        principalName: names.identity
        principalType: 'ServicePrincipal'
      }
      {
        objectId: dbopsIdentity.outputs.principalId
        principalName: names.dbopsIdentity
        principalType: 'ServicePrincipal'
      }
    ]
  }
}

// db-ops for the state database: its own identity, so the platform identity keeps read-only backup access.
module dbopsIdentity 'identity.bicep' = {
  name: 'platform-dbops-identity'
  params: {
    name: names.dbopsIdentity
    location: location
    tags: tags
  }
}

resource dbopsAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, names.dbopsIdentity, roles.acrPull)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
    principalId: dbopsIdentity.outputs.principalId
    principalType: 'ServicePrincipal'
  }
}

module dbopsJob 'job.bicep' = {
  name: 'platform-dbops-job'
  params: {
    name: names.dbopsJob
    location: location
    tags: tags
    environmentId: cae.outputs.id
    identityId: dbopsIdentity.outputs.id
    registryServer: acr.properties.loginServer
    image: dbopsImage
    command: ['blufire-dbops']
    containerName: 'dbops'
    triggerType: 'Manual'
    replicaTimeout: 7200
    cpu: '1.0'
    memory: '2Gi'
    env: [
      { name: 'PGHOST', value: stateDb.outputs.fqdn }
      { name: 'AZURE_CLIENT_ID', value: dbopsIdentity.outputs.clientId }
      { name: 'PGUSER', value: names.dbopsIdentity }
      { name: 'BACKUP_STORAGE_ACCOUNT', value: backupStorageAccountName }
      { name: 'BACKUP_CONTAINER', value: 'pg-dumps' }
      { name: 'BACKUP_CONTAINER_PRE_PROMOTION', value: 'pg-dumps-prepromotion' }
      { name: 'RESULT_CONTAINER', value: 'dbops-results' }
    ]
  }
  dependsOn: [dbopsAcrPull]
}

resource dbopsJobRef 'Microsoft.App/jobs@2024-03-01' existing = {
  name: names.dbopsJob
}

resource dbopsStarter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: dbopsJobRef
  name: guid(resourceGroup().id, names.dbopsJob, names.identity)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.contributor)
    principalId: identity.outputs.principalId
    principalType: 'ServicePrincipal'
  }
  dependsOn: [dbopsJob]
}

resource emailService 'Microsoft.Communication/emailServices@2023-04-01' = {
  name: names.emailService
  location: 'global'
  tags: tags
  properties: {
    dataLocation: 'United States'
  }
}

resource emailDomain 'Microsoft.Communication/emailServices/domains@2023-04-01' = {
  parent: emailService
  name: 'AzureManagedDomain'
  location: 'global'
  tags: tags
  properties: {
    domainManagement: 'AzureManaged'
    userEngagementTracking: 'Disabled'
  }
}

resource acs 'Microsoft.Communication/communicationServices@2023-04-01' = {
  name: names.communicationService
  location: 'global'
  tags: tags
  properties: {
    dataLocation: 'United States'
    linkedDomains: [emailDomain.id]
  }
}

// Sending email with an Entra identity needs write on the Communication Services resource. Contributor scoped to
// this single resource is the narrowest built-in role that covers it.
resource acsSender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acs
  name: guid(acs.id, names.identity, roles.contributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.contributor)
    principalId: identity.outputs.principalId
    principalType: 'ServicePrincipal'
  }
}

var kvSecret = 'https://${names.keyVault}${environment().suffixes.keyvaultDns}/secrets'
var apiUrl = 'http://${names.apiApp}'
var mcpResourceUrl = empty(mcpDomain) ? '' : 'https://${mcpDomain}/mcp'

var commonEnv = [
  { name: 'AZURE_CLIENT_ID', value: identity.outputs.clientId }
  { name: 'ENTRA_TENANT_ID', value: tenantId }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
]

var backendEnv = concat(commonEnv, [
  { name: 'API_AUDIENCE', value: empty(settings.apiClientId) ? settings.apiAudience : '${settings.apiAudience},${settings.apiClientId}' }
  { name: 'UI_CLIENT_ID', value: settings.uiClientId }
  { name: 'STEP_UP_ACRS', value: settings.stepUpAcrs }
  { name: 'STATE_DB_HOST', value: stateDb.outputs.fqdn }
  { name: 'STATE_DB_NAME', value: 'blufire' }
  { name: 'STATE_DB_USER', value: names.identity }
  { name: 'GITHUB_OWNER', value: githubOwner }
  { name: 'GITHUB_REPO', value: githubRepo }
  { name: 'GITHUB_APP_ID', value: settings.githubAppId }
  { name: 'GITHUB_APP_INSTALLATION_ID', value: settings.githubAppInstallationId }
  { name: 'GITHUB_APP_PRIVATE_KEY', secretRef: 'github-app-private-key' }
  { name: 'LOG_ANALYTICS_WORKSPACE_ID', value: law.properties.customerId }
  { name: 'BACKUP_STORAGE_ACCOUNT', value: backupStorageAccountName }
])

var backendSecrets = [
  { name: 'github-app-private-key', keyVaultUrl: '${kvSecret}/github-app-private-key' }
]

var adminCidrs = [
  { name: 'admin-static-ip', cidr: adminStaticIp }
]

var mcpCidrs = concat(adminCidrs, map(range(0, length(mcpClientCidrs)), i => {
  name: 'mcp-client-${i}'
  cidr: mcpClientCidrs[i]
}))

module api 'container-app.bicep' = if (deployApps) {
  name: 'platform-api'
  params: {
    name: names.apiApp
    location: location
    tags: tags
    environmentId: cae.outputs.id
    identityId: identity.outputs.id
    registryServer: acr.properties.loginServer
    image: controlPlaneImage
    command: ['blufire-api']
    external: false
    targetPort: 8000
    minReplicas: 1
    maxReplicas: 2
    env: concat(backendEnv, [
      { name: 'HEARTBEAT_TOKEN', secretRef: 'heartbeat-token' }
    ])
    secrets: concat(backendSecrets, [
      { name: 'heartbeat-token', keyVaultUrl: '${kvSecret}/heartbeat-token' }
    ])
    probes: [
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
  }
  dependsOn: [acrPull, kv]
}

var uiEnv = [
  { name: 'AUTH_SECRET', secretRef: 'ui-auth-secret' }
  { name: 'AUTH_MICROSOFT_ENTRA_ID_ID', value: settings.uiClientId }
  { name: 'AUTH_MICROSOFT_ENTRA_ID_SECRET', secretRef: 'ui-entra-client-secret' }
  { name: 'AUTH_MICROSOFT_ENTRA_ID_ISSUER', value: '${environment().authentication.loginEndpoint}${tenantId}/v2.0' }
  { name: 'AUTH_TRUST_HOST', value: 'true' }
  { name: 'PLATFORM_API_URL', value: apiUrl }
  { name: 'PLATFORM_API_SCOPE', value: '${settings.apiAudience}/access_as_user' }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
]

var uiSecrets = [
  { name: 'ui-auth-secret', keyVaultUrl: '${kvSecret}/ui-auth-secret' }
  { name: 'ui-entra-client-secret', keyVaultUrl: '${kvSecret}/ui-entra-client-secret' }
]

var mcpEnv = [
  { name: 'AZURE_CLIENT_ID', value: mcpIdentity.outputs.clientId }
  { name: 'ENTRA_TENANT_ID', value: tenantId }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
  { name: 'PLATFORM_API_URL', value: apiUrl }
  { name: 'MCP_AUDIENCE', value: settings.mcpClientId }
  { name: 'MCP_RESOURCE_URL', value: mcpResourceUrl }
  { name: 'MCP_ALLOWED_OIDS', value: settings.adminObjectId }
  { name: 'API_SCOPE', value: '${settings.apiAudience}/.default' }
]

var bindUi = deployApps && bindCustomDomains && !empty(uiDomain)
var bindMcp = deployApps && bindCustomDomains && !empty(mcpDomain)

// Custom domains need two passes: the host name is added without a certificate, a managed certificate is issued
// for it, then the app is updated to bind it. DNS (CNAME + asuid TXT) must exist before the first pass.
module ui 'container-app.bicep' = if (deployApps) {
  name: 'platform-ui'
  params: {
    name: names.uiApp
    location: location
    tags: tags
    environmentId: cae.outputs.id
    identityId: uiIdentity.outputs.id
    registryServer: acr.properties.loginServer
    image: uiImage
    external: true
    targetPort: 3000
    minReplicas: 1
    maxReplicas: 2
    allowedCidrs: adminCidrs
    env: uiEnv
    secrets: uiSecrets
    customDomain: bindUi ? uiDomain : ''
  }
  dependsOn: [uiAcrPull, uiSecretRead]
}

module mcp 'container-app.bicep' = if (deployApps) {
  name: 'platform-mcp'
  params: {
    name: names.mcpApp
    location: location
    tags: tags
    environmentId: cae.outputs.id
    identityId: mcpIdentity.outputs.id
    registryServer: acr.properties.loginServer
    image: controlPlaneImage
    command: ['blufire-mcp']
    external: true
    targetPort: 8080
    minReplicas: 1
    maxReplicas: 2
    allowedCidrs: mcpCidrs
    env: mcpEnv
    customDomain: bindMcp ? mcpDomain : ''
  }
  dependsOn: [mcpAcrPull]
}

resource caeRef 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: names.cae
}

resource uiCert 'Microsoft.App/managedEnvironments/managedCertificates@2024-03-01' = if (bindUi) {
  parent: caeRef
  name: 'cert-admin-ui'
  location: location
  tags: tags
  properties: {
    subjectName: uiDomain
    domainControlValidation: 'CNAME'
  }
  dependsOn: [ui, cae]
}

resource mcpCert 'Microsoft.App/managedEnvironments/managedCertificates@2024-03-01' = if (bindMcp) {
  parent: caeRef
  name: 'cert-mcp'
  location: location
  tags: tags
  properties: {
    subjectName: mcpDomain
    domainControlValidation: 'CNAME'
  }
  dependsOn: [mcp, cae]
}

module uiBound 'container-app.bicep' = if (bindUi) {
  name: 'platform-ui-bound'
  params: {
    name: names.uiApp
    location: location
    tags: tags
    environmentId: cae.outputs.id
    identityId: uiIdentity.outputs.id
    registryServer: acr.properties.loginServer
    image: uiImage
    external: true
    targetPort: 3000
    minReplicas: 1
    maxReplicas: 2
    allowedCidrs: adminCidrs
    env: uiEnv
    secrets: uiSecrets
    customDomain: uiDomain
    customDomainCertificateId: uiCert.id
  }
}

module mcpBound 'container-app.bicep' = if (bindMcp) {
  name: 'platform-mcp-bound'
  params: {
    name: names.mcpApp
    location: location
    tags: tags
    environmentId: cae.outputs.id
    identityId: mcpIdentity.outputs.id
    registryServer: acr.properties.loginServer
    image: controlPlaneImage
    command: ['blufire-mcp']
    external: true
    targetPort: 8080
    minReplicas: 1
    maxReplicas: 2
    allowedCidrs: mcpCidrs
    env: mcpEnv
    customDomain: mcpDomain
    customDomainCertificateId: mcpCert.id
  }
}

var workerEnv = concat(backendEnv, [
  { name: 'ACS_ENDPOINT', value: 'https://${acs.properties.hostName}' }
  { name: 'DIGEST_SENDER', value: 'DoNotReply@${emailDomain.properties.mailFromSenderDomain}' }
])

var workerJobs = [
  { name: 'ops', job: 'ops', cron: '*/2 * * * *' }
  { name: 'drift-check', job: 'drift_check', cron: '0 * * * *' }
  { name: 'sync', job: 'sync', cron: '*/15 * * * *' }
  { name: 'nightly-backup', job: 'nightly_backup', cron: '0 6 * * *' }
  { name: 'restore-test', job: 'restore_test', cron: '0 7 1 * *' }
  { name: 'digest', job: 'digest', cron: digestCronUtc }
]

module jobs 'job.bicep' = [for j in workerJobs: if (deployApps) {
  name: 'platform-job-${j.name}'
  params: {
    name: 'caj-platform-${j.name}-prod'
    location: location
    tags: tags
    environmentId: cae.outputs.id
    identityId: identity.outputs.id
    registryServer: acr.properties.loginServer
    image: controlPlaneImage
    command: ['blufire-worker']
    args: [j.job]
    triggerType: 'Schedule'
    cronExpression: j.cron
    replicaTimeout: 3600
    env: workerEnv
    secrets: backendSecrets
  }
  dependsOn: [acrPull, kv, acsSender]
}]

output identityPrincipalId string = identity.outputs.principalId
output identityClientId string = identity.outputs.clientId
output mcpPrincipalId string = mcpIdentity.outputs.principalId
output dbopsPrincipalId string = dbopsIdentity.outputs.principalId
output workspaceId string = law.id
output workspaceCustomerId string = law.properties.customerId
output acrLoginServer string = acr.properties.loginServer
output keyVaultName string = kv.outputs.name
output caeSubnetId string = network.outputs.subnetIds['snet-cae']
output customDomainVerificationId string = cae.outputs.customDomainVerificationId
output uiFqdn string = ui.?outputs.fqdn ?? ''
output mcpFqdn string = mcp.?outputs.fqdn ?? ''
output digestSender string = 'DoNotReply@${emailDomain.properties.mailFromSenderDomain}'
