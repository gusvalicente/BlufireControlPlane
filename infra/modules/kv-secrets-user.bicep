// Grants an app identity read access to exactly its own secrets in the tier's Key Vault (shared resource group).
// Vaults are shared by several apps (and, in the sandbox, by several clients), so access is per secret, never
// vault-wide. Every listed secret must already exist: bootstrap 85/90 create the auth secrets, and secrets listed
// in the registry must be created in the vault before the app is deployed.
param keyVaultName string
param principalId string
param secretNames array

var secretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource secret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' existing = [for s in secretNames: {
  parent: kv
  name: s
}]

resource assignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (s, i) in secretNames: {
  scope: secret[i]
  name: guid(kv.id, s, principalId, secretsUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsUserRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

output vaultUri string = kv.properties.vaultUri
