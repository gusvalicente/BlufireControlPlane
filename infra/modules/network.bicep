// Virtual network, delegated subnets, and the private DNS zone Postgres private access uses.
param location string
param tags object
param vnetName string
param addressPrefix string

@description('[{name, prefix, delegation, serviceEndpoints: string[]}]. delegation is Microsoft.App/environments or Microsoft.DBforPostgreSQL/flexibleServers.')
param subnets array

param postgresDnsZoneName string

resource vnet 'Microsoft.Network/virtualNetworks@2024-01-01' = {
  name: vnetName
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [addressPrefix]
    }
    subnets: [for s in subnets: {
      name: s.name
      properties: {
        addressPrefix: s.prefix
        delegations: [
          {
            name: 'delegation'
            properties: {
              serviceName: s.delegation
            }
          }
        ]
        serviceEndpoints: map(s.serviceEndpoints, e => { service: e })
      }
    }]
  }
}

resource zone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: postgresDnsZoneName
  location: 'global'
  tags: tags
}

resource link 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: zone
  name: '${vnetName}-link'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}

output subnetIds object = toObject(subnets, s => s.name, s => '${vnet.id}/subnets/${s.name}')
output dnsZoneId string = zone.id
