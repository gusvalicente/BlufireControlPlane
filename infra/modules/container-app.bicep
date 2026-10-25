// One Container App. Until an image exists in the registry (image = ''), a public placeholder runs so
// infrastructure can be created before the first build.
param name string
param location string
param tags object
param environmentId string
param identityId string
param registryServer string
param image string
param command array = []
param args array = []
param external bool
param targetPort int

@description('[{name, cidr}]. Empty = no IP restriction. Container Apps allows only allow-rules or only deny-rules per app; this module uses allow-rules.')
param allowedCidrs array = []

@description('[{name, value}] or [{name, secretRef}]')
param env array = []

@description('[{name, keyVaultUrl}]. Fetched with identityId.')
param secrets array = []

param minReplicas int
param maxReplicas int
param probes array = []

@description('Custom domain host name. Empty = none.')
param customDomain string = ''

@description('Managed certificate resource ID. Empty with a customDomain set = hostname added without binding.')
param customDomainCertificateId string = ''

param cpu string = '0.5'
param memory string = '1Gi'

var useAcr = !empty(image)
var placeholderImage = 'mcr.microsoft.com/k8se/quickstart:latest'

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: {
    environmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: external
        targetPort: useAcr ? targetPort : 80
        transport: 'auto'
        allowInsecure: false
        ipSecurityRestrictions: [for c in allowedCidrs: {
          name: c.name
          ipAddressRange: c.cidr
          action: 'Allow'
        }]
        customDomains: empty(customDomain) ? [] : [
          {
            name: customDomain
            bindingType: empty(customDomainCertificateId) ? 'Disabled' : 'SniEnabled'
            certificateId: empty(customDomainCertificateId) ? null : customDomainCertificateId
          }
        ]
      }
      registries: useAcr ? [
        {
          server: registryServer
          identity: identityId
        }
      ] : []
      secrets: [for s in secrets: {
        name: s.name
        keyVaultUrl: s.keyVaultUrl
        identity: identityId
      }]
    }
    template: {
      containers: [
        {
          name: 'main'
          image: useAcr ? image : placeholderImage
          command: useAcr ? command : []
          args: useAcr ? args : []
          env: env
          probes: useAcr ? probes : []
          resources: {
            cpu: json(cpu)
            memory: memory
          }
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
    }
  }
}

output id string = app.id
output name string = app.name
output fqdn string = app.properties.configuration.ingress.fqdn
