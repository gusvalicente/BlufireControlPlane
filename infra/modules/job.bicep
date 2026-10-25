// Container Apps Job, manual (db-ops) or scheduled (platform worker).
param name string
param location string
param tags object
param environmentId string
param identityId string
param registryServer string
param image string
param command array = []
param args array = []
param env array = []

@description('[{name, keyVaultUrl}]')
param secrets array = []

@allowed(['Manual', 'Schedule'])
param triggerType string

param cronExpression string = ''
param replicaTimeout int = 3600
param containerName string = 'main'
param cpu string = '0.5'
param memory string = '1Gi'

var useAcr = !empty(image)

resource job 'Microsoft.App/jobs@2024-03-01' = {
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
      triggerType: triggerType
      replicaTimeout: replicaTimeout
      replicaRetryLimit: 0
      manualTriggerConfig: triggerType == 'Manual' ? {
        parallelism: 1
        replicaCompletionCount: 1
      } : null
      scheduleTriggerConfig: triggerType == 'Schedule' ? {
        cronExpression: cronExpression
        parallelism: 1
        replicaCompletionCount: 1
      } : null
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
          name: containerName
          image: useAcr ? image : 'mcr.microsoft.com/k8se/quickstart-jobs:latest'
          command: useAcr ? command : []
          args: useAcr ? args : []
          env: env
          resources: {
            cpu: json(cpu)
            memory: memory
          }
        }
      ]
    }
  }
}

output id string = job.id
output name string = job.name
